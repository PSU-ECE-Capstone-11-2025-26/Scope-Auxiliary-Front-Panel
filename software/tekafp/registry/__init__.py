class Registry[Key, Value]:

    def __init__(self) -> None:
        self._registry: dict[Key, Value] = {}

    def __delitem__(self, key: Key) -> None:
        del self._registry[key]

    def __contains__(self, key: Key) -> bool:
        return key in self._registry

    def register(self, key: Key, value: Value) -> None:
        if key in self._registry:
            raise ValueError(f"Key {key} already registered")
        self._registry[key] = value

    def get(self, key: Key) -> Value | None:
        if value := self._registry.get(key):
            return value
        else:
            raise KeyError(f"Key {key} not found")