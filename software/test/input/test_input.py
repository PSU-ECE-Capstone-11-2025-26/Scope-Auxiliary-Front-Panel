from tekafp.input import Input


def test_input() -> None:
    data: bytes = b'VP1:-2.1\n'
    uart_input: Input = Input.from_bytes(data)
    assert uart_input.id == "VP1" and uart_input.value == -2.1