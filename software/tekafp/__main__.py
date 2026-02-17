import time
from typing import List

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
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        self.scope: MessageBasedResource = scope

        # first item is LRU, last is MRU, therefore MRU is the active channel.
        # if a channel is in this list, it is enabled
        self._channel_lru: List[int] = []

    def is_channel_enabled(self, channel: int) -> bool:
        return channel in self._channel_lru

    @property
    def active_channel(self) -> int:
        """Get the currently active channel."""
        return 0 if len(self._channel_lru) == 0 else self._channel_lru[-1]

    # Scope helpers
    def set_channel_display(self, channel: int) -> None:
        state: bool = self.is_channel_enabled(channel)
        if state:
            # enabled
            if self.active_channel == channel:
                # enabled and active => disable it
                self._channel_lru.pop()
            else:
                # enabled and NOT active => select it
                self._channel_lru.remove(channel)
                self._channel_lru.append(channel)
        else:
            # disabled
            self._channel_lru.append(channel)
        state = self.is_channel_enabled(channel)
        self.scope.write(f"DISPLAY:GLOBAL:CH{channel}:STATE {1 if state else 0}")

        print(
            f"[SCOPE] CH{channel} display -> {'ON' if state else 'OFF'} (active_ch={self.active_channel})"  # noqa: E501
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self.active_channel
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
          V10..V80, KA1/KA0, KB1/KB0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        # Channel Selection
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60", "V70", "V80"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V60' -> 6
            self.set_channel_display(ch)
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
