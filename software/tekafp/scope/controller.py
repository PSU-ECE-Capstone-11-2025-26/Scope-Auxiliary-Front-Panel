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
from tekafp.scope.scope import Scope
from tekafp.scope.state import Channel, ChannelState, TriggerEdgeSlope, TriggerMode, TriggerState
from tekafp.uart import UARTBridge
from tekafp.util import clamp, parse_resp
from tekafp.util.observable import ObservableVariable


logger = logging.getLogger(__name__)


def _scale_idx_to_val(mantissas: list[float], idx: int) -> float:
    return mantissas[idx % 3] * 10 ** (idx // 3)


def _scale_val_to_idx(v: float) -> int:
    # Multiply log10 by 3 (steps/decade) and round to nearest step,
    # which absorbs small floating-point error in scope-returned values.
    return round(math.log10(v) * 3)


class Controller:
    def __init__(self, res: MessageBasedResource, bridge: UARTBridge) -> None:
        self.bridge: UARTBridge = bridge
        idn = (res.query("*IDN?").strip(),)
        channel_count = self._channels_from_idn(idn)
        self.scope = Scope(
            resource=res,
            resource_name=res.resource_name,
            connected=True,
            idn=idn,
            channel_count=channel_count,
            channels={
                Channel.from_number(ch): ObservableVariable(ChannelState())
                for ch in range(1, channel_count + 1)
            }
            | {
                Channel.MATH: ObservableVariable(ChannelState()),
                Channel.BUS: ObservableVariable(ChannelState()),
            },
            source_channel=ObservableVariable(Channel.NONE),
            run=ObservableVariable(True),
            fast_acquire=ObservableVariable(False),
            zoom=ObservableVariable(False),
            trigger_mode=ObservableVariable(TriggerMode.AUTO),
            trigger_edge_slope=ObservableVariable(TriggerEdgeSlope.FALL),
            trigger_state=ObservableVariable(TriggerState.TRIGGERED),
            trigger_source=ObservableVariable(Channel.NONE),
        )
        # Make sure we're in a mode where horizontal position behaves like the
        # front panel knob
        # delay mode OFF => HORizontal:POSition works like HORIZONTAL POSITION knob
        self.scope.resource.write("HORIZONTAL:DELAY:MODE OFF")
        logger.info("Connected ctrl: %s, channels=%d", self.scope.idn, self.scope.channel_count)

        self._vert_fine: bool = False  # fine mode toggle for vertical scale
        self._fast_acquire: bool = False
        self._run_state: bool = False
        self._zoom: bool = False
        self._touch_state: bool = False
        self._high_res: bool = False

    def sync_zoom(self) -> None:
        resp: str = parse_resp(
            self.scope.resource.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE?"), str
        )
        self.scope.zoom.value = resp not in ("OFF", "0")
        msg = f"IHZ0:{int(self.scope.zoom.value)}\n".encode()
        self.bridge.write_sync(msg)

    def _channels_from_idn(self, idn: str) -> int:
        m = re.search(r"MSO\d(\d)", idn, re.IGNORECASE)
        if m is None:
            return 1
        return int(m.group(1))

    def get_scope_channel_state(self, channel: Channel) -> bool:
        resp = self.scope.resource.query(f"DISPLAY:GLOBAL:{channel.label}:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def sync_all_channels_from_scope(self) -> None:
        for ch, obs in self.scope.channels.items():
            actual = self.get_scope_channel_state(ch)
            obs.value = ChannelState(enabled=actual)
            self.send_channel_led(ch, actual)
            logger.debug(f"{ch.label} -> {actual}")

        if not self.scope.channels[self.scope.source_channel].value.enabled:
            highest = self._get_highest_enabled_channel()
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE {highest.label}")

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
        if channel not in range(1, self.scope.channel_count + 1):
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

        r, g, b = self.CHANNEL_COLORS.get(self.scope.source_channel.value, (0, 0, 0))

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

    def get_scope_selected_source(self) -> Channel:
        resp = self.scope.resource.query("DISPLAY:SELECT:SOURCE?").strip().upper()
        return Channel.from_label(resp)

    def set_scope_selected_source(self) -> None:
        if self.scope.source_channel.value == 0:
            self.scope.resource.write("DISPLAY:SELECT:SOURCE NONE")
        else:
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE CH{self.scope.source_channel.value}")

    def sync_selected_source_from_scope(self) -> None:
        actual_source = self.get_scope_selected_source()

        if actual_source != self.scope.source_channel.value:
            self.scope.source_channel.value = actual_source
            self.send_selected_channel_leds()
            logger.debug(f"selected source -> CH{actual_source}")

    def set_channel_display(self, channel: Channel) -> None:
        last_state: bool = self.scope.channels[channel].value.enabled

        if self.scope.source_channel.value == channel:
            # enabled and source => disable, select highest enabled as active
            self.scope.resource.write(
                f"DISPLAY:GLOBAL:{channel.label}:STATE {int(self.scope.channels[channel].value.enabled)}"  # noqa: E501
            )
            highest: Channel = self._get_highest_enabled_channel()
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE {highest.label}")
        elif last_state:
            # enabled => set as source
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE {channel.label}")
        else:
            # disabled => enable, set as source
            self.scope.resource.write(f"DISPLAY:GLOBAL:{channel.label}:STATE ON")
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE {channel.label}")

        if last_state != self.scope.channels[channel].value.enabled:
            self.scope.resource.write(
                f"DISPLAY:GLOBAL:CH{channel}:STATE {int(self.scope.channels[channel].value.enabled)}"
            )

        new_value: bool = self.scope.channels[channel].value.enabled
        new_source: str = self.scope.source_channel.value.label
        logger.debug(f"{channel.label} display -> {new_value} (source={new_source})")

    def force_channel_display(self, channel: Channel, desired: bool) -> None:
        if self.scope.source_channel == channel and not desired:
            highest: Channel = self._get_highest_enabled_channel()
            self.scope.resource.write(f"DISPLAY:SELECT:SOURCE {highest.label}")
        self.scope.resource.write(f"DISPLAY:GLOBAL:{channel.label}:STATE {int(desired)}")
        logger.debug(f"{channel.label} forced -> {self.scope.channels[channel]}")

    def _get_highest_enabled_channel(self) -> Channel:
        highest: Channel = Channel.NONE
        for ch, obs in self.scope.channels.items():
            if obs.value:
                highest = ch
        return highest

    def adjust_vertical_position(self, detents: int) -> None:
        ch = self.scope.source_channel.value
        if ch == 0:
            logger.debug("No active channel selected, ignoring vertical position.")
            return
        cur = float(self.scope.resource.query(f"CH{ch}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        # No hard guarantee on min/max in the snippet we pulled, so clamp conservatively
        new = clamp(new, -10.0, 10.0)

        self.scope.resource.write(f"CH{ch}:POSITION {new}")
        logger.debug(f"CH{ch} vertical position: {cur:.3f} -> {new:.3f}")

    def center_vertical_position(self) -> None:
        ch = self.scope.source_channel.value
        if ch == 0:
            return

        cur = float(self.scope.resource.query(f"CH{ch}:POSITION?").strip().split()[-1])
        self.scope.resource.write(f"CH{ch}:POSITION 0")
        logger.debug(f"CH{ch} vertical position centered: {cur:.3f} -> 0.000")

    def adjust_horizontal_position(self, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(self.scope.resource.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        self.scope.resource.write(f"HORIZONTAL:POSITION {new}")
        logger.debug(f"horizontal position (%): {cur:.2f} -> {new:.2f}")

    def center_horizontal_position(self) -> None:
        cur = float(self.scope.resource.query("HORIZONTAL:POSITION?").strip().split()[-1])
        self.scope.resource.write("HORIZONTAL:POSITION 50")
        logger.debug(f"horizontal position centered (%): {cur:.2f} -> 50.00")

    def adjust_vertical_scale(self, detents: int) -> None:
        ch = self.scope.source_channel.value
        if ch == 0:
            return
        cur = float(self.scope.resource.query(f"CH{ch}:SCALE?").strip().split()[-1])

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

        self.scope.resource.write(f"CH{ch}:SCALE {new}")
        mode = "fine" if self._vert_fine else "coarse"
        logger.debug(f"CH{ch} vertical ({mode}): {cur:.3e} -> {new:.3e} V/div")

    def adjust_horizontal_scale(self, detents: int) -> None:
        cur = float(self.scope.resource.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        nearest = _scale_val_to_idx(cur)
        new_idx = int(clamp(nearest + detents, HORIZ_MIN_IDX, HORIZ_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)

        self.scope.resource.write(f"HORIZONTAL:MODE:SCALE {new}")
        actual = float(self.scope.resource.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        logger.debug(f"horizontal scale (coarse): {cur:.3e} -> {actual:.3e} s/div")

    def adjust_zoom_scale(self, detents: int) -> None:
        cur: float = parse_resp(
            self.scope.resource.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE?"), float
        )
        if not self.scope.zoom.value and cur <= 2 and detents > 0:
            self.scope.resource.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE ON")
        nearest = _scale_val_to_idx(max(cur, 1.0))
        new_idx = int(clamp(nearest + detents, ZOOM_MIN_IDX, ZOOM_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)
        if new < 2.0:
            self.scope.resource.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE OFF")
        else:
            self.scope.resource.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE {new}")
        logger.debug(f"zoom scale: {cur:.3e} -> {new:.3e}x")

    def encoder_trigger_level(self, detents: int, trigger: str = "A") -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        source = self.scope.trigger_source.value.label
        query = f"TRIGGER:{trigger}:LEVEL:{source}"
        cur: float = parse_resp(self.scope.resource.query(query + "?"), float)

        vert_scale: float = parse_resp(self.scope.resource.query(f"{source}:SCALE?"), float)
        # index _LEVEL_MANTISSAS as (idx - 5) for feel (MSO matching would be -6)
        step = _scale_idx_to_val(LEVEL_MANTISSAS, _scale_val_to_idx(vert_scale) - 5)
        new = clamp(cur + detents * step, -100.0, 100.0)

        self.scope.resource.write(query + f" {new}")
        logger.debug(f"trigger level: {cur:.2f} -> {new:.2f} V")

    def sync_trigger_state(self) -> None:
        source: str = parse_resp(self.scope.resource.query("TRIGGER:A:EDGE:SOURCE?"), str)
        # FIXME the [2] index on this string is due to subchannels, e.g. for a digital probe
        #  where channel 1 could have CH1_D0, CH1_D1, etc. source[2] gives just the channel (1)
        r, g, b = self.CHANNEL_COLORS[int(source[2])]
        self.bridge.write_sync(f"ITL1_R:{r}\n".encode())
        self.bridge.write_sync(f"ITL1_G:{g}\n".encode())
        self.bridge.write_sync(f"ITL1_B:{b}\n".encode())
        cur: str = parse_resp(self.scope.resource.query("TRIGGER:A:EDGE:SLOPE?"), str).upper()
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
        cur: str = parse_resp(self.scope.resource.query("TRIGGER:A:MODE?"), str).upper()
        if cur == "AUTO":
            rise = 1
            fall = 0
        else:
            rise = 0
            fall = 1
        self.bridge.write_sync(f"ITM0_A:{rise}\n".encode())
        self.bridge.write_sync(f"ITM0_N:{fall}\n".encode())
        cur = parse_resp(self.scope.resource.query("TRIGGER:STATE?"), str).upper()
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
        cur = self.scope.trigger_edge_slope.value
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
        self.scope.resource.write(f"TRIGGER:A:EDGE:SLOPE {new}")

    # Toggle the scope's Run/Stop state
    def toggle_run_stop(self) -> None:
        new_state = not self.scope.run.value
        self.scope.resource.write(f"ACQUIRE:STATE {'RUN' if new_state else 'STOP'}")

    # Run the scope's AutoSet feature
    def autoset(self) -> None:
        self.scope.resource.write("AUTOSET EXECUTE")

    def clear(self) -> None:
        self.scope.write("CLEAR")

    def default_setup(self) -> None:
        self.scope.write("*RST")

    # Toggle the scope's Fast Acquire state
    def toggle_fast_acquire(self) -> None:
        new_state = not self.scope.fast_acquire.value
        self.scope.resource.write(f"ACQUIRE:FASTACQ:STATE {int(new_state)}")

    def get_scope_fast_acquire_state(self) -> bool:
        resp = self.scope.resource.query("ACQUIRE:FASTACQ:STATE?").strip().upper()
        return resp.endswith("1") or resp.endswith("ON")

    def send_fast_acquire_led(self, state: bool) -> None:
        msg = f"IAF0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def sync_fast_acquire_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_fast_acquire_state()

        if force or self.scope.fast_acquire.value != actual:
            self.scope.fast_acquire.value = actual
            self.send_fast_acquire_led(actual)
            logger.debug(f"Fast Acquire -> {actual}")

    def get_scope_run_state(self) -> bool:
        resp = self.scope.resource.query("ACQUIRE:STATE?").strip().upper()
        return resp in ("RUN", "ON", "1")

    def send_run_stop_led(self, state: bool) -> None:
        msg = f"IAR0:{int(state)}\n".encode("utf-8")
        self.bridge.write_sync(msg)
        logger.debug(f"[UART->PICO] {msg.decode().strip()}")

    def sync_run_stop_from_scope(self, force: bool = False) -> None:
        actual = self.get_scope_run_state()

        if force or self.scope.run.value != actual:
            self.scope.run.value = actual
            self.send_run_stop_led(actual)
            logger.debug(f"Run/Stop -> {actual}")

    def get_touch_off_state(self) -> bool:
        resp = parse_resp(self.scope.query("TOUCHSCREEN:STATE?"), str)
        touch_enabled = resp in ("OFF", "0")
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
                    logger.debug(
                        f"Vertical scale fine mode -> {'ON' if self._vert_fine else 'OFF'}"
                    )

            # Trigger level encoder
            case "TL1":
                if detents := int(val):
                    self.encoder_trigger_level(detents)

            # Trigger level push: set to 50%
            case "TL0":
                self.scope.resource.write("TRIGGER:A SETLevel")

            # Trigger force
            case "TF0":
                self.scope.resource.write("TRIGGER FORCE")

            # Trigger slope type
            case "TS0":
                self.next_trigger_slope()

            # Trigger mode
            case "TM0":
                cur = self.scope.trigger_mode.value
                new: str = "AUTO" if cur == "NORMAL" else "NORMAL"
                self.scope.resource.write(f"TRIGGER:A:MODE {new}")

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
                self.scope.resource.write(
                    f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE {int(not self.scope.zoom.value)}"
                )

            # Zoom encoder
            case "HZ1":
                self.adjust_zoom_scale(val)

            # Pan encoder
            case "HX1":
                if self.scope.zoom.value:
                    cur: float = parse_resp(
                        self.scope.resource.query(
                            "DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION?"
                        ), float
                    )
                    new: float = clamp(cur + val * 2, 0.0, 100.0)
                    self.scope.resource.write(
                        f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION {new}"
                    )
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
