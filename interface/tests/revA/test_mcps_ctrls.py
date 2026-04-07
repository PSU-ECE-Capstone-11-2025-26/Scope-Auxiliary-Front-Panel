from machine import Pin, I2C
import utime

# =========================
# Configuration
# =========================
I2C_ID = 0
SDA_PIN = 0
SCL_PIN = 1
I2C_FREQ = 400000
DEBOUNCE_MS = 30
REPEATED_READ_SAMPLES = 5
REPEATED_READ_DELAY_MS = 500

EXPECTED_MCPS = {
    0x20: "MCP 2",
    0x21: "MCP 1",
    0x22: "MCP 3",
    0x23: "MCP 4",
}

ADDR_MCP1 = 0x21
ADDR_MCP2 = 0x20
ADDR_MCP3 = 0x22
ADDR_MCP4 = 0x23

# MCP23017 registers
IODIRA = 0x00
IODIRB = 0x01
IOCON  = 0x0A
GPPUA  = 0x0C
GPPUB  = 0x0D
GPIOA  = 0x12
GPIOB  = 0x13


# =========================
# Helpers
# =========================
def fmt8(x):
    s = bin(x)[2:]
    return ("00000000" + s)[-8:]


def changed_bits(old, new):
    diff = old ^ new
    bits = []
    for bit in range(8):
        if diff & (1 << bit):
            bits.append(bit)
    return bits


def pin_from_snapshot(snap, pin):
    if snap is None:
        return 1
    if pin < 8:
        return (snap["A"] >> pin) & 1
    return (snap["B"] >> (pin - 8)) & 1


def gpio_name(pin):
    if pin < 8:
        return "A{}".format(pin)
    return "B{}".format(pin - 8)


def emit(msg):
    print(msg)


# =========================
# MCP class
# =========================
class MCP23017:
    def __init__(self, i2c, addr):
        self.i2c = i2c
        self.addr = addr

    def write_reg(self, reg, value):
        self.i2c.writeto_mem(self.addr, reg, bytes([value]))

    def read_reg(self, reg):
        return self.i2c.readfrom_mem(self.addr, reg, 1)[0]

    def init_inputs_pullups(self):
        self.write_reg(IOCON, 0x00)
        self.write_reg(IODIRA, 0xFF)
        self.write_reg(IODIRB, 0xFF)
        self.write_reg(GPPUA, 0xFF)
        self.write_reg(GPPUB, 0xFF)

    def read_gpio(self):
        return self.read_reg(GPIOA), self.read_reg(GPIOB)

    def snapshot(self):
        return {
            "A": self.read_reg(GPIOA),
            "B": self.read_reg(GPIOB),
        }


# =========================
# Init / read helpers
# =========================
def safe_init_mcp(i2c, addr, name):
    try:
        mcp = MCP23017(i2c, addr)
        mcp.init_inputs_pullups()

        iodira = mcp.read_reg(IODIRA)
        iodirb = mcp.read_reg(IODIRB)
        gpioa, gpiob = mcp.read_gpio()

        print("[PASS] {} found at 0x{:02X}".format(name, addr))
        print("       IODIRA=0x{:02X} IODIRB=0x{:02X}".format(iodira, iodirb))
        print("       GPIOA =0b{} GPIOB =0b{}".format(fmt8(gpioa), fmt8(gpiob)))

        return mcp
    except Exception as e:
        print("[FAIL] {} responded in scan but register read/init failed: {}".format(name, e))
        return None


def read_mcp_snapshot(mcp):
    if mcp is None:
        return None
    try:
        return mcp.snapshot()
    except:
        return None


# =========================
# Raw detail printers
# =========================
def print_raw_button_detail(mcp, pin, old_snap, new_snap):
    print("    {} {}".format(EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)), gpio_name(pin)))

    if old_snap is None or new_snap is None:
        return

    if new_snap["A"] != old_snap["A"]:
        bits = changed_bits(old_snap["A"], new_snap["A"])
        print("    {} GPIOA: 0b{} -> 0b{}".format(
            EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)),
            fmt8(old_snap["A"]), fmt8(new_snap["A"])
        ))
        for bit in bits:
            value = (new_snap["A"] >> bit) & 1
            print("      A{} changed to {}".format(bit, value))

    if new_snap["B"] != old_snap["B"]:
        bits = changed_bits(old_snap["B"], new_snap["B"])
        print("    {} GPIOB: 0b{} -> 0b{}".format(
            EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)),
            fmt8(old_snap["B"]), fmt8(new_snap["B"])
        ))
        for bit in bits:
            value = (new_snap["B"] >> bit) & 1
            print("      B{} changed to {}".format(bit, value))


def print_raw_encoder_detail(mcp, pin_a, pin_b, old_snap, new_snap):
    print("    {} {} + {}".format(
        EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)),
        gpio_name(pin_a),
        gpio_name(pin_b)
    ))

    if old_snap is None or new_snap is None:
        return

    if new_snap["A"] != old_snap["A"]:
        bits = changed_bits(old_snap["A"], new_snap["A"])
        print("    {} GPIOA: 0b{} -> 0b{}".format(
            EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)),
            fmt8(old_snap["A"]), fmt8(new_snap["A"])
        ))
        for bit in bits:
            value = (new_snap["A"] >> bit) & 1
            print("      A{} changed to {}".format(bit, value))

    if new_snap["B"] != old_snap["B"]:
        bits = changed_bits(old_snap["B"], new_snap["B"])
        print("    {} GPIOB: 0b{} -> 0b{}".format(
            EXPECTED_MCPS.get(mcp.addr, hex(mcp.addr)),
            fmt8(old_snap["B"]), fmt8(new_snap["B"])
        ))
        for bit in bits:
            value = (new_snap["B"] >> bit) & 1
            print("      B{} changed to {}".format(bit, value))


def print_raw_split_encoder_detail(mcp_a, pin_a, old_a, new_a, mcp_b, pin_b, old_b, new_b):
    print("    {} {} + {} {}".format(
        EXPECTED_MCPS.get(mcp_a.addr, hex(mcp_a.addr)), gpio_name(pin_a),
        EXPECTED_MCPS.get(mcp_b.addr, hex(mcp_b.addr)), gpio_name(pin_b)
    ))

    if old_a is not None and new_a is not None:
        if new_a["A"] != old_a["A"]:
            bits = changed_bits(old_a["A"], new_a["A"])
            print("    {} GPIOA: 0b{} -> 0b{}".format(
                EXPECTED_MCPS.get(mcp_a.addr, hex(mcp_a.addr)),
                fmt8(old_a["A"]), fmt8(new_a["A"])
            ))
            for bit in bits:
                value = (new_a["A"] >> bit) & 1
                print("      A{} changed to {}".format(bit, value))
        if new_a["B"] != old_a["B"]:
            bits = changed_bits(old_a["B"], new_a["B"])
            print("    {} GPIOB: 0b{} -> 0b{}".format(
                EXPECTED_MCPS.get(mcp_a.addr, hex(mcp_a.addr)),
                fmt8(old_a["B"]), fmt8(new_a["B"])
            ))
            for bit in bits:
                value = (new_a["B"] >> bit) & 1
                print("      B{} changed to {}".format(bit, value))

    if old_b is not None and new_b is not None:
        if new_b["A"] != old_b["A"]:
            bits = changed_bits(old_b["A"], new_b["A"])
            print("    {} GPIOA: 0b{} -> 0b{}".format(
                EXPECTED_MCPS.get(mcp_b.addr, hex(mcp_b.addr)),
                fmt8(old_b["A"]), fmt8(new_b["A"])
            ))
            for bit in bits:
                value = (new_b["A"] >> bit) & 1
                print("      A{} changed to {}".format(bit, value))
        if new_b["B"] != old_b["B"]:
            bits = changed_bits(old_b["B"], new_b["B"])
            print("    {} GPIOB: 0b{} -> 0b{}".format(
                EXPECTED_MCPS.get(mcp_b.addr, hex(mcp_b.addr)),
                fmt8(old_b["B"]), fmt8(new_b["B"])
            ))
            for bit in bits:
                value = (new_b["B"] >> bit) & 1
                print("      B{} changed to {}".format(bit, value))


# =========================
# Quadrature LUT
# =========================
LUT = [0] * 16
LUT[0b0001] = +1
LUT[0b0010] = -1
LUT[0b0100] = -1
LUT[0b0111] = +1
LUT[0b1000] = +1
LUT[0b1011] = -1
LUT[0b1101] = -1
LUT[0b1110] = +1


# =========================
# Control constructors
# =========================
def make_encoder(mcp, a_pin, b_pin, sw_pin, id_rot, id_sw):
    if mcp is None:
        return None
    return {
        "mcp": mcp,
        "a": a_pin,
        "b": b_pin,
        "sw": sw_pin,
        "id_rot": id_rot,
        "id_sw": id_sw,
        "last": 0,
        "last_sw": 1,
        "t_sw": utime.ticks_ms(),
        "acc": 0,
    }


def make_split_encoder(mcp_a, pin_a, mcp_b, pin_b, mcp_sw, pin_sw, id_rot, id_sw):
    if mcp_a is None or mcp_b is None or mcp_sw is None:
        return None
    return {
        "is_split": True,
        "mcp_a": mcp_a, "a": pin_a,
        "mcp_b": mcp_b, "b": pin_b,
        "mcp_sw": mcp_sw, "sw": pin_sw,
        "id_rot": id_rot,
        "id_sw": id_sw,
        "last": 0,
        "last_sw": 1,
        "t_sw": utime.ticks_ms(),
        "acc": 0,
    }


def make_button(mcp, gpio, btn_id):
    if mcp is None:
        return None
    return {
        "mcp": mcp,
        "pin": gpio,
        "id": btn_id,
        "last": 1,
        "t": utime.ticks_ms(),
    }


# =========================
# Update functions
# =========================
def update_encoder(e, snaps, prev_snaps):
    try:
        if e.get("is_split"):
            val_a = pin_from_snapshot(snaps.get(e["mcp_a"]), e["a"])
            val_b = pin_from_snapshot(snaps.get(e["mcp_b"]), e["b"])
        else:
            snap = snaps.get(e["mcp"])
            val_a = pin_from_snapshot(snap, e["a"])
            val_b = pin_from_snapshot(snap, e["b"])
    except:
        return

    new_rot = (val_a << 1) | val_b
    if new_rot != e["last"]:
        key = (e["last"] << 2) | new_rot
        e["last"] = new_rot
        delta = -LUT[key]
        if delta != 0:
            e["acc"] += delta
            if e["acc"] >= 4:
                emit("{}:+1".format(e["id_rot"]))
                if e.get("is_split"):
                    print_raw_split_encoder_detail(
                        e["mcp_a"], e["a"], prev_snaps.get(e["mcp_a"]), snaps.get(e["mcp_a"]),
                        e["mcp_b"], e["b"], prev_snaps.get(e["mcp_b"]), snaps.get(e["mcp_b"])
                    )
                else:
                    print_raw_encoder_detail(
                        e["mcp"], e["a"], e["b"],
                        prev_snaps.get(e["mcp"]), snaps.get(e["mcp"])
                    )
                e["acc"] -= 4
            elif e["acc"] <= -4:
                emit("{}:-1".format(e["id_rot"]))
                if e.get("is_split"):
                    print_raw_split_encoder_detail(
                        e["mcp_a"], e["a"], prev_snaps.get(e["mcp_a"]), snaps.get(e["mcp_a"]),
                        e["mcp_b"], e["b"], prev_snaps.get(e["mcp_b"]), snaps.get(e["mcp_b"])
                    )
                else:
                    print_raw_encoder_detail(
                        e["mcp"], e["a"], e["b"],
                        prev_snaps.get(e["mcp"]), snaps.get(e["mcp"])
                    )
                e["acc"] += 4

    if e["sw"] is not None:
        try:
            if e.get("is_split"):
                val_sw = pin_from_snapshot(snaps.get(e["mcp_sw"]), e["sw"])
            else:
                val_sw = pin_from_snapshot(snaps.get(e["mcp"]), e["sw"])
        except:
            return

        now = utime.ticks_ms()
        if val_sw != e["last_sw"] and utime.ticks_diff(now, e["t_sw"]) > DEBOUNCE_MS:
            e["t_sw"] = now
            e["last_sw"] = val_sw
            if val_sw == 0:
                emit("{}:PRESS".format(e["id_sw"]))
                if e.get("is_split"):
                    print_raw_button_detail(
                        e["mcp_sw"], e["sw"],
                        prev_snaps.get(e["mcp_sw"]), snaps.get(e["mcp_sw"])
                    )
                else:
                    print_raw_button_detail(
                        e["mcp"], e["sw"],
                        prev_snaps.get(e["mcp"]), snaps.get(e["mcp"])
                    )


def update_button(b, snaps, prev_snaps):
    try:
        v = pin_from_snapshot(snaps.get(b["mcp"]), b["pin"])
    except:
        return

    now = utime.ticks_ms()
    if v != b["last"] and utime.ticks_diff(now, b["t"]) > DEBOUNCE_MS:
        b["t"] = now
        b["last"] = v
        if v == 0:
            emit("{}:PRESS".format(b["id"]))
            print_raw_button_detail(
                b["mcp"], b["pin"],
                prev_snaps.get(b["mcp"]), snaps.get(b["mcp"])
            )


# =========================
# Start
# =========================
print("\n=== MCP FULL VERIFICATION TEST ===")
print("Using I2C{} with SDA=GP{}, SCL=GP{}, {} Hz".format(
    I2C_ID, SDA_PIN, SCL_PIN, I2C_FREQ
))

i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=I2C_FREQ)

print("\nScanning I2C bus...")
found = i2c.scan()
found_sorted = sorted(found)

if not found_sorted:
    print("No I2C devices found.")
else:
    print("Found devices:", [hex(a) for a in found_sorted])

print("\nChecking expected MCPs...")
mcp_objects = {}

for addr, name in EXPECTED_MCPS.items():
    if addr in found_sorted:
        mcp = safe_init_mcp(i2c, addr, name)
        if mcp is not None:
            mcp_objects[addr] = mcp
    else:
        print("[FAIL] {} missing at 0x{:02X}".format(name, addr))

missing = [a for a in EXPECTED_MCPS if a not in found_sorted]
unexpected = [a for a in found_sorted if a not in EXPECTED_MCPS]

print("\nSummary:")
print("Expected found: {}/{}".format(len(mcp_objects), len(EXPECTED_MCPS)))
if missing:
    print("Missing expected:", [hex(a) for a in missing])
if unexpected:
    print("Unexpected devices:", [hex(a) for a in unexpected])

print("\nRepeated read test ({} samples)...".format(REPEATED_READ_SAMPLES))
for sample in range(REPEATED_READ_SAMPLES):
    print("\nSample", sample + 1)
    for addr in sorted(mcp_objects):
        name = EXPECTED_MCPS[addr]
        try:
            gpioa, gpiob = mcp_objects[addr].read_gpio()
            print("  {} 0x{:02X}  GPIOA=0b{} GPIOB=0b{}".format(
                name, addr, fmt8(gpioa), fmt8(gpiob)
            ))
        except Exception as e:
            print("  [FAIL] {} read error: {}".format(name, e))
    utime.sleep_ms(REPEATED_READ_DELAY_MS)

if not mcp_objects:
    print("\nNo MCPs available. Stopping.")
    raise SystemExit

mcp1 = mcp_objects.get(ADDR_MCP1)
mcp2 = mcp_objects.get(ADDR_MCP2)
mcp3 = mcp_objects.get(ADDR_MCP3)
mcp4 = mcp_objects.get(ADDR_MCP4)

# =========================
# Control map
# =========================
enc1 = make_encoder(mcp1, 9, 10, 11, "KA1", "KA0")
enc2 = make_encoder(mcp1, 12, 13, 14, "KB1", "KB0")
enc3 = make_split_encoder(mcp1, 15, mcp2, 0, mcp2, 1, "TL1", "TL0")
enc4 = make_encoder(mcp2, 2, 3, 4, "VP1", "VP0")
enc5 = make_encoder(mcp2, 5, 6, 7, "VS1", "VS0")
enc6 = make_encoder(mcp3, 3, 4, 5, "HP1", "HP0")
enc7 = make_encoder(mcp3, 6, 7, 8, "HS1", "HS0")
enc8 = make_encoder(mcp3, 9, 10, None, "HZ1", None)
enc9 = make_encoder(mcp3, 11, 12, None, "HX1", None)

encoders = [e for e in [enc1, enc2, enc3, enc4, enc5, enc6, enc7, enc8, enc9] if e is not None]

buttons_raw = [
    make_button(mcp1, 0,  "AS0"),
    make_button(mcp1, 1,  "AR0"),
    make_button(mcp1, 2,  "AX0"),
    make_button(mcp1, 3,  "AH0"),
    make_button(mcp1, 4,  "AF0"),
    make_button(mcp1, 5,  "AC0"),
    make_button(mcp1, 6,  "TF0"),
    make_button(mcp1, 7,  "TS0"),
    make_button(mcp1, 8,  "TM0"),

    make_button(mcp2, 8,  "V10"),
    make_button(mcp2, 9,  "V20"),
    make_button(mcp2, 10, "V30"),
    make_button(mcp2, 11, "V40"),
    make_button(mcp2, 12, "V50"),
    make_button(mcp2, 13, "V60"),
    make_button(mcp2, 14, "V70"),
    make_button(mcp2, 15, "V80"),

    make_button(mcp3, 0,  "VM0"),
    make_button(mcp3, 1,  "VR0"),
    make_button(mcp3, 2,  "VB0"),
    make_button(mcp3, 13, "HL0"),
    make_button(mcp3, 14, "HR0"),
    make_button(mcp3, 15, "HZ0"),

    make_button(mcp4, 0,  "M10"),
    make_button(mcp4, 1,  "M20"),
    make_button(mcp4, 2,  "M30"),
    make_button(mcp4, 3,  "M40"),
    make_button(mcp4, 4,  "XT0"),
    make_button(mcp4, 5,  "XS0"),
    make_button(mcp4, 6,  "XD0"),
    make_button(mcp4, 7,  "XA0"),
]

buttons = [b for b in buttons_raw if b is not None]

print("\n=== LIVE CONTROL VERIFICATION ===")
print("Operate each button and encoder.")
print("Important validation is the named ID line, such as V10:PRESS or VP1:+1.")
print("For encoders, the raw detail now shows both quadrature channels.")
print("The MCP/pin/binary lines underneath are supporting diagnostic detail.")
print("Ctrl+C to stop.\n")

prev_snaps = {}
for addr, mcp in mcp_objects.items():
    prev_snaps[mcp] = read_mcp_snapshot(mcp)

while True:
    snaps = {}
    for addr, mcp in mcp_objects.items():
        snaps[mcp] = read_mcp_snapshot(mcp)

    for e in encoders:
        update_encoder(e, snaps, prev_snaps)

    for b in buttons:
        update_button(b, snaps, prev_snaps)

    prev_snaps = snaps
    utime.sleep_ms(2)
