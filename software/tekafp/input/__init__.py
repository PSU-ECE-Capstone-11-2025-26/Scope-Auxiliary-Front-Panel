from dataclasses import dataclass


@dataclass
class Input:
    id: str
    value: float

    @classmethod
    def from_bytes(cls, data: bytes) -> "Input":
        split = data.decode("utf-8").rstrip().split(":")
        return cls(split[0], float(split[1]))
