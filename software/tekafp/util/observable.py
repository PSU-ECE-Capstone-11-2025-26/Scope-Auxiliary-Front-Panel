import threading
from typing import Callable


class ObservableVariable[T]:
    def __init__(self, initial: T) -> None:
        self._value: T = initial
        self._callbacks: list[Callable[[T, T], None]] = []
        self._lock: threading.RLock = threading.RLock()

    def register(self, cb: Callable[[T, T], None]) -> None:
        with self._lock:
            self._callbacks.append(cb)

    @property
    def value(self) -> T:
        return self._value

    @value.setter
    def value(self, new: T) -> None:
        with self._lock:
            if new != self._value:
                old = self._value
                self._value = new
                for cb in self._callbacks:
                    cb(old, new)
