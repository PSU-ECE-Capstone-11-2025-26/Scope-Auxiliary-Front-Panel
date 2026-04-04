import pytest

from tekafp.api_server.packets import (
    MacroRecordPacketData,
    MacroStatePacketData,
    PacketData,
    ScopeActionPacketData,
    ScopeInfoPacketData,
    ScopeListPacketData,
    ScopeStatePacketData,
)


SAMPLE_DATA = [
    (MacroRecordPacketData, {"record": True, "slot": 2}),
    (MacroStatePacketData, {"macros": [True, False, True, False]}),
    (ScopeActionPacketData, {"action": "enable", "scope": "USB0::::::::INSTR"}),
    (ScopeInfoPacketData, {"channel_count": 8}),
    (ScopeListPacketData, {"scopes": ["USB0::A::INSTR", "USB0::B::INSTR"]}),
    (
        ScopeStatePacketData,
        {
            "type": "ScopeState",
            "status": "connected",
            "channels": [False, False, False, True],
            "source_channel": 0,
            "trigger_source": 0,
            "trigger_mode": "AUTO",
            "trigger_edge_slope": "RISE",
            "run_stop": True,
            "zoom_enabled": False,
        },
    ),
]


def test_registry_keys() -> None:
    expected = {"MacroRecord", "MacroState", "ScopeAction", "ScopeInfo", "ScopeList", "ScopeState"}
    assert set(PacketData.REGISTRY.keys()) == expected


@pytest.mark.parametrize(("cls", "data"), SAMPLE_DATA)
def test_from_dict(cls: type[PacketData], data: dict) -> None:
    pkt = cls.from_dict(data)
    for key, value in data.items():
        assert getattr(pkt, key) == value


@pytest.mark.parametrize(("cls", "data"), SAMPLE_DATA)
def test_to_dict(cls: type[PacketData], data: dict) -> None:
    pkt = cls(**data)
    assert pkt.to_dict() == data


@pytest.mark.parametrize(("cls", "data"), SAMPLE_DATA)
def test_roundtrip(cls: type[PacketData], data: dict) -> None:
    original = cls(**data)
    reconstructed = cls.from_dict(original.to_dict())
    assert original == reconstructed


def test_from_dict_ignores_extra_keys() -> None:
    data = {"$type": "ScopeInfo", "channel_count": 4, "extra": "ignored"}
    pkt = ScopeInfoPacketData.from_dict(data)
    assert pkt.channel_count == 4
    assert not hasattr(pkt, "extra")
