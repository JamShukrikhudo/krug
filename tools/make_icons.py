"""Рисует символьные иконки krug (16×16, только заливка) в krug/icons/hicolor/scalable/actions.

Иконки свои, чтобы интерфейс выглядел одинаково при любой теме: в новых версиях Adwaita
многих привычных иконок больше нет. Запуск: python3 tools/make_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "krug" / "icons" / "hicolor" / "scalable" / "actions"


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _rr(x, y, w, h, r=0.0) -> str:
    if r <= 0:
        return f"M{f(x)} {f(y)}h{f(w)}v{f(h)}h{f(-w)}z"
    r = min(r, w / 2, h / 2)
    return (f"M{f(x + r)} {f(y)}h{f(w - 2 * r)}a{f(r)} {f(r)} 0 0 1 {f(r)} {f(r)}v{f(h - 2 * r)}"
            f"a{f(r)} {f(r)} 0 0 1 {f(-r)} {f(r)}h{f(-(w - 2 * r))}a{f(r)} {f(r)} 0 0 1 {f(-r)} {f(-r)}"
            f"v{f(-(h - 2 * r))}a{f(r)} {f(r)} 0 0 1 {f(r)} {f(-r)}z")


def rrect(x, y, w, h, r=0.0) -> list[str]:
    return [_rr(x, y, w, h, r)]


def frame(x, y, w, h, t=1.5, r=1.5) -> list[str]:
    """Контур прямоугольника толщиной t: внешний и внутренний контур в одном path (evenodd)."""
    return [_rr(x, y, w, h, r) + _rr(x + t, y + t, w - 2 * t, h - 2 * t, max(r - t, 0))]


def _circle(cx, cy, r) -> str:
    return f"M{f(cx - r)} {f(cy)}a{f(r)} {f(r)} 0 1 0 {f(2 * r)} 0a{f(r)} {f(r)} 0 1 0 {f(-2 * r)} 0z"


def circle(cx, cy, r) -> list[str]:
    return [_circle(cx, cy, r)]


def ring(cx, cy, r, t=1.5) -> list[str]:
    return [_circle(cx, cy, r) + _circle(cx, cy, r - t)]


def pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def band(cx, cy, r, t, a0, a1) -> list[str]:
    """Дуга-полоса от a0 до a1 градусов по часовой (0° — вправо)."""
    large = 1 if (a1 - a0) % 360 > 180 else 0
    x0, y0 = pt(cx, cy, r, a0)
    x1, y1 = pt(cx, cy, r, a1)
    x2, y2 = pt(cx, cy, r - t, a1)
    x3, y3 = pt(cx, cy, r - t, a0)
    ri = r - t
    return [f"M{f(x0)} {f(y0)}A{f(r)} {f(r)} 0 {large} 1 {f(x1)} {f(y1)}L{f(x2)} {f(y2)}"
            f"A{f(ri)} {f(ri)} 0 {large} 0 {f(x3)} {f(y3)}z"]


def _poly(*points) -> str:
    return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in points) + "z"


def poly(*points) -> list[str]:
    return [_poly(*points)]


def bar(x0, y0, x1, y1, t=1.6) -> list[str]:
    """Отрезок толщиной t как многоугольник."""
    dx, dy = x1 - x0, y1 - y0
    n = math.hypot(dx, dy) or 1
    ox, oy = -dy / n * t / 2, dx / n * t / 2
    return poly((x0 + ox, y0 + oy), (x1 + ox, y1 + oy), (x1 - ox, y1 - oy), (x0 - ox, y0 - oy))


def arrow_head(x, y, deg, size=4.2) -> list[str]:
    """Треугольник-стрелка с вершиной в (x, y), смотрящий в направлении deg."""
    back = deg + 180
    return poly((x, y), pt(x, y, size, back - 32), pt(x, y, size, back + 32))


def cross(cx, cy, s=4, t=1.7) -> list[str]:
    return bar(cx - s, cy - s, cx + s, cy + s, t) + bar(cx - s, cy + s, cx + s, cy - s, t)


def folder() -> list[str]:
    return frame(1, 3, 14, 11, 1.5, 1.5) + rrect(1, 2, 6, 3, 1)


ICONS: dict[str, list[str]] = {
    "rotate-left": band(8, 8.5, 6.5, 1.7, 200, 120 + 360 - 360 + 360) + arrow_head(1.2, 6.2, 260),
    "rotate-right": band(8, 8.5, 6.5, 1.7, 60, 340) + arrow_head(14.8, 6.2, 280),
    "flip": poly((1, 13), (6.5, 3), (6.5, 13)) + rrect(7.3, 1, 1.4, 14) + poly((9.5, 3), (15, 13), (9.5, 13)),
    "compare": frame(1, 2, 14, 12, 1.5, 2) + rrect(8, 2, 7, 12, 0),
    "select": rrect(1, 1, 5, 1.6) + rrect(1, 1, 1.6, 5) + rrect(10, 1, 5, 1.6) + rrect(13.4, 1, 1.6, 5)
              + rrect(1, 13.4, 5, 1.6) + rrect(1, 10, 1.6, 5) + rrect(10, 13.4, 5, 1.6) + rrect(13.4, 10, 1.6, 5),
    "clear": ring(8, 8, 7, 1.6) + cross(8, 8, 2.8, 1.6),
    "resize": bar(3.5, 12.5, 12.5, 3.5, 1.7) + arrow_head(14, 2, -45, 5) + arrow_head(2, 14, 135, 5),
    "archive": frame(2, 5, 12, 10, 1.5, 1.2) + rrect(1, 1.5, 14, 4, 1) + rrect(6, 7.5, 4, 1.6, 0.8),
    "border": frame(1, 1, 14, 14, 1.5, 1.5) + rrect(4.5, 4.5, 7, 7, 1),
    "contrast": ring(8, 8, 7, 1.5) + ["M8 2.5a5.5 5.5 0 0 1 0 11z"],
    "eraser": poly((6, 14), (1.5, 9.5), (9, 2), (14.5, 7.5), (8, 14)) + rrect(8, 13.4, 7, 1.6),
    "plus": rrect(7.2, 2, 1.6, 12) + rrect(2, 7.2, 12, 1.6),
    "scissors": ring(4, 12, 2.8, 1.5) + ring(12, 12, 2.8, 1.5) + bar(5.6, 9.8, 12, 1, 1.6) + bar(10.4, 9.8, 4, 1, 1.6),
    "video": frame(1, 3, 10, 10, 1.5, 2) + poly((11.5, 8), (15, 4.5), (15, 11.5)),
    "mute": poly((1, 5.5), (4, 5.5), (8, 2), (8, 14), (4, 10.5), (1, 10.5)) + cross(12, 8, 2.6, 1.5),
    "speaker": poly((1, 5.5), (4, 5.5), (8, 2), (8, 14), (4, 10.5), (1, 10.5)) + band(8, 8, 4.5, 1.4, -55, 55)
               + band(8, 8, 7.2, 1.4, -55, 55),
    "speed": poly((1, 3), (8, 8), (1, 13)) + poly((8, 3), (15, 8), (8, 13)),
    "camera": frame(1, 4, 14, 10, 1.5, 2) + rrect(5, 2, 6, 3, 1) + ring(8, 9, 2.8, 1.5),
    "folder": folder(),
    "folder-open": frame(1, 3, 14, 11, 1.5, 1.5) + rrect(1, 2, 6, 3, 1) + poly((4, 7), (15, 7), (13, 14), (2, 14)),
    "move": folder() + bar(4.5, 8.5, 9.5, 8.5, 1.6) + arrow_head(12, 8.5, 0, 4),
    "copy": frame(5, 5, 10, 10, 1.5, 1.5) + rrect(1, 1, 9.5, 1.5, 0.75) + rrect(1, 1, 1.5, 9.5, 0.75),
    "paste": frame(2, 3, 12, 12, 1.5, 1.5) + rrect(5, 1, 6, 3.5, 1) + rrect(5, 8, 6, 1.5) + rrect(5, 11, 4, 1.5),
    "text": rrect(2, 2, 12, 2.2, 0.5) + rrect(6.9, 2, 2.2, 12, 0.5),
    "terminal": frame(1, 2, 14, 12, 1.5, 1.5) + bar(4, 5.5, 7, 8, 1.6) + bar(7, 8, 4, 10.5, 1.6) + rrect(8.5, 10, 4, 1.6),
    "phone": frame(4, 1, 8, 14, 1.5, 2) + circle(8, 12, 1),
    "image": frame(1, 2, 14, 12, 1.5, 1.5) + poly((3, 12), (7, 6.5), (10, 10), (11.5, 8.5), (13, 12)) + circle(11, 5.5, 1.3),
    "magic": bar(2, 14, 10, 6, 2) + poly((12, 1), (12.8, 3.2), (15, 4), (12.8, 4.8), (12, 7), (11.2, 4.8), (9, 4),
                                          (11.2, 3.2)) + circle(4.5, 4, 1) + circle(14, 10, 1),
    "edit": poly((2, 14), (2.6, 10.6), (10.6, 2.6), (13.4, 5.4), (5.4, 13.4)) + poly((11.4, 1.8), (12.6, 0.6),
                                                                                      (15.4, 3.4), (14.2, 4.6)),
    "grid": rrect(1, 1, 6, 6, 1) + rrect(9, 1, 6, 6, 1) + rrect(1, 9, 6, 6, 1) + rrect(9, 9, 6, 6, 1),
    "play": poly((3, 1.5), (14, 8), (3, 14.5)),
    "target": ring(8, 8, 6, 1.5) + circle(8, 8, 2) + rrect(7.25, 0, 1.5, 3) + rrect(7.25, 13, 1.5, 3)
              + rrect(0, 7.25, 3, 1.5) + rrect(13, 7.25, 3, 1.5),
    "convert": band(8, 8, 6.5, 1.6, 200, 330) + arrow_head(14.3, 6, 80) + band(8, 8, 6.5, 1.6, 20, 150)
               + arrow_head(1.7, 10, 260),
    "tools": ring(11, 5, 3.6, 1.6) + bar(2, 14, 8.4, 7.6, 2.2),
    "home": poly((8, 1), (15, 7.5), (13, 7.5), (13, 15), (9.5, 15), (9.5, 10.5), (6.5, 10.5), (6.5, 15), (3, 15),
                 (3, 7.5), (1, 7.5)),
    "clock": ring(8, 8, 7, 1.5) + rrect(7.25, 3.5, 1.5, 5) + rrect(7.25, 7.25, 4, 1.5),
    "puzzle": rrect(1, 4, 11, 11, 1.5) + circle(6.5, 3, 2) + circle(13, 9.5, 2),
    "check": poly((1.5, 8.5), (3, 7), (6, 10), (13, 3), (14.5, 4.5), (6, 13)),
    "warning": poly((8, 1), (15.5, 14.5), (0.5, 14.5)) + rrect(7.1, 5.5, 1.8, 5) + rrect(7.1, 11.5, 1.8, 1.8),
    "error": ring(8, 8, 7, 1.6) + cross(8, 8, 2.8, 1.6),
    "refresh": band(8, 8, 6.5, 1.7, 300, 240 + 360 - 360) + arrow_head(14.8, 3.5, 300),
    "trash": rrect(1.5, 2.5, 13, 1.6, 0.8) + rrect(6, 1, 4, 2, 0.8)
             + [_poly((3, 5), (13, 5), (12, 15), (4, 15)) + "M5.5 6.5h1.5v7h-1.5zM9 6.5h1.5v7H9z"],
    "audio": circle(5, 12.5, 2.5) + rrect(6.2, 2, 1.6, 10.5) + poly((6.2, 2), (14, 1), (14, 4), (6.2, 5)),
    "back": poly((10.5, 1.5), (12, 3), (7, 8), (12, 13), (10.5, 14.5), (4, 8)),
    "doc": frame(2, 1, 12, 14, 1.5, 1.5) + rrect(5, 5, 6, 1.5) + rrect(5, 8, 6, 1.5) + rrect(5, 11, 4, 1.5),
    "download": bar(8, 1, 8, 10, 1.7) + arrow_head(8, 12, 90, 5) + rrect(1.5, 13.5, 13, 1.6),
}

# стрелки на концах дуг: вершина продолжает дугу по касательной
ICONS["rotate-left"] = band(8, 8.5, 6.5, 1.7, 200, 120) + arrow_head(1.5, 9.9, 110, 4.6)
ICONS["rotate-right"] = band(8, 8.5, 6.5, 1.7, 60, 340) + arrow_head(14.5, 9.9, 70, 4.6)
ICONS["refresh"] = band(8, 8, 6.5, 1.7, 330, 260) + arrow_head(10.5, 1.8, 350, 4.6)
ICONS["convert"] = (band(8, 8, 6.5, 1.6, 200, 330) + arrow_head(14.6, 8, 60, 4.4)
                    + band(8, 8, 6.5, 1.6, 20, 150) + arrow_head(1.4, 8, 240, 4.4))

HEAD = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
PATH = '<path fill="#222222" fill-rule="evenodd" d="{d}"/>'



def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("krug-*-symbolic.svg"):
        old.unlink()
    for name, d in ICONS.items():
        assert isinstance(d, list), name
        svg = HEAD + "".join(PATH.format(d=part) for part in d) + "</svg>\n"
        (OUT / f"krug-{name}-symbolic.svg").write_text(svg, encoding="utf-8")
    print(f"{len(ICONS)} иконок в {OUT}")


if __name__ == "__main__":
    main()
