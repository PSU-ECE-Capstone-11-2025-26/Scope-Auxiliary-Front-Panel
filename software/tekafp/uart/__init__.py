from queue import Queue

import serial


class UARTBridge:
    """
    A class to represent the UART bridge between the interface processor and the main
    processor.
    """
    def __init__(self, port: str, baudrate: int = 9600) -> None:
        self.queue: Queue[bytes] = Queue()
        self.port: str = port
        self.baudrate: int = baudrate
        self.serial = None

    def connect(self) -> bool:
        """
        Initialize a connection with the UART interface.
        :return: True if the connection was successful, False otherwise.
        """
        self.serial = serial.Serial(self.port, self.baudrate)
        return True

    def read(self) -> None:
        """
        Read data from the UART.
        The raw bytes received are added to the queue attribute.
        """
        if not self.serial or not self.serial.is_open:
            return
        line: bytes = self.serial.readline()
        self.queue.put(line)

    def _write(self, msg: bytes) -> None:
        if not self.serial or not self.serial.is_open:
            return
        self.serial.write(msg)
