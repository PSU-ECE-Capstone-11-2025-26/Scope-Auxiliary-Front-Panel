from dataclasses import dataclass

from pyvisa.resources import MessageBasedResource
from util import parse_channel_count

from tekafp.scope.state import (
    Channel,
    ChannelState,
    RunState,
    TriggerEdgeSlope,
    TriggerMode,
    TriggerState,
)
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

    @classmethod
    def connect(cls, resource: MessageBasedResource) -> "Scope":
        idn = resource.query("*IDN?").strip()
        channel_count = parse_channel_count(idn)
        return cls(
            resource=resource,
            resource_name=resource.resource_name,
            connected=ObservableVariable(False),
            idn=idn,
            channel_count=channel_count,
            channels={
                Channel.from_number(ch): ObservableVariable(ChannelState())
                for ch in range(1, channel_count + 1)
            }
            | {
                Channel.MATH: ObservableVariable(ChannelState()),
                Channel.BUS: ObservableVariable(ChannelState()),
            },
            source_channel=ObservableVariable(Channel.NONE),
            run=ObservableVariable(RunState.RUN),
            fast_acquire=ObservableVariable(False),
            zoom=ObservableVariable(False),
            trigger_mode=ObservableVariable(TriggerMode.AUTO),
            trigger_edge_slope=ObservableVariable(TriggerEdgeSlope.FALL),
            trigger_state=ObservableVariable(TriggerState.TRIGGERED),
            trigger_source=ObservableVariable(Channel.NONE),
        )
