import logging
import math

from tekafp.util import clamp, parse_resp

from .constants import (
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
from .scope import Scope
from .state import Channel, ChannelState, RunState, TriggerEdgeSlope, TriggerMode, TriggerState


logger = logging.getLogger(__name__)


def _scale_idx_to_val(mantissas: list[float], idx: int) -> float:
    return mantissas[idx % 3] * 10 ** (idx // 3)


def _scale_val_to_idx(v: float) -> int:
    # Multiply log10 by 3 (steps/decade) and round to nearest step,
    # which absorbs small floating-point error in scope-returned values.
    return round(math.log10(v) * 3)


class Action:
    @staticmethod
    def sync(scope: Scope) -> None:
        Action.sync_all_channels(scope)
        scope.source_channel.value = Action.get_selected_source(scope)
        scope.trigger_source.value = Action.get_trigger_source(scope)
        scope.trigger_mode.value = Action.get_trigger_mode(scope)
        scope.trigger_edge_slope.value = Action.get_trigger_slope(scope)
        scope.trigger_state.value = Action.get_trigger_state(scope)
        scope.run.value = Action.get_run_state(scope)
        scope.zoom.value = Action.get_zoom_state(scope)
        scope.fast_acquire.value = Action.get_fast_acquire_state(scope)

    @staticmethod
    def sync_all_channels(scope: Scope) -> None:
        for ch, obs in scope.channels.items():
            actual = Action.get_channel_state(scope, ch)
            obs.value = ChannelState(enabled=actual)

        if (
            scope.source_channel == Channel.NONE
            or not scope.channels[scope.source_channel.value].value.enabled
        ):
            highest = Action._get_highest_enabled_channel(scope)
            scope.resource.write(f"DISPLAY:SELECT:SOURCE {highest.label}")

    @staticmethod
    def get_run_state(scope: Scope) -> bool:
        resp = parse_resp(scope.resource.query("ACQUIRE:STATE?"), str)
        return resp in ("ON", "1", "RUN", "START")

    @staticmethod
    def get_fast_acquire_state(scope: Scope) -> bool:
        resp = parse_resp(scope.resource.query("ACQUIRE:FASTACQ:STATE?"), str)
        return resp not in ("OFF", "0")

    @staticmethod
    def get_zoom_state(scope: Scope) -> bool:
        resp: str = parse_resp(scope.resource.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE?"), str)
        return resp not in ("OFF", "0")

    @staticmethod
    def get_selected_source(scope: Scope) -> Channel:
        resp = parse_resp(scope.resource.query("DISPLAY:SELECT:SOURCE?"), str)
        try:
            return Channel.from_label(resp)
        except ValueError as e:
            logger.error("Unknown SOURCE %s: %s", resp, e)
            return Action._get_highest_enabled_channel(scope)

    @staticmethod
    def get_channel_state(scope: Scope, channel: Channel) -> bool:
        resp = parse_resp(
            scope.resource.query(f"DISPLAY:GLOBAL:{channel.display_label}:STATE?"), str
        )
        return resp not in ("OFF", "0")

    @staticmethod
    def _get_highest_enabled_channel(scope: Scope) -> Channel:
        highest: Channel = Channel.NONE
        for ch, obs in scope.channels.items():
            if obs.value.enabled:
                highest = ch
        return highest

    @staticmethod
    def get_trigger_source(scope: Scope) -> Channel:
        resp = parse_resp(scope.resource.query("TRIGGER:A:EDGE:SOURCE?"), str)
        try:
            return Channel.from_label(resp)
        except ValueError as e:
            logger.error("Unknown trigger source %s: %s", resp, e)
            return scope.trigger_source.value

    @staticmethod
    def get_trigger_slope(scope: Scope) -> TriggerEdgeSlope:
        return TriggerEdgeSlope(parse_resp(scope.resource.query("TRIGGER:A:EDGE:SLOPE?"), str))

    @staticmethod
    def get_trigger_mode(scope: Scope) -> TriggerMode:
        return TriggerMode(parse_resp(scope.resource.query("TRIGGER:A:MODE?"), str))

    @staticmethod
    def get_trigger_state(scope: Scope) -> TriggerState:
        return TriggerState(parse_resp(scope.resource.query("TRIGGER:STATE?"), str))

    @staticmethod
    def adjust_vertical_position(scope: Scope, detents: int) -> None:
        ch = scope.source_channel.value
        if ch == Channel.NONE or ch not in scope.channels:
            return
        cur = float(scope.resource.query(f"{ch.label}:POSITION?").strip().split()[-1])

        new = cur + detents * VERT_STEP_DIVS
        new = clamp(new, -10.0, 10.0)

        scope.resource.write(f"{ch.label}:POSITION {new}")
        logger.debug(f"{ch.label} vertical position: {cur:.3f} -> {new:.3f}")

    @staticmethod
    def center_vertical_position(scope: Scope) -> None:
        ch = scope.source_channel.value
        if ch == Channel.NONE or ch not in scope.channels:
            return

        cur = float(scope.resource.query(f"{ch.label}:POSITION?").strip().split()[-1])
        scope.resource.write(f"{ch.label}:POSITION 0")
        logger.debug(f"{ch.label} vertical position centered: {cur:.3f} -> 0.000")

    @staticmethod
    def adjust_vertical_scale(scope: Scope, detents: int, fine: bool = False) -> None:
        ch = scope.source_channel.value
        if ch == Channel.NONE or ch not in scope.channels:
            return
        cur = float(scope.resource.query(f"{ch.label}:SCALE?").strip().split()[-1])

        if fine:
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

        scope.resource.write(f"CH{ch}:SCALE {new}")
        mode = "fine" if fine else "coarse"
        logger.debug(f"CH{ch} vertical ({mode}): {cur:.3e} -> {new:.3e} V/div")

    @staticmethod
    def adjust_horizontal_position(scope: Scope, detents: int) -> None:
        # HORizontal:POSition is ~0..100 (% trigger position on screen)
        cur = float(scope.resource.query("HORIZONTAL:POSITION?").strip().split()[-1])

        new = cur + detents * HORIZ_STEP_PCT
        new = clamp(new, 0.0, 100.0)

        scope.resource.write(f"HORIZONTAL:POSITION {new}")
        logger.debug(f"horizontal position (%): {cur:.2f} -> {new:.2f}")

    @staticmethod
    def center_horizontal_position(scope: Scope) -> None:
        cur = float(scope.resource.query("HORIZONTAL:POSITION?").strip().split()[-1])
        scope.resource.write("HORIZONTAL:POSITION 50")
        logger.debug(f"horizontal position centered (%): {cur:.2f} -> 50.00")

    @staticmethod
    def adjust_horizontal_scale(scope: Scope, detents: int) -> None:
        cur = float(scope.resource.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        nearest = _scale_val_to_idx(cur)
        new_idx = int(clamp(nearest + detents, HORIZ_MIN_IDX, HORIZ_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)

        scope.resource.write(f"HORIZONTAL:MODE:SCALE {new}")
        actual = float(scope.resource.query("HORIZONTAL:MODE:SCALE?").strip().split()[-1])

        logger.debug(f"horizontal scale (coarse): {cur:.3e} -> {actual:.3e} s/div")

    @staticmethod
    def adjust_zoom_scale(scope: Scope, detents: int) -> None:
        cur: float = parse_resp(
            scope.resource.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE?"), float
        )
        if not scope.zoom.value and cur <= 2 and detents > 0:
            scope.resource.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE ON")
        nearest = _scale_val_to_idx(max(cur, 1.0))
        new_idx = int(clamp(nearest + detents, ZOOM_MIN_IDX, ZOOM_MAX_IDX))
        new = _scale_idx_to_val(HORIZ_MANTISSAS, new_idx)
        if new < 2.0:
            scope.resource.write("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE OFF")
        else:
            scope.resource.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:SCALE {new}")
        logger.debug(f"zoom scale: {cur:.3e} -> {new:.3e}x")

    @staticmethod
    def toggle_zoom(scope: Scope) -> None:
        Action.set_zoom(scope, not scope.zoom.value)

    @staticmethod
    def set_zoom(scope: Scope, enabled: bool) -> None:
        scope.resource.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:STATE {int(enabled)}")

    @staticmethod
    def adjust_pan(scope: Scope, detents: int) -> None:
        if scope.zoom.value:
            cur: float = parse_resp(
                scope.resource.query("DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION?"), float
            )
            new: float = clamp(cur + detents * 2, 0.0, 100.0)
            scope.resource.write(f"DISPLAY:WAVEVIEW1:ZOOM:ZOOM1:HORIZONTAL:POSITION {new}")

    @staticmethod
    def adjust_trigger_level(scope: Scope, detents: int, trigger: str = "A") -> None:
        # FIXME: the MSO has both A (primary) and B (delay) triggers for sequencing.
        # for now, default to A
        source = scope.trigger_source.value
        if source == Channel.NONE or source not in scope.channels:
            return
        query = f"TRIGGER:{trigger}:LEVEL:{source.label}"
        cur: float = parse_resp(scope.resource.query(query + "?"), float)

        vert_scale: float = parse_resp(scope.resource.query(f"{source.label}:SCALE?"), float)
        # index _LEVEL_MANTISSAS as (idx - 5) for feel (MSO matching would be -6)
        step = _scale_idx_to_val(LEVEL_MANTISSAS, _scale_val_to_idx(vert_scale) - 5)
        new = clamp(cur + detents * step, -100.0, 100.0)

        scope.resource.write(query + f" {new}")
        logger.debug(f"trigger level: {cur:.2f} -> {new:.2f} V")

    @staticmethod
    def cycle_trigger_slope(scope: Scope) -> None:
        cur = scope.trigger_edge_slope.value
        new = None
        match cur:
            case TriggerEdgeSlope.RISE:
                new = TriggerEdgeSlope.FALL
            case TriggerEdgeSlope.FALL:
                new = TriggerEdgeSlope.EITHER
            case TriggerEdgeSlope.EITHER:
                new = TriggerEdgeSlope.RISE
            case _:
                raise AssertionError("Invalid trigger slope. Something is wrong!")
        Action.set_trigger_slope(scope, new)

    @staticmethod
    def set_trigger_slope(scope: Scope, slope: TriggerEdgeSlope) -> None:
        scope.resource.write(f"TRIGGER:A:EDGE:SLOPE {slope.value}")

    @staticmethod
    def cycle_trigger_mode(scope: Scope) -> None:
        cur = scope.trigger_mode.value
        new = TriggerMode.AUTO if cur == TriggerMode.NORMAL else TriggerMode.NORMAL
        Action.set_trigger_mode(scope, new)

    @staticmethod
    def set_trigger_mode(scope: Scope, mode: TriggerMode) -> None:
        scope.resource.write(f"TRIGGER:A:MODE {mode.value}")

    @staticmethod
    def force_trigger(scope: Scope) -> None:
        scope.resource.write("TRIGGER FORCE")

    @staticmethod
    def center_trigger(scope: Scope) -> None:
        scope.resource.write("TRIGGER:A SETLevel")

    @staticmethod
    def toggle_fast_acquire(scope: Scope) -> None:
        Action.set_fast_acquire(scope, not scope.fast_acquire.value)

    @staticmethod
    def set_fast_acquire(scope: Scope, state: bool) -> None:
        scope.resource.write(f"ACQUIRE:FASTACQ:STATE {int(state)}")

    @staticmethod
    def toggle_run_stop(scope: Scope) -> None:
        Action.set_run_stop(scope, not scope.run.value)

    @staticmethod
    def set_run_stop(scope: Scope, state: bool) -> None:
        scope.resource.write(f"ACQUIRE:STATE {'RUN' if state else 'STOP'}")

    @staticmethod
    def run_autoset(scope: Scope) -> None:
        scope.resource.write("AUTOSET EXECUTE")

    @staticmethod
    def set_channel(scope: Scope, channel: Channel, state: bool) -> None:
        if channel not in scope.channels:
            return
        scope.resource.write(f"DISPLAY:GLOBAL:{channel.display_label}:STATE {int(state)}")

    @staticmethod
    def set_channel_display(scope: Scope, channel: Channel) -> None:
        if channel not in scope.channels:
            return
        last_state: bool = scope.channels[channel].value.enabled

        if scope.source_channel.value == channel:
            # enabled and source => disable, select highest enabled as active
            scope.resource.write(f"DISPLAY:GLOBAL:{channel.display_label}:STATE OFF")
            highest: Channel = Action._get_highest_enabled_channel(scope)
            scope.resource.write(f"DISPLAY:SELECT:SOURCE {highest.label}")
        elif last_state:
            # enabled => set as source
            scope.resource.write(f"DISPLAY:SELECT:SOURCE {channel.label}")
        else:
            # disabled => enable, set as source
            scope.resource.write(f"DISPLAY:GLOBAL:{channel.display_label}:STATE ON")
            scope.resource.write(f"DISPLAY:SELECT:SOURCE {channel.label}")

        new_value: bool = scope.channels[channel].value.enabled
        new_source: str = scope.source_channel.value.label
        logger.debug(f"{channel.label} display -> {new_value} (source={new_source})")
        Action.sync_all_channels(scope)
