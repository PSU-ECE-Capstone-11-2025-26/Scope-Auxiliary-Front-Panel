from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import ClassVar

from .actions import Action
from .scope import Scope
from .state import Channel, TriggerEdgeSlope, TriggerMode


_REGISTRY: dict[str, type[Command]] = {}


@dataclass
class Command:
    kind: ClassVar[str]

    def __init_subclass__(cls, kind: str | None = None, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if kind is not None:
            cls.kind = kind
            _REGISTRY[kind] = cls

    def execute(self, scope: Scope) -> None:
        raise NotImplementedError

    def to_dict(self) -> dict:
        return {"kind": self.kind} | dataclasses.asdict(self)

    @staticmethod
    def from_dict(d: dict) -> Command:
        d = dict(d)
        kind = d.pop("kind")
        return _REGISTRY[kind](**d)


# Channel


@dataclass
class SetChannel(Command, kind="set_channel"):
    channel: str  # Channel.label, e.g. "CH1", "MATH1", "BUS1"
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_channel(scope, Channel.from_label(self.channel), self.enabled)


# Vertical


@dataclass
class AdjustVerticalPosition(Command, kind="adjust_vertical_position"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_vertical_position(scope, self.detents)


@dataclass
class CenterVerticalPosition(Command, kind="center_vertical_position"):
    def execute(self, scope: Scope) -> None:
        Action.center_vertical_position(scope)


@dataclass
class AdjustVerticalScale(Command, kind="adjust_vertical_scale"):
    detents: int
    fine: bool

    def execute(self, scope: Scope) -> None:
        Action.adjust_vertical_scale(scope, self.detents, self.fine)


# Horizontal


@dataclass
class AdjustHorizontalPosition(Command, kind="adjust_horizontal_position"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_horizontal_position(scope, self.detents)


@dataclass
class CenterHorizontalPosition(Command, kind="center_horizontal_position"):
    def execute(self, scope: Scope) -> None:
        Action.center_horizontal_position(scope)


@dataclass
class AdjustHorizontalScale(Command, kind="adjust_horizontal_scale"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_horizontal_scale(scope, self.detents)


# Trigger


@dataclass
class CenterTrigger(Command, kind="center_trigger"):
    def execute(self, scope: Scope) -> None:
        Action.center_trigger(scope)


@dataclass
class ForceTrigger(Command, kind="force_trigger"):
    def execute(self, scope: Scope) -> None:
        Action.force_trigger(scope)


@dataclass
class SetTriggerSlope(Command, kind="set_trigger_slope"):
    slope: str  # TriggerEdgeSlope value string

    def execute(self, scope: Scope) -> None:
        Action.set_trigger_slope(scope, TriggerEdgeSlope(self.slope))


@dataclass
class SetTriggerMode(Command, kind="set_trigger_mode"):
    mode: str  # TriggerMode value string

    def execute(self, scope: Scope) -> None:
        Action.set_trigger_mode(scope, TriggerMode(self.mode))


@dataclass
class AdjustTriggerLevel(Command, kind="adjust_trigger_level"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_trigger_level(scope, self.detents)


# Acquisition


@dataclass
class SetRunStop(Command, kind="set_run_stop"):
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_run_stop(scope, self.enabled)


@dataclass
class SetCursorMode(Command, kind="set_cursor_state"):
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_cursor_state(scope, self.enabled)


@dataclass
class SetFastAcquire(Command, kind="set_fast_acquire"):
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_fast_acquire(scope, self.enabled)


@dataclass
class SetAcquireMode(Command, kind="set_acquire_mode"):
    mode: str

    def execute(self, scope: Scope) -> None:
        Action.set_acquire_mode(scope, self.mode)


@dataclass
class RunAutoset(Command, kind="run_autoset"):
    def execute(self, scope: Scope) -> None:
        Action.run_autoset(scope)


@dataclass
class Clear(Command, kind="clear"):
    def execute(self, scope: Scope) -> None:
        Action.clear(scope)


@dataclass
class RunDefaultSetup(Command, kind="run_default_setup"):
    def execute(self, scope: Scope) -> None:
        Action.run_default_setup(scope)


# Zoom / Pan


@dataclass
class SetZoom(Command, kind="set_zoom"):
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_zoom(scope, self.enabled)


@dataclass
class AdjustZoomScale(Command, kind="adjust_zoom_scale"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_zoom_scale(scope, self.detents)


@dataclass
class AdjustPan(Command, kind="adjust_pan"):
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.adjust_pan(scope, self.detents)


# Touch


@dataclass
class SetTouchEnabled(Command, kind="set_touch_enabled"):
    enabled: bool

    def execute(self, scope: Scope) -> None:
        Action.set_touch_enabled(scope, self.enabled)


# Navigation


@dataclass
class Navigate(Command, kind="navigate"):
    direction: str  # "PREV" or "NEXT"

    def execute(self, scope: Scope) -> None:
        Action.navigate(scope, self.direction)


# General purpose knobs


@dataclass
class FpanelTurn(Command, kind="fpanel_turn"):
    knob: str  # "GPKNOB1" or "GPKNOB2"
    detents: int

    def execute(self, scope: Scope) -> None:
        Action.fpanel_turn(scope, self.knob, self.detents)
