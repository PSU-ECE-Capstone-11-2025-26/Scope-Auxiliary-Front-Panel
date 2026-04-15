import sys
import uselect
from machine import Pin, UART, I2C
import utime

"""
AFP Oscilloscope Master Firmware (Thin Client)
- Architecture: 1x Pico, 4x MCP23017, 3x TLC5947
- Logic: High-speed I2C caching for encoders & split-chip support.
- Additions: Rate-Limited Half-Step Encoders (Fast response, no double-clicks)
"""

# ============================================================================
# 1. HARDWARE CONFIGURATION
# ============================================================================
UART_ID = 0
UART_TX = 16
UART_RX = 17
BAUD    = 115200

I2C_ID  = 0
SDA_PIN = 0 
SCL_PIN = 1 

TLC_DIN = 19
TLC_CLK = 18
TLC_LAT = 22
TLC_OE  = 15 #Actually 20
NUM_TLC_CHIPS = 3
LED_BRIGHTNESS = 300 

DEBOUNCE_MS = 30
ROT_COOLDOWN_MS = 40 # Mutes the encoder for 40ms after a successful output
DEBUG_ECHO = True # Change to false to make it faster if not debugging

# Initialize Comms
uart = UART(UART_ID, BAUD, tx=Pin(UART_TX), rx=Pin(UART_RX))
i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)

# Setup USB Polling for Thonny Shell
spoll = uselect.poll()
spoll.register(sys.stdin, uselect.POLLIN)

def send(msg_id, value):
    msg = "{}:{}\n".format(msg_id, value)
    uart.write(msg)
    if DEBUG_ECHO: print(msg, end="")

# ============================================================================
# 2. DEVICE DRIVERS
# ============================================================================
class MCP23017:
    def __init__(self, i2c, address):
        self.i2c = i2c
        self.addr = address
        self.cache = 0xFFFF # Start with all pins HIGH (unpressed)
        try:
            self.i2c.writeto_mem(self.addr, 0x0A, b'\x00') 
            self.write_reg(0x00, 0xFF) 
            self.write_reg(0x01, 0xFF) 
            self.write_reg(0x0C, 0xFF) 
            self.write_reg(0x0D, 0xFF)
        except: pass

    def write_reg(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, bytes([value]))

    def update_cache(self):
        # Reads all 16 pins in one fast transaction
        try:
            data = self.i2c.readfrom_mem(self.addr, 0x12, 2)
            self.cache = data[0] | (data[1] << 8)
        except: pass

    def get_pin(self, pin):
        # Checks the local snapshot instead of the network
        return (self.cache >> pin) & 1

class TLC5947:
    def __init__(self, din, clk, lat, oe, num_drivers=1):
        self.din = Pin(din, Pin.OUT)
        self.clk = Pin(clk, Pin.OUT)
        self.lat = Pin(lat, Pin.OUT)
        self.oe  = Pin(oe, Pin.OUT, value=1) # Start OFF
        
        self.n = num_drivers * 24 
        self.buffer = [0] * self.n
        self.dirty = True 
        
        self.write() # Clear memory
        self.oe.value(0) # Enable outputs (Active Low)

    def set_pin(self, pin, value):
        pwm = LED_BRIGHTNESS if value else 0
        if 0 <= pin < self.n:
            idx = (self.n - 1) - pin
            if self.buffer[idx] != pwm:
                self.buffer[idx] = pwm
                self.dirty = True

    def write(self):
        if not self.dirty: return
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

def safe_init_mcp(i2c, addr, name):
    try:
        chip = MCP23017(i2c, addr)
        chip.update_cache() # Do an initial read to verify it's alive
        print(f"✅ {name} (0x{addr:02X}) Connected")
        return chip
    except:
        print(f"❌ {name} (0x{addr:02X}) Not Found")
        return None

# ============================================================================
# 3. INITIALIZE HARDWARE
# ============================================================================
print("\nScanning Hardware on I2C Bus...")
mcp1 = safe_init_mcp(i2c, 0x21, "MCP 1")
mcp2 = safe_init_mcp(i2c, 0x20, "MCP 2")
mcp3 = safe_init_mcp(i2c, 0x22, "MCP 3")
mcp4 = safe_init_mcp(i2c, 0x23, "MCP 4")

tlc = TLC5947(TLC_DIN, TLC_CLK, TLC_LAT, TLC_OE, num_drivers=NUM_TLC_CHIPS)

# ============================================================================
# 4. COMPONENT MAPPING
# ============================================================================
LUT = [0]*16
LUT[0b0001] = +1; LUT[0b0010] = -1; LUT[0b0100] = -1; LUT[0b0111] = +1
LUT[0b1000] = +1; LUT[0b1011] = -1; LUT[0b1101] = -1; LUT[0b1110] = +1

def make_encoder(mcp, a_pin, b_pin, sw_pin, id_rot, id_sw):
    if mcp is None: return None
    return {"mcp": mcp, "a": a_pin, "b": b_pin, "sw": sw_pin, "id_rot": id_rot, "id_sw": id_sw, "last": 0, "last_sw": 1, "t_sw": utime.ticks_ms(), "acc": 0, "t_idle": 0, "t_out": 0}

def make_split_encoder(mcp_a, pin_a, mcp_b, pin_b, mcp_sw, pin_sw, id_rot, id_sw):
    return {
        "is_split": True,
        "mcp_a": mcp_a, "a": pin_a,
        "mcp_b": mcp_b, "b": pin_b,
        "mcp_sw": mcp_sw, "sw": pin_sw,
        "id_rot": id_rot, "id_sw": id_sw, 
        "last": 0, "last_sw": 1, "t_sw": utime.ticks_ms(), "acc": 0, "t_idle": 0, "t_out": 0
    }

def make_button(mcp, gpio, btn_id):
    if mcp is None: return None
    return {"mcp": mcp, "pin": gpio, "id": btn_id, "last": 1, "t": utime.ticks_ms()}

# --- Encoders ---
enc1 = make_encoder(mcp1, 10, 9, 11, "KA1", "KA0")
enc2 = make_encoder(mcp1, 13, 12, 14, "KB1", "KB0")
enc3 = make_split_encoder(mcp2, 0, mcp1, 15, mcp2, 1, "TL1", "TL0") # Split encoder
enc4 = make_encoder(mcp2, 3, 2, 4, "VP1", "VP0")
enc5 = make_encoder(mcp2, 6, 5, 7, "VS1", "VS0")
enc6 = make_encoder(mcp3, 4, 3, 5, "HP1", "HP0")
enc7 = make_encoder(mcp3, 7, 6, 8, "HS1", "HS0")
enc8 = make_encoder(mcp3, 10, 9, None, "HZ1", None)
enc9 = make_encoder(mcp3, 12, 11, None, "HX1", None)
encoders = [e for e in [enc1, enc2, enc3, enc4, enc5, enc6, enc7, enc8, enc9] if e is not None]

# --- Buttons ---
buttons_raw = [
    make_button(mcp1,  0, "AS0"), make_button(mcp1,  1, "AR0"), make_button(mcp1,  2, "AX0"),
    make_button(mcp1,  3, "AH0"), make_button(mcp1,  4, "AF0"), make_button(mcp1,  5, "AC0"),
    make_button(mcp1,  6, "TF0"), make_button(mcp1,  7, "TS0"), make_button(mcp1,  8, "TM0"),
    make_button(mcp2,  8, "V10"), make_button(mcp2,  9, "V20"), make_button(mcp2,  10, "V30"),
    make_button(mcp2, 11, "V40"), make_button(mcp2, 12, "V50"), make_button(mcp2,  13, "V60"),
    make_button(mcp2, 14, "V70"), make_button(mcp2, 15, "V80"), make_button(mcp3,  0, "VM0"),
    make_button(mcp3,  1, "VR0"), make_button(mcp3,  2, "VB0"), make_button(mcp3,  13, "HL0"),
    make_button(mcp3, 14, "HR0"), make_button(mcp3, 15, "HZ0"), make_button(mcp4,  0, "M10"),
    make_button(mcp4,  1, "M20"), make_button(mcp4,  2, "M30"), make_button(mcp4,  3, "M40"),
    make_button(mcp4,  4, "XT0"), make_button(mcp4,  5, "XS0"), make_button(mcp4,  6, "XD0"),
    make_button(mcp4,  7, "XA0")
]
buttons = [b for b in buttons_raw if b is not None]

# --- LEDs Mapping ---
LED_MAP = {
    "TL1_B": 0, "TL1_G": 1, "TL1_R": 2, "AR0_B": 3, "AR0_G": 4, "AR0_R": 5, "AS0": 6, "AH0": 7,
    "AF0": 8, "AC0": 9, "KA1": 10, "KA0": 11, "KB1": 12, "KB0": 13, "TF0_R": 14, "TF0_T": 15,
    "TS0_UP": 16, "TS0_DN": 17, "TM0_A": 18, "TM0_N": 19, "VS0": 20, "VM0": 21, "VR0": 22,
    "VB0": 23, "VP1_B": 24, "VP1_G": 25, "VP1_R": 26, "VS1_B": 27, "VS1_G": 28, "VS1_R": 29,
    "V10_B": 30, "V10_G": 31, "V10_R": 32, "V20_B": 33, "V20_G": 34, "V20_R": 35, "V30_B": 36,
    "V30_G": 37, "V30_R": 38, "V40_B": 39, "V40_G": 40, "V40_R": 41, "V50_B": 42, "V50_G": 43,
    "V50_R": 44, "V60_B": 45, "V60_G": 46, "V60_R": 47, "V70_B": 48, "V70_G": 49, "V70_R": 50,
    "V80_B": 51, "V80_G": 52, "V80_R": 53, "HZ0": 54, "M10_B": 55, "M10_G": 56, "M10_R": 57, "M20_B": 58,
    "M20_G": 59, "M20_R": 60, "M30_B": 61, "M30_G": 62, "M30_R": 63, "M40_B": 64, "M40_G": 65,
    "M40_R": 66, "SP_CON": 67, "HS0": 68, "T_OFF": 69
}

# ============================================================================
# 5. CORE LOGIC
# ============================================================================
def process_command(line):
    line = line.strip()
    if not line or ":" not in line: return
    try:
        msg_id, value = line.split(":")
        value = int(value)
        if msg_id.startswith("I"):
            base_id = msg_id[1:]
            if base_id in LED_MAP:
                tlc.set_pin(LED_MAP[base_id], value)
                if DEBUG_ECHO: print(f"[COMMAND] LED {base_id} -> {value}")
    except Exception as e:
        if DEBUG_ECHO: print("Parse error:", e)

def poll_inputs():
    # 1. Drain the ENTIRE Hardware UART buffer
    while uart.any():
        line = uart.readline().decode().strip()
        process_command(line)
        
    # 2. Drain the ENTIRE USB Shell buffer
    while spoll.poll(0):
        line = sys.stdin.readline()
        process_command(line)

def update_encoder(e):
    try:
        if e.get("is_split"):
            val_a = e["mcp_a"].get_pin(e["a"])
            val_b = e["mcp_b"].get_pin(e["b"])
        else:
            val_a = e["mcp"].get_pin(e["a"])
            val_b = e["mcp"].get_pin(e["b"])
    except: return

    new_rot = (val_a << 1) | val_b
    now = utime.ticks_ms() # Get the current time
    
    if new_rot != e["last"]:
        key = (e["last"] << 2) | new_rot
        e["last"] = new_rot
        e["t_idle"] = now # Reset the idle timer because they are turning it
        
        delta = LUT[key]
        if delta != 0:
            e["acc"] += delta
            
            # Check for Right Turn (Half-Step Threshold of 2)
            if e["acc"] >= 2:
                # Only send if the 40ms cooldown has expired
                if utime.ticks_diff(now, e["t_out"]) > ROT_COOLDOWN_MS:
                    send(e["id_rot"], 1)
                    e["t_out"] = now # Reset the output stopwatch
                e["acc"] = 0 # ALWAYS reset the math, even if muted
                
            # Check for Left Turn
            elif e["acc"] <= -2:
                # Only send if the 40ms cooldown has expired
                if utime.ticks_diff(now, e["t_out"]) > ROT_COOLDOWN_MS:
                    send(e["id_rot"], -1)
                    e["t_out"] = now # Reset the output stopwatch
                e["acc"] = 0 # ALWAYS reset the math, even if muted
                
    # If the knob hasn't moved in 200ms, wipe the slate clean
    elif e["acc"] != 0 and utime.ticks_diff(now, e["t_idle"]) > 200:
        e["acc"] = 0

    if e["sw"] is not None:
        try:
            if e.get("is_split"):
                val_sw = e["mcp_sw"].get_pin(e["sw"])
            else:
                val_sw = e["mcp"].get_pin(e["sw"])
        except: return
        
        if val_sw != e["last_sw"] and utime.ticks_diff(now, e["t_sw"]) > DEBOUNCE_MS:
            e["t_sw"] = now; e["last_sw"] = val_sw
            if val_sw == 0: send(e["id_sw"], 1)

def update_button(b):
    try: v = b["mcp"].get_pin(b["pin"])
    except: return
    now = utime.ticks_ms()
    if v != b["last"] and utime.ticks_diff(now, b["t"]) > DEBOUNCE_MS:
        b["t"] = now; b["last"] = v
        if v == 0: send(b["id"], 1)

# ============================================================================
# 6. MAIN LOOP
# ============================================================================
print("\nSystem Ready. Type commands in Thonny Shell (e.g., IVP1_R:1)")
send("BOOT", 1)

while True:
    # 1. Take a high-speed snapshot of all chips
    if mcp1: mcp1.update_cache()
    if mcp2: mcp2.update_cache()
    if mcp3: mcp3.update_cache()
    if mcp4: mcp4.update_cache()
    
    # 2. Process logic using the cached snapshots
    for e in encoders: update_encoder(e)
    for b in buttons: update_button(b)
    
    poll_inputs()
    tlc.write()
    utime.sleep_us(100)