from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Annotated, NamedTuple, ReadOnly, Tuple, TypedDict

from pyvisa.resources import MessageBasedResource

from tekafp.input import Input
from tekafp.registry import Registry
from tekafp.util import clamp, parse_resp


# function types:
# encoder
#   - query current value
#   - data transform with +-1 encoder value and step scaler
#   - clamp
#   - write back
# cycle (stateful)
#   - query current value
#   - flow is like: if current is A, then new is B, else C
#   - write back
# opaque (stateless)
#   - if pressed, write a command (TRIGGER FORCE, fastacq, ...)

SCPIResponseType = float | int | str

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
    state: dict[str, str]


class ControlType:
    def run(self, scope: MessageBasedResource, ctx: dict[str, str],
            inp: Input) -> None:
        raise NotImplementedError


class EncoderControl(ControlType):

    def __int__(
            self,
            query_cmd: str,
            write_cmd: str = None,
            scaler: float = 1.0,
            clamp_range: tuple[float, float] = (0, 100)
    ) -> None:
        self.query_cmd: str = query_cmd
        if write_cmd is not None:
            self.write: str = write_cmd
        else:
            self.write_cmd: str = query_cmd + " {value}"
        self.scaler: float = scaler
        self.clamp_range: tuple[float, float] = clamp_range

    def run(self, scope: MessageBasedResource, ctx: dict[str, str],
            inp: Input) -> None:
        # state -> context?
        # would contain:
        # active_channel, trigger_bus, ... ?
        resp: float = parse_resp(scope.query((self.query_cmd + "?").format(**ctx)), float)

        value = resp + int(inp.value) * self.scaler
        value = clamp(value, self.clamp_range[0], 100.0)

        scope.write(self.write_cmd.format(**ctx, value=value))

class StatefulControl(ControlType):
    query_cmd: str
    write_cmd: str
    comparator: Callable[[SCPIResponseType], SCPIResponseType]

    def run(self, scope: MessageBasedResource, ctx: dict[str, str],
            inp: Input) -> None:
        resp: str = parse_resp(scope.query(self.query_cmd + "?"), str).upper()
        value = self.comparator(resp)
        scope.write(self.write_cmd.format(**ctx, value=value))


control_registry: Registry[str, ControlType] = Registry()

control_registry.register("VP1", EncoderControl())

def register(key: str, func: ControlType) -> None:
    pass

def func(scope: MessageBasedResource, state: dict[str, str], inp: Input,
         **kwargs: int) -> None:
    pass

register("VP1", func)