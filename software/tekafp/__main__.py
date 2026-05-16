import argparse
import threading
import time
from time import sleep

import pyvisa
from pyvisa import VisaIOError
from pyvisa.resources import MessageBasedResource

from tekafp.api_server import (
    RawPacket,
    get_raw_packet,
    run_api_server,
    send_packet_data,
    startup_event,
)
from tekafp.api_server.error import APIError
from tekafp.api_server.packets import (
    ErrorPacketData,
    MacroRecordPacketData,
    PacketData,
    ScopeActionPacketData,
    ScopeInfoPacketData,
    ScopeListPacketData,
)
from tekafp.input import Input
from tekafp.uart import MockUARTBridge, UARTBridge
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
    500e-6, 1e-3, 2e-3, 5e-3,
    10e-3, 20e-3, 50e-3,
    100e-3, 200e-3, 500e-3,
    1.0, 2.0, 5.0,
    10.0, 20.0, 50.0,
    100.0,
]

# Horizontal scale sequences follow a 1/2/4 pattern per Tektronix spec
# e.g. 1ns, 2ns, 4ns, 10ns, 20ns, 40ns, 100ns, ...
HORIZ_SCALE_STEPS = [
    200e-12, 400e-12,
    1e-9, 2e-9, 4e-9,
    10e-9, 20e-9, 40e-9,
    100e-9, 200e-9, 400e-9,
    1e-6, 2e-6, 4e-6,
    10e-6, 20e-6, 40e-6,
    100e-6, 200e-6, 400e-6,
    1e-3, 2e-3, 4e-3,
    10e-3, 20e-3, 40e-3,
    100e-3, 200e-3, 400e-3,
    1.0, 2.0, 4.0, 10.0, 20.0, 40.0, 
    100.0, 200.0, 400.0, 
    1000.0,
]


def connect_uart(mock: bool = False) -> UARTBridge:
    if mock:
        return MockUARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


class Controller:
    def __init__(self, scope: MessageBasedResource, bridge: UARTBridge) -> None:
        self.scope: MessageBasedResource = scope
        self.bridge: UARTBridge = bridge 

        self._channels: dict[int, bool] = {ch: False for ch in range(1, 9)}
        self._source_channel: int = 0
        self._vert_fine: bool = False # fine mode toggle for vertical scale

        self._fast_acquire: bool = False

    def get_scope_channel_state(self, channel: int) -> bool:
        resp = self.scope.query(f"DISPLAY:GLOBAL:CH{channel}:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def sync_all_channels_from_scope(self) -> None:
        highest = 0
        for ch in range(1, 9):
            actual = self.get_scope_channel_state(ch)
            self._channels[ch] = actual
            self.send_channel_led(ch, actual)
            if actual:
                highest = ch
            print(f"[INIT] CH{ch} -> {actual}")

        # Chooses highest enabled channel as the active selected channel
        self._source_channel = highest

        self.set_scope_selected_source()
        self.send_selected_channel_leds()
        self.sync_fast_acquire_from_scope(force=True)

    def sync_all_changed_channels_from_scope(self) -> None:
        any_changed = False

        for ch in range(1,9):
            actual = self.get_scope_channel_state(ch)
            if self._channels[ch] != actual:
                self._channels[ch] = actual
                self.send_channel_led(ch, actual)
                print(f"[SYNC] CH{ch} -> {actual}")
                any_changed = True

                if actual:
                    self._source_channel = ch
                    self.scope.write(f"DISPLAY:SELECT:SOURCE CH{self._source_channel}")
                    self.send_selected_channel_leds()

        # Keep selected source sane if current source is now off
        if self._source_channel != 0 and not self._channels[self._source_channel]:
            highest = 0
            for k, v in self._channels.items():
                if v:
                    highest = k

            self._source_channel = highest

            self.set_scope_selected_source()
            self.send_selected_channel_leds()

        # If nothing changed, stay quiet
        if any_changed:
            print("[SYNC] Full channel sync pass complete")

    # Per-channel RGB color (R,G,B)
    CHANNEL_COLORS: dict[int, tuple[int, int, int]] = {
        1: (1, 1, 0),  # Yellow
        2: (0, 1, 1),  # Cyan
        3: (1, 0, 0),  # Red
        4: (0, 1, 0),  # Lime Green
        5: (1, 1, 0),  # Orange approximation
        6: (0, 0, 1),  # Blue
        7: (1, 0, 1),  # Purple
        8: (0, 1, 0),  # Forest Green approximation
    }

    def send_channel_led(self, channel: int, state: bool) -> None:
        # Send indicator update back to Pico
        if channel not in range(1,9):
            return

        r, g, b = self.CHANNEL_COLORS[channel]

        if not state: 
            r, g, b = 0, 0, 0

        msgs = [
            f"IV{channel}0_R:{r}\n".encode("utf-8"), 
            f"IV{channel}0_G:{g}\n".encode("utf-8"),
            f"IV{channel}0_B:{b}\n".encode("utf-8"),
        ]

        for msg in msgs:
            self.bridge.write_sync(msg)
            print(f"[UART->PICO] {msg.decode().strip()}")


    def send_selected_channel_leds(self) -> None: 
        # Two RGB LEDs used to show the active selected channel: 
        # VP1_RGB and VS1_RGB should always match the selected channel color
        
        r, g, b = self.CHANNEL_COLORS.get(self._source_channel, (0,0,0))

        msgs = [
            f"IVP1_R:{r}\n".encode("utf-8"),
            f"IVP1_G:{g}\n".encode("utf-8"),
            f"IVP1_B:{b}\n".encode("utf-8"),
            f"IVS1_R:{r}\n".encode("utf-8"),
            f"IVS1_G:{g}\n".encode("utf-8"),
            f"IVS1_B:{b}\n".encode("utf-8"),
        ]

        for msg in msgs:
            self.bridge.write_sync(msg)
            print(f"[UART->PICO] {msg.decode().strip()}")

    def get_scope_selected_source(self) -> int:
        resp = self.scope.query("DISPLAY:SELECT:SOURCE?").strip().upper()

        if resp.endswith("NONE"):
            return 0

        for ch in range(1, 9):
            if resp.endswith(f"CH{ch}") or f"CH{ch}" in resp:
                return ch

        print(f"[SYNC] Unknown selected source response: {resp}")
        return self._source_channel


    def set_scope_selected_source(self) -> None:
        if self._source_channel == 0:
            self.scope.write("DISPLAY:SELECT:SOURCE NONE")
        else:
            self.scope.write(f"DISPLAY:SELECT:SOURCE CH{self._source_channel}")


    def sync_selected_source_from_scope(self) -> None:
        actual_source = self.get_scope_selected_source()

        if actual_source != self._source_channel:
            self._source_channel = actual_source
            self.send_selected_channel_leds()
            print(f"[SYNC] selected source -> CH{actual_source}")

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
            self._source_channel = highest
        elif last_state:
            # enabled => set as source
            self._source_channel = channel
        else:
            # disabled => enable, set as source
            self._channels[channel] = True
            self._source_channel = channel

        self.set_scope_selected_source()
        self.send_selected_channel_leds()

        if last_state != self._channels[channel]:
            self.scope.write(
                f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self._channels[channel])}"
            )
            self.send_channel_led(channel, self._channels[channel]) 

        print(
            f"[SCOPE] CH{channel} display -> {self._channels[channel]} (source={self._source_channel})"  # noqa: E501
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical position.")
            return
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"CH{ch}:POSITION {new}")
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def center_vertical_position(self) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical center.")
            return

        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])
        self.scope.write(f"CH{ch}:POSITION 0")
        print(f"[SCOPE] CH{ch} vertical position centered: {cur:.3f} -> 0.000")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.write(f"HORIZONTAL:POSITION {new}")
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    def center_horizontal_position(self) -> None:
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])
        self.scope.write("HORIZONTAL:POSITION 50")
        print(f"[SCOPE] horizontal position centered (%): {cur:.2f} -> 50.00")

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
        current = self.get_scope_fast_acquire_state()
        new_state = not current

        self.scope.write(f"ACQUIRE:FASTACQ:STATE {int(new_state)}")

        self._fast_acquire = new_state
        self.send_fast_acquire_led(new_state)

        print(f"[SCOPE] Fast Acquire -> {'ON' if new_state else 'OFF'}")

    def get_scope_fast_acquire_state(self) -> bool:
        resp = self.scope.query("ACQUIRE:FASTACQ:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def send_fast_acquire_led(self, state: bool) -> None:
        msg = f"IAF0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        print(f"[UART->PICO] {msg.decode().strip()}")

    def sync_fast_acquire_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_fast_acquire_state()

        if force or self._fast_acquire != actual:
            self._fast_acquire = actual
            self.send_fast_acquire_led(actual)
            print(f"[SYNC] Fast Acquire -> {actual}")

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

        # Encoder VP0 press: center vertical position of current active channel
        if msg_id == "VP0":
            if int(val) == 1:
                self.center_vertical_position()
            return

        # Encoder HP1 rotation: horizontal position (global)
        if msg_id == "HP1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return

        # Encoder HP0 press: center horizontal position globally
        if msg_id == "HP0":
            if int(val) == 1:
                self.center_horizontal_position()
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
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mock", action="store_true", help="Run in mock mode")
    parser.add_argument(
        "-a",
        "--auto",
        action="store_true",
        help="Automatically connect to the first available scope",
    )
    args = parser.parse_args()
    # internal setup
    bridge = connect_uart(args.mock)
    print("Starting WebSocket API thread...")
    api_thead = threading.Thread(target=run_api_server, daemon=True)
    api_thead.start()
    startup_event.wait()

    # ctrl setup
    rm: pyvisa.ResourceManager = pyvisa.ResourceManager(PYVISA_BACKEND)
    scopes: dict[str, Controller] = {}

    def send_scope_connection_led(state: bool) -> None:
        msg = f"SP_CON:{int(state)}\n".encode("utf-8")
        bridge.write_sync(msg)
        print(f"[UART->PICO] {msg.decode().strip()}")

    def connect_to_scope(resource_name: str) -> None:
        try:
            scope: MessageBasedResource = rm.open_resource(
                resource_name,
                resource_pyclass=MessageBasedResource,
                timeout=SCOPE_TIMEOUT_MS,
                write_termination="\n",
                read_termination="\n",
            )
        except (VisaIOError, ValueError) as err:
            send_packet_data(
                ErrorPacketData(
                    resource_name, APIError.CONNECTION_ERROR, error_str=str(err)
                )
            )
            return
        # Make sure we're in a mode where horizontal position behaves like the
        # front panel knob
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        scope.write("HORIZONTAL:DELAY:MODE OFF")
        idn = scope.query("*IDN?").strip()
        print("Connected ctrl:", idn)

        ctrl = Controller(scope, bridge)
        ctrl.sync_all_channels_from_scope()
        scopes[resource_name] = ctrl
        send_scope_connection_led(True)

    def auto_connect_first_scope() -> None:
        resources = rm.list_resources("(USB?*::INSTR|TCPIP?*::INSTR)")

        if not resources:
            print("[AUTO] No scopes found")
            return

        first = resources[0]
        print(f"[AUTO] Connecting to: {first}")

        if first not in scopes:
            connect_to_scope(first)

    def handle_packet(packet: RawPacket) -> None:
        for pd in packet["data"]:
            data = PacketData.decode(pd)
            match data:
                case ScopeActionPacketData(action=a):
                    print(f"Received packet action='{a}'")
                    match a:
                        case "enable":
                            if data.resource_name not in scopes:
                                print(f"enabling scope {data.resource_name}")
                                if args.mock:
                                    scopes[data.resource_name] = None
                                    send_packet_data(
                                        ScopeInfoPacketData(
                                            data.resource_name,
                                            "TEKTRONIX,MSO58,C012345,CF:91.1CT FV:1.0.1.8",
                                            8,
                                        )
                                    )
                                else:
                                    connect_to_scope(data.resource_name)
                        case "disable":
                            if data.resource_name in scopes:
                                print(f"disabling scope {data.resource_name}")
                                if args.mock:
                                    del scopes[data.resource_name]
                                else:
                                    c = scopes.pop(data.resource_name)
                                    c.scope.close()
                            else:
                                print(
                                    f"scope {data.resource_name} not enabled: ignoring"
                                )
                        case "list":
                            if args.mock:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            "USB0::0x0699::0x0363::C102912::INSTR": False,
                                            "USB0::0x0699::0x0408::B011823::INSTR": False,
                                        }
                                    )
                                )
                            else:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            r: r in scopes
                                            for r in rm.list_resources(
                                                "(USB?*::INSTR|TCPIP?*::INSTR)"
                                            )
                                        }
                                    )
                                )
                        case _:
                            print(f"Unknown action: {a}")
                case MacroRecordPacketData():
                    if data.record:
                        pass
                        # TODO record for slot data.slot
                        # If a different slot is recording, stop that one first.
                    else:
                        pass # TODO stop recording for slot data.slot
                case _:
                    print(f"Unknown or incorrect packet type {data.type}")

    if args.auto:
        auto_connect_first_scope()

    try:
        last_sync = time.monotonic()
        last_input = 0.0 # no input yet
        sync_period_s = 0.05

        while True:
            raw = bridge.get()
            if not args.mock and scopes and raw:
                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"Bad UART message {raw!r}: {e}")
                    continue

                # iterating all scopes here would allow control of multiple at once
                ctrl = list(scopes.values())[0]
                ctrl.handle_input(inp)
                last_input = time.monotonic()

            new_packet = get_raw_packet()
            if new_packet:
                handle_packet(new_packet)

            now = time.monotonic()
            if not args.mock and scopes and now - last_sync > sync_period_s and now - last_input > 0.05:
                ctrl = list(scopes.values())[0]
                ctrl.sync_all_changed_channels_from_scope()
                ctrl.sync_selected_source_from_scope()
                ctrl.sync_fast_acquire_from_scope()
                last_sync = now

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        for ctrl in scopes.values():
            if ctrl:
                ctrl.scope.close()
        bridge.close()


if __name__ == "__main__":
    main()
