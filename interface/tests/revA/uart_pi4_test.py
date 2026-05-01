import serial
import time

# Update '/dev/serial0' to whatever UART port the Pi 4 is using
ser = serial.Serial('/dev/serial0', 115200, timeout=1) 

print("Sending Ping to Pico...")
ser.write(b"HELLO_PICO\n")
time.sleep(0.1)

response = ser.readline().decode('utf-8').strip()
print(f"Pi 4 Received: {response}")