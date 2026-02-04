import asyncio
from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue, ShutDown
import threading
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
        self._queue: Queue[bytes] = Queue()
        self.port: str = port
        self.baudrate: int = baudrate
        self.timeout: Optional[float] = timeout
        self.write_timeout: Optional[float] = write_timeout
        self.serial: serial.Serial | None = None
        # self._loop: asyncio.AbstractEventLoop = asyncio.get_event_loop()
        self._read_executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=1)
        self._tasks: set[asyncio.Task] = set()
        self._thread = None
        self._close_thread = False

    # async def _read_worker(self) -> None:
    #     while True:
    #         data: bytes = await self._loop.run_in_executor(
    #             self._read_executor,
    #             self.serial.readline,
    #             -1
    #         )
    #         if data:
    #             self._queue.put(data)
    #
    # async def _start_workers(self) -> None:
    #     self._tasks.add(asyncio.create_task(self._read_worker()))

    def _thread_main(self) -> None:
        while not self._close_thread:
            data: bytes = self.serial.readline()
            if data:
                try:
                    self._queue.put(data)
                except ShutDown:
                    break

    def connect(self) -> bool:
        """
        Initialize a connection with the UART interface.
        :return: True if the connection was successful, False otherwise.
        :rtype: bool
        """
        try:
            if self.serial:
                self.serial.open()
            else:
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
        self._queue = Queue()
        self._close_thread = False
        self._thread = threading.Thread(target=self._thread_main)
        self._thread.start()
        return True

    def close(self) -> None:
        """
        Close the UART bridge. This function will block until the queue is empty
        and close is successful. In testing, this could take several seconds after the
        queue has been drained.
        """
        self._close_thread = True
        self._queue.shutdown()
        self._queue.join()
        self._thread.join()
        self.serial.close()

    def get(self, timeout: Optional[float] = None) -> Optional[bytes]:
        """
        Get data from the UART read queue, with or without waiting.
        :type timeout: float, optional
        :param timeout: if timeout is greater than zero,
        blocks for at most 'timeout' seconds.
        :return: if data is available, returns data, otherwise returns None.
        :rtype bytes, optional
        """
        try:
            data: bytes
            if timeout:
                data = self._queue.get(timeout=timeout)
            else:
                data = self._queue.get_nowait()
            self._queue.task_done()
            return data
        except Empty:
            return None
        except ShutDown:
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