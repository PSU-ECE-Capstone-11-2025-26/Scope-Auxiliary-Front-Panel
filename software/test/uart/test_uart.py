import serial

from tekafp.uart import UARTBridge


def test_uart_read() -> None:
    msg: bytes = b'testing123\n'

    bridge = UARTBridge("/dev/serial0", timeout=5, write_timeout=5)
    # overwrite the default serial with a loopback url
    bridge.serial = serial.serial_for_url(
        "loop://",
        baudrate=115200,
        do_not_open=True,
        timeout=bridge.timeout,
        write_timeout=bridge.write_timeout
    )
    bridge.connect()
    write_status = bridge._write(msg)
    assert write_status
    # if this takes longer even half a second, something is wrong!
    raw: bytes = bridge.get(timeout=0.5)
    bridge.close()
    assert raw == msg
