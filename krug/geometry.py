"""Геометрия кольца: отдельно от GTK, чтобы проверять тестами."""
import math

RADIUS = 184.0     # расстояние от центра до середины карточки; при 8 пунктах карточки не касаются
BUBBLE_W, BUBBLE_H = 116, 80
CENTER = 150       # круг в середине: миниатюра файла и имя
DISC = RADIUS + BUBBLE_W / 2 + 22  # полупрозрачный диск под карточками


def bubble_positions(count: int, cx: float, cy: float) -> list[tuple[float, float]]:
    """Центры карточек по кругу: первая сверху, дальше по часовой стрелке."""
    return [(cx + RADIUS * math.sin(2 * math.pi * i / count), cy - RADIUS * math.cos(2 * math.pi * i / count))
            for i in range(count)]


def divider_angles(count: int) -> list[float]:
    """Углы линий между секторами (радианы от направления вверх по часовой). Для одного пункта линий нет."""
    if count < 2:
        return []
    return [2 * math.pi * (i + 0.5) / count for i in range(count)]
