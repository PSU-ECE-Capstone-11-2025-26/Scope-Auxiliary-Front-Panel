from machine import Pin
import utime

# ---------------- Quadrature LUT ----------------
LUT = [0]*16
LUT[0b0001] = +1
LUT[0b0010] = -1
LUT[0b0100] = -1
LUT[0b0111] = +1
LUT[0b1000] = +1
LUT[0b1011] = -1
LUT[0b1101] = -1
LUT[0b1110] = +1

# ---------------- Encoder helpers ----------------
def make_encoder(a_pin, b_pin, sw_pin, DIR=-1, STEP=4, name="E"):
    a  = Pin(a_pin,  Pin.IN, Pin.PULL_UP)   # "A"
    b  = Pin(b_pin,  Pin.IN, Pin.PULL_UP)   # "B"
    sw = Pin(sw_pin, Pin.IN, Pin.PULL_UP)   # push switch

    def read_state():
        return (a.value() << 1) | b.value()

    return {
        "name": name,
        "a": a, "b": b, "sw": sw,
        "DIR": DIR, "STEP": STEP,
        "last": read_state(),
        "acc": 0,
        "pos": 0,
        "last_pos": 0,
        "last_sw": sw.value(),
        "t_sw": utime.ticks_ms(),
    }

def update_encoder(e):
    # rotary
    new = (e["a"].value() << 1) | e["b"].value()
    if new != e["last"]:
        key = (e["last"] << 2) | new
        e["last"] = new

        delta = LUT[key]
        if delta:
            e["acc"] += e["DIR"] * delta

            if e["acc"] >= e["STEP"]:
                e["pos"] += 1
                e["acc"] -= e["STEP"]
            elif e["acc"] <= -e["STEP"]:
                e["pos"] -= 1
                e["acc"] += e["STEP"]

            if e["pos"] != e["last_pos"]:
                d = e["pos"] - e["last_pos"]
                print(e["name"], ("CW" if d > 0 else "CCW"), "pos =", e["pos"])
                e["last_pos"] = e["pos"]

    # push button (only report presses/releases)
    v = e["sw"].value()
    if v != e["last_sw"] and utime.ticks_diff(utime.ticks_ms(), e["t_sw"]) > 30:
        e["t_sw"] = utime.ticks_ms()
        e["last_sw"] = v
        print(e["name"], "SW pressed" if v == 0 else "SW released")

# ---------------- Button helpers ----------------
def make_button(gpio, name):
    return {
        "name": name,
        "pin": Pin(gpio, Pin.IN, Pin.PULL_UP),
        "last": 1,
        "t": utime.ticks_ms(),
    }

def update_button(b):
    v = b["pin"].value()
    now = utime.ticks_ms()
    if v != b["last"] and utime.ticks_diff(now, b["t"]) > 30:
        b["t"] = now
        b["last"] = v
        print(b["name"], "pressed" if v == 0 else "released")

# ---------------- Your NEW pin configuration ----------------
# EN1: SW=GP0, A=GP1, B=GP2
enc1 = make_encoder(a_pin=1, b_pin=2, sw_pin=0, DIR=-1, STEP=4, name="EN1")

# EN2: SW=GP3, A=GP4, B=GP5
enc2 = make_encoder(a_pin=4, b_pin=5, sw_pin=3, DIR=-1, STEP=4, name="EN2")

# Buttons: GP6..GP9 (one side to GND rail)
buttons = [
    make_button(6, "BUTT4"),
    make_button(7, "BUTT3"),
    make_button(8, "BUTT2"),
    make_button(9, "BUTT1"),
]

print("Running:")
print("  EN1: SW=GP0 A=GP1 B=GP2")
print("  EN2: SW=GP3 A=GP4 B=GP5")
print("  Buttons: BUTT4=GP6 BUTT3=GP7 BUTT2=GP8 BUTT1=GP9")
print("Press buttons / encoder switches and turn knobs...")

while True:
    update_encoder(enc1)
    update_encoder(enc2)
    for b in buttons:
        update_button(b)
    utime.sleep_ms(1)
