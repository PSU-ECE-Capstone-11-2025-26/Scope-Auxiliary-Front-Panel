from machine import Pin, UART
uart = UART(0, 115200, tx=Pin(16), rx=Pin(17))
print("Pico Listening on Hardware UART...")

while True:
    if uart.any():
        msg = uart.readline().decode().strip()
        print(f"Pico Received: {msg}")
        uart.write(f"ACK:{msg}\n") # Send a receipt back to the Pi 4