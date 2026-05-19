from collections.abc import Generator
import time

import pytest
import serial

from tekafp.uart import UARTBridge


@pytest.fixture
def uart_bridge() -> Generator[UARTBridge, None, None]:
    bridge = UARTBridge("/dev/serial0", timeout=0.1, write_timeout=1)
    bridge.serial = serial.serial_for_url(
        "loop://",
        baudrate=115200,
        do_not_open=True,
        timeout=bridge.timeout,
        write_timeout=bridge.write_timeout,
    )
    bridge.connect()
    yield bridge
    bridge.close()


def test_uart_roundtrip(uart_bridge: UARTBridge) -> None:
    msg: bytes = b"testing123\n"
    uart_bridge.queue_write(msg)
    raw: bytes = uart_bridge.get(timeout=3)
    assert raw == msg


def test_uart_bulk_write(uart_bridge: UARTBridge) -> None:
    msgs = [f"msg{i}\n".encode() for i in range(10)]
    for msg in msgs:
        uart_bridge.queue_write(msg)

    start = time.monotonic()
    received = [uart_bridge.get(timeout=3) for _ in msgs]
    elapsed = time.monotonic() - start

    assert received == msgs
    # All messages should arrive well under one timeout period each
    # if only one is sent per loop they would take ~N * timeout (1.0s).
    assert elapsed < len(msgs) * uart_bridge.timeout / 2


def test_uart_bulk_read(uart_bridge: UARTBridge) -> None:
    msgs = [f"msg{i}\n".encode() for i in range(10)]
    for msg in msgs:
        # pre-fill buffer
        uart_bridge.write_sync(msg)

    start = time.monotonic()
    received = [uart_bridge.get(timeout=3) for _ in msgs]
    elapsed = time.monotonic() - start

    assert received == msgs
    # reading one per loop should still drain them well under N * timeout
    assert elapsed < len(msgs) * uart_bridge.timeout / 2
