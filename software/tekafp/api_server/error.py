from enum import IntEnum, unique


@unique
class APIError(IntEnum):
    CONNECTION_ERROR = 0
