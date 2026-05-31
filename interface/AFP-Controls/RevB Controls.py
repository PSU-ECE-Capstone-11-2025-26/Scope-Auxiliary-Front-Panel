import sys
import uselect
from machine import Pin, UART, I2C
import utime

"""
AFP Oscilloscope Master Firmware
- Architecture: 1x Pico, 4x MCP23017, 3x TLC5947
- Logic: Hardware Interrupts, SEL Macros, Hybrid Detent-Lock Debouncer
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
LED_BRIGHTNESS = 150 

DEBOUNCE_MS = 30
ROT_COOLDOWN_MS = 30 # Hybrid debouncer vibration cooldown
DEBUG_ECHO = True

# Initialize Comms
uart = UART(UART_ID, BAUD, tx=Pin(UART_TX), rx=Pin(UART_RX))
i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)

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
        self.cache = 0xFFFF 
        self.dirty = True # Force an initial read on boot
        try:
            # Set IOCON: ODR=1 (Open Drain Interrupts)
            self.i2c.writeto_mem(self.addr, 0x0A, b'\x04') 
            
            # Enable internal pull-ups for all pins
            self.write_reg(0x0C, 0xFF) 
            self.write_reg(0x0D, 0xFF)
            
            # Enable Interrupt-On-Change for all pins
            self.write_reg(0x04, 0xFF) 
            self.write_reg(0x05, 0xFF) 

            # Read the pins once to clear any startup interrupt flags
            self.update_cache()
        except: pass

    def write_reg(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, bytes([value]))

    def update_cache(self):
        try:
            # NEW: Read 0x10 (INTCAPA/B) instead of 0x12 (GPIOA/B)
            # This fetches the frozen snapshot of the pins and clears the interrupt
            data = self.i2c.readfrom_mem(self.addr, 0x10, 2)
            self.cache = data[0] | (data[1] << 8)
            self.dirty = False
        except: pass

    def get_pin(self, pin):
        return (self.cache >> pin) & 1

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

    def set_pin(self, pin, pwm_value):
        if 0 <= pin < self.n:
            idx = (self.n - 1) - pin
            if self.buffer[idx] != pwm_value:
                self.buffer[idx] = pwm_value
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
        print(f"✅ {name} (0x{addr:02X}) Connected")
        return chip
    except:
        print(f"❌ {name} (0x{addr:02X}) Not Found")
        return None

# ============================================================================
# 3. INITIALIZE HARDWARE & INTERRUPTS
# ============================================================================
print("\nScanning Hardware on I2C Bus...")
mcp1 = safe_init_mcp(i2c, 0x21, "MCP 1")
mcp2 = safe_init_mcp(i2c, 0x20, "MCP 2")
mcp3 = safe_init_mcp(i2c, 0x22, "MCP 3")
mcp4 = safe_init_mcp(i2c, 0x23, "MCP 4")

tlc = TLC5947(TLC_DIN, TLC_CLK, TLC_LAT, TLC_OE, num_drivers=NUM_TLC_CHIPS)

# Interrupt Service Routines (Hardware Triggers)
def isr_mcp1(pin):
    if mcp1: mcp1.dirty = True
def isr_mcp2(pin):
    if mcp2: mcp2.dirty = True
def isr_mcp3(pin):
    if mcp3: mcp3.dirty = True
def isr_mcp4(pin):
    if mcp4: mcp4.dirty = True

try:
    Pin(2, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp1)
    Pin(3, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp1)
    Pin(4, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp2)
    Pin(5, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp2)
    Pin(6, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp3)
    Pin(7, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp3)
    Pin(8, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp4)
    Pin(9, Pin.IN, Pin.PULL_UP).irq(trigger=Pin.IRQ_FALLING, handler=isr_mcp4)
    print("✅ Hardware Interrupts Armed")
except Exception as e:
    print("❌ Interrupt Setup Failed:", e)


# ============================================================================
# 4. COMPONENT MAPPING
# ============================================================================
LUT = [0]*16
LUT[0b0001] = +1; LUT[0b0010] = -1; LUT[0b0100] = -1; LUT[0b0111] = +1
LUT[0b1000] = +1; LUT[0b1011] = -1; LUT[0b1101] = -1; LUT[0b1110] = +1

def make_encoder(mcp, a_pin, b_pin, sw_pin, id_rot, id_sw):
    if mcp is None: return None
    return {"mcp": mcp, "a": a_pin, "b": b_pin, "sw": sw_pin, "id_rot": id_rot, "id_sw": id_sw, "last": 0, "last_sw": 1, "t_sw": utime.ticks_ms(), "acc": 0, "locked": False, "t_out": 0}

def make_split_encoder(mcp_a, pin_a, mcp_b, pin_b, mcp_sw, pin_sw, id_rot, id_sw):
    return {
        "is_split": True,
        "mcp_a": mcp_a, "a": pin_a,
        "mcp_b": mcp_b, "b": pin_b,
        "mcp_sw": mcp_sw, "sw": pin_sw,
        "id_rot": id_rot, "id_sw": id_sw, 
        "last": 0, "last_sw": 1, "t_sw": utime.ticks_ms(), "acc": 0, "locked": False, "t_out": 0
    }

def make_button(mcp, gpio, btn_id):
    if mcp is None: return None
    return {"mcp": mcp, "pin": gpio, "id": btn_id, "last": 1, "t": utime.ticks_ms()}

# --- Encoders & Buttons ---
enc1 = make_encoder(mcp1, 10, 9, 11, "KA1", "KA0")
enc2 = make_encoder(mcp1, 13, 12, 14, "KB1", "KB0")
enc3 = make_split_encoder(mcp2, 0, mcp1, 15, mcp2, 1, "TL1", "TL0") 
enc4 = make_encoder(mcp2, 3, 2, 4, "VP1", "VP0")
enc5 = make_encoder(mcp2, 6, 5, 7, "VS1", "VS0")
enc6 = make_encoder(mcp3, 4, 3, 5, "HP1", "HP0")
enc7 = make_encoder(mcp3, 7, 6, 8, "HS1", "HS0")
enc8 = make_encoder(mcp3, 10, 9, None, "HZ1", None)
enc9 = make_encoder(mcp3, 12, 11, None, "HX1", None)
encoders = [e for e in [enc1, enc2, enc3, enc4, enc5, enc6, enc7, enc8, enc9] if e is not None]

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

# --- COLOR MACROS ---
COLOR_MACROS = {
    # --- Channel Buttons ---
    "V10": {"V10_R": 100, "V10_G": 25,  "V10_B": 0},   # Yellow
    "V20": {"V20_R": 0, "V20_G": 15,  "V20_B": 15},    # Cyan
    "V30": {"V30_R": 100, "V30_G": 0,  "V30_B": 0},     # Red
    "V40": {"V40_R": 0, "V40_G": 12,  "V40_B": 0},      # Green
    "V50": {"V50_R": 150, "V50_G": 15,  "V50_B": 0},   # Orange
    "V60": {"V60_R": 0, "V60_G": 0,  "V60_B": 50},     # Blue
    "V70": {"V70_R": 75, "V70_G": 0,  "V70_B": 38},   # Pink
    "V80": {"V80_R": 4, "V80_G": 20,  "V80_B": 4},    # Forest Green

    # --- Macro Buttons ---
    "M10": {"M10_R": 0, "M10_G": 12, "M10_B": 0},    # Green
    "M20": {"M20_R": 0, "M20_G": 12, "M20_B": 0},    # Green
    "M30": {"M30_R": 0, "M30_G": 12, "M30_B": 0},    # Green
    "M40": {"M40_R": 0, "M40_G": 12, "M40_B": 0},    # Green
    
    # --- Vertical Position/Scale Channel SELECTIONS ---
    "SEL1": {
        "VP1_R": 100, "VP1_G": 25, "VP1_B": 0,
        "VS1_R": 100, "VS1_G": 25, "VS1_B": 0,
    },
    "SEL2": {
        "VP1_R": 0, "VP1_G": 15, "VP1_B": 15,
        "VS1_R": 0, "VS1_G": 15, "VS1_B": 15,
    },
    "SEL3": {
        "VP1_R": 100, "VP1_G": 0, "VP1_B": 0,
        "VS1_R": 100, "VS1_G": 0, "VS1_B": 0,
    },
    "SEL4": {
        "VP1_R": 0, "VP1_G": 12, "VP1_B": 0,
        "VS1_R": 0, "VS1_G": 12, "VS1_B": 0,
    },
    "SEL5": {
        "VP1_R": 150, "VP1_G": 15, "VP1_B": 0,
        "VS1_R": 150, "VS1_G": 15, "VS1_B": 0,
    },
    "SEL6": {
        "VP1_R": 0, "VP1_G": 0, "VP1_B": 50,
        "VS1_R": 0, "VS1_G": 0, "VS1_B": 50,
    },
    "SEL7": {
        "VP1_R": 75, "VP1_G": 0, "VP1_B": 38,
        "VS1_R": 75, "VS1_G": 0, "VS1_B": 38,
    },
    "SEL8": {
        "VP1_R": 4, "VP1_G": 20, "VP1_B": 4,
        "VS1_R": 4, "VS1_G": 20, "VS1_B": 4,
    },
    "SEL_M": {
        "VP1_R": 75, "VP1_G": 2, "VP1_B": 0,
        "VS1_R": 75, "VS1_G": 2, "VS1_B": 0,
    },
    "SEL_B": {
        "VP1_R": 0, "VP1_G": 0, "VP1_B": 60,
        "VS1_R": 0, "VS1_G": 0, "VS1_B": 60,
    },
    "SEL_OFF": {
        "VP1_R": 0, "VP1_G": 0, "VP1_B": 0,
        "VS1_R": 0, "VS1_G": 0, "VS1_B": 0,
    },
    
    # --- Trigger Color SELECTIONS ---
    "TL1_C1": {
        "TL1_R": 100, "TL1_G": 25, "TL1_B": 0,
    },
    "TL1_C2": {
        "TL1_R": 0, "TL1_G": 15, "TL1_B": 15,
    },
    "TL1_C3": {
        "TL1_R": 100, "TL1_G": 0, "TL1_B": 0,
    },
    "TL1_C4": {
        "TL1_R": 0, "TL1_G": 12, "TL1_B": 0,
    },
    "TL1_C5": {
        "TL1_R": 150, "TL1_G": 15, "TL1_B": 0,
    },
    "TL1_C6": {
        "TL1_R": 0, "TL1_G": 0, "TL1_B": 50,
    },
    "TL1_C7": {
        "TL1_R": 75, "TL1_G": 0, "TL1_B": 38,
    },
    "TL1_C8": {
        "TL1_R": 4, "TL1_G": 20, "TL1_B": 4,
    },
    
    # --- Turn All LEDs Off ---
    "ALL_OFF": {
        "TL1_B": 0, "TL1_G": 0, "TL1_R": 0, "AR0_B": 0, "AR0_G": 0, "AR0_R": 0, "AS0": 0,
        "AH0": 0, "AF0": 0, "AC0": 0, "KA1": 0, "KA0": 0, "KB1": 0, "KB0": 0, "TF0_R": 0,
        "TF0_T": 0, "TS0_UP": 0, "TS0_DN": 0, "TM0_A": 0, "TM0_N": 0, "VS0": 0, "VM0": 0,
        "VR0": 0, "VB0": 0, "VP1_B": 0, "VP1_G": 0, "VP1_R": 0, "VS1_B": 0, "VS1_G": 0,
        "VS1_R": 0, "V10_B": 0, "V10_G": 0, "V10_R": 0, "V20_B": 0, "V20_G": 0, "V20_R": 0,
        "V30_B": 0, "V30_G": 0, "V30_R": 0, "V40_B": 0, "V40_G": 0, "V40_R": 0, "V50_B": 0,
        "V50_G": 0, "V50_R": 0, "V60_B": 0, "V60_G": 0, "V60_R": 0, "V70_B": 0, "V70_G": 0,
        "V70_R": 0, "V80_B": 0, "V80_G": 0, "V80_R": 0, "HZ0": 0, "M10_B": 0, "M10_G": 0,
        "M10_R": 0, "M20_B": 0, "M20_G": 0, "M20_R": 0, "M30_B": 0, "M30_G": 0, "M30_R": 0,
        "M40_B": 0, "M40_G": 0, "M40_R": 0, "SP_CON": 0, "HS0": 0, "T_OFF": 0,
    },
}

# ============================================================================
# 5. CORE LOGIC
# ============================================================================
def startup_led_test():
    STARTUP_BRIGHT = 200 
    for ch in range(tlc.n): tlc.set_pin(ch, 0)
    tlc.write()
    utime.sleep_ms(100)

    for ch in range(tlc.n):
        tlc.set_pin(ch, STARTUP_BRIGHT)
        tlc.write()
        utime.sleep_ms(12)
        tlc.set_pin(ch, 0)
        
    tlc.write() 
    utime.sleep_ms(50)

    for ch in range(tlc.n): tlc.set_pin(ch, STARTUP_BRIGHT)
    tlc.write()
    utime.sleep_ms(250)

    for ch in range(tlc.n): tlc.set_pin(ch, 0)
    tlc.write()
    utime.sleep_ms(100)

def process_command(line):
    line = line.strip()
    if not line or ":" not in line: return
    
    try:
        msg_id, value = line.split(":")
        value = int(value)
        if msg_id.startswith("I"):
            base_id = msg_id[1:]
            
            if base_id == "AR0":
                if value == 1:
                    # State 1: RUN (Green)
                    r_val, g_val = 0, 12
                    state_name = "GREEN"
                elif value == 0:
                    # State 0: STOP (Red)
                    r_val, g_val = 50, 0
                    state_name = "RED"
                elif value == -1: 
                    # State -1 (or anything else): OFF
                    r_val, g_val = 0, 0
                    state_name = "OFF"

                tlc.set_pin(LED_MAP["AR0_R"], r_val)
                tlc.set_pin(LED_MAP["AR0_G"], g_val)
                tlc.set_pin(LED_MAP["AR0_B"], 0)
                if DEBUG_ECHO: print(f"[COMMAND] Run/Stop -> {state_name}")
                return

            elif base_id in COLOR_MACROS:
                for sub_pin, intensity in COLOR_MACROS[base_id].items():
                    if sub_pin in LED_MAP:
                        pwm_val = intensity if value == 1 else 0
                        tlc.set_pin(LED_MAP[sub_pin], pwm_val)
                if DEBUG_ECHO: print(f"[COMMAND] MACRO {base_id} -> {'ON' if value else 'OFF'}")
                
            elif base_id in LED_MAP:
                pwm_val = LED_BRIGHTNESS if value == 1 else 0
                tlc.set_pin(LED_MAP[base_id], pwm_val)
                if DEBUG_ECHO: print(f"[COMMAND] LED {base_id} -> {'ON' if value else 'OFF'}")
                
    except Exception as e:
        if DEBUG_ECHO: print("Parse error:", e)

def poll_inputs():
    while uart.any():
        line = uart.readline().decode().strip()
        process_command(line)
        
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
    now = utime.ticks_ms()

    # --- THE HYBRID DEBOUNCER ---
    # Only unlock IF we are in a physical detent AND the mechanical vibration time has passed
    if (new_rot == 0 or new_rot == 3) and utime.ticks_diff(now, e["t_out"]) > ROT_COOLDOWN_MS:
        e["locked"] = False
        e["acc"] = 0

    if new_rot != e["last"]:
        key = (e["last"] << 2) | new_rot
        e["last"] = new_rot

        # Only do math if we aren't locked waiting for the bounce to settle!
        if not e.get("locked"):
            delta = LUT[key]
            if delta != 0:
                e["acc"] += delta
                
                if e["acc"] >= 2:
                    send(e["id_rot"], 1)
                    e["locked"] = True
                    e["t_out"] = now  # Record the exact time we fired
                    
                elif e["acc"] <= -2:
                    send(e["id_rot"], -1)
                    e["locked"] = True
                    e["t_out"] = now  # Record the exact time we fired

    # Button Switch Logic
    if e["sw"] is not None:
        try:
            val_sw = e["mcp_sw"].get_pin(e["sw"]) if e.get("is_split") else e["mcp"].get_pin(e["sw"])
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
print("\nSystem Ready. Type commands in Thonny Shell (e.g., ISEL1:1 or IAR0:1)")

startup_led_test() 
send("BOOT", 1)
process_command("IAR0:1") 

while True:
    # BURST MODE: If any wire is pulled, trap the Pico here and read as fast as possible!
    while mcp1.dirty or mcp2.dirty or mcp3.dirty or mcp4.dirty:
        if mcp1 and mcp1.dirty: mcp1.update_cache()
        if mcp2 and mcp2.dirty: mcp2.update_cache()
        if mcp3 and mcp3.dirty: mcp3.update_cache()
        if mcp4 and mcp4.dirty: mcp4.update_cache()
        
        for e in encoders: update_encoder(e)
        for b in buttons: update_button(b)
        
    poll_inputs()
    tlc.write() # LEDs only update when the spinning stops
    utime.sleep_us(50) # Lowered the sleep time to keep the loop tighter