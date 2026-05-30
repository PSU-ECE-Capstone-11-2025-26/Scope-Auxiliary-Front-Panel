from collections.abc import Callable

import pytest

from tekafp.scope.controller import Channel, Controller


class StubBridge:
    """Records UART writes."""

    def __init__(self) -> None:
        self.writes: list[bytes | str] = []

    def write_sync(self, data: bytes) -> bool:
        self.writes.append(data)
        return True

    def queue_write(self, data: bytes) -> None:
        self.writes.append(data)


class FakeScope:
    """Minimal fake MessageBasedResource.

    `responses` maps an exact SCPI query to its reply; unknown queries return
    "0". All writes and queries are recorded for assertions.
    """

    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self.writes: list[str] = []
        self.queries: list[str] = []
        self.responses = {"*IDN?": "TEKTRONIX,MSO54,C012345,1.2.3"}
        if responses:
            self.responses.update(responses)

    def write(self, cmd: str) -> None:
        self.writes.append(cmd)

    def query(self, cmd: str) -> str:
        self.queries.append(cmd)
        return self.responses.get(cmd, "0")


def make_controller(responses: dict[str, str] | None = None) -> Controller:
    return Controller(FakeScope(responses), StubBridge())  # type: ignore[arg-type]


def writes_after(ctrl: Controller, mark: Callable[[], None]) -> list[str]:
    """Run `mark`, returning only the scope writes it produced."""
    before = len(ctrl.scope.writes)
    mark()
    return ctrl.scope.writes[before:]


@pytest.mark.parametrize(
    ("channel", "kind", "global_label"),
    [(Channel.MATH, "MATH", "MATH1"), (Channel.BUS, "BUS", "B1")],
)
def test_button_creates_instance_when_absent(
    channel: Channel, kind: str, global_label: str
) -> None:
    # LIST? empty => no instance exists yet
    ctrl = make_controller({f"{kind}:LIST?": ""})

    writes = writes_after(ctrl, lambda: ctrl.set_channel_display(channel))

    assert f'{kind}:ADDNew "{kind}1"' in writes
    assert f"DISPLAY:GLOBAL:{global_label}:STATE 1" in writes
    # Newly enabled MATH/BUS becomes the vertical-control source
    assert ctrl._source_channel is channel


@pytest.mark.parametrize(("channel", "kind"), [(Channel.MATH, "MATH"), (Channel.BUS, "BUS")])
def test_button_does_not_recreate_existing_instance(channel: Channel, kind: str) -> None:
    ctrl = make_controller({f"{kind}:LIST?": f"{kind}1"})

    writes = writes_after(ctrl, lambda: ctrl.set_channel_display(channel))

    assert not any("ADDNew" in w for w in writes)


@pytest.mark.parametrize(("channel", "kind"), [(Channel.MATH, "MATH"), (Channel.BUS, "BUS")])
def test_absent_instance_reads_as_off(channel: Channel, kind: str) -> None:
    ctrl = make_controller({f"{kind}:LIST?": ""})
    ctrl.scope.queries.clear()

    assert ctrl.get_scope_channel_state(channel) is False
    # Must not probe DISPLAY:GLOBAL for an instance that doesn't exist
    assert not any(q.startswith("DISPLAY:GLOBAL") for q in ctrl.scope.queries)


@pytest.mark.parametrize(
    ("channel", "kind", "global_label"),
    [(Channel.MATH, "MATH", "MATH1"), (Channel.BUS, "BUS", "B1")],
)
def test_present_instance_reads_global_state(
    channel: Channel, kind: str, global_label: str
) -> None:
    ctrl = make_controller(
        {f"{kind}:LIST?": f"{kind}1", f"DISPLAY:GLOBAL:{global_label}:STATE?": "1"}
    )

    assert ctrl.get_scope_channel_state(channel) is True


@pytest.mark.parametrize(
    ("channel", "sel_id"),
    [(Channel.CH2, "ISEL2"), (Channel.MATH, "ISEL_M"), (Channel.BUS, "ISEL_B")],
)
def test_selected_led_sends_only_selected(channel: Channel, sel_id: str) -> None:
    ctrl = make_controller()
    bridge = ctrl.bridge

    bridge.writes.clear()
    ctrl._source_channel = channel
    ctrl.send_selected_channel_leds()

    # ISEL indicators override each other, so only the selected source is emitted.
    sent = [m.decode().strip() if isinstance(m, bytes) else m.strip() for m in bridge.writes]
    assert sent == [f"{sel_id}:1"]


def test_selected_led_clears_when_none() -> None:
    ctrl = make_controller()
    ctrl.bridge.writes.clear()
    ctrl._source_channel = Channel.NONE
    ctrl.send_selected_channel_leds()

    # Any ISEL id with value 0 clears the shared indicator.
    sent = [m.decode().strip() if isinstance(m, bytes) else m.strip() for m in ctrl.bridge.writes]
    assert sent == ["ISEL1:0"]
