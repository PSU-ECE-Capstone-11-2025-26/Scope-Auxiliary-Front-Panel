from machine import Pin, UART, I2C
import utime

"""
AFP Firmware (2-Chip Edition)
- Chip A (0x20): Buttons 1-16
- Chip B (0x21): Buttons 17-32
- Channel 1 Test: Button on GPA0, LED on GPA1 (Same Chip)
"""

# ---------------- CONFIGURATION ----------------
UART_ID = 0
UART_TX = 16 
UART_RX = 17 
BAUD    = 115200

# I2C Config (GP8/GP9)
I2C_ID  = 0
SDA_PIN = 8 
SCL_PIN = 9 

DEBUG_ECHO = True

# Initialize Hardware
uart = UART(UART_ID, BAUD, tx=Pin(UART_TX), rx=Pin(UART_RX))
i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=100000)

def send(btn_id, value):
    msg = "{}:{}\n".format(btn_id, value)
    uart.write(msg)
    if DEBUG_ECHO: print(msg, end="")

# ---------------- MCP23017 DRIVER ----------------
class MCP23017:
    def __init__(self, i2c, address):
        self.i2c = i2c
        self.addr = address
        # Initialize
        self.i2c.writeto_mem(self.addr, 0x0A, b'\x00') # IOCON
        self.write_reg(0x00, 0xFF) # IODIRA (Inputs)
        self.write_reg(0x01, 0xFF) # IODIRB
        self.write_reg(0x0C, 0xFF) # GPPUA (Pullups)
        self.write_reg(0x0D, 0xFF) # GPPUB

    def write_reg(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, bytes([value]))

    def read_reg(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0] 

    def get_pin(self, pin):
        reg = 0x12 if pin < 8 else 0x13
        bit = pin if pin < 8 else pin - 8
        return (self.read_reg(reg) >> bit) & 1

    def set_pin(self, pin, value):
        reg = 0x12 if pin < 8 else 0x13 
        bit = pin if pin < 8 else pin - 8
        current = self.read_reg(reg)
        if value: current |= (1 << bit)
        else:     current &= ~(1 << bit)
        self.write_reg(reg, current)
        # Force Direction Output
        dir_reg = 0x00 if pin < 8 else 0x01
        current_dir = self.read_reg(dir_reg)
        self.write_reg(dir_reg, current_dir & ~(1 << bit))

# --- SAFE INITIALIZATION ---
def safe_init_mcp(i2c, addr, name):
    try:
        chip = MCP23017(i2c, addr)
        chip.read_reg(0x00) # Dummy read
        print(f"✅ {name} (0x{addr:02X}) Connected")
        return chip
    except:
        print(f"❌ {name} (0x{addr:02X}) Not Found - Skipping")
        return None

print("Scanning Hardware...")
mcp_a = safe_init_mcp(i2c, 0x20, "Chip A")
mcp_b = safe_init_mcp(i2c, 0x21, "Chip B")

# ---------------- LOGIC HELPERS ----------------
LUT = [0]*16
LUT[0b0001] = +1; LUT[0b0010] = -1; LUT[0b0100] = -1; LUT[0b0111] = +1
LUT[0b1000] = +1; LUT[0b1011] = -1; LUT[0b1101] = -1; LUT[0b1110] = +1
DEBOUNCE_MS = 30

def make_encoder(a_pin, b_pin, sw_pin, id_rot, id_sw, DIR=-1, STEP=4, name="E"):
    if a_pin is None: return None
    a  = Pin(a_pin,  Pin.IN, Pin.PULL_UP)
    b  = Pin(b_pin,  Pin.IN, Pin.PULL_UP)
    sw = Pin(sw_pin, Pin.IN, Pin.PULL_UP) if sw_pin is not None else None
    def read_state(): return (a.value() << 1) | b.value()
    return {
        "type": "ENC", "name": name,
        "a": a, "b": b, "sw": sw,
        "id_rot": id_rot, "id_sw": id_sw,
        "DIR": DIR, "STEP": STEP,
        "last": read_state(), "acc": 0,
        "last_sw": sw.value() if sw else 1, "t_sw": utime.ticks_ms(),
    }

def make_button(btn_chip, btn_pin, btn_id, name, latching=False, led_chip=None, led_pin=None):
    if btn_chip is None: return None
    return {
        "type": "BTN", "name": name, "id": btn_id,
        "mcp": btn_chip,   "pin": btn_pin,
        "led_mcp": led_chip, "led_pin": led_pin, 
        "latching": latching,
        "state": 0, "last": 1, "t": utime.ticks_ms()
    }

def update_encoder(e):
    if e is None: return
    new = (e["a"].value() << 1) | e["b"].value()
    if new != e["last"]:
        key = (e["last"] << 2) | new
        e["last"] = new
        delta = LUT[key]
        if delta:
            e["acc"] += e["DIR"] * delta
            if e["acc"] >= e["STEP"]:
                e["acc"] -= e["STEP"]
                send(e["id_rot"], +1)
            elif e["acc"] <= -e["STEP"]:
                e["acc"] += e["STEP"]
                send(e["id_rot"], -1)
    if e["sw"]:
        v = e["sw"].value()
        if v != e["last_sw"] and utime.ticks_diff(utime.ticks_ms(), e["t_sw"]) > DEBOUNCE_MS:
            e["t_sw"] = utime.ticks_ms()
            e["last_sw"] = v
            send(e["id_sw"], 1 if v == 0 else 0)

def update_button(b):
    if b is None: return
    try:
        v = b["mcp"].get_pin(b["pin"])
    except: return 
    
    if v != b["last"] and utime.ticks_diff(utime.ticks_ms(), b["t"]) > DEBOUNCE_MS:
        b["t"] = utime.ticks_ms()
        b["last"] = v
        
        has_led = (b["led_mcp"] is not None)
        if v == 0: # Pressed
            if b["latching"]:
                b["state"] ^= 1 
                send(b["id"], b["state"])
                if has_led: b["led_mcp"].set_pin(b["led_pin"], b["state"])
            else:
                send(b["id"], 1) 
                if has_led: b["led_mcp"].set_pin(b["led_pin"], 1)
        else: # Released
            if not b["latching"]:
                send(b["id"], 0)
                if has_led: b["led_mcp"].set_pin(b["led_pin"], 0)

def check_uart_sync(all_buttons):
    while uart.any():
        try:
            line = uart.readline().decode().strip()
            if ":" in line:
                cmd_id, val = line.split(":")
                val = int(val)
                for b in all_buttons:
                    if b and b["id"] == cmd_id:
                        b["state"] = val
                        if b["led_mcp"]: b["led_mcp"].set_pin(b["led_pin"], val)
                        if DEBUG_ECHO: print(f" [SYNC {cmd_id}->{val}] ", end="")
        except: pass

# ---------------- PIN MAPPING ----------------
encoders = []
buttons_raw = [] 

# 1. ENCODERS (GP0 - GP5)
encoders.append(make_encoder(1, 2, 0, "KA1", "KA0", name="Enc1"))
# encoders.append(make_encoder(4, 5, 3, "KB1", "KB0", name="Enc2"))

# 2. CHANNEL 1 (The Test)
# Button: Chip A, Pin 0 (GPA0)
# LED:    Chip A, Pin 1 (GPA1)
buttons_raw.append(make_button(mcp_a, 0, "V10", "CH1", True, mcp_a, 1))

# 3. EXTRA BUTTONS (Example on Chip B)
# Only active if you plug in the second chip (0x21)
buttons_raw.append(make_button(mcp_b, 0, "M10", "Macro1", False, None, None))

# Filter out missing chips
buttons = [b for b in buttons_raw if b is not None]

# ---------------- MAIN LOOP ----------------
print("System Ready. Press Button on GPA0 to toggle LED on GPA1.")
send("BOOT", 1)

while True:
    for e in encoders: update_encoder(e)
    for b in buttons:  update_button(b)
    check_uart_sync(buttons)
    utime.sleep_ms(1)
