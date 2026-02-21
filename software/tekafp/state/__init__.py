from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, NamedTuple, ReadOnly, TypedDict

from pyvisa.resources import MessageBasedResource


@dataclass
class ValueRange:
    min: int
    max: int

class ChannelState(NamedTuple):
    channel1:  bool
    channel2: bool
    channel3: bool
    channel4: bool
    channel5: bool
    channel6: bool
    channel7: bool
    channel8: bool
    # possible to add math, bus, etc. with this type

class TriggerMode(StrEnum):
    AUTO = "AUTO"
    NORMAL = "NORMAL"

class TriggerEdgeSlope(StrEnum):
    RISE = "RISE"
    FALL = "FALL"
    EITHER = "EITHER"

class ScopeState(TypedDict):
    scope_address: ReadOnly[str]
    channel_count: ReadOnly[Annotated[int, ValueRange(1, 8)]]
    scope_connected: bool
    channels: ChannelState
    source_channel: Annotated[int, ValueRange(0, 8)]
    trigger_source: Annotated[int, ValueRange(0, 8)]
    trigger_mode: TriggerMode
    trigger_edge_slope: TriggerEdgeSlope
    run: bool
    zoom_enabled: bool

class AFPScope(TypedDict):
    scope: MessageBasedResource
    state: ScopeState