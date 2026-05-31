from dataclasses import asdict, dataclass, fields
from enum import IntEnum
from typing import ClassVar, TypedDict

from tekafp.api_server.error import APIError


class LogMessageLevel(IntEnum):
    INFO = 0
    WARNING = 1
    ERROR = 2
    DEBUG = 3


class MacroAction(IntEnum):
    RECORD = 0
    SAVE = 1
    DELETE = 2


class RawPacket(TypedDict):
    origin: str
    data: list[dict]


@dataclass
class PacketData:
    _registry: ClassVar[dict[str, type["PacketData"]]] = {}
    type: ClassVar[str] = ""

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        name = cls.__name__.removesuffix("PacketData")
        cls.type = name
        cls._registry[name] = cls

    @classmethod
    def from_dict(cls, data: dict) -> "PacketData":
        field_names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in field_names})

    @classmethod
    def decode(cls, data: dict) -> "PacketData":
        subclass = cls._registry[data["type"]]
        return subclass.from_dict(data)

    def to_dict(self) -> dict:
        return {"type": self.type, **asdict(self)}


@dataclass
class HandshakePacketData(PacketData):
    id: str
    version: str


@dataclass
class LogMessagePacketData(PacketData):
    level: LogMessageLevel
    message: str
    toast: bool


@dataclass
class MacroActionPacketData(PacketData):
    action: MacroAction
    slot: int


@dataclass
class MacroStatePacketData(PacketData):
    macros: list[bool]


@dataclass
class ErrorPacketData(PacketData):
    resource_name: str
    error_code: APIError
    error_str: str


@dataclass
class ScopeActionPacketData(PacketData):
    resource_name: str
    action: str


@dataclass
class ScopeInfoPacketData(PacketData):
    resource_name: str
    connected: bool
    synced: bool
    idn: str
    channel_count: int


@dataclass
class ScopeListPacketData(PacketData):
    scopes: dict[str, bool]


@dataclass
class ScopeStatePacketData(PacketData):
    resource_name: str
    status: str
    channels: list[bool]
    source_channel: int
    trigger_source: int
    trigger_mode: str
    trigger_edge_slope: str
    run_stop: bool
    zoom_enabled: bool
