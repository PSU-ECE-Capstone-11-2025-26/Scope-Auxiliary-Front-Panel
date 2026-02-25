from machine import Pin, UART
import utime

"""
Prototype control scanner -> UART event stream

Message format (newline terminated):
  <ID>:<VALUE>\n

Semantics (PRESS-ONLY):
- Encoders: ID:+1 / ID:-1 per detent step
- Encoder push: ID:1 on press (NO release)
- Buttons (macros + channels): ID:1 on press (NO release)
- Indicators: Pico updates indicators ONLY from UART RX commands sent by Pi.

Indicator ID convention:
  Indicator IDs are the control ID prefixed with 'I'
    e.g. V10  is CH1 button press event (Pico->Pi)
         IV10 is CH1 indicator command (Pi->Pico)

Notes:
- Inputs are active-low (PULL_UP): pressed == 0, released == 1
- DEBUG_ECHO prints to Thonny while still transmitting UART.
"""

# ---------------- UART CONFIG ----------------
UART_ID = 0
UART_TX = 16
UART_RX = 17
BAUD    = 115200

uart = UART(UART_ID, BAUD, tx=Pin(UART_TX), rx=Pin(UART_RX))

DEBUG_ECHO = True  # True: show messages in Thonny; False: UART-only

def send(btn_id, value):
    """Send one event line to the host/controller."""
    msg = "{}:{}\n".format(btn_id, value)
    uart.write(msg)
    if DEBUG_ECHO:
        print(msg, end="")

# ---------------- Quadrature decode LUT ----------------
LUT = [0]*16
LUT[0b0001] = +1
LUT[0b0010] = -1
LUT[0b0100] = -1
LUT[0b0111] = +1
LUT[0b1000] = +1
LUT[0b1011] = -1
LUT[0b1101] = -1
LUT[0b1110] = +1

DEBOUNCE_MS = 30

# ---------------- Encoder helpers ----------------
def make_encoder(a_pin, b_pin, sw_pin, id_rot, id_sw, DIR=-1, STEP=4, name="E"):
    a  = Pin(a_pin,  Pin.IN, Pin.PULL_UP)
    b  = Pin(b_pin,  Pin.IN, Pin.PULL_UP)
    sw = Pin(sw_pin, Pin.IN, Pin.PULL_UP)

    def read_state():
        return (a.value() << 1) | b.value()

    return {
        "name": name,
        "a": a, "b": b, "sw": sw,
        "a_pin": a_pin, "b_pin": b_pin, "sw_pin": sw_pin,
        "id_rot": id_rot, "id_sw": id_sw,
        "DIR": DIR, "STEP": STEP,
        "last": read_state(),
        "acc": 0,
        "last_sw": sw.value(),
        "t_sw": utime.ticks_ms(),
    }

def update_encoder(e):
    # rotation (A/B)
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

    # push switch (PRESS ONLY)
    v = e["sw"].value()
    now = utime.ticks_ms()
    if v != e["last_sw"] and utime.ticks_diff(now, e["t_sw"]) > DEBOUNCE_MS:
        e["t_sw"] = now
        e["last_sw"] = v
        if v == 0:  # pressed
            send(e["id_sw"], 1)

# ---------------- Button helpers ----------------
def make_button(gpio, btn_id, name=None):
    return {
        "name": name if name else btn_id,
        "pin": Pin(gpio, Pin.IN, Pin.PULL_UP),
        "gpio": gpio,
        "id": btn_id,
        "last": 1,
        "t": utime.ticks_ms()
    }

def update_button_press_only(b):
    """Button: emit 1 on press only (NO release)."""
    v = b["pin"].value()
    now = utime.ticks_ms()
    if v != b["last"] and utime.ticks_diff(now, b["t"]) > DEBOUNCE_MS:
        b["t"] = now
        b["last"] = v
        if v == 0:  # pressed
            send(b["id"], 1)

# ---------------- PIN MAP + ID MAP ----------------
enc1 = make_encoder(a_pin=1, b_pin=2, sw_pin=0, id_rot="KA1", id_sw="KA0", DIR=-1, STEP=4, name="EN1")
enc2 = make_encoder(a_pin=4, b_pin=5, sw_pin=3, id_rot="KB1", id_sw="KB0", DIR=-1, STEP=4, name="EN2")

macros = [
    make_button(6, "M10", "MACRO1"),
    make_button(7, "M20", "MACRO2"),
    make_button(8, "M30", "MACRO3"),
    make_button(9, "M40", "MACRO4"),
]

CH_BTN_PINS = [10,11,12,13,14,15]            # CH1..CH6
CH_IDS      = ["V10","V20","V30","V40","V50","V60"]
ch_btn = [make_button(CH_BTN_PINS[i], CH_IDS[i], f"CH{i+1}") for i in range(6)]

CH_LED_PINS_ALL = [18,19,20,21,22,26,27,28]  # CH1..CH8 LED pins (wired)
CH_LED_PINS = CH_LED_PINS_ALL[:6]            # active LEDs: CH1..CH6
ch_led = [Pin(pin, Pin.OUT) for pin in CH_LED_PINS]

ACTIVE_HIGH = True

def led_write(i, on):
    if ACTIVE_HIGH:
        ch_led[i].value(1 if on else 0)
    else:
        ch_led[i].value(0 if on else 1)

# cache (mirrors Pi commands; NOT used for decisions)
ch_state = [0]*6
for i in range(6):
    led_write(i, False)

def print_gpio_assignments():
    print("\n=== Current GPIO Assignments ===")
    print("UART0: TX=GP{}  RX=GP{}  BAUD={}".format(UART_TX, UART_RX, BAUD))

    print("\nEncoders:")
    print("  EN1: A=GP{} B=GP{} SW=GP{}  -> {} (turn), {} (push)".format(
        enc1["a_pin"], enc1["b_pin"], enc1["sw_pin"], enc1["id_rot"], enc1["id_sw"]))
    print("  EN2: A=GP{} B=GP{} SW=GP{}  -> {} (turn), {} (push)".format(
        enc2["a_pin"], enc2["b_pin"], enc2["sw_pin"], enc2["id_rot"], enc2["id_sw"]))

    print("\nMacros (press-only):")
    for b in macros:
        print("  GP{} -> {}".format(b["gpio"], b["id"]))

    print("\nChannel buttons (press-only):")
    for i in range(6):
        print("  CH{} GP{} -> {}".format(i+1, CH_BTN_PINS[i], CH_IDS[i]))

    print("\nChannel LEDs (wired):")
    for i, p in enumerate(CH_LED_PINS_ALL, start=1):
        tag = "ACTIVE" if i <= 6 else "disabled"
        print("  CH{} LED -> GP{} ({})".format(i, p, tag))

    print("==============================\n")

if DEBUG_ECHO:
    print_gpio_assignments()

send("BOOT", 1)

# ---------------- UART RECEIVE (Pi/Scope -> Pico Indicators) ----------------
def handle_uart_message(line):
    """
    Expecting:
        <ID>:<VALUE>

    Indicator IDs are prefixed with 'I'
      e.g. IV10:1  -> turn CH1 indicator ON
           IV20:0  -> turn CH2 indicator OFF
    """
    try:
        msg = line.strip()
        if not msg:
            return

        parts = msg.split(":")
        if len(parts) != 2:
            return

        msg_id, value = parts[0], parts[1]

        if not msg_id.startswith("I"):
            return

        base_id = msg_id[1:]   # "IV10" -> "V10"
        state = int(value)

        if base_id in CH_IDS:
            idx = CH_IDS.index(base_id)
            ch_state[idx] = state
            led_write(idx, state)

    except Exception as e:
        if DEBUG_ECHO:
            print("UART parse error:", e)

def poll_uart():
    while uart.any():
        line = uart.readline()
        if line:
            try:
                handle_uart_message(line.decode())
            except:
                pass

# ---------------- Main Loop ----------------
while True:
    update_encoder(enc1)
    update_encoder(enc2)

    for b in macros:
        update_button_press_only(b)

    for b in ch_btn:
        update_button_press_only(b)

    poll_uart()

    utime.sleep_ms(1)
