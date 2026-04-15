import time

import pyvisa
from pyvisa.resources import MessageBasedResource

from tekafp.input import Input
from tekafp.uart import UARTBridge
from tekafp.util import clamp, parse_resp


# UART config
PORT = "/dev/serial0"
BAUD = 115200

# Scope config
PYVISA_BACKEND = "@py"
SCOPE_TIMEOUT_MS = 5000

# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10  # Vertical position step per encoder detent (+/-1)
HORIZ_STEP_PCT = 1.0  # Horizontal position step in percent (0..~100) per detent

# Vertical scale sequences follow a 1/2/5 pattern per Tektronix spec
# e.g. 100mV, 200mV, 500mV, 1V, 2V, 5V, 10V, ...
VERT_SCALE_STEPS = [
    1e-3, 2e-3, 5e-3,
    10e-3, 20e-3, 50e-3,
    100e-3, 200e-3, 500e-3,
    1.0, 2.0, 5.0,
    10.0, 20.0, 50.0,
    100.0,
]

# Horizontal scale sequences follow a 1/2/4 pattern per Tektronix spec
# e.g. 1ns, 2ns, 4ns, 10ns, 20ns, 40ns, 100ns, ...
HORIZ_SCALE_STEPS = [
    1e-9, 2e-9, 4e-9,
    10e-9, 20e-9, 40e-9,
    100e-9, 200e-9, 400e-9,
    1e-6, 2e-6, 4e-6,
    10e-6, 20e-6, 40e-6,
    100e-6, 200e-6, 400e-6,
    1e-3, 2e-3, 4e-3,
    10e-3, 20e-3, 40e-3,
    100e-3, 200e-3, 400e-3,
    1.0, 2.0, 4.0, 10.0,
]


def connect_scope() -> MessageBasedResource:
    rm = pyvisa.ResourceManager(PYVISA_BACKEND)

    while True:
        resources = rm.list_resources()
        usb = [r for r in resources if r.startswith("USB")]

        if usb:
            scope: MessageBasedResource = rm.open_resource(usb[0])
            scope.timeout = SCOPE_TIMEOUT_MS
            scope.write_termination = "\n"
            scope.read_termination = "\n"

            # Make sure we're in a mode where horizontal position behaves like the
            # front panel knob
            # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
            scope.write("HORIZONTAL:DELAY:MODE OFF")
            return scope

        print("No USB scope found, retrying in 2s...")
        time.sleep(2)


def connect_uart() -> UARTBridge:
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        self.scope: MessageBasedResource = scope

        self._channels: dict[int, bool] = {ch: False for ch in range(1, 9)}
        self._source_channel: int = 0

        self._vert_fine: bool = False # fine mode toggle for vertical scale

    def seed_current_state_from_scope(self) -> None:
        try:
            # Ask scope which channel is currently the selected source
            resp = self.scope.query("DISPLAY:SELECT:SOURCE?").strip()
            # Response should be something like "CH1", "CH2", etc.
            if resp.startswith("CH") and resp[2:].isdigit():
                ch = int(resp[2:])
                self._source_channel = ch
                self._channels[ch] = True
                print(f"[SCOPE] Synced source channel from scope: CH{ch}")
            else:
                print(f"[SCOPE] Could not parse source channel from: {resp!r}")
        except Exception as e:
            print(f"[SCOPE] Failed to sync state from scope: {e}")

    def set_channel_display(self, channel: int) -> None:
        if channel not in range(1, 9):
            return
        last_state: bool = self._channels[channel]

        if self._source_channel == channel:
            # enabled and source => disable, select highest enabled as active
            self._channels[channel] = False
            highest: int = 0
            for k, v in self._channels.items():
                if v:
                    highest = k
                    if k > channel:
                        break
            self._source_channel = highest
        elif last_state:
            # enabled => set as source
            self._source_channel = channel
        else:
            # disabled => enable, set as source
            self._channels[channel] = True
            self._source_channel = channel

        if self._source_channel == 0:
            self.scope.write("DISPLAY:SELECT:SOURCE:NONE")
        else:
            self.scope.write(f"DISPLAY:SELECT:SOURCE:CH{self._source_channel}")

        if last_state != self._channels[channel]:
            self.scope.write(
                f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self._channels[channel])}"
            )

        print(
            f"[SCOPE] CH{channel} display -> {self._channels[channel]} (source={self._source_channel})"  # noqa: E501
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"CH{ch}:POSITION {new}")
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.write(f"HORIZONTAL:POSITION {new}")
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    def adjust_vertical_scale(self, detents: int) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical scale.")
            return
        cur = float(self.scope.query(f"CH{ch}:SCALE?").strip().split()[-1])

        if self._vert_fine:
            # Fine mode: find the coarse step that owns the current value,
            # then use 1/10th of it as the fine step
            nearest = min(range(len(VERT_SCALE_STEPS)), key=lambda i: abs(VERT_SCALE_STEPS[i] - cur))
            coarse_step = VERT_SCALE_STEPS[nearest]
            fine_step = coarse_step / 20.0
            new = cur + detents * fine_step
            # Clamp between the two surrounding coarse steps
            lower = VERT_SCALE_STEPS[max(nearest - 1, 0)]
            upper = VERT_SCALE_STEPS[min(nearest + 1, len(VERT_SCALE_STEPS) - 1)]
            new = clamp(new, lower, upper)
        else: 
            nearest = min(range(len(VERT_SCALE_STEPS)), key=lambda i: abs(VERT_SCALE_STEPS[i] - cur))
            new_idx = clamp(nearest + detents, 0, len(VERT_SCALE_STEPS) - 1)
            new = VERT_SCALE_STEPS[new_idx]

        self.scope.write(f"CH{ch}:SCALE {new}")
        print(f"[SCOPE] CH{ch} vertical scale ({'fine' if self._vert_fine else 'coarse'}): {cur:.3e} -> {new:.3e} V/div")

    def adjust_horizontal_scale(self, detents: int) -> None:
        cur = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        nearest = min(range(len(HORIZ_SCALE_STEPS)),key=lambda i: abs(HORIZ_SCALE_STEPS[i] - cur))
        new_idx = int(clamp(nearest + detents, 0, len(HORIZ_SCALE_STEPS) - 1))
        new = HORIZ_SCALE_STEPS[new_idx]

        self.scope.write(f"HORIZONTAL:MODE:SCALE {new}")
        actual = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        print(
            f"[SCOPE] horizontal scale (coarse): "
            f"{cur:.3e} -> {actual:.3e} s/div"
        )

    def encoder_trigger_level(self, detents: int) -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        ab = "A"
        source: str = parse_resp(self.scope.query(f"TRIGGER:{ab}:EDGE:SOURCE?"), str)
        query = f"TRIGGER:{ab}:LEVEL:CH{source}"
        cur: float = parse_resp(self.scope.query(query + "?"), float)

        trigger_scale: float = 0.4
        new = cur + detents * trigger_scale
        new = clamp(new, -100.0, 100.0)

        self.scope.write(query + f" {new}")
        print(f"[SCOPE] trigger level (%): {cur:.2f} -> {new:.2f}")

    def next_trigger_slope(self) -> None:
        cur: str = parse_resp(self.scope.query("TRIGGER:A:EDGE:SLOPE?"), str).upper()
        new: str = ""
        match cur:
            case "RISE":
                new = "FALL"
            case "FALL":
                new = "EITHER"
            case "EITHER":
                new = "RISE"
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        self.scope.write(f"TRIGGER:A:EDGE:SLOPE {new}")

    # Toggle the scope's Run/Stop state
    def toggle_run_stop(self) -> None:
        resp = self.scope.query("ACQUIRE:STATE?").strip().upper()

        # Tek scopes may return RUN/STOP, ON/OFF, or 1/0
        if resp in ("RUN", "ON", "1"):
            self.scope.write("ACQUIRE:STATE STOP")
            print("[SCOPE] Run/Stop -> STOP")
            return
        else:
            self.scope.write("ACQUIRE:STATE RUN")
            print("[SCOPE] Run/Stop -> RUN")
            return
        
    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.write("AUTOSET EXECUTE")
        print("[SCOPE] AutoSet executed")

    # Toggle the scope's Fast Acquire state
    def toggle_fast_acquire(self) -> None:
        resp = self.scope.query("FASTACQ:STATE?").strip().upper()

        # Tek scopes may return headers, e.g. ":FASTACQ:STATE 1"
        if resp.endswith("1") or resp.endswith("ON"):
            self.scope.write("FASTACQ:STATE OFF")
            print("[SCOPE] Fast Acquire -> OFF")
            return
        else:
            self.scope.write("FASTACQ:STATE ON")
            print("[SCOPE] Fast Acquire -> ON")
            return

    # UART event handler
    def handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V80, VP1/VP0, HP1/HP0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        # Channel Selection
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60", "V70", "V80"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V80' -> 8
            self.set_channel_display(ch)
            return

        # Encoder VP1 rotation: vertical position of current active channel
        if msg_id == "VP1":
            detents = int(val)  # should be +1 / -1
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder HP1 rotation: horizontal position (global)
        if msg_id == "HP1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return

        # Encoder VS1 rotation: vertical scale of current source channel (1/2/5 steps)
        if msg_id == "VS1":
            detents = int(val)
            if detents: 
                self.adjust_vertical_scale(-detents)
            return
        
        # Encoder HS1 rotation: horizontal timebase scale (1/2/4 steps)
        if msg_id == "HS1":
            detents = int(val)
            if detents: 
                self.adjust_horizontal_scale(-detents)
            return

        # VS0: toggle fine mode for vertical scale encoder
        if msg_id == "VS0":
            if int(val) == 1: 
                self._vert_fine = not self._vert_fine
                print(f"[SCOPE] Vertical scale fine mode -> {'ON' if self._vert_fine else 'OFF'}")
            return
        
        # trigger level encoder
        if msg_id == "TL1":
            detents = int(val)
            if detents:
                self.encoder_trigger_level(detents)
            return
        # trigger level push
        if msg_id == "TL0":
            self.scope.write("TRIGGER:A: SETLevel")
            return

        # trigger force
        if msg_id == "TF0":
            self.scope.write("TRIGGER FORCE")
            return

        # trigger slope type
        if msg_id == "TS0":
            self.next_trigger_slope()
            return

        # trigger mode
        if msg_id == "TM0":
            cur: str = parse_resp(self.scope.query("TRIGGER:A:MODE?"), str).upper()
            new: str = "AUTO" if cur == "NORMAL" else "NORMAL"
            self.scope.write(f"TRIGGER:A:MODE {new}")
            return

        # Run/Stop button
        if msg_id == "AR0":
            self.toggle_run_stop()
            return
        
        # Fast Acquire button
        if msg_id == "AF0":
            self.toggle_fast_acquire()
            return

        # AutoSet button
        if msg_id == "XA0":
            self.autoset()
            return

def main() -> None:
    scope: MessageBasedResource = connect_scope()
    print("Connected scope:", scope.query("*IDN?").strip())

    bridge = connect_uart()
    controller = Controller(scope)
    controller.seed_current_state_from_scope()

    try:
        while True:
            raw = bridge.get()
            if raw:
                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"Bad UART message {raw!r}: {e}")
                    continue

                controller.handle_input(inp)

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        scope.close()
        bridge.close()


if __name__ == "__main__":
    main()