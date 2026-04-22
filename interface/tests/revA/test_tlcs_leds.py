from machine import Pin
import utime

# =========================
# Configuration
# =========================
TLC_DIN = 19
TLC_CLK = 18
TLC_LAT = 22
TLC_OE  = 15
NUM_TLC_CHIPS = 3
LED_BRIGHTNESS = 300

LED_MAP = {
    "TL1_B": 0, "TL1_G": 1, "TL1_R": 2, "AR0_B": 3, "AR0_G": 4, "AR0_R": 5, "AS0": 6, "AH0": 7,
    "AF0": 8, "AC0": 9, "KA1": 10, "KA0": 11, "KB1": 12, "KB0": 13, "TF0_R": 14, "TF0_T": 15,
    "TS0_UP": 16, "TS0_DN": 17, "TM0_A": 18, "TM0_N": 19, "VS0": 20, "VM0": 21, "VR0": 22,
    "VB0": 23, "VP1_B": 24, "VP1_G": 25, "VP1_R": 26, "VS1_B": 27, "VS1_G": 28, "VS1_R": 29,
    "V10_B": 30, "V10_G": 31, "V10_R": 32, "V20_B": 33, "V20_G": 34, "V20_R": 35, "V30_B": 36,
    "V30_G": 37, "V30_R": 38, "V40_B": 39, "V40_G": 40, "V40_R": 41, "V50_B": 42, "V50_G": 43,
    "V50_R": 44, "V60_B": 45, "V60_G": 46, "V60_R": 47, "V70_B": 48, "V70_G": 49, "V70_R": 50,
    "V80_B": 51, "V80_G": 52, "V80_R": 53, "HZ0": 54, "M10_B": 55, "M10_G": 56, "M10_R": 57,
    "M20_B": 58, "M20_G": 59, "M20_R": 60, "M30_B": 61, "M30_G": 62, "M30_R": 63, "M40_B": 64,
    "M40_G": 65, "M40_R": 66, "SP_CON": 67, "HS0": 68, "T_OFF": 69
}


class TLC5947:
    def __init__(self, din, clk, lat, oe, num_drivers=1):
        self.din = Pin(din, Pin.OUT)
        self.clk = Pin(clk, Pin.OUT)
        self.lat = Pin(lat, Pin.OUT)
        self.oe  = Pin(oe, Pin.OUT, value=1)

        self.n = num_drivers * 24
        self.buffer = [0] * self.n
        self.dirty = True

        self.write()
        self.oe.value(0)

    def set_pin(self, pin, value):
        pwm = LED_BRIGHTNESS if value else 0
        if 0 <= pin < self.n:
            idx = (self.n - 1) - pin
            if self.buffer[idx] != pwm:
                self.buffer[idx] = pwm
                self.dirty = True

    def clear_all(self):
        for i in range(self.n):
            self.buffer[i] = 0
        self.dirty = True

    def set_all(self, value):
        pwm = LED_BRIGHTNESS if value else 0
        for i in range(self.n):
            self.buffer[i] = pwm
        self.dirty = True

    def write(self):
        if not self.dirty:
            return
        self.lat.value(0)
        for val in self.buffer:
            for i in range(11, -1, -1):
                self.clk.value(0)
                self.din.value((val >> i) & 1)
                self.clk.value(1)
        self.clk.value(0)
        self.lat.value(1)
        utime.sleep_us(10)
        self.lat.value(0)
        self.dirty = False


print("\n=== TLC COMBINED BUS + INDICATOR ID TEST ===")
print("DIN=GP{} CLK=GP{} LAT=GP{} OE=GP{}".format(TLC_DIN, TLC_CLK, TLC_LAT, TLC_OE))
print("TLC chips: {}".format(NUM_TLC_CHIPS))
print("Total channels: {}".format(NUM_TLC_CHIPS * 24))

tlc = TLC5947(TLC_DIN, TLC_CLK, TLC_LAT, TLC_OE, num_drivers=NUM_TLC_CHIPS)

# -------------------------
# Bus / alive portion
# -------------------------
print("\n--- BUS / ALIVE CHECK ---")

print("All OFF")
tlc.clear_all()
tlc.write()
utime.sleep_ms(500)

print("All ON")
tlc.set_all(1)
tlc.write()
utime.sleep_ms(1000)

print("All OFF")
tlc.clear_all()
tlc.write()
utime.sleep_ms(500)

print("Quick channel chase")
for ch in range(tlc.n):
    tlc.clear_all()
    tlc.set_pin(ch, 1)
    tlc.write()
    utime.sleep_ms(5)

tlc.clear_all()
tlc.write()
utime.sleep_ms(300)

print("--- BUS / ALIVE CHECK COMPLETE ---")

# -------------------------
# Named indicator ID portion
# -------------------------
print("\n--- NAMED INDICATOR ID TEST ---")
print("Commands: n = next, p = previous, q = quit\n")

items = sorted(LED_MAP.items(), key=lambda item: item[1])
idx = 0

while 0 <= idx < len(items):
    name, ch = items[idx]

    tlc.clear_all()
    tlc.set_pin(ch, 1)
    tlc.write()

    print("Testing {} -> channel {} ({}/{})".format(name, ch, idx + 1, len(items)))
    cmd = input("Command [n/p/q]: ").strip().lower()

    if cmd == "q":
        print("Named indicator test stopped by user.")
        break
    elif cmd == "p":
        if idx > 0:
            idx -= 1
        else:
            print("Already at first indicator.")
    else:
        idx += 1

# Final all off
tlc.clear_all()
tlc.write()

print("\n=== TLC COMBINED TEST COMPLETE ===")