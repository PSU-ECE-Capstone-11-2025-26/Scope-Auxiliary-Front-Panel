import serial

from tekafp.uart import UARTBridge


def test_uart_read() -> None:
    msg: bytes = b'testing123\n'

    bridge = UARTBridge("/dev/serial0", timeout=1, write_timeout=1)
    # overwrite the default serial with a loopback url
    bridge.serial = serial.serial_for_url(
        "loop://",
        baudrate=115200,
        do_not_open=True,
        timeout=bridge.timeout,
        write_timeout=bridge.write_timeout
    )
    bridge.connect()
    bridge.queue_write(msg)
    raw: bytes = bridge.get(timeout=3)
    assert raw == msg
    bridge.close()