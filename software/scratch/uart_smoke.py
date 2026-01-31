# A simple UART smoke test script.
# It opens a serial port and continuously reads lines,
# printing the raw bytes and the decoded string.
# Connections: GP16 (TX) on Pico to GPIO 15 (RXD) on Pi 4 with a common ground.
# Works perfectly. 

import serial

PORT = "/dev/serial0"
BAUD = 115200

with serial.Serial(PORT, BAUD, timeout=1) as ser:
    print(f"Listening on {PORT} at {BAUD} baud...")
    while True:
        line = ser.readline() # reads until '\n' or timeout
        if line:
            print(repr(line), "->", line.decode("utf-8", errors="replace").rstrip())