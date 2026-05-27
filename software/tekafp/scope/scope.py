from dataclasses import dataclass

from pyvisa.resources import MessageBasedResource

from tekafp.scope.state import Channel, ChannelState, TriggerEdgeSlope, TriggerMode, TriggerState
from tekafp.util.observable import ObservableVariable


@dataclass
class Scope:
    resource: MessageBasedResource
    resource_name: str
    idn: str
    channel_count: int
    connected: ObservableVariable[bool]
    channels: dict[Channel, ObservableVariable[ChannelState]]
    source_channel: ObservableVariable[Channel]
    trigger_source: ObservableVariable[Channel]
    trigger_mode: ObservableVariable[TriggerMode]
    trigger_edge_slope: ObservableVariable[TriggerEdgeSlope]
    trigger_state: ObservableVariable[TriggerState]
    run: ObservableVariable[bool]
    zoom: ObservableVariable[bool]
    fast_acquire: ObservableVariable[bool]
