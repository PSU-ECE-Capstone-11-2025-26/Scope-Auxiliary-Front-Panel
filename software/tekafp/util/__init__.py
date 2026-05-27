import re


def parse_resp(resp: str, rtype: type[float | int | str]) -> float | int | str:
    return rtype(resp.strip().split()[-1])


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def parse_channel_count(idn: str) -> int:
    m = re.search(r"MSO\d(\d)", idn, re.IGNORECASE)
    if m is None:
        return 1
    return int(m.group(1))
