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


class TriggerEdgeSlope(StrEnum):
    RISE = "RISE"
    FALL = "FALL"
    EITHER = "EITHER"


@dataclass(frozen=True)
class ChannelState:
    enabled: bool


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
    MATH = (None, "MATH")
    BUS = (None, "BUS")

    def __init__(self, number: Optional[int], label: str) -> None:
        self.number = number
        self.label = label

    @property
    def is_numbered(self) -> bool:
        return self.number is not None
