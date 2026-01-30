from uart import UARTBridge

from tekafp.input import Input


def main() -> None:
    bridge = UARTBridge("/dev/serial0", 115200)
    bridge.connect()

    # main loop
    while True:
        bridge.read()
        if bridge.queue.empty():
            continue
        else:
            afp_input = Input.from_bytes(bridge.queue.get())
            # TODO: translate afp_input to SCPI and send it


if __name__ == "__main__":
    main()