"""Круглое меню на GTK4.

На Wayland приложение не может поставить окно под курсор, поэтому окно прозрачное
и на весь экран, а кольцо рисуется там, где оказался указатель.
"""
from __future__ import annotations

import math
import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from . import ops  # noqa: E402
from .geometry import R_IN, R_OUT, sector_index  # noqa: E402
from .util import notify  # noqa: E402

PER_PAGE = 8
GAP = 0.03  # радиан между секторами
ACCENT = (0.21, 0.52, 0.89)
CSS = "window.krug-menu { background: transparent; }"


class RadialMenu(Gtk.ApplicationWindow):
    def __init__(self, app: "MenuApp", title: str, items: list[ops.Item], files: list[Path]):
        super().__init__(application=app, title="krug")
        self.app = app
        self.menu_title = title
        self.files = files
        self.stack: list[list[ops.Item]] = [items]
        self.page = 0
        self.hover: int | None = None
        self.center: tuple[float, float] | None = None

        self.set_decorated(False)
        self.add_css_class("krug-menu")
        self.area = Gtk.DrawingArea()
        self.area.set_draw_func(self.draw)
        self.set_child(self.area)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_motion)
        motion.connect("motion", self.on_motion)
        self.area.add_controller(motion)
        click = Gtk.GestureClick()
        click.set_button(0)
        click.connect("released", self.on_click)
        self.area.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", lambda _c, _dx, dy: self.turn_page(1 if dy > 0 else -1) or True)
        self.area.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

        self.fullscreen()
        # если указатель не сдвинулся и событие входа не пришло, рисуем по центру экрана
        GLib.timeout_add(250, self.fallback_center)

    # ------------------------------------------------------------ состояние
    @property
    def items(self) -> list[ops.Item]:
        return self.stack[-1]

    @property
    def pages(self) -> int:
        return max(1, math.ceil(len(self.items) / PER_PAGE))

    @property
    def visible_items(self) -> list[ops.Item]:
        start = self.page * PER_PAGE
        return self.items[start:start + PER_PAGE]

    def turn_page(self, step: int) -> None:
        if self.pages > 1:
            self.page = (self.page + step) % self.pages
            self.hover = None
            self.area.queue_draw()

    def back(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self.page = 0
            self.hover = None
            self.area.queue_draw()
        else:
            self.close()

    def fallback_center(self) -> bool:
        if self.center is None:
            self.set_center(self.area.get_width() / 2, self.area.get_height() / 2)
        return False

    def set_center(self, x: float, y: float) -> None:
        w, h = self.area.get_width(), self.area.get_height()
        margin = R_OUT + 12
        if w > 2 * margin:
            x = min(max(x, margin), w - margin)
        if h > 2 * margin:
            y = min(max(y, margin), h - margin)
        self.center = (x, y)
        self.area.queue_draw()

    # -------------------------------------------------------------- события
    def on_motion(self, _controller, x: float, y: float) -> None:
        if self.center is None:
            self.set_center(x, y)
            return
        hover = sector_index(x - self.center[0], y - self.center[1], len(self.visible_items))
        if hover != self.hover:
            self.hover = hover
            self.area.queue_draw()

    def on_click(self, gesture, _n: int, x: float, y: float) -> None:
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            self.back()
            return
        if self.center is None:
            self.set_center(x, y)
            return
        index = sector_index(x - self.center[0], y - self.center[1], len(self.visible_items))
        if index is None:
            self.close()
        elif index == -1:
            if len(self.stack) > 1:
                self.back()
            elif self.pages > 1:
                self.turn_page(1)
            else:
                self.close()
        else:
            self.activate_item(index)

    def on_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        count = len(self.visible_items)
        if keyval == Gdk.KEY_Escape:
            self.back()
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Down):
            self.turn_page(1)
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Up):
            self.turn_page(-1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Tab) and count:
            self.hover = 0 if self.hover in (None, -1) else (self.hover + 1) % count
            self.area.queue_draw()
        elif keyval in (Gdk.KEY_Left, Gdk.KEY_ISO_Left_Tab) and count:
            self.hover = count - 1 if self.hover in (None, -1) else (self.hover - 1) % count
            self.area.queue_draw()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            if self.hover is not None and self.hover >= 0:
                self.activate_item(self.hover)
        elif Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and keyval - Gdk.KEY_1 < count:
            self.activate_item(keyval - Gdk.KEY_1)
        else:
            return False
        return True

    def activate_item(self, index: int) -> None:
        item = self.visible_items[index]
        if item.children and not item.missing:
            self.stack.append(item.children)
            self.page = 0
            self.hover = None
            self.area.queue_draw()
            return
        self.app.start(item, self.files)
        self.close()

    # ------------------------------------------------------------ рисование
    def draw(self, _area, cr, width: int, height: int) -> None:
        cr.set_source_rgba(0, 0, 0, 0.22)
        cr.paint()
        if self.center is None:
            return
        cx, cy = self.center
        items = self.visible_items
        count = len(items)
        span = 2 * math.pi / count if count else 0

        for i, item in enumerate(items):
            mid = -math.pi / 2 + i * span
            a0, a1 = mid - span / 2, mid + span / 2
            if count > 1:
                a0, a1 = a0 + GAP / 2, a1 - GAP / 2
            cr.new_path()
            cr.arc(cx, cy, R_OUT, a0, a1)
            cr.arc_negative(cx, cy, R_IN + 6, a1, a0)
            cr.close_path()
            if i == self.hover and not item.missing:
                cr.set_source_rgba(*ACCENT, 0.96)
            elif i == self.hover:
                cr.set_source_rgba(0.32, 0.32, 0.35, 0.96)
            else:
                cr.set_source_rgba(0.13, 0.13, 0.15, 0.94)
            cr.fill()

            radius = (R_OUT + R_IN) / 2 + 4
            tx, ty = cx + radius * math.cos(mid), cy + radius * math.sin(mid)
            label = item.label + (" ›" if item.children else "")
            alpha = 0.45 if item.missing else 1.0
            self.text(cr, label, tx, ty, 118, 11, alpha, bold=(i == self.hover))

        # середина: заголовок, файл, подсказка
        cr.new_path()
        cr.arc(cx, cy, R_IN, 0, 2 * math.pi)
        cr.set_source_rgba(0.09, 0.09, 0.11, 0.97 if self.hover != -1 else 1.0)
        cr.fill()
        if len(self.stack) > 1:
            head, sub = "‹ Назад", ""
        else:
            head = self.menu_title
            sub = self.files[0].name if len(self.files) == 1 else f"файлов: {len(self.files)}"
            if self.pages > 1:
                sub = f"стр. {self.page + 1}/{self.pages} ›"
        self.text(cr, head, cx, cy - (9 if sub else 0), 2 * R_IN - 20, 11, 1.0, bold=True)
        if sub:
            self.text(cr, sub, cx, cy + 12, 2 * R_IN - 24, 9, 0.7, ellipsize=True)

        hovered = items[self.hover] if self.hover is not None and 0 <= self.hover < count else None
        if hovered is not None and hovered.missing:
            below = cy + R_OUT + 26 if cy + R_OUT + 50 < height else cy - R_OUT - 26
            self.text(cr, hovered.missing, cx, below, 520, 11, 1.0)

    def text(self, cr, text: str, x: float, y: float, width: float, size: int, alpha: float,
             bold: bool = False, ellipsize: bool = False) -> None:
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription(f"Sans {'Bold ' if bold else ''}{size}")
        layout.set_font_description(font)
        layout.set_width(int(width * Pango.SCALE))
        layout.set_alignment(Pango.Alignment.CENTER)
        if ellipsize:
            layout.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        else:
            layout.set_wrap(Pango.WrapMode.WORD_CHAR)
        layout.set_text(text, -1)
        _w, h = layout.get_pixel_size()
        cr.move_to(x - width / 2, y - h / 2)
        cr.set_source_rgba(1, 1, 1, alpha)
        PangoCairo.show_layout(cr, layout)


class MenuApp(Gtk.Application):
    def __init__(self, menu: str, files: list[Path]):
        super().__init__(application_id="io.github.krug.Menu", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.menu = menu
        self.files = files

    def do_activate(self) -> None:
        provider = Gtk.CssProvider()
        try:
            provider.load_from_string(CSS)
        except AttributeError:  # GTK до 4.12
            provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        items = ops.build_menu(self.menu, self.files)
        RadialMenu(self, ops.MENU_TITLES[self.menu], items, self.files).present()

    # --------------------------------------------------------- выполнение
    def start(self, item: ops.Item, files: list[Path]) -> None:
        self.hold()  # окно меню закроется, а приложение должно дожить до конца работы
        if item.missing:
            notify("Не хватает программы", item.missing, error=True)
            self.release()
        elif item.folder:
            dialog = Gtk.FileDialog()
            dialog.set_title(item.label)
            dialog.set_initial_folder(Gio.File.new_for_path(str(files[0].parent)))
            dialog.select_folder(None, None, self.on_folder, (item, files))
        else:
            self.work(item, files, None)

    def on_folder(self, dialog, result, data) -> None:
        item, files = data
        try:
            folder = Path(dialog.select_folder_finish(result).get_path())
        except GLib.Error:
            self.release()  # пользователь закрыл окно выбора
            return
        self.work(item, files, folder)

    def work(self, item: ops.Item, files: list[Path], folder: Path | None) -> None:
        state = {"done": False}

        def slow() -> bool:
            if not state["done"]:
                notify(f"{item.label}: обработка…", "Сообщу, когда закончу")
            return False

        def job() -> None:
            results, errors = ops.execute(item, files, folder)
            GLib.idle_add(finish, results, errors)

        def finish(results: list[Path], errors: list[str]) -> bool:
            state["done"] = True
            if errors:
                notify(f"{item.label}: ошибка", "\n".join(errors[:4]), error=True)
            elif not item.quiet:
                names = ", ".join(p.name for p in results[:3]) + (" …" if len(results) > 3 else "")
                notify(f"{item.label}: готово", names)
            self.release()
            return False

        GLib.timeout_add_seconds(3, slow)
        threading.Thread(target=job, daemon=True).start()


def show(menu: str, files: list[Path]) -> int:
    return MenuApp(menu, files).run([])
