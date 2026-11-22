"""Геометрия кольца: отдельно от GTK, чтобы проверять тестами."""
import math

RADIUS = 168.0     # расстояние от центра до середины пузыря
BUBBLE_W, BUBBLE_H = 112, 86
CENTER = 132
DISC = RADIUS + BUBBLE_W / 2 + 18  # подложка кольца


def bubble_positions(count: int, cx: float, cy: float) -> list[tuple[float, float]]:
    """Центры пузырей по кругу: первый сверху, дальше по часовой стрелке."""
    return [(cx + RADIUS * math.sin(2 * math.pi * i / count), cy - RADIUS * math.cos(2 * math.pi * i / count))
            for i in range(count)]
