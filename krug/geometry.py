"""Геометрия кольца: отдельно от GTK, чтобы проверять тестами."""
import math

R_OUT = 200.0
R_IN = 72.0


def sector_index(dx: float, dy: float, count: int) -> int | None:
    """Номер сектора по смещению от центра; -1 это середина, None это мимо кольца."""
    r = math.hypot(dx, dy)
    if r < R_IN:
        return -1
    if r > R_OUT or count == 0:
        return None
    span = 2 * math.pi / count
    angle = (math.atan2(dy, dx) + math.pi / 2 + span / 2) % (2 * math.pi)
    return min(int(angle / span), count - 1)
