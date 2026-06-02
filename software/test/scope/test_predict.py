from tekafp.scope.commands import (
    AdjustVerticalScale,
    SetAcquireMode,
    SetChannel,
    SetCursorMode,
    SetFastAcquire,
    SetRunStop,
    SetTouchEnabled,
    SetTriggerMode,
    SetTriggerSlope,
    SetZoom,
)
from tekafp.scope.scope import Scope
from tekafp.scope.state import Channel, ChannelState, TriggerEdgeSlope, TriggerMode


def test_predict_simple_toggles_update_observables() -> None:
    scope = Scope.mock()
    scope.run.value = True
    scope.cursors.value = False
    scope.fast_acquire.value = False
    scope.zoom.value = False
    scope.touch_enabled.value = True
    scope.high_res.value = False

    SetRunStop(enabled=False).predict(scope)
    SetCursorMode(enabled=True).predict(scope)
    SetFastAcquire(enabled=True).predict(scope)
    SetZoom(enabled=True).predict(scope)
    SetTouchEnabled(enabled=False).predict(scope)
    SetAcquireMode(mode="HIRES").predict(scope)

    assert scope.run.value is False
    assert scope.cursors.value is True
    assert scope.fast_acquire.value is True
    assert scope.zoom.value is True
    assert scope.touch_enabled.value is False
    assert scope.high_res.value is True


def test_predict_trigger_modes() -> None:
    scope = Scope.mock()
    SetTriggerMode(mode="NORMAL").predict(scope)
    SetTriggerSlope(slope="RISE").predict(scope)
    assert scope.trigger_mode.value == TriggerMode.NORMAL
    assert scope.trigger_edge_slope.value == TriggerEdgeSlope.RISE


def test_predict_fires_led_callback() -> None:
    scope = Scope.mock()
    scope.fast_acquire.value = False
    seen: list[bool] = []
    scope.fast_acquire.register(lambda _, v: seen.append(v))

    SetFastAcquire(enabled=True).predict(scope)

    assert seen == [True]


def test_predict_enable_channel_sets_source() -> None:
    scope = Scope.mock()
    assert scope.source_channel.value == Channel.NONE

    SetChannel(channel="CH2", enabled=True).predict(scope)

    assert scope.channels[Channel.CH2].value == ChannelState(enabled=True)
    assert scope.source_channel.value == Channel.CH2


def test_predict_disable_active_source_falls_back_to_highest() -> None:
    scope = Scope.mock()
    SetChannel(channel="CH1", enabled=True).predict(scope)
    SetChannel(channel="CH3", enabled=True).predict(scope)
    assert scope.source_channel.value == Channel.CH3

    SetChannel(channel="CH3", enabled=False).predict(scope)

    assert scope.channels[Channel.CH3].value == ChannelState(enabled=False)
    assert scope.source_channel.value == Channel.CH1


def test_predict_feature_guarded_when_unsupported() -> None:
    scope = Scope.mock()
    object.__setattr__(scope, "features", frozenset())
    scope.fast_acquire.value = False
    scope.touch_enabled.value = True
    scope.high_res.value = False

    SetFastAcquire(enabled=True).predict(scope)
    SetTouchEnabled(enabled=False).predict(scope)
    SetAcquireMode(mode="HIRES").predict(scope)

    assert scope.fast_acquire.value is False
    assert scope.touch_enabled.value is True
    assert scope.high_res.value is False


def test_predict_relative_command_is_noop() -> None:
    scope = Scope.mock()
    before = scope.source_channel.value
    AdjustVerticalScale(detents=1, fine=False).predict(scope)
    assert scope.source_channel.value == before
