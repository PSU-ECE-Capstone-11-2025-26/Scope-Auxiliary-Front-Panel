import argparse
import math
import re
import threading
import time
from time import sleep
from typing import Optional

import pyvisa
from pyvisa import VisaIOError
from pyvisa.resources import MessageBasedResource

from tekafp.api_server import (
    RawPacket,
    get_raw_packet,
    run_api_server,
    send_packet_data,
    startup_event,
)
from tekafp.api_server.error import APIError
from tekafp.api_server.packets import (
    ErrorPacketData,
    MacroRecordPacketData,
    MacroStatePacketData,
    PacketData,
    ScopeActionPacketData,
    ScopeInfoPacketData,
    ScopeListPacketData,
)
from tekafp.input import Input
from tekafp.uart import MockUARTBridge, UARTBridge
from tekafp.util import clamp, parse_resp

# UART config
PORT = "/dev/serial0"
BAUD = 115200

# Scope config
PYVISA_BACKEND = "@py"
SCOPE_TIMEOUT_MS = 5000

# Tuning knobs for “feel”
VERT_STEP_DIVS = 0.10  # Vertical position step per encoder detent (+/-1)
HORIZ_STEP_PCT = 1.0  # Horizontal position step in percent (0..~100) per detent

def _scale_idx_to_val(mantissas: list[float], idx: int) -> float:
    return mantissas[idx % 3] * 10 ** (idx // 3)


def _scale_val_to_idx(v: float) -> int:
    # Multiply log10 by 3 (steps/decade) and round to nearest step,
    # which absorbs small floating-point error in scope-returned values.
    return round(math.log10(v) * 3)


# Vertical scale: 1/2/5 sequence per Tektronix spec, index 0 = 1 V/div
# Range: index -10 (500 µV/div) to index 6 (100 V/div)
_VERT_MANTISSAS = [1.0, 2.0, 5.0]
_VERT_MIN_IDX = -10
_VERT_MAX_IDX = 6

# Horizontal scale: 1/2/4 sequence per Tektronix spec, index 0 = 1 s/div
# Range: index -29 (200 ps/div) to index 9 (1000 s/div)
_HORIZ_MANTISSAS = [1.0, 2.0, 4.0]
_HORIZ_MIN_IDX = -29
_HORIZ_MAX_IDX = 9

# Level encoder step size: 2/4/8 sequence
# to match the MSO, index as (vert_idx - 6) (~2% of vert scale per detent)
# e.g. 100mV/div -> 2mV/step, 200mV/div -> 4mV/step, 1V/div -> 20mV/step
_LEVEL_MANTISSAS = [2.0, 4.0, 8.0]


def connect_uart(mock: bool = False) -> UARTBridge:
    if mock:
        return MockUARTBridge(PORT, baudrate=BAUD, timeout=1, write_timeout=1)
    bridge = UARTBridge(PORT, baudrate=BAUD, timeout=0.1, write_timeout=1)
    if not bridge.connect():
        raise RuntimeError(f"Failed to open UART on {PORT}")
    print(f"Connected UART: {PORT} @ {BAUD}")
    return bridge


class Controller:
    def __init__(self, scope: MessageBasedResource, bridge: UARTBridge) -> None:
        self.scope: MessageBasedResource = scope
        self.bridge: UARTBridge = bridge
        # Make sure we're in a mode where horizontal position behaves like the
        # front panel knob
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        self.scope.write("HORIZONTAL:DELAY:MODE OFF")
        self.idn = self.scope.query("*IDN?").strip()
        print("Connected ctrl:", self.idn)
        self.channel_count = self._channels_from_idn(self.idn)
        print(f"Channel count = {self.channel_count}")

        self._channels: dict[int, bool] = {ch: False for ch in range(1, self.channel_count + 1)}
        self._source_channel: int = 0
        self._vert_fine: bool = False # fine mode toggle for vertical scale

        self._fast_acquire: bool = False

        self._run_state: bool = False

    def _channels_from_idn(self, idn: str) -> int:
        m = re.search(r"MSO\d(\d)", idn, re.IGNORECASE)
        if m is None:
            return 1
        return int(m.group(1))

    def get_scope_channel_state(self, channel: int) -> bool:
        resp = self.scope.query(f"DISPLAY:GLOBAL:CH{channel}:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def sync_all_channels_from_scope(self) -> None:
        highest = 0
        for ch in range(1, 9):
            actual = self.get_scope_channel_state(ch)
            self._channels[ch] = actual
            self.send_channel_led(ch, actual)
            if actual:
                highest = ch
            print(f"[INIT] CH{ch} -> {actual}")

        # Chooses highest enabled channel as the active selected channel
        self._source_channel = highest

        self.set_scope_selected_source()
        self.send_selected_channel_leds()
        self.sync_fast_acquire_from_scope(force=True)
        self.sync_run_stop_from_scope(force=True)

    def sync_all_changed_channels_from_scope(self) -> None:
        any_changed = False

        for ch in range(1,9):
            actual = self.get_scope_channel_state(ch)
            if self._channels[ch] != actual:
                self._channels[ch] = actual
                self.send_channel_led(ch, actual)
                print(f"[SYNC] CH{ch} -> {actual}")
                any_changed = True

                if actual:
                    self._source_channel = ch
                    self.scope.write(f"DISPLAY:SELECT:SOURCE CH{self._source_channel}")
                    self.send_selected_channel_leds()

        # Keep selected source sane if current source is now off
        if self._source_channel != 0 and not self._channels[self._source_channel]:
            highest = 0
            for k, v in self._channels.items():
                if v:
                    highest = k

            self._source_channel = highest

            self.set_scope_selected_source()
            self.send_selected_channel_leds()

        # If nothing changed, stay quiet
        if any_changed:
            print("[SYNC] Full channel sync pass complete")

    # Per-channel RGB color (R,G,B)
    CHANNEL_COLORS: dict[int, tuple[int, int, int]] = {
        1: (1, 1, 0),  # Yellow
        2: (0, 1, 1),  # Cyan
        3: (1, 0, 0),  # Red
        4: (0, 1, 0),  # Lime Green
        5: (1, 1, 0),  # Orange approximation
        6: (0, 0, 1),  # Blue
        7: (1, 0, 1),  # Purple
        8: (0, 1, 0),  # Forest Green approximation
    }

    def send_channel_led(self, channel: int, state: bool) -> None:
        # Send indicator update back to Pico
        if channel not in range(1,9):
            return

        r, g, b = self.CHANNEL_COLORS[channel]

        if not state: 
            r, g, b = 0, 0, 0

        msgs = [
            f"IV{channel}0_R:{r}\n".encode("utf-8"), 
            f"IV{channel}0_G:{g}\n".encode("utf-8"),
            f"IV{channel}0_B:{b}\n".encode("utf-8"),
        ]

        for msg in msgs:
            self.bridge.write_sync(msg)
            print(f"[UART->PICO] {msg.decode().strip()}")


    def send_selected_channel_leds(self) -> None: 
        # Two RGB LEDs used to show the active selected channel: 
        # VP1_RGB and VS1_RGB should always match the selected channel color
        
        r, g, b = self.CHANNEL_COLORS.get(self._source_channel, (0,0,0))

        msgs = [
            f"IVP1_R:{r}\n".encode("utf-8"),
            f"IVP1_G:{g}\n".encode("utf-8"),
            f"IVP1_B:{b}\n".encode("utf-8"),
            f"IVS1_R:{r}\n".encode("utf-8"),
            f"IVS1_G:{g}\n".encode("utf-8"),
            f"IVS1_B:{b}\n".encode("utf-8"),
        ]

        for msg in msgs:
            self.bridge.write_sync(msg)
            print(f"[UART->PICO] {msg.decode().strip()}")

    def get_scope_selected_source(self) -> int:
        resp = self.scope.query("DISPLAY:SELECT:SOURCE?").strip().upper()

        if resp.endswith("NONE"):
            return 0

        for ch in range(1, 9):
            if resp.endswith(f"CH{ch}") or f"CH{ch}" in resp:
                return ch

        print(f"[SYNC] Unknown selected source response: {resp}")
        return self._source_channel


    def set_scope_selected_source(self) -> None:
        if self._source_channel == 0:
            self.scope.write("DISPLAY:SELECT:SOURCE NONE")
        else:
            self.scope.write(f"DISPLAY:SELECT:SOURCE CH{self._source_channel}")


    def sync_selected_source_from_scope(self) -> None:
        actual_source = self.get_scope_selected_source()

        if actual_source != self._source_channel:
            self._source_channel = actual_source
            self.send_selected_channel_leds()
            print(f"[SYNC] selected source -> CH{actual_source}")

    def set_channel_display(self, channel: int) -> None:
        if channel not in range(1, 9):
            return
        last_state: bool = self._channels[channel]

        if self._source_channel == channel:
            # enabled and source => disable, select highest enabled as active
            self._channels[channel] = False
            highest: int = 0
            for k, v in self._channels.items():
                if v:
                    highest = k
            self._source_channel = highest
        elif last_state:
            # enabled => set as source
            self._source_channel = channel
        else:
            # disabled => enable, set as source
            self._channels[channel] = True
            self._source_channel = channel

        self.set_scope_selected_source()
        self.send_selected_channel_leds()

        if last_state != self._channels[channel]:
            self.scope.write(
                f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self._channels[channel])}"
            )
            self.send_channel_led(channel, self._channels[channel]) 

        print(
            f"[SCOPE] CH{channel} display -> {self._channels[channel]} (source={self._source_channel})"  # noqa: E501
        )

    def force_channel_display(self, channel: int, desired: bool) -> None:
        if channel not in range(1, self.channel_count + 1):
            return

        self._channels[channel] = desired

        if self._source_channel == channel and not desired:
            self._source_channel = max(
                (k for k, v in self._channels.items() if v),
                default=0,
            )

        self.scope.write(f"DISPLAY:GLOBAL:CH{channel}:STATE {int(desired)}")
        self.send_channel_led(channel, desired)

        print(
            f"[SCOPE] CH{channel} forced -> {self._channels[channel]}"
        )

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical position.")
            return
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"CH{ch}:POSITION {new}")
        print(f"[SCOPE] CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def center_vertical_position(self) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical center.")
            return

        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])
        self.scope.write(f"CH{ch}:POSITION 0")
        print(f"[SCOPE] CH{ch} vertical position centered: {cur:.3f} -> 0.000")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.write(f"HORIZONTAL:POSITION {new}")
        print(f"[SCOPE] horizontal position (%): {cur:.2f} -> {new:.2f}")

    def center_horizontal_position(self) -> None:
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])
        self.scope.write("HORIZONTAL:POSITION 50")
        print(f"[SCOPE] horizontal position centered (%): {cur:.2f} -> 50.00")

    def adjust_vertical_scale(self, detents: int) -> None:
        ch = self._source_channel
        if ch == 0:
            print("[SCOPE] No active channel selected, ignoring vertical scale.")
            return
        cur = float(self.scope.query(f"CH{ch}:SCALE?").strip().split()[-1])

        if self._vert_fine:
            # Fine mode: find the coarse step that owns the current value,
            # then use 1/20th of it as the fine step
            nearest = _scale_val_to_idx(cur)
            coarse_step = _scale_idx_to_val(_VERT_MANTISSAS, nearest)
            fine_step = coarse_step / 20.0
            new = cur + detents * fine_step
            # Clamp between the two surrounding coarse steps
            lower = _scale_idx_to_val(_VERT_MANTISSAS, max(nearest - 1, _VERT_MIN_IDX))
            upper = _scale_idx_to_val(_VERT_MANTISSAS, min(nearest + 1, _VERT_MAX_IDX))
            new = clamp(new, lower, upper)
        else:
            nearest = _scale_val_to_idx(cur)
            new_idx = int(clamp(nearest + detents, _VERT_MIN_IDX, _VERT_MAX_IDX))
            new = _scale_idx_to_val(_VERT_MANTISSAS, new_idx)

        self.scope.write(f"CH{ch}:SCALE {new}")
        print(f"[SCOPE] CH{ch} vertical scale ({'fine' if self._vert_fine else 'coarse'}): {cur:.3e} -> {new:.3e} V/div")

    def adjust_horizontal_scale(self, detents: int) -> None:
        cur = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        nearest = _scale_val_to_idx(cur)
        new_idx = int(clamp(nearest + detents, _HORIZ_MIN_IDX, _HORIZ_MAX_IDX))
        new = _scale_idx_to_val(_HORIZ_MANTISSAS, new_idx)

        self.scope.write(f"HORIZONTAL:MODE:SCALE {new}")
        actual = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        print(
            f"[SCOPE] horizontal scale (coarse): "
            f"{cur:.3e} -> {actual:.3e} s/div"
        )

    def encoder_trigger_level(self, detents: int, trigger: str = "A") -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        source: str = parse_resp(self.scope.query(f"TRIGGER:{trigger}:EDGE:SOURCE?"), str)
        query = f"TRIGGER:{trigger}:LEVEL:{source}"
        cur: float = parse_resp(self.scope.query(query + "?"), float)

        vert_scale: float = parse_resp(self.scope.query(f"{source}:SCALE?"), float)
        # index _LEVEL_MANTISSAS as (idx - 5) for feel (MSO matching would be -6)
        step = _scale_idx_to_val(_LEVEL_MANTISSAS, _scale_val_to_idx(vert_scale) - 5)
        new = clamp(cur + detents * step, -100.0, 100.0)

        self.scope.write(query + f" {new}")
        print(f"[SCOPE] trigger level: {cur:.2f} -> {new:.2f} V")

    def sync_trigger_state(self) -> None:
        source: str = parse_resp(
            self.scope.query("TRIGGER:A:EDGE:SOURCE?"), str
        )
        # FIXME the [2] index on this string is due to subchannels, e.g. for a digital probe
        #  where channel 1 could have CH1_D0, CH1_D1, etc. source[2] gives just the channel (1)
        r, g, b = self.CHANNEL_COLORS[int(source[2])]
        self.bridge.write_sync(f"ITL1_R:{r}\n".encode())
        self.bridge.write_sync(f"ITL1_G:{g}\n".encode())
        self.bridge.write_sync(f"ITL1_B:{b}\n".encode())
        cur: str = parse_resp(self.scope.query("TRIGGER:A:EDGE:SLOPE?"), str).upper()
        match cur:
            case "RISE":
                rise = 1
                fall = 0
            case "FALL":
                rise = 0
                fall = 1
            case "EITHER":
                rise = fall = 1
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        self.bridge.write_sync(f"ITS0_UP:{rise}\n".encode())
        self.bridge.write_sync(f"ITS0_DN:{fall}\n".encode())
        cur: str = parse_resp(self.scope.query("TRIGGER:A:MODE?"), str).upper()
        if cur == "AUTO":
            rise = 1
            fall = 0
        else:
            rise = 0
            fall = 1
        self.bridge.write_sync(f"ITM0_A:{rise}\n".encode())
        self.bridge.write_sync(f"ITM0_N:{fall}\n".encode())
        cur = parse_resp(self.scope.query("TRIGGER:STATE?"), str).upper()
        match cur:
            case "READY" | "AUTO":
                rise = 1
                fall = 0
            case "TRIGGER":
                rise = 0
                fall = 1
            case _:
                rise = fall = 0
        self.bridge.write_sync(f"ITF0_R:{rise}\n".encode())
        self.bridge.write_sync(f"ITF0_T:{fall}\n".encode())

    def next_trigger_slope(self) -> None:
        cur: str = parse_resp(self.scope.query("TRIGGER:A:EDGE:SLOPE?"), str).upper()
        new: str = ""
        match cur:
            case "RISE":
                new = "FALL"
            case "FALL":
                new = "EITHER"
            case "EITHER":
                new = "RISE"
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        self.scope.write(f"TRIGGER:A:EDGE:SLOPE {new}")

    # Toggle the scope's Run/Stop state
    def toggle_run_stop(self) -> None:
        current = self.get_scope_run_state()
        new_state = not current

        self.scope.write(f"ACQUIRE:STATE {'RUN' if new_state else 'STOP'}")

        self._run_state = new_state
        self.send_run_stop_led(new_state)

        print(f"[SCOPE] Run/Stop -> {'RUN' if new_state else 'STOP'}")

    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.write("AUTOSET EXECUTE")
        print("[SCOPE] AutoSet executed")

    # Toggle the scope's Fast Acquire state
    def toggle_fast_acquire(self) -> None:
        current = self.get_scope_fast_acquire_state()
        new_state = not current

        self.scope.write(f"ACQUIRE:FASTACQ:STATE {int(new_state)}")

        self._fast_acquire = new_state
        self.send_fast_acquire_led(new_state)

        print(f"[SCOPE] Fast Acquire -> {'ON' if new_state else 'OFF'}")

    def get_scope_fast_acquire_state(self) -> bool:
        resp = self.scope.query("ACQUIRE:FASTACQ:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def send_fast_acquire_led(self, state: bool) -> None:
        msg = f"IAF0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        print(f"[UART->PICO] {msg.decode().strip()}")

    def sync_fast_acquire_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_fast_acquire_state()

        if force or self._fast_acquire != actual:
            self._fast_acquire = actual
            self.send_fast_acquire_led(actual)
            print(f"[SYNC] Fast Acquire -> {actual}")

    def get_scope_run_state(self) -> bool:
        resp = self.scope.query("ACQUIRE:STATE?").strip().upper()
        return resp in ("RUN", "ON", "1")


    def send_run_stop_led(self, state: bool) -> None:
        msg = f"IAR0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        print(f"[UART->PICO] {msg.decode().strip()}")


    def sync_run_stop_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_run_state()

        if force or self._run_state != actual:
            self._run_state = actual
            self.send_run_stop_led(actual)
            print(f"[SYNC] Run/Stop -> {actual}")

    # UART event handler
    def handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V80, VP1/VP0, HP1/HP0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        # Channel Selection
        if msg_id in ("V10", "V20", "V30", "V40", "V50", "V60", "V70", "V80"):
            ch = int(msg_id[1])  # 'V10' -> 1, 'V80' -> 8
            self.set_channel_display(ch)
            return

        # Encoder VP1 rotation: vertical position of current active channel
        if msg_id == "VP1":
            detents = int(val)  # should be +1 / -1
            if detents:
                self.adjust_vertical_position(detents)
            return

        # Encoder VP0 press: center vertical position of current active channel
        if msg_id == "VP0":
            if int(val) == 1:
                self.center_vertical_position()
            return

        # Encoder HP1 rotation: horizontal position (global)
        if msg_id == "HP1":
            detents = int(val)
            if detents:
                self.adjust_horizontal_position(detents)
            return

        # Encoder HP0 press: center horizontal position globally
        if msg_id == "HP0":
            if int(val) == 1:
                self.center_horizontal_position()
            return

        # Encoder VS1 rotation: vertical scale of current source channel (1/2/5 steps)
        if msg_id == "VS1":
            detents = int(val)
            if detents: 
                self.adjust_vertical_scale(-detents)
            return

        # Encoder HS1 rotation: horizontal timebase scale (1/2/4 steps)
        if msg_id == "HS1":
            detents = int(val)
            if detents: 
                self.adjust_horizontal_scale(-detents)
            return

        # VS0: toggle fine mode for vertical scale encoder
        if msg_id == "VS0":
            if int(val) == 1: 
                self._vert_fine = not self._vert_fine
                print(f"[SCOPE] Vertical scale fine mode -> {'ON' if self._vert_fine else 'OFF'}")
            return

        # trigger level encoder
        if msg_id == "TL1":
            detents = int(val)
            if detents:
                self.encoder_trigger_level(detents)
            return
        # trigger level push
        if msg_id == "TL0":
            self.scope.write("TRIGGER:A SETLevel")
            return

        # trigger force
        if msg_id == "TF0":
            self.scope.write("TRIGGER FORCE")
            return

        # trigger slope type
        if msg_id == "TS0":
            self.next_trigger_slope()
            return

        # trigger mode
        if msg_id == "TM0":
            cur: str = parse_resp(self.scope.query("TRIGGER:A:MODE?"), str).upper()
            new: str = "AUTO" if cur == "NORMAL" else "NORMAL"
            self.scope.write(f"TRIGGER:A:MODE {new}")
            return

        # Run/Stop button
        if msg_id == "AR0":
            self.toggle_run_stop()
            return

        # Fast Acquire button
        if msg_id == "AF0":
            self.toggle_fast_acquire()
            return

        # AutoSet button
        if msg_id == "XA0":
            self.autoset()
            return

        # zoom enable
        if msg_id == "HZ0":
            # FIXME: uses scope state
            cur: str = parse_resp(
                self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE?"),
                str
            )
            new: str = "ON" if cur in ("OFF", 0) else "OFF"
            self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE {new}")

        # zoom encoder
        if msg_id == "HZ1":
            # FIXME: needs to use 1-2-4 increments
            cur: int = parse_resp(
                self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE?"),
                int
            )
            new: int = clamp(cur + inp.value, 0.0, 10.0)
            self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE {new}")

        # pan encoder
        if msg_id == "HX1":
            cur: float = parse_resp(
                self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION?"),
                float
            )
            # TODO: how many percent to change for each detent?
            new: float = clamp(cur + inp.value * 10, 0.0, 100.0)
            self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION {new}")


class MacroManager:
    NUM_SLOTS = 4

    PHYSICAL_MACRO_IDS = {
        "M10": 0,
        "M20": 1,
        "M30": 2,
        "M40": 3,
    }

    def __init__(self) -> None:
        self.macros: list[list[bytes | tuple[str, int, bool]]] = [
            [] for _ in range(self.NUM_SLOTS)
        ]
        self.recording_slot: Optional[int] = None
        self._playing_back = False

    def _valid_slot(self, slot: int) -> bool:
        return 0 <= slot < self.NUM_SLOTS

    def should_handle(self, inp: Input) -> bool:
        msg_id = str(inp.id)

        return (
            self.recording_slot is not None
            or msg_id in self.PHYSICAL_MACRO_IDS
        )

    def send_macro_state(self) -> None:
        send_packet_data(
            MacroStatePacketData(
                [bool(macro) for macro in self.macros]
            )
        )

    def start_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            print(f"[MACRO] Invalid slot {slot}")
            return

        if self.recording_slot is not None and self.recording_slot != slot:
            print(f"[MACRO] Stopping slot {self.recording_slot} before recording slot {slot}")

        self.recording_slot = slot
        self.macros[slot] = []
        print(f"[MACRO] Recording started for slot {slot}")

    def stop_recording(self, slot: int) -> None:
        if not self._valid_slot(slot):
            print(f"[MACRO] Invalid slot {slot}")
            return

        if self.recording_slot != slot:
            print(f"[MACRO] Stop ignored for slot {slot}; currently recording {self.recording_slot}")
            return

        self.recording_slot = None
        print(f"[MACRO] Recording stopped for slot {slot}. {len(self.macros[slot])} events saved.")
        self.send_macro_state()

    def handle_uart_input(self, raw: bytes, inp: Input, ctrl: Controller) -> None:
        msg_id = str(inp.id)

        if msg_id in self.PHYSICAL_MACRO_IDS:
            try:
                if int(inp.value) != 1:
                    return
            except ValueError:
                return

            slot = self.PHYSICAL_MACRO_IDS[msg_id]
            self.playback(slot, ctrl)
            return

        is_channel_toggle = msg_id in (
            "V10", "V20", "V30", "V40",
            "V50", "V60", "V70", "V80",
        )

        if self.recording_slot is not None and not self._playing_back and is_channel_toggle:
            ch = int(msg_id[1])

            ctrl.handle_input(inp)

            desired = ctrl._channels[ch]
            event = ("channel_state", ch, desired)

            self.macros[self.recording_slot].append(event)
            print(f"[MACRO] slot {self.recording_slot} + {event!r}")
            return

        if self.recording_slot is not None and not self._playing_back:
            self.macros[self.recording_slot].append(raw)
            print(f"[MACRO] slot {self.recording_slot} + {raw!r}")

        ctrl.handle_input(inp)

    def playback(self, slot: int, ctrl: Controller) -> None:
        if not self._valid_slot(slot):
            print(f"[MACRO] Invalid slot {slot}")
            return

        if self.recording_slot is not None:
            print("[MACRO] Playback ignored while recording")
            return

        macro = self.macros[slot]
        if not macro:
            print(f"[MACRO] Slot {slot} is empty")
            return

        played_channel_event = False

        print(f"[MACRO] Playing slot {slot}: {len(macro)} events")
        self._playing_back = True

        try:
            for raw in macro:
                if isinstance(raw, tuple):
                    kind, ch, desired = raw

                    if kind == "channel_state":
                        played_channel_event = True
                        ctrl.force_channel_display(ch, desired)
                        time.sleep(0.25)
                        continue

                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"[MACRO] Bad recorded message {raw!r}: {e}")
                    continue

                if str(inp.id) in self.PHYSICAL_MACRO_IDS:
                    continue

                ctrl.handle_input(inp)
                time.sleep(0.25)
            if played_channel_event:
                ctrl._source_channel = max(
                    (k for k, v in ctrl._channels.items() if v),
                    default=0,
                )

                ctrl.set_scope_selected_source()
                ctrl.send_selected_channel_leds()

        finally:
            self._playing_back = False
            print(f"[MACRO] Playback done for slot {slot}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mock", action="store_true", help="Run in mock mode")
    parser.add_argument(
        "-a",
        "--auto",
        action="store_true",
        help="Automatically connect to the first available scope",
    )
    args = parser.parse_args()
    # internal setup
    bridge = connect_uart(args.mock)
    print("Starting WebSocket API thread...")
    api_thead = threading.Thread(target=run_api_server, daemon=True)
    api_thead.start()
    startup_event.wait()

    # ctrl setup
    rm: pyvisa.ResourceManager = pyvisa.ResourceManager(PYVISA_BACKEND)
    scopes: dict[str, Controller] = {}

    macro_manager = MacroManager()
    def send_scope_connection_led(state: bool) -> None:
        msg = f"ISP_CON:{int(state)}\n".encode("utf-8")
        bridge.write_sync(msg)
        print(f"[UART->PICO] {msg.decode().strip()}")

    def connect_to_scope(resource_name: str) -> None:
        try:
            scope: MessageBasedResource = rm.open_resource(
                resource_name,
                resource_pyclass=MessageBasedResource,
                timeout=SCOPE_TIMEOUT_MS,
                write_termination="\n",
                read_termination="\n",
            )
        except (VisaIOError, ValueError) as err:
            send_packet_data(
                ErrorPacketData(
                    resource_name, APIError.CONNECTION_ERROR, error_str=str(err)
                )
            )
            return

        ctrl = Controller(scope, bridge)
        ctrl.sync_all_channels_from_scope()
        scopes[resource_name] = ctrl
        send_scope_connection_led(True)
        send_packet_data(
            ScopeInfoPacketData(
                resource_name=resource_name, idn=ctrl.idn, channel_count=ctrl.channel_count
            )
        )

    def auto_connect_first_scope() -> None:
        resources = rm.list_resources("(USB?*::INSTR|TCPIP?*::INSTR)")

        if not resources:
            print("[AUTO] No scopes found")
            return

        first = resources[0]
        print(f"[AUTO] Connecting to: {first}")

        if first not in scopes:
            connect_to_scope(first)

    def handle_packet(packet: RawPacket) -> None:
        for pd in packet["data"]:
            data = PacketData.decode(pd)
            match data:
                case ScopeActionPacketData(action=a):
                    print(f"Received packet action='{a}'")
                    match a:
                        case "enable":
                            if data.resource_name not in scopes:
                                print(f"enabling scope {data.resource_name}")
                                if args.mock:
                                    scopes[data.resource_name] = None
                                    send_packet_data(
                                        ScopeInfoPacketData(
                                            data.resource_name,
                                            "TEKTRONIX,MSO58,C012345,CF:91.1CT FV:1.0.1.8",
                                            8,
                                        )
                                    )
                                else:
                                    connect_to_scope(data.resource_name)
                        case "disable":
                            if data.resource_name in scopes:
                                print(f"disabling scope {data.resource_name}")
                                if args.mock:
                                    del scopes[data.resource_name]
                                else:
                                    c = scopes.pop(data.resource_name)
                                    c.scope.close()

                                    if not scopes:
                                        send_scope_connection_led(False)
                            else:
                                print(
                                    f"scope {data.resource_name} not enabled: ignoring"
                                )
                        case "list":
                            if args.mock:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            "USB0::0x0699::0x0363::C102912::INSTR": False,
                                            "USB0::0x0699::0x0408::B011823::INSTR": False,
                                        }
                                    )
                                )
                            else:
                                send_packet_data(
                                    ScopeListPacketData(
                                        {
                                            r: r in scopes
                                            for r in rm.list_resources(
                                                "(USB?*::INSTR|TCPIP?*::INSTR)"
                                            )
                                        }
                                    )
                                )
                        case _:
                            print(f"Unknown action: {a}")
                case MacroRecordPacketData():
                    if data.record:
                        macro_manager.start_recording(data.slot)
                    else:
                        macro_manager.stop_recording(data.slot)
                case _:
                    print(f"Unknown or incorrect packet type {data.type}")

    if args.auto:
        auto_connect_first_scope()

    try:
        last_sync = time.monotonic()
        last_input = 0.0 # no input yet
        sync_period_s = 0.05

        while True:
            raw = bridge.get()
            if not args.mock and scopes and raw:
                try:
                    inp = Input.from_bytes(raw)
                except Exception as e:
                    print(f"Bad UART message {raw!r}: {e}")
                    continue

                # iterating all scopes here would allow control of multiple at once
                ctrl = list(scopes.values())[0]
                if macro_manager.should_handle(inp):
                    macro_manager.handle_uart_input(raw, inp, ctrl)
                else:
                    ctrl.handle_input(inp)
                last_input = time.monotonic()

            new_packet = get_raw_packet()
            if new_packet:
                handle_packet(new_packet)

            now = time.monotonic()
            if not args.mock and scopes and now - last_sync > sync_period_s and now - last_input > 0.05:
                ctrl = list(scopes.values())[0]
                ctrl.sync_all_changed_channels_from_scope()
                ctrl.sync_selected_source_from_scope()
                ctrl.sync_fast_acquire_from_scope()
                ctrl.sync_run_stop_from_scope()
                ctrl.sync_trigger_state()
                last_sync = now

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        for ctrl in scopes.values():
            if ctrl:
                ctrl.scope.close()
        send_scope_connection_led(False)
        bridge.close()


if __name__ == "__main__":
    main()
