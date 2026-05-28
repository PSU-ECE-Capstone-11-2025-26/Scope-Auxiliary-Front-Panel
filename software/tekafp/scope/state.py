from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Optional


class TriggerState(StrEnum):
    READY = "READY"
    AUTO = "AUTO"
    TRIGGERED = "TRIGGER"


class TriggerMode(StrEnum):
    AUTO = "AUTO"
    NORMAL = "NORMAL"

    def __invert__(self) -> "TriggerMode":
        return TriggerMode.NORMAL if self == TriggerMode.AUTO else TriggerMode.AUTO


class TriggerEdgeSlope(StrEnum):
    RISE = "RISE"
    FALL = "FALL"
    EITHER = "EITHER"

    def __invert__(self) -> "TriggerEdgeSlope":
        state_map = {
            TriggerEdgeSlope.RISE: TriggerEdgeSlope.FALL,
            TriggerEdgeSlope.FALL: TriggerEdgeSlope.EITHER,
            TriggerEdgeSlope.EITHER: TriggerEdgeSlope.RISE,
        }
        return state_map[self]


class RunState(StrEnum):
    OFF = "OFF"
    ON = "ON"
    RUN = "RUN"
    STOP = "STOP"

    def __invert__(self) -> "RunState":
        state_map = {
            RunState.OFF: RunState.RUN,
            RunState.ON: RunState.OFF,
            RunState.RUN: RunState.STOP,
            RunState.STOP: RunState.RUN,
        }
        return state_map[self]

    @property
    def int_value(self) -> int:
        state_map = {RunState.OFF: 0, RunState.ON: 1, RunState.RUN: 1, RunState.STOP: 2}
        return state_map[self]


@dataclass(frozen=True)
class ChannelState:
    enabled: bool = False


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
