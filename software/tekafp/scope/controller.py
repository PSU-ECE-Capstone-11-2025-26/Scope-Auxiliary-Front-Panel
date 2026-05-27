import logging
import math
import re

from pyvisa.resources import MessageBasedResource

from tekafp.input import Input
from tekafp.scope.constants import (
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

        self._channels: dict[int, bool] = {ch: False for ch in range(1, self.channel_count + 1)}
        self._source_channel: int = 0
        self._vert_fine: bool = False  # fine mode toggle for vertical scale
        self._fast_acquire: bool = False
        self._run_state: bool = False
        self._zoom: bool = False

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

    def get_scope_channel_state(self, channel: int) -> bool:
        resp = self.scope.query(f"DISPLAY:GLOBAL:CH{channel}:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def sync_all_channels_from_scope(self) -> None:
        highest = 0
        for ch in range(1, self.channel_count + 1):
            actual = self.get_scope_channel_state(ch)
            self._channels[ch] = actual
            self.send_channel_led(ch, actual)
            if actual:
                highest = ch
            logger.debug(f"CH{ch} -> {actual}")

        # Chooses highest enabled channel as the active selected channel
        self._source_channel = highest

        self.set_scope_selected_source()
        self.send_selected_channel_leds()
        self.sync_fast_acquire_from_scope(force=True)
        self.sync_run_stop_from_scope(force=True)

    def sync_all_changed_channels_from_scope(self) -> None:
        any_changed = False

        for ch in range(1, self.channel_count + 1):
            actual = self.get_scope_channel_state(ch)
            if self._channels[ch] != actual:
                self._channels[ch] = actual
                self.send_channel_led(ch, actual)
                logger.debug(f"CH{ch} -> {actual}")
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
            logger.debug("Full channel sync pass complete")

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
        if channel not in range(1, self.channel_count + 1):
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
            logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def send_selected_channel_leds(self) -> None:
        # Two RGB LEDs used to show the active selected channel:
        # VP1_RGB and VS1_RGB should always match the selected channel color

        r, g, b = self.CHANNEL_COLORS.get(self._source_channel, (0, 0, 0))

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
            logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def get_scope_selected_source(self) -> int:
        resp = self.scope.query("DISPLAY:SELECT:SOURCE?").strip().upper()

        if resp.endswith("NONE"):
            return 0

        for ch in range(1, self.channel_count + 1):
            if resp.endswith(f"CH{ch}") or f"CH{ch}" in resp:
                return ch

        logger.error(f"Unknown selected source response: {resp}")
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
            logger.debug(f"selected source -> CH{actual_source}")

    def set_channel_display(self, channel: int) -> None:
        if channel not in range(1, self.channel_count + 1):
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
            self.scope.write(f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self._channels[channel])}")
            self.send_channel_led(channel, self._channels[channel])

        logger.debug(
            f"CH{channel} display -> {self._channels[channel]} (source={self._source_channel})"  # noqa: E501
        )

    def force_channel_display(self, channel: int, desired: bool) -> None:
        if channel not in range(1, self.channel_count + 1):
            return

        self._channels[channel] = desired

        if self._source_channel == channel and not desired:
            self._source_channel = max((k for k, v in self._channels.items() if v), default=0)

        self.scope.write(f"DISPLAY:GLOBAL:CH{channel}:STATE {int(desired)}")
        self.send_channel_led(channel, desired)

        logger.debug(f"CH{channel} forced -> {self._channels[channel]}")

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self._source_channel
        if ch == 0:
            logger.debug("No active channel selected, ignoring vertical position.")
            return
        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.write(f"CH{ch}:POSITION {new}")
        logger.debug(f"CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def center_vertical_position(self) -> None:
        ch = self._source_channel
        if ch == 0:
            return

        cur = float(self.scope.query(f"CH{ch}:POSITION?").strip().split()[-1])
        self.scope.write(f"CH{ch}:POSITION 0")
        logger.debug(f"CH{ch} vertical position centered: {cur:.3f} -> 0.000")

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
        if ch == 0:
            return
        cur = float(self.scope.query(f"CH{ch}:SCALE?").strip().split()[-1])

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

        self.scope.write(f"CH{ch}:SCALE {new}")
        mode = "fine" if self._vert_fine else "coarse"
        logger.debug(f"CH{ch} vertical ({mode}): {cur:.3e} -> {new:.3e} V/div")

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

        logger.debug(f"Run/Stop -> {'RUN' if new_state else 'STOP'}")

    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.write("AUTOSET EXECUTE")

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

        match msg_id:
            # Channel Selection: 'V10' -> ch 1, 'V80' -> ch 8
            case "V10" | "V20" | "V30" | "V40" | "V50" | "V60" | "V70" | "V80":
                self.set_channel_display(int(msg_id[1]))

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
                    logger.debug(f"Vertical scale fine mode -> {'ON' if self._vert_fine else 'OFF'}")

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
                        self.scope.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION?"),
                        float,
                    )
                    new: float = clamp(cur + val * 2, 0.0, 100.0)
                    self.scope.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION {new}")
