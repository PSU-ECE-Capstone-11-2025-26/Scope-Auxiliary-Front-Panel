import time

import pyvisa
from pyvisa.resources import MessageBasedResource

from tekafp.input import Input
from tekafp.uart import UARTBridge


# UART config
PORT = "/dev/serial0"
BAUD = 115200

# Scope config
PYVISA_BACKEND = "@py"
SCOPE_TIMEOUT_MS = 5000

# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10  # Vertical position step per encoder detent (+/-1)
HORIZ_STEP_PCT = 1.0  # Horizontal position step in percent (0..~100) per detent


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
    bridge = UARTBridge(PORT, baudrate=BAUD)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        self.scope: MessageBasedResource = scope

        # Track CH1..CH6 on/off state to support "current active channel"
        self.ch_enabled = {ch: False for ch in range(1, 7)}
        self.active_ch = 1  # Default if nothing has been enabled yet

    # Scope helpers
    def set_channel_display(self, ch: int, on: bool) -> None:
        # DISplay:GLObal:CH<x>:STATE {ON|OFF|0|1}
        self.scope.write(f"DISPLAY:GLOBAL:CH{ch}:STATE {1 if on else 0}")

        self.ch_enabled[ch] = on
        if on:
            self.active_ch = ch
        else:
            # If we turned off the active channel, pick another enabled one (lowest #)
            # else default to 1
            if self.active_ch == ch:
                enabled = [c for c, state in self.ch_enabled.items() if state]
                self.active_ch = enabled[0] if enabled else 1

        print(
            f"[SCOPE] CH{ch} display -> {'ON' if on else 'OFF'} (active_ch={self.active_ch})"  # noqa: E501
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self.active_ch
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

    # UART event handler
    def handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V60, KA1/KA0, KB1/KB0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        # Channel toggles: V10..V60 => CH1..CH6 display on/off
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V60' -> 6
            on = bool(int(val))
            self.set_channel_display(ch, on)
            return

        # Encoder 1 rotation => vertical position of current active channel
        if msg_id == "KA1":
            detents = int(val)  # should be +1 / -1
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder 2 rotation => horizontal position (global)
        if msg_id == "KB1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return

def main() -> None:
    scope: MessageBasedResource = connect_scope()
    print("Connected scope:", scope.query("*IDN?").strip())

    bridge = connect_uart()
    controller = Controller(scope)

    try:
        while True:
            # Reads one line into bridge.queue
            bridge.read()

            # Drain queue: if multiple lines arrived quickly, handle them all now
            while not bridge.queue.empty():
                raw = bridge.queue.get()

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


if __name__ == "__main__":
    main()
