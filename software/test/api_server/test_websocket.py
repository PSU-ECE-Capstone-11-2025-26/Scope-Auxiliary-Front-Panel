from fastapi.testclient import TestClient

from tekafp.api_server import app


SCOPE_ACTION_PACKET = {
    "from": "client",
    "data": [
        {"$type": "ScopeAction", "action": "enable", "scope": "USB0::::::::INSTR"},
    ],
}

MACRO_RECORD_PACKET = {
    "from": "client",
    "data": [
        {"$type": "MacroRecord", "record": True, "slot": 0},
    ],
}

SCOPE_STATE_PACKET = {
    "from": "server",
    "data": [
        {
            "$type": "ScopeState",
            "status": "connected",
            "channels": [False, False, False, True],
            "source_channel": 0,
            "trigger_source": 0,
            "trigger_mode": "AUTO",
            "trigger_edge_slope": "RISE",
            "run_stop": True,
            "zoom_enabled": False,
        },
    ],
}


def test_websocket_receive() -> None:
    """Client-sent JSON is placed into the receive queue."""
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        ws.send_json(SCOPE_ACTION_PACKET)

    queued = app.state.receive_queue.get(timeout=1)
    assert queued == SCOPE_ACTION_PACKET


def test_websocket_send() -> None:
    """Items in the send queue are forwarded to the client."""
    client = TestClient(app)
    app.state.send_queue.put(SCOPE_STATE_PACKET)

    with client.websocket_connect("/ws") as ws:
        ws.send_json(MACRO_RECORD_PACKET)
        data = ws.receive_json()

    assert data == SCOPE_STATE_PACKET
