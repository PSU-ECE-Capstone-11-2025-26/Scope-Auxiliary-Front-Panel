import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from warnings import deprecated

import serial


class UARTBridge:
    """
    A class to represent the UART bridge between the interface processor and the main
    processor. UART reading is done asynchronously.
    :type port: str
    :param port: The serial port of the UART.
    :type baudrate: int
    :param baudrate: The baudrate of the UART.
    :type timeout: float, optional
    :param timeout: The (read) timeout of the UART.
    :type write_timeout: float, optional
    :param write_timeout: The write timeout of the UART.
    """
    def __init__(
            self,
            port: str,
            baudrate: int = 9600,
            timeout: Optional[float] = None,
            write_timeout: Optional[float] = None,
    ) -> None:
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()
        self.port: str = port
        self.baudrate: int = baudrate
        self.timeout: Optional[float] = timeout
        self.write_timeout: Optional[float] = write_timeout
        self.serial: serial.Serial | None = None
        self._loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._read_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1)

    async def _read_worker(self) -> None:
        while True:
            data: bytes = await self._loop.run_in_executor(
                self._read_executor,
                self.serial.readline
            )
            if data:
                await self._queue.put(data)

    async def _start_workers(self) -> None:
        asyncio.create_task(self._read_worker())

    def connect(self) -> bool:
        """
        Initialize a connection with the UART interface.
        :return: True if the connection was successful, False otherwise.
        :rtype: bool
        """
        try:
            self.serial = serial.Serial(
                self.port,
                self.baudrate,
                timeout=self.timeout,
                write_timeout=self.write_timeout
            )
        except serial.SerialException:
            return False
        except ValueError:
            return False

        asyncio.run(self._start_workers())
        return True

    def get(self) -> Optional[bytes]:
        """
        Get data from the UART read queue, without waiting.
        :return: if data is available, returns data, otherwise returns None.
        :rtype bytes, optional
        """
        try:
            return self._queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    @deprecated("Blocking read no longer required")
    def read(self) -> None:
        pass

    def _write(self, msg: bytes) -> bool:
        if not self.serial or not self.serial.is_open:
            return False
        try:
            self.serial.write(msg)
            return True
        except serial.SerialTimeoutException:
            return False