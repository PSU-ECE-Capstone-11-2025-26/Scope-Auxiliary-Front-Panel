def parse_resp(resp: str, rtype: type[float | int | str]) -> float | int | str:
    return rtype(resp.strip().split()[-1])

def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))