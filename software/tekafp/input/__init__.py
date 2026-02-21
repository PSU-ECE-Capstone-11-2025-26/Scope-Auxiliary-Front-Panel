from dataclasses import dataclass
from typing import Callable

from pyvisa.resources import MessageBasedResource

from tekafp.util import clamp, parse_resp


SCPIResponseType = float | int | str

@dataclass
class Input:
    id: str
    value: float

    @classmethod
    def from_bytes(cls, data: bytes) -> "Input":
        split = data.decode("utf-8").rstrip().split(":")
        return cls(split[0], float(split[1]))

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