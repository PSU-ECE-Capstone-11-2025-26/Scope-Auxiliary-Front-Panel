from dataclasses import asdict, dataclass, field, fields
from typing import ClassVar, TypedDict


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
class MacroRecordPacketData(PacketData):
    record: bool
    slot: int


@dataclass
class MacroStatePacketData(PacketData):
    macros: list[bool]


@dataclass
class ScopeActionPacketData(PacketData):
    action: str
    scope: str


@dataclass
class ScopeInfoPacketData(PacketData):
    channel_count: int


@dataclass
class ScopeListPacketData(PacketData):
    scopes: list[str]


@dataclass
class ScopeStatePacketData(PacketData):
    status: str
    channels: list[bool]
    source_channel: int
    trigger_source: int
    trigger_mode: str
    trigger_edge_slope: str
    run_stop: bool
    zoom_enabled: bool
