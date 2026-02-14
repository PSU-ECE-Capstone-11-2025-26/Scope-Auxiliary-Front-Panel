import time

import pyvisa
from pyvisa.resources import MessageBasedResource

from tekafp.input import Input # Decoder for incoming UART messages
from tekafp.uart import UARTBridge 


# UART config
PORT = "/dev/serial0" # Raspberry Pi primary UART device
BAUD = 115200

# Scope config
PYVISA_BACKEND = "@py"  # Use pyvisa-py backend
SCOPE_TIMEOUT_MS = 5000 # VISA read timeout

# Tuning knobs for “feel”
# Control how much each encoder detent moves the scope setting
VERT_STEP_DIVS = 0.10  # Vertical position step (divisions) per encoder detent 
HORIZ_STEP_PCT = 1.0  # Horizontal position step % per detent

# Find and connect to the first USB scope that PyVisa can see. 
# Returns an open VISA instrument handle for the scope (MessageBasedResource)
def connect_scope() -> MessageBasedResource:
    # Create a VISA resource manager using the chosen backend
    rm = pyvisa.ResourceManager(PYVISA_BACKEND)

    # Keep trying until a USB instrument is detected
    while True:
        # List all VISA resources the backend can see
        resources = rm.list_resources()
        
        # Filter down to just USB devices
        usb = [r for r in resources if r.startswith("USB")]

        # If we found at least one USB resource, connect to the first one
        if usb:
            scope: MessageBasedResource = rm.open_resource(usb[0])

            # Configure standard VISA timeouts and line endings
            scope.timeout = SCOPE_TIMEOUT_MS
            scope.write_termination = "\n"
            scope.read_termination = "\n"

            # Ensure horizontal position behaves like the front panel knob
            # Turning delay mode off makes HORIZONTAL:POSITION act as expected
            scope.write("HORIZONTAL:DELAY:MODE OFF")

            # Return the connected, configured scope handle
            return scope

        # No scope found, wait and try again
        print("No USB scope found, retrying in 2s...")
        time.sleep(2)

# Connect to the UART bridge (Pico <-> Pi serial port)
# Returns: connected UARTBridge instance (UARTBridge)
def connect_uart() -> UARTBridge:
    # Create UART bridge object. 
    # Timeout affects reads, write_timeout affects writes. 
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)

    # Attempt to open serial port and start background read thread
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    
    # Log successful connection
    print(f"Connected UART: {PORT} @ {BAUD}")

    return bridge

# Clamp a numeric value into a specified range [lo, hi]
# Ex: clamp(200,0,100) -> 100
def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))

# Translates parsed UART input messages into scope control commands
class Controller:
    def __init__(self, scope: MessageBasedResource) -> None:
        # Store VISA handle to the scope so we can send SCPI commands
        self.scope: MessageBasedResource = scope

        # Track on/off state for channels CH1 to CH6
        # This is used to decide which channel is "active" for vertical moves
        self.ch_enabled = {ch: False for ch in range(1, 7)}

        # The currently "active" channel (default to 1)
        self.active_ch = 1  

    # Enable/disable a channel display on the scope
    # Also updates "active channel" tracking
    def set_channel_display(self, ch: int, on: bool) -> None:

        # SCPI command: set channel state (1=on, 0=off)
        self.scope.write(f"DISPLAY:GLOBAL:CH{ch}:STATE {1 if on else 0}")

        # Record state locally so we can manage active channel logic
        self.ch_enabled[ch] = on

        # If turning ON a channel, make it active
        if on:
            self.active_ch = ch
        else:
            # If turning OFF the active channel, select another enabled one
            if self.active_ch == ch:
                enabled = [c for c, state in self.ch_enabled.items() if state]
                self.active_ch = enabled[0] if enabled else 1

        # Pring a status line for debugging
        print(f"[SCOPE] CH{ch} display -> {'ON' if on else 'OFF'} (active_ch={self.active_ch})")

    # Move vertical position of the active channel by detents * VERT_STEP_DIVS 
    def adjust_vertical_position(self, detents: int) -> None:
        ch = self.active_ch

        # Query current vertical position 
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        # Apply detent step size
        new = cur + detents * VERT_STEP_DIVS

        # Clamp to a reasonable range 
        new = clamp(new, -10.0, 10.0)

        # Write the new position 
        self.scope.write(f"CH{ch}:POSITION {new}")

        # Print debug output
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    # Move horizontal position by detents * HORIZ_STEP_PCT
    # Horizontal position is approximately 0 to 100% across the screen, so we use percentage steps here
    def adjust_horizontal_position(self, detents: int) -> None:        
        # Query current horizontal position (%)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        # Apply step
        new = cur + detents * HORIZ_STEP_PCT

        # Clamp to valid 0 to 100%
        new = clamp(new, 0.0, 100.0)

        # Write the new position 
        self.scope.write(f"HORIZONTAL:POSITION {new}")

        # Print debug output
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    # UART event handler
    # Dispatch a parsed input event to the correct scope action
    # Expected ID patterns: 
        # V10 to V60 for channel toggles
        # KA1 for encoder 1 (vertical position)
        # KB1 for encoder 2 (horizontal position)
    def handle_input(self, inp: Input) -> None:
        # Normalize ID to string
        msg_id = str(inp.id)

        # Value is either 0/1 for toggles or +/-1 for encoders
        val = inp.value

        # Channel toggles: V10 to V60 => CH1 to CH6 display on/off
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V60' -> 6
            on = bool(int(val))  # Ensure it becomes a proper boolean
            self.set_channel_display(ch, on)
            return

        # Encoder A rotation: adjust vertical position of active channel
        if msg_id == "KA1":
            detents = int(val)  # should be +/-1 for encoder direction
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder B rotation: adjust horizontal position
        if msg_id == "KB1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return


# Connects to scope and connects to UART
# Loops forever:
    # Get next UART message (already buffererd by UARTBridge thread)
    # Parse it into an Input object
    # Apply mappings to scope
def main() -> None:
    # Connect to scope and confirm identity
    scope: MessageBasedResource = connect_scope()
    print("Connected scope:", scope.query("*IDN?").strip())

    # Connect to UART bridge
    bridge = connect_uart()

    # Create the controller that maps UART inputs to scope actions
    controller = Controller(scope)

    try:
        while True:
            # Get one inbound UART message from the bridge
            # Under the hood, the bridge's thread is reading serial.readline()
            # and pushing completed lines into an internal queue 
            # The get() method pops one message from that queue, or returns None if the queue is empty.
            raw = bridge.get()

            # bridge.get() returns bytes or None (if no data available)
            if raw:
                try:
                    # Decode raw bytes into the structured Input object (parses the message format and extracts ID and value)
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    # If it doesn't parse, print error and continue
                    print(f"Bad UART message {raw!r}: {e}")
                    continue

                # Apply the action on the scope
                controller.handle_input(inp)

    except KeyboardInterrupt:
        # Allow clean Ctrl+C exit
        print("\nExiting...")
    finally:
        # Always close resources so threads/USB handles are released cleanly
        scope.close()
        bridge.close()


if __name__ == "__main__":
    main()
