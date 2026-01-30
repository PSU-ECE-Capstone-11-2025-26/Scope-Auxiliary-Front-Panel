from os import uname

import pytest

from tekafp.uart import UARTBridge


@pytest.mark.skipif(uname().nodename != "tek-afp",
                    reason="Hostname != tek-afp: test must run on a testbench")
def test_uart_read() -> None:
    # Requires UART set up on the Pi and the pins to be connected in loopback
    # GPIO 14 connected to GPIO 15 (UART0)
    msg: bytes = b'testing123\n'

    bridge = UARTBridge("/dev/serial0")
    bridge.connect()
    bridge._write(msg)
    bridge.read()
    raw: bytes = bytes(0)
    if not bridge.queue.empty():
        raw = bridge.queue.get(timeout=0.1)
    assert raw == msg
