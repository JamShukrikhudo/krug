"""Круглое меню: светлый полупрозрачный диск с секторами, на нём карточки пунктов,
в середине миниатюра файла и его имя. Экран вокруг не затемняется.

На Wayland приложение не может поставить окно под курсор, поэтому окно прозрачное
и на весь экран, а кольцо появляется там, где оказался указатель.
"""
from __future__ import annotations

import math
from pathlib import Path

import cairo

from .ui import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, icon_name, in_thread, load_css
from . import history, ops
from .geometry import BUBBLE_H, BUBBLE_W, CENTER, DISC, bubble_positions, divider_angles
from .util import notify

PER_PAGE = 8
# как в образце: зажали клавишу — кольцо переключилось на свой набор
MODES = (
    ("convert", "Shift", (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R)),
    ("actions", "Ctrl", (Gdk.KEY_Control_L, Gdk.KEY_Control_R)),
    ("tools", "Alt", (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R, Gdk.KEY_ISO_Level3_Shift)),
)
THUMB = 64


def file_preview(path: Path) -> Gtk.Widget:
    """Миниатюра файла: готовая из кэша «Файлов», уменьшенная картинка или значок типа файла."""
    gfile = Gio.File.new_for_path(str(path))
    try:
        info = gfile.query_info("thumbnail::path,standard::icon", Gio.FileQueryInfoFlags.NONE, None)
    except GLib.Error:
        info = None
    sources = []
    if info and info.get_attribute_byte_string("thumbnail::path"):
        sources.append(info.get_attribute_byte_string("thumbnail::path"))
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg", ".avif", ".heic"}:
        sources.append(str(path))
    for source in sources:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(source, THUMB, THUMB, True)
        except GLib.Error:
            continue
        picture = Gtk.Picture.new_for_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
        picture.set_can_shrink(True)
        picture.set_size_request(pixbuf.get_width(), pixbuf.get_height())
        frame = Gtk.Box(css_classes=["krug-thumb-frame"], halign=Gtk.Align.CENTER, overflow=Gtk.Overflow.HIDDEN)
        frame.append(picture)
        return frame
    image = Gtk.Image(pixel_size=THUMB)
    if info and info.get_icon():
        image.set_from_gicon(info.get_icon())
    else:
        image.set_from_icon_name("krug-file-symbolic")
    return image


class RadialMenu(Gtk.ApplicationWindow):
    def __init__(self, app: "MenuApp", title: str, items: list[ops.Item], files: list[Path]):
        super().__init__(application=app, title="krug")
        self.app = app
        self.menu_title = title
        self.menu = next((m for m, t in ops.MENU_TITLES.items() if t == title), "convert")
        self.files = files
        self.stack: list[list[ops.Item]] = [items]
        self.page = 0
        self.center: tuple[float, float] | None = None
        self.bubbles: list[Gtk.Button] = []
        self.preview: Gtk.Widget | None = None

        self.set_decorated(False)
        self.add_css_class("krug-menu")
        self.dark = Adw.StyleManager.get_default().get_dark()
        if self.dark:
            self.add_css_class("dark")

        self.backdrop = Gtk.DrawingArea()
        self.backdrop.set_draw_func(self.draw_backdrop)
        self.fixed = Gtk.Fixed()
        self.hint = Gtk.Label(css_classes=["krug-hint"], visible=False)
        overlay = Gtk.Overlay(child=self.backdrop)
        overlay.add_overlay(self.fixed)
        self.set_child(overlay)

        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self.on_pointer)
        motion.connect("motion", self.on_pointer)
        overlay.add_controller(motion)
        click = Gtk.GestureClick(button=0)
        click.connect("released", self.on_empty_click)
        overlay.add_controller(click)
        scroll = Gtk.EventControllerScroll.new(Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", lambda _c, _dx, dy: self.turn_page(1 if dy > 0 else -1) or True)
        overlay.add_controller(scroll)
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self.on_key)
        self.add_controller(keys)

        # размер экрана задаём и сами: без оконного менеджера fullscreen() не срабатывает
        monitors = Gdk.Display.get_default().get_monitors()
        if monitors.get_n_items():
            geometry = monitors.get_item(0).get_geometry()
            self.set_default_size(geometry.width, geometry.height)
        self.fullscreen()
        # если событие входа указателя не пришло, ставим кольцо в центр экрана
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
            self.rebuild()

    def back(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self.page = 0
            self.rebuild()
        else:
            self.close()

    def fallback_center(self) -> bool:
        if self.center is None:
            self.place(self.get_width() / 2, self.get_height() / 2)
        return False

    def place(self, x: float, y: float) -> None:
        w, h = self.get_width(), self.get_height()
        margin = DISC + 8
        if w > 2 * margin:
            x = min(max(x, margin), w - margin)
        if h > 2 * margin:
            y = min(max(y, margin), h - margin)
        self.center = (x, y)
        self.rebuild()

    # ---------------------------------------------------------------- вид
    def rebuild(self) -> None:
        while (child := self.fixed.get_first_child()) is not None:
            self.fixed.remove(child)
        if self.preview is not None and self.preview.get_parent() is not None:
            self.preview.unparent()
        self.bubbles = []
        if self.center is None:
            return
        cx, cy = self.center
        items = self.visible_items
        for i, ((bx, by), item) in enumerate(zip(bubble_positions(len(items), cx, cy), items)):
            button = self.make_bubble(i, item)
            self.fixed.put(button, bx - BUBBLE_W / 2, by - BUBBLE_H / 2)
            self.bubbles.append(button)
        self.fixed.put(self.make_center(), cx - CENTER / 2, cy - CENTER / 2)
        self.hint.set_visible(False)
        self.fixed.put(self.hint, cx - 260, cy + DISC + 6)
        self.hint.set_size_request(520, -1)
        self.fixed.put(self.make_modes(), cx - 230, cy - DISC - 50)
        if not self.items:
            self.show_hint("Для этого файла здесь ничего нет. Попробуйте Shift, Ctrl или Alt")
        self.backdrop.queue_draw()
        if self.bubbles:
            self.bubbles[0].grab_focus()

    def make_modes(self) -> Gtk.Box:
        """Строка над кольцом: какой набор открыт и какой клавишей переключить."""
        bar = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, css_classes=["krug-modes", "krug-pop"])
        bar.set_size_request(460, -1)
        for menu, key, _keys in MODES:
            box = Gtk.Box(spacing=6)
            box.append(Gtk.Label(label=key, css_classes=["keycap"]))
            box.append(Gtk.Label(label=ops.MENU_TITLES[menu]))
            button = Gtk.Button(child=box, css_classes=["krug-mode"])
            if menu == self.menu:
                button.add_css_class("active")
            button.connect("clicked", lambda _b, m=menu: self.switch_menu(m))
            bar.append(button)
        return bar

    def switch_menu(self, menu: str) -> None:
        if menu == self.menu and len(self.stack) == 1:
            return
        self.menu = menu
        self.menu_title = ops.MENU_TITLES[menu]
        self.stack = [ops.build_menu(menu, self.files)]
        self.page = 0
        self.rebuild()

    def make_bubble(self, index: int, item: ops.Item) -> Gtk.Button:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, valign=Gtk.Align.CENTER)
        # у форматов конвертации своей иконки нет: рисуем лист, а формат пишем подписью
        box.append(Gtk.Image.new_from_icon_name(icon_name(item.icon or "krug-file-symbolic")))
        box.append(Gtk.Label(label=item.label, css_classes=["caption"], wrap=True, justify=Gtk.Justification.CENTER,
                             max_width_chars=13, lines=2, ellipsize=Pango.EllipsizeMode.END))
        if item.children:
            box.append(Gtk.Label(label="•••", css_classes=["more"]))
        button = Gtk.Button(child=box, css_classes=["krug-bubble", "krug-pop"])
        button.set_size_request(BUBBLE_W, BUBBLE_H)
        if item.missing:
            button.add_css_class("missing")
            button.set_tooltip_text(item.missing)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda _c: self.show_hint(item.missing))
        button.add_controller(focus)
        hover = Gtk.EventControllerMotion()
        hover.connect("enter", lambda _c, _x, _y: self.show_hint(item.missing))
        hover.connect("leave", lambda _c: self.show_hint(""))
        button.add_controller(hover)
        button.connect("clicked", lambda _b: self.activate_item(index))
        return button

    def make_center(self) -> Gtk.Button:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, valign=Gtk.Align.CENTER,
                      halign=Gtk.Align.CENTER)
        if len(self.stack) > 1:
            image = Gtk.Image.new_from_icon_name("krug-back-symbolic")
            image.set_pixel_size(32)
            box.append(image)
            box.append(Gtk.Label(label="Назад", css_classes=["krug-name"]))
        else:
            if self.preview is None:
                self.preview = file_preview(self.files[0])
            box.append(self.preview)
            name = self.files[0].name if len(self.files) == 1 else f"Файлов: {len(self.files)}"
            box.append(Gtk.Label(label=name, css_classes=["krug-name"], wrap=True, lines=2,
                                 ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=16,
                                 justify=Gtk.Justification.CENTER))
            if self.pages > 1:
                box.append(Gtk.Label(label=f"{self.page + 1} / {self.pages}  ›", css_classes=["krug-page"]))
        box.set_tooltip_text(self.menu_title)
        button = Gtk.Button(child=box, css_classes=["krug-center", "krug-pop"])
        button.set_size_request(CENTER, CENTER)
        button.connect("clicked", lambda _b: self.on_center())
        return button

    def show_hint(self, text: str) -> None:
        self.hint.set_label(text)
        self.hint.set_visible(bool(text))

    def draw_backdrop(self, _area, cr, width: int, height: int) -> None:
        # экран не затемняем: рисуем только диск под кольцом
        if self.center is None:
            return
        cx, cy = self.center
        fill, line = ((0.13, 0.13, 0.15, 0.62), (1, 1, 1, 0.10)) if self.dark else ((1, 1, 1, 0.50), (1, 1, 1, 0.75))
        cr.arc(cx, cy, DISC, 0, 2 * math.pi)
        cr.set_source_rgba(*fill)
        cr.fill()
        # светлый обод по краю
        cr.arc(cx, cy, DISC - 6, 0, 2 * math.pi)
        cr.set_source_rgba(*line)
        cr.set_line_width(10)
        cr.stroke()
        cr.arc(cx, cy, DISC - 0.5, 0, 2 * math.pi)
        cr.set_source_rgba(0, 0, 0, 0.08 if not self.dark else 0.3)
        cr.set_line_width(1)
        cr.stroke()
        # линии между секторами: от середины к ободу
        inner, outer = CENTER / 2 + 6, DISC - 12
        cr.set_source_rgba(*line)
        cr.set_line_width(2)
        for angle in divider_angles(len(self.visible_items)):
            dx, dy = math.sin(angle), -math.cos(angle)
            cr.move_to(cx + inner * dx, cy + inner * dy)
            cr.line_to(cx + outer * dx, cy + outer * dy)
        cr.stroke()
        # мягкое свечение в середине, под файлом
        glow = cairo.RadialGradient(cx, cy, 0, cx, cy, CENTER / 2 + 6)
        glow.add_color_stop_rgba(0, 1, 1, 1, 0.0 if self.dark else 0.35)
        glow.add_color_stop_rgba(1, 1, 1, 1, 0.0)
        cr.arc(cx, cy, CENTER / 2 + 6, 0, 2 * math.pi)
        cr.set_source(glow)
        cr.fill()

    # -------------------------------------------------------------- события
    def on_pointer(self, _controller, x: float, y: float) -> None:
        if self.center is None:
            self.place(x, y)

    def on_empty_click(self, gesture, _n: int, x: float, y: float) -> None:
        if gesture.get_current_button() == Gdk.BUTTON_SECONDARY:
            self.back()
        elif self.center is None:
            self.place(x, y)
        elif math.hypot(x - self.center[0], y - self.center[1]) > DISC:
            self.close()

    def on_center(self) -> None:
        if len(self.stack) > 1:
            self.back()
        elif self.pages > 1:
            self.turn_page(1)
        else:
            self.close()

    def on_key(self, _controller, keyval: int, _keycode: int, _state) -> bool:
        mode = next((m for m, _k, keys in MODES if keyval in keys), None)
        if mode:
            self.switch_menu(mode)
        elif keyval == Gdk.KEY_Escape:
            self.back()
        elif keyval in (Gdk.KEY_Page_Down, Gdk.KEY_Down):
            self.turn_page(1)
        elif keyval in (Gdk.KEY_Page_Up, Gdk.KEY_Up):
            self.turn_page(-1)
        elif keyval in (Gdk.KEY_Right, Gdk.KEY_Left) and self.bubbles:
            focused = next((i for i, b in enumerate(self.bubbles) if b.has_focus()), -1)
            step = 1 if keyval == Gdk.KEY_Right else -1
            self.bubbles[(focused + step) % len(self.bubbles)].grab_focus()
        elif Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and keyval - Gdk.KEY_1 < len(self.bubbles):
            self.activate_item(keyval - Gdk.KEY_1)
        else:
            return False  # Tab, Enter и пробел обрабатывает сама кнопка
        return True

    def activate_item(self, index: int) -> None:
        item = self.visible_items[index]
        if item.children and not item.missing:
            self.stack.append(item.children)
            self.page = 0
            self.rebuild()
            return
        self.app.start(item, self.files)
        self.close()


class MenuApp(Adw.Application):
    def __init__(self, menu: str, files: list[Path]):
        super().__init__(application_id="io.github.krug.Menu", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.menu = menu
        self.files = files

    def do_activate(self) -> None:
        load_css()
        items = ops.build_menu(self.menu, self.files)
        RadialMenu(self, ops.MENU_TITLES[self.menu], items, self.files).present()

    # --------------------------------------------------------- выполнение
    def start(self, item: ops.Item, files: list[Path]) -> None:
        if item.missing:
            notify("Не хватает программы", item.missing, error=True)
        elif item.editor:
            from .editors import open_editor
            open_editor(self, item.editor, files)
        elif item.folder:
            self.hold()  # окно меню закроется, а приложение должно дождаться выбора папки
            dialog = Gtk.FileDialog(title=item.label)
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
        self.release()

    def work(self, item: ops.Item, files: list[Path], folder: Path | None) -> None:
        self.hold()
        state = {"done": False}

        def slow() -> bool:
            if not state["done"]:
                notify(f"{item.label}: обработка…", "Сообщу, когда закончу")
            return False

        def finish(outcome, error) -> None:
            state["done"] = True
            results, errors = outcome if outcome else ([], [str(error)])
            history.add(item.label, results, errors)
            if errors:
                notify(f"{item.label}: ошибка", "\n".join(errors[:4]), error=True)
            elif not item.quiet:
                names = ", ".join(p.name for p in results[:3]) + (" …" if len(results) > 3 else "")
                notify(f"{item.label}: готово", names)
            self.release()

        GLib.timeout_add_seconds(3, slow)
        in_thread(lambda: ops.execute(item, files, folder), finish)


def show(menu: str, files: list[Path]) -> int:
    return MenuApp(menu, files).run([])
