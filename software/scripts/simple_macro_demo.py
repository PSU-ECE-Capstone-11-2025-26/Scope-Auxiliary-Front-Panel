"""
simple_macro_demo.py

Macro proof-of-concept using existing hardware.

Current demo UX:
- Uses CH1 toggle message (V10) as the macro button
- Press CH1: start recording
- Press CH1 again: stop recording
- Press CH1 again: playback recorded events (1s delay between events)

Notes:
- A "macro" is just a recorded sequence of input events
- In this demo, each event is stored as the raw UART bytes that came from the Pico 
- Later, playback re-decodes those bytes into Input objects and re-applies them


Playback applies actions to the scope by calling Controller.handle_input().
"""

import time
from typing import List, Optional

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

# Macro behavior
MACRO_ID = "V10"          # CH1 message treated as macro button
PLAYBACK_DELAY_S = 1.0    # demo delay between events

# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10
HORIZ_STEP_PCT = 1.0


# Connections
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

            # Make horizontal position behave like front-panel knob
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


# Scope controller mapping
# This is not "macro logic", it's the action layer
# Macro playback simply feeds events into this same code path
class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        self.scope = scope
        self.ch_enabled = {ch: False for ch in range(1, 7)}
        self.active_ch = 1

    def set_channel_display(self, ch: int, on: bool) -> None:
        self.scope.write(f"DISPLAY:GLOBAL:CH{ch}:STATE {1 if on else 0}")
        self.ch_enabled[ch] = on

        if on:
            self.active_ch = ch
        else:
            if self.active_ch == ch:
                enabled = [c for c, state in self.ch_enabled.items() if state]
                self.active_ch = enabled[0] if enabled else 1

        print(f"[SCOPE] CH{ch} display -> {'ON' if on else 'OFF'} (active_ch={self.active_ch})")

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self.active_ch
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = clamp(cur + detents * VERT_STEP_DIVS, -10.0, 10.0)
        self.scope.write(f"CH{ch}:POSITION {new}")
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def adjust_horizontal_position(self, detents: int) -> None:
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = clamp(cur + detents * HORIZ_STEP_PCT, 0.0, 100.0)
        self.scope.write(f"HORIZONTAL:POSITION {new}")
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    # This function is the "execution engine" for events
    # Real-time UART events call this
    # Macro playback also calls this
    # I.E. macros replay the same actions as if the user did them live
    def handle_input(self, inp: Input) -> None:
        msg_id = str(inp.id)
        val = inp.value

        # Channel toggles: V10..V60 => CH1..CH6 on/off
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60"):
            ch = int(msg_id[1])
            on = bool(int(val))
            self.set_channel_display(ch, on)
            return

        # Encoder A rotation -> vertical position
        if msg_id == "KA1":
            detents = int(val)
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder B rotation -> horizontal position
        if msg_id == "KB1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return


# Macro state machine
# This is the main piece we're going to reuse later with a touchscreen UI
class MacroDemo:
    def __init__(self, controller: Controller) -> None:
        self.controller = controller

        # Are we currently recording a macro?
        # When recording == True, we save incoming UART events into self.macro
        self.recording: bool = False

        # The macro itself:
            # This is the "stored sequence"
            # Each element is ONE raw UART line (bytes) exactly as received from UARTBridge.get()
            # This means the macro is independent of the Input parser, it's just raw data
        self.macro: List[bytes] = []

        # Used to detect macro button state changes, because CH buttons are toggles
        # We want "macro button activated" when V10 changes from 0 to 1 or from 1 to 0
        self._last_macro_val: Optional[int] = None

        # Prevent weird interactions
        # We don't want playback events to get recorded into the macro again
        self._playing_back: bool = False

    def _is_macro_toggle(self, inp: Input) -> bool:
        # Decides whether a given Input should be treated as "macro button toggled"
        # Because CH buttons are toggle-type events, you'll see values like 0/1
        # We treat any changes from 0 to 1 or 1 to 0 as a macro "press"
        if str(inp.id) != MACRO_ID:
            return False

        try:
            v = int(inp.value)
        except Exception:
            return False

        # First time we ever see V10:
            # We set last value
            # And trigger macro recording immediately
        if self._last_macro_val is None:
            self._last_macro_val = v
            return True

        # If the value changed since last time, it counts as an activation
        changed = (v != self._last_macro_val)

        # Update last value so we can detect the next change
        self._last_macro_val = v

        return changed

    def handle_uart_raw(self, raw: bytes) -> None:
        # This is the entry point for every UART line received
        # 1) Decode raw bytes into an Input object
        # 2) If this event is the macro button, change macro state (start/stop/playback)
        # 3) Otherwise, if recording is ON, append raw bytes to self.macro
        # 4) Apply the event to the scope (controller.handle_input)

        # Step 1: parse raw UART bytes into a structured Input (id + value)
        try:
            inp = Input.from_bytes(raw)
        except Exception as e:
            print(f"[WARN] Bad UART message {raw!r}: {e}")
            return

        msg_id = str(inp.id)

        # Step 2: If this Input corresponds to macro control button (V10), 
        # handle macro state transitions. We don't treat it as a normal scope event
        if self._is_macro_toggle(inp):
            self._on_macro_button()
            return

        # Step 2b safety: even if V10 arrives but doesn't count as a "toggle", never record it and never apply it
        if msg_id == MACRO_ID:
            return

        # Step 3: If we are currently recording and we're not currently playing back, 
        # then we capture this UART line into the macro sequence
        # Note: 
            # We store raw bytes instead of Input objects
            # This means playback re-parses them later with Input.from_bytes()
        if self.recording and not self._playing_back:
            self.macro.append(raw)
            print(f"[REC] + {raw!r}")

        # Step 4: Apply the event immediately (real-time response)
        self.controller.handle_input(inp)

    def _on_macro_button(self) -> None:
        # Macro button behavior
        # This is the "macro state machine"
        # States are implicit from two booleans
            # self.recording
            # whether self.macro has items
        # Decision logic: 
            # If currently playing back: ignore (prevents recursion)
            # If currently recording: stop recording
            # Else if macro exists: playback
            # Else: start recording
        if self._playing_back:
            print("[MACRO] Ignored toggle during playback")
            return

        # If we were recording, this toggle ends the recording session
        if self.recording:
            self.recording = False

            # At this moment, self.macro contains all events recorded so far
            # This is our "captured macro"
            if self.macro:
                print(f"[MACRO] Recording stopped. {len(self.macro)} events saved.")
            else:
                print("[MACRO] Recording stopped, but no events were captured.")
            return

        # If we're not recording and we already have a macro saved, 
        # then the macro button means "run it"
        if self.macro:
            print(f"[MACRO] Playing back {len(self.macro)} events...")
            self.playback()
            print("[MACRO] Playback done.")
            return

        # Otherwise: no macro exists yet, so start a new recording session
        self.macro = []
        self.recording = True
        print("[MACRO] Recording started. Toggle CH1 again to stop.")

    # Run the recorded macro
    # In the real system, we'd want no delay between events
    # For this demo: 
        # we add a fixed 1 second delay between each event so it's visible
    # Implementation: 
        # Iterate stored raw UART lines in self.macro
        # Parse each line back into Input
        # Feed it to controller.handle_input(inp)
    def playback(self) -> None:
        self._playing_back = True
        try:
            for raw in self.macro:
                # Convert stored raw bytes back into Input objects
                # This makes playback use the exact same decode path as live UART input
                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"[WARN] Bad recorded message {raw!r}: {e}")
                    continue

                # Extra safety: never allow macro button events to be executed
                # Macro button should only control macro state, not be part of macro actions
                if str(inp.id) == MACRO_ID:
                    continue

                # Execute the event using the same path as live input
                self.controller.handle_input(inp)

                # Demo pacing
                time.sleep(PLAYBACK_DELAY_S)
        finally:
            self._playing_back = False


# Main loop
def main() -> None:
    scope = connect_scope()
    print("Connected scope:", scope.query("*IDN?").strip())

    bridge = connect_uart()
    controller = Controller(scope)
    demo = MacroDemo(controller)

    print("\nMacro demo:")
    print("- CH1 (V10) = macro button")
    print("- Press CH1: start recording")
    print("- Press CH1: stop recording")
    print("- Press CH1: playback with 1s delay\n")

    try:
        while True:
            # UARTBridge is already reading in the background thread
            # get() pops the next complete UART line from the inbound queue
            raw = bridge.get()

            # If we got a UART line, feed it to macro logic
            if raw:
                demo.handle_uart_raw(raw)

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        try:
            scope.close()
        except Exception:
            pass
        bridge.close()


if __name__ == "__main__":
    main()
