import threading
from typing import Callable


class ObservableVariable[T]:
    def __init__(self, initial: T) -> None:
        self._value: T = initial
        self._callbacks: dict[int, Callable[[T, T], None]] = {}
        self._next_token: int = 0
        self._lock: threading.RLock = threading.RLock()

    def register(self, cb: Callable[[T, T], None]) -> int:
        with self._lock:
            token = self._next_token
            self._next_token += 1
            self._callbacks[token] = cb
            return token

    def unregister(self, token: int) -> None:
        with self._lock:
            self._callbacks.pop(token, None)

    def clear_callbacks(self) -> None:
        with self._lock:
            self._callbacks.clear()
            self._next_token = 0

    @property
    def value(self) -> T:
        return self._value

    @value.setter
    def value(self, new: T) -> None:
        with self._lock:
            if new != self._value:
                old = self._value
                self._value = new
                for cb in self._callbacks.values():
                    cb(old, new)
