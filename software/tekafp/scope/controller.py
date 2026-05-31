from enum import Enum
import logging
import math
import re
from typing import Optional

from pyvisa.resources import MessageBasedResource

from tekafp.input import Input
from tekafp.scope.constants import (
    GP_KNOB_COARSE_SCALE,
    GP_KNOB_FINE_SCALE,
    HORIZ_MANTISSAS,
    HORIZ_MAX_IDX,
    HORIZ_MIN_IDX,
    HORIZ_STEP_PCT,
    LEVEL_MANTISSAS,
    VERT_MANTISSAS,
    VERT_MAX_IDX,
    VERT_MIN_IDX,
    VERT_STEP_DIVS,
    ZOOM_MAX_IDX,
    ZOOM_MIN_IDX,
)
from tekafp.uart import UARTBridge
from tekafp.util import clamp, parse_resp


logger = logging.getLogger(__name__)


def _scale_idx_to_val(mantissas: list[float], idx: int) -> float:
    return mantissas[idx % 3] * 10 ** (idx // 3)


def _scale_val_to_idx(v: float) -> int:
    # Multiply log10 by 3 (steps/decade) and round to nearest step,
    # which absorbs small floating-point error in scope-returned values.
    return round(math.log10(v) * 3)


class Channel(Enum):
    """Represents a channel.

    Usage: `Channel.MATH.label -> "MATH"`
    `Channel.CH1.number -> 1`
    """

    NONE = (0, "NONE")
    CH1 = (1, "CH1")
    CH2 = (2, "CH2")
    CH3 = (3, "CH3")
    CH4 = (4, "CH4")
    CH5 = (5, "CH5")
    CH6 = (6, "CH6")
    CH7 = (7, "CH7")
    CH8 = (8, "CH8")
    MATH = (None, "MATH1")
    BUS = (None, "BUS1")

    def __init__(self, number: Optional[int], label: str) -> None:
        self.number = number
        self.label = label

    @property
    def is_numbered(self) -> bool:
        return self.number is not None

    @property
    def display_label(self) -> str:
        """The display label of the channel.

        This can be used where the standard label is invalid. For example,
        DISPLAY:SELECT:SOURCE needs BUS<x>, whereas DISPLAY:GLOBAL uses B<x>
        """
        if self == Channel.BUS:
            return "B1"
        else:
            return self.label

    @classmethod
    def from_number(cls, n: int) -> "Channel":
        for member in cls:
            if member.number == n:
                return member
        raise ValueError(f"Invalid channel number: {n}")

    @classmethod
    def from_label(cls, label: str) -> "Channel":
        for member in cls:
            if member.label == label or label.startswith(member.label):
                return member
        raise ValueError(f"Invalid channel label: {label!r}")


class Controller:
    def __init__(self, scope: MessageBasedResource, bridge: UARTBridge) -> None:
        self.scope: MessageBasedResource = scope
        self.bridge: UARTBridge = bridge
        # Make sure we're in a mode where horizontal position behaves like the
        # front panel knob
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        self.scope.write("HORIZONTAL:DELAY:MODE OFF")
        self.idn = self.scope.query("*IDN?").strip()
        self.channel_count = self._channels_from_idn(self.idn)
        logger.info("Connected ctrl: %s, channels=%d", self.idn, self.channel_count)

        self._channels: dict[Channel, bool] = {
            Channel.from_number(ch): False for ch in range(1, self.channel_count + 1)
        } | {Channel.MATH: False, Channel.BUS: False}
        self._source_channel: Channel = Channel.NONE
        self._vert_fine: bool = False  # fine mode toggle for vertical scale
        self._gp_a_fine: bool = False
        self._gp_b_fine: bool = False
        self._fast_acquire: bool = False
        self._run_state: bool = False
        self._zoom: bool = False
        self._touch_state: bool = False
        self._high_res: bool = False

    def _math_bus_exists(self, channel: Channel) -> bool:
        """Whether any MATH/BUS instance is defined on the scope.

        MATH/BUS can only be enabled/selected once they exist.
        """
        kind = "MATH" if channel is Channel.MATH else "BUS"
        resp = self.scope.query(f"{kind}:LIST?").strip().strip('"')
        return bool(resp) and resp.upper() != "NONE"

    def _create_math_bus(self, channel: Channel) -> None:
        """Create instance 1 of a MATH/BUS that doesn't exist yet."""
        kind = "MATH" if channel is Channel.MATH else "B"
        self.scope.write(f'{kind}:ADDNew "{kind}1"')
        logger.debug(f"Created {kind}1")

    @property
    def highest_enabled_channel(self) -> Channel:
        highest = Channel.NONE
        for ch, state in self._channels.items():
            if state:
                highest = ch
        return highest

    def sync_zoom(self) -> None:
        resp: str = parse_resp(self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE?"), str)
        self._zoom = resp not in ("OFF", "0")
        msg = f"IHZ0:{int(self._zoom)}\n".encode()
        self.bridge.write_sync(msg)

    def _channels_from_idn(self, idn: str) -> int:
        m = re.search(r"MSO\d(\d)", idn, re.IGNORECASE)
        if m is None:
            return 1
        return int(m.group(1))

    def get_scope_channel_state(self, channel: Channel) -> bool:
        # MATH/BUS report a state only once an instance exists; treat absent as off.
        if channel in (Channel.MATH, Channel.BUS) and not self._math_bus_exists(channel):
            return False
        resp = parse_resp(self.scope.query(f"DISPLAY:GLOBAL:{channel.display_label}:STATE?"), str)
        return resp not in ("OFF", "0")

    def sync_all_channels_from_scope(self) -> None:
        for ch in self._channels.keys():
            actual = self.get_scope_channel_state(ch)
            self._channels[ch] = actual
            self.send_channel_led(ch, actual)
            logger.debug(f"{ch.label} -> {actual}")

        # Chooses highest enabled channel as the active selected channel
        self._source_channel = self.highest_enabled_channel

        self.set_scope_selected_source()
        self.send_selected_channel_leds()
        self.sync_fast_acquire_from_scope(force=True)
        self.sync_run_stop_from_scope(force=True)

    def sync_all_changed_channels_from_scope(self) -> None:
        any_changed = False

        for ch, state in self._channels.items():
            actual = self.get_scope_channel_state(ch)
            if state != actual:
                self._channels[ch] = actual
                self.send_channel_led(ch, actual)
                logger.debug(f"{ch.label} -> {actual}")
                any_changed = True

                if actual:
                    self._source_channel = ch
                    self.scope.write(f"DISPLAY:SELECT:SOURCE {self._source_channel.label}")
                    self.send_selected_channel_leds()

        # Keep selected source sane if current source is now off
        if self._source_channel != Channel.NONE and not self._channels[self._source_channel]:
            self._source_channel = self.highest_enabled_channel

            self.set_scope_selected_source()
            self.send_selected_channel_leds()

        # If nothing changed, stay quiet
        if any_changed:
            logger.debug("Full channel sync pass complete")

    def send_channel_led(self, channel: Channel, state: bool) -> None:
        # Send indicator update back to Pico
        if channel not in self._channels.keys():
            return

        if channel is Channel.MATH:
            self.bridge.queue_write(f"IVM0:{int(state)}\n".encode())
        elif channel is Channel.BUS:
            self.bridge.queue_write(f"IVB0:{int(state)}\n".encode())
        else:
            self.bridge.queue_write(f"IV{channel.number}0\n".encode())

    @staticmethod
    def _sel_led_id(channel: Channel) -> str:
        """Translate channel to selected source LED ID"""
        if channel is Channel.MATH:
            return "ISEL_M"
        if channel is Channel.BUS:
            return "ISEL_B"
        return f"ISEL{channel.number}"

    def send_selected_channel_leds(self) -> None:
        # ISEL indicators override each other, so one message suffices: the selected
        # source on, or any id with value 0 to clear it when nothing is selected.
        if self._source_channel is Channel.NONE:
            msg = b"ISEL1:0\n"
        else:
            msg = f"{self._sel_led_id(self._source_channel)}:1\n".encode()
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def get_scope_selected_source(self) -> Channel:
        resp = parse_resp(self.scope.query("DISPLAY:SELECT:SOURCE?"), str)
        return Channel.from_label(resp)

    def set_scope_selected_source(self) -> None:
        self.scope.write(f"DISPLAY:SELECT:SOURCE {self._source_channel.label}")

    def sync_selected_source_from_scope(self) -> None:
        actual_source = self.get_scope_selected_source()

        if actual_source != self._source_channel:
            self._source_channel = actual_source
            self.send_selected_channel_leds()
            logger.debug(f"selected source -> {actual_source.label}")

    def set_channel_display(self, channel: Channel) -> None:
        if channel not in self._channels.keys():
            return

        # MATH/BUS can only be enabled if an instance exists; create one on first use.
        if (
            channel in (Channel.MATH, Channel.BUS)
            and not self._channels[channel]
            and not self._math_bus_exists(channel)
        ):
            self._create_math_bus(channel)

        last_state: bool = self._channels[channel]

        if self._source_channel == channel:
            # enabled and source => disable, select highest enabled as active
            self._channels[channel] = False
            self._source_channel = self.highest_enabled_channel
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
                f"DISPLAY:GLOBAL:{channel.display_label}:STATE {int(self._channels[channel])}"
            )
            self.send_channel_led(channel, self._channels[channel])

        logger.debug(
            f"{channel.label} display -> {self._channels[channel]} (source={self._source_channel.label})"  # noqa: E501
        )

    def force_channel_display(self, channel: Channel, desired: bool) -> None:
        if channel not in self._channels.keys():
            return

        self._channels[channel] = desired

        if self._source_channel == channel and not desired:
            self._source_channel = self.highest_enabled_channel

        self.scope.write(f"DISPLAY:GLOBAL:{channel.display_label}:STATE {int(desired)}")
        self.send_channel_led(channel, desired)

        logger.debug(f"{channel.label} forced -> {self._channels[channel]}")

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        if ch == Channel.NONE:
            logger.debug("No active channel selected, ignoring vertical position.")
            return
        cur = float(self.scope.query(f"{ch.label}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"{ch.label}:POSITION {new}")
        logger.debug(f"{ch.label} vertical position: {cur:.3f} -> {new:.3f}")

    def center_vertical_position(self) -> None:
        ch = self._source_channel
        if ch == Channel.NONE:
            return

        cur = float(self.scope.query(f"{ch.label}:POSITION?").strip().split()[-1])
        self.scope.write(f"{ch.label}:POSITION 0")
        logger.debug(f"{ch.label} vertical position centered: {cur:.3f} -> 0.000")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.write(f"HORIZONTAL:POSITION {new}")
        logger.debug(f"horizontal position (%): {cur:.2f} -> {new:.2f}")

    def center_horizontal_position(self) -> None:
        cur = float(self.scope.query("HORIZONTAL:POSITION?").strip().split()[-1])
        self.scope.write("HORIZONTAL:POSITION 50")
        logger.debug(f"horizontal position centered (%): {cur:.2f} -> 50.00")

    def adjust_vertical_scale(self, detents: int) -> None:
        ch = self._source_channel
        if ch == Channel.NONE:
            return
        cur = float(self.scope.query(f"{ch.label}:SCALE?").strip().split()[-1])

        if self._vert_fine:
            # Fine mode: find the coarse step that owns the current value,
            # then use 1/20th of it as the fine step
            nearest = _scale_val_to_idx(cur)
            coarse_step = _scale_idx_to_val(VERT_MANTISSAS, nearest)
            fine_step = coarse_step / 20.0
            new = cur + detents * fine_step
            # Clamp between the two surrounding coarse steps
            lower = _scale_idx_to_val(VERT_MANTISSAS, max(nearest - 1, VERT_MIN_IDX))
            upper = _scale_idx_to_val(VERT_MANTISSAS, min(nearest + 1, VERT_MAX_IDX))
            new = clamp(new, lower, upper)
        else:
            nearest = _scale_val_to_idx(cur)
            new_idx = int(clamp(nearest + detents, VERT_MIN_IDX, VERT_MAX_IDX))
            new = _scale_idx_to_val(VERT_MANTISSAS, new_idx)

        self.scope.write(f"{ch.label}:SCALE {new}")
        mode = "fine" if self._vert_fine else "coarse"
        logger.debug(f"{ch.label} vertical ({mode}): {cur:.3e} -> {new:.3e} V/div")

    def adjust_horizontal_scale(self, detents: int) -> None:
        cur = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        nearest = _scale_val_to_idx(cur)
        new_idx = int(clamp(nearest + detents, HORIZ_MIN_IDX, HORIZ_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)

        self.scope.write(f"HORIZONTAL:MODE:SCALE {new}")
        actual = float(self.scope.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        logger.debug(f"horizontal scale (coarse): {cur:.3e} -> {actual:.3e} s/div")

    def adjust_zoom_scale(self, detents: int) -> None:
        cur: float = parse_resp(
            self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE?"), float
        )
        if not self._zoom and cur <= 2 and detents > 0:
            self.scope.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE ON")
        nearest = _scale_val_to_idx(max(cur, 1.0))
        new_idx = int(clamp(nearest + detents, ZOOM_MIN_IDX, ZOOM_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)
        if new < 2.0:
            self.scope.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE OFF")
        else:
            self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE {new}")
        logger.debug(f"zoom scale: {cur:.3e} -> {new:.3e}x")

    def encoder_trigger_level(self, detents: int, trigger: str = "A") -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        source: str = parse_resp(self.scope.query(f"TRIGGER:{trigger}:EDGE:SOURCE?"), str)
        query = f"TRIGGER:{trigger}:LEVEL:{source}"
        cur: float = parse_resp(self.scope.query(query + "?"), float)

        vert_scale: float = parse_resp(self.scope.query(f"{source}:SCALE?"), float)
        # index _LEVEL_MANTISSAS as (idx - 5) for feel (MSO matching would be -6)
        step = _scale_idx_to_val(LEVEL_MANTISSAS, _scale_val_to_idx(vert_scale) - 5)
        new = clamp(cur + detents * step, -100.0, 100.0)

        self.scope.write(query + f" {new}")
        logger.debug(f"trigger level: {cur:.2f} -> {new:.2f} V")

    def sync_trigger_state(self) -> None:
        source: str = parse_resp(self.scope.query("TRIGGER:A:EDGE:SOURCE?"), str)
        channel = Channel.from_label(source)
        self.bridge.queue_write(f"TL1_C{channel.number}\n".encode())
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

        logger.debug(f"Run/Stop -> {'RUN' if new_state else 'STOP'}")

    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.write("AUTOSET EXECUTE")

    def clear(self) -> None:
        self.scope.write("CLEAR")

    def default_setup(self) -> None:
        self.scope.write("*RST")

    # Toggle the scope's Fast Acquire state
    def toggle_fast_acquire(self) -> None:
        current = self.get_scope_fast_acquire_state()
        new_state = not current

        self.scope.write(f"ACQUIRE:FASTACQ:STATE {int(new_state)}")

        self._fast_acquire = new_state
        self.send_fast_acquire_led(new_state)

        logger.debug(f"Fast Acquire -> {'ON' if new_state else 'OFF'}")

    def get_scope_fast_acquire_state(self) -> bool:
        resp = self.scope.query("ACQUIRE:FASTACQ:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def send_fast_acquire_led(self, state: bool) -> None:
        msg = f"IAF0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def sync_fast_acquire_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_fast_acquire_state()

        if force or self._fast_acquire != actual:
            self._fast_acquire = actual
            self.send_fast_acquire_led(actual)
            logger.debug(f"Fast Acquire -> {actual}")

    def get_scope_run_state(self) -> bool:
        resp = self.scope.query("ACQUIRE:STATE?").strip().upper()
        return resp in ("RUN", "ON", "1")

    def send_run_stop_led(self, state: bool) -> None:
        msg = f"IAR0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def sync_run_stop_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_run_state()

        if force or self._run_state != actual:
            self._run_state = actual
            self.send_run_stop_led(actual)
            logger.debug(f"Run/Stop -> {actual}")

    def get_touch_off_state(self) -> bool:
        resp = parse_resp(self.scope.query("TOUCHSCREEN:STATE?"), str)
        touch_enabled = resp not in ("OFF", "0")
        return touch_enabled

    def send_touch_off_led(self, state: bool) -> None:
        # Touch Off LED should be ON when touchscreen is disabled
        self.bridge.queue_write(f"IT_OFF:{int(not state)}\n".encode())

    def sync_touch_off(self, force: bool = False) -> None:
        actual = self.get_touch_off_state()
        if force or self._touch_state != actual:
            self._touch_state = actual
            self.send_touch_off_led(actual)

    def toggle_touch_off(self) -> None:
        new = self.get_touch_off_state()
        self.scope.write(f"TOUCHSCREEN:STATE {int(not new)}")
        self.send_touch_off_led(new)
        self._touch_state = not new

    def get_high_res(self) -> bool:
        resp: str = parse_resp(self.scope.query("ACQUIRE:MODE?"), str)
        return resp.endswith("HIRES")

    def send_high_res_led(self, state: bool) -> None:
        self.bridge.queue_write(f"IAH0:{int(state)}\n".encode())

    def sync_high_res(self, force: bool = False) -> None:
        actual = self.get_high_res()
        if force or self._high_res != actual:
            self._high_res = actual
            self.send_high_res_led(actual)

    def toggle_high_res(self) -> None:
        new = not self.get_high_res()
        self.scope.write(f"ACQUIRE:MODE {'HIRES' if new else 'SAMPLE'}")
        self._high_res = new
        self.send_high_res_led(new)

    def navigate_prev(self) -> None:
        current_search: str = parse_resp(self.scope.query("SEARCH:SELECTED?"), str)
        if current_search != "NONE":
            self.scope.write(f"SEARCH:{current_search}:NAVIGATE PREV")

    def navigate_next(self) -> None:
        current_search: str = parse_resp(self.scope.query("SEARCH:SELECTED?"), str)
        if current_search != "NONE":
            self.scope.write(f"SEARCH:{current_search}:NAVIGATE NEXT")

    def handle_input(self, inp: Input) -> None:
        """
        inp.id is expected to be strings like:
          V10..V80, VP1/VP0, HP1/HP0, etc.
        inp.value for encoders is expected +/-1 per detent.
        inp.value for toggles is expected 0/1 (latched state).
        """

        msg_id = str(inp.id)
        val = inp.value

        match msg_id:
            # Channel Selection: 'V10' -> ch 1, 'V80' -> ch 8
            case "V10" | "V20" | "V30" | "V40" | "V50" | "V60" | "V70" | "V80":
                self.set_channel_display(Channel.from_number(int(msg_id[1])))
            case "VM0":
                self.set_channel_display(Channel.MATH)
            case "VB0":
                self.set_channel_display(Channel.BUS)

            # Encoder VP1 rotation: vertical position of current active channel
            case "VP1":
                if detents := int(val):
                    self.adjust_vertical_position(detents)

            # Encoder VP0 press: center vertical position of current active channel
            case "VP0":
                if int(val) == 1:
                    self.center_vertical_position()

            # Encoder HP1 rotation: horizontal position (global)
            case "HP1":
                if detents := int(val):
                    self.adjust_horizontal_position(detents)

            # Encoder HP0 press: center horizontal position globally
            case "HP0":
                if int(val) == 1:
                    self.center_horizontal_position()

            # Encoder VS1 rotation: vertical scale of current source channel (1/2/5 steps)
            case "VS1":
                if detents := int(val):
                    self.adjust_vertical_scale(-detents)

            # Encoder HS1 rotation: horizontal timebase scale (1/2/4 steps)
            case "HS1":
                if detents := int(val):
                    self.adjust_horizontal_scale(-detents)

            # VS0: toggle fine mode for vertical scale encoder
            case "VS0":
                if int(val) == 1:
                    self._vert_fine = not self._vert_fine
                    logger.debug(
                        f"Vertical scale fine mode -> {'ON' if self._vert_fine else 'OFF'}"
                    )

            # Trigger level encoder
            case "TL1":
                if detents := int(val):
                    self.encoder_trigger_level(detents)

            # Trigger level push: set to 50%
            case "TL0":
                self.scope.write("TRIGGER:A SETLevel")

            # Trigger force
            case "TF0":
                self.scope.write("TRIGGER FORCE")

            # Trigger slope type
            case "TS0":
                self.next_trigger_slope()

            # Trigger mode
            case "TM0":
                cur: str = parse_resp(self.scope.query("TRIGGER:A:MODE?"), str).upper()
                new: str = "AUTO" if cur == "NORMAL" else "NORMAL"
                self.scope.write(f"TRIGGER:A:MODE {new}")

            # Run/Stop button
            case "AR0":
                self.toggle_run_stop()

            # Fast Acquire button
            case "AF0":
                self.toggle_fast_acquire()

            # AutoSet button
            case "XA0":
                self.autoset()

            # Zoom enable toggle
            case "HZ0":
                self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE {int(not self._zoom)}")

            # Zoom encoder
            case "HZ1":
                self.adjust_zoom_scale(val)

            # Pan encoder
            case "HX1":
                if self._zoom:
                    cur: float = parse_resp(
                        self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION?"), float
                    )
                    new: float = clamp(cur + val * 2, 0.0, 100.0)
                    self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION {new}")
            case "XD0":
                if int(val) == 1:
                    self.default_setup()
            case "XT0":
                if int(val) == 1:
                    self.toggle_touch_off()
            case "AH0":
                if int(val) == 1:
                    self.toggle_high_res()
            case "AX0":
                if int(val) == 1:
                    self.clear()
            case "HL0":
                if not self._run_state:
                    self.navigate_prev()
            case "HR0":
                if not self._run_state:
                    self.navigate_next()
            case "KA0":
                if int(val) == 1:
                    self._gp_a_fine = not self._gp_a_fine
                    self.bridge.queue_write(f"IKA0:{int(self._gp_a_fine)}\n".encode())
            case "KA1":
                if detents := int(val):
                    mult = GP_KNOB_FINE_SCALE if self._gp_a_fine else GP_KNOB_COARSE_SCALE
                    self.scope.write(f"FPANEL:TURN GPKNOB1, {mult * detents}")
            case "KB0":
                if int(val) == 1:
                    self._gp_b_fine = not self._gp_b_fine
                    self.bridge.queue_write(f"IKB0:{int(self._gp_b_fine)}\n".encode())
            case "KB1":
                if detents := int(val):
                    mult = GP_KNOB_FINE_SCALE if self._gp_a_fine else GP_KNOB_COARSE_SCALE
                    self.scope.write(f"FPANEL:TURN GPKNOB2, {mult * detents}")
