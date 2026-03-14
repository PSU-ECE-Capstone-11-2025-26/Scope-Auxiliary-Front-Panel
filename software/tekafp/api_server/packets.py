from typing import Required, TypedDict


class MacroRecordPacketData(TypedDict):
    record: Required[bool]
    slot: Required[int]

class MacroStatePacketData(TypedDict):
    macros: Required[list[bool]]

class ScopeActionPacketData(TypedDict):
    action: Required[str]
    scope: Required[str]

class ScopeInfoPacketData(TypedDict):
    channel_count: Required[int]

class ScopeListPacketData(TypedDict):
    scopes: Required[list[str]]

class ScopeStatePacketData(TypedDict):
    status: Required[str]
    channels: Required[list[bool]]
    source_channel: Required[int]
    trigger_source: Required[int]
    trigger_mode: Required[str]
    trigger_edge_slope: Required[str]
    run_stop: Required[bool]
    zoom_enabled: Required[bool]

BY_TYPE: dict[str, type[TypedDict]] = {
    "ScopeState": ScopeStatePacketData,
    "ScopeList": ScopeListPacketData,
    "ScopeAction": ScopeActionPacketData,
    "ScopeInfo": ScopeInfoPacketData,
    "MacroRecord": MacroRecordPacketData,
    "MacroState": MacroStatePacketData,
}
