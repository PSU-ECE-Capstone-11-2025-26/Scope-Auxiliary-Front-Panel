from dataclasses import dataclass

from pyvisa.resources import MessageBasedResource
from util import parse_channel_count

from tekafp.scope.state import Channel, ChannelState, TriggerEdgeSlope, TriggerMode, TriggerState
from tekafp.util.observable import ObservableVariable


_ALL_FEATURES: frozenset[str] = frozenset({"fast_acquire", "touch", "high_res", "gp_knobs"})


def _parse_features(idn: str) -> frozenset[str]:
    model = idn.split(",")[1].upper() if "," in idn else ""
    if model.startswith("MSO2"):
        return _ALL_FEATURES - {"fast_acquire", "high_res"}
    return _ALL_FEATURES


class MockResource:
    def close(self) -> None:
        pass


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
    touch_enabled: ObservableVariable[bool]
    high_res: ObservableVariable[bool]
    features: frozenset[str]

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
            run=ObservableVariable(True),
            fast_acquire=ObservableVariable(False),
            zoom=ObservableVariable(False),
            trigger_mode=ObservableVariable(TriggerMode.AUTO),
            trigger_edge_slope=ObservableVariable(TriggerEdgeSlope.FALL),
            trigger_state=ObservableVariable(TriggerState.TRIGGERED),
            trigger_source=ObservableVariable(Channel.NONE),
            touch_enabled=ObservableVariable(True),
            high_res=ObservableVariable(False),
            features=_parse_features(idn),
        )

    @classmethod
    def mock(cls) -> "Scope":
        idn = "TEKTRONIX,MSO58,C012345,CF:91.1CT FV:1.0.1.8"
        return cls(
            resource=MockResource(),
            resource_name="USB0::0x0699::0x0363::C102912::INSTR",
            connected=ObservableVariable(False),
            idn=idn,
            channel_count=8,
            channels={
                Channel.from_number(ch): ObservableVariable(ChannelState()) for ch in range(1, 9)
            }
            | {
                Channel.MATH: ObservableVariable(ChannelState()),
                Channel.BUS: ObservableVariable(ChannelState()),
            },
            source_channel=ObservableVariable(Channel.NONE),
            run=ObservableVariable(True),
            fast_acquire=ObservableVariable(False),
            zoom=ObservableVariable(False),
            trigger_mode=ObservableVariable(TriggerMode.AUTO),
            trigger_edge_slope=ObservableVariable(TriggerEdgeSlope.FALL),
            trigger_state=ObservableVariable(TriggerState.TRIGGERED),
            trigger_source=ObservableVariable(Channel.NONE),
            touch_enabled=ObservableVariable(True),
            high_res=ObservableVariable(False),
            features=_parse_features(idn),
        )
