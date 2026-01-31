"""
- This simple scripts reads UART messages from a connected device (in this case, a Raspberry Pi Pico)
- and prints out the parsed message ID and value using the tekafp UART reading and decoding library created by Andrew. 
- Connections: GP16 (TX) on Pico to GPIO 15 (RXD) on Pi 4 with a common ground.
- Works perfectly. 
"""


from tekafp.input import Input
from tekafp.uart import UARTBridge

PORT = "/dev/serial0"
BAUD = 115200

def main():
    bridge = UARTBridge(PORT, baudrate=BAUD)

    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    
    print(f"Connected UART: {PORT} @ {BAUD}")

    while True:
        bridge.read() # Reads one line into bridge.queue

        # Drain queue (in case multiple lines arrived quickly)
        # Doesn't leave unread UART data sitting around.
        while not bridge.queue.empty():
            raw = bridge.queue.get()
            try: 
                inp = Input.from_bytes(raw)
            except Exception as e:
                print(f"Bad UART message {raw!r}: {e}")
                continue

            print(f"ID={inp.id} value={inp.value}")

if __name__ == "__main__":
    main()