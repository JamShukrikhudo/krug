"""Общее для всех окон: GTK4 + libadwaita, стили, мелкие виджеты и фоновые задачи."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Pango", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango  # noqa: E402

from .params import drag_to_crop, fit_rect  # noqa: E402

CSS = """
window.krug-menu { background: transparent; }

button.krug-bubble {
  min-width: 100px; min-height: 78px; padding: 6px 8px;
  border-radius: 24px;
  background-color: alpha(#1f1f25, 0.94);
  color: #ffffff;
  border: 1px solid alpha(#ffffff, 0.08);
  box-shadow: 0 8px 22px alpha(#000000, 0.35);
  transition: background-color 120ms ease-out, transform 120ms ease-out, box-shadow 120ms ease-out;
}
button.krug-bubble:hover, button.krug-bubble:focus-visible {
  background-color: @accent_bg_color;
  color: @accent_fg_color;
  transform: scale(1.08);
  box-shadow: 0 10px 28px alpha(#000000, 0.45);
}
button.krug-bubble.missing { color: alpha(#ffffff, 0.45); }
button.krug-bubble.missing:hover { background-color: alpha(#3a3a42, 0.96); color: #ffffff; }
button.krug-bubble .format { font-size: 17pt; font-weight: 800; letter-spacing: 0.5px; }
button.krug-bubble .caption { font-size: 9.5pt; font-weight: 600; }
button.krug-bubble image { -gtk-icon-size: 26px; color: inherit; -gtk-icon-style: symbolic; }
image { -gtk-icon-style: symbolic; }

button.krug-center {
  min-width: 132px; min-height: 132px; padding: 8px;
  border-radius: 999px;
  background-color: alpha(#121216, 0.97);
  color: #ffffff;
  border: 1px solid alpha(#ffffff, 0.10);
  box-shadow: 0 10px 30px alpha(#000000, 0.45);
}
button.krug-center:hover { background-color: alpha(#26262e, 0.98); }
button.krug-center .title { font-size: 12pt; font-weight: 800; }
button.krug-center .file { font-size: 9pt; color: alpha(#ffffff, 0.7); }
.krug-hint {
  padding: 6px 14px; border-radius: 999px;
  background-color: alpha(#121216, 0.92); color: #ffffff; font-weight: 600;
}

.krug-pop { animation: krug-pop 170ms ease-out; }
@keyframes krug-pop {
  from { opacity: 0; transform: scale(0.55); }
  to { opacity: 1; transform: scale(1); }
}

.krug-preview { background-color: alpha(@view_fg_color, 0.06); border-radius: 12px; }
.krug-thumb { padding: 6px; border-radius: 10px; }
.krug-thumb:checked { background-color: alpha(@accent_bg_color, 0.25); }
.krug-thumb .order { font-weight: 800; color: @accent_color; }
.keycap {
  padding: 2px 8px; border-radius: 6px; font-weight: 700;
  background-color: alpha(@view_fg_color, 0.08);
  border: 1px solid alpha(@view_fg_color, 0.15);
}
"""

_css_loaded = False
ICONS_DIR = Path(__file__).resolve().parent / "icons"


def load_css() -> None:
    global _css_loaded
    if _css_loaded:
        return
    provider = Gtk.CssProvider()
    try:
        provider.load_from_string(CSS)
    except AttributeError:  # GTK до 4.12
        provider.load_from_data(CSS.encode())
    display = Gdk.Display.get_default()
    Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    # свои иконки: одинаковый вид при любой теме, в том числе в новых Adwaita без старых имён
    theme = Gtk.IconTheme.get_for_display(display)
    # файлы прямо в папке поиска GTK находит без index.theme («иконки вне темы»)
    for sub in ("actions", "apps"):
        theme.add_search_path(str(ICONS_DIR / "hicolor" / "scalable" / sub))
    _css_loaded = True


def icon_name(name: str, fallback: str = "krug-tools-symbolic") -> str:
    """Иконка из темы; если такой нет, берётся запасная, чтобы не было пустого квадрата."""
    if not name:
        return ""
    theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
    return name if theme.has_icon(name) else fallback


def in_thread(work: Callable[[], object], done: Callable[[object, Exception | None], None]) -> None:
    """Выполняет work() в фоне, затем done(result, error) в главном потоке."""
    def runner() -> None:
        try:
            result, error = work(), None
        except Exception as e:  # noqa: BLE001 — показываем пользователю любую ошибку
            result, error = None, e
        GLib.idle_add(lambda: done(result, error) and False)
    threading.Thread(target=runner, daemon=True).start()


def show_in_files(path: Path, parent: Gtk.Window | None = None) -> None:
    launcher = Gtk.FileLauncher.new(Gio.File.new_for_path(str(path)))
    launcher.open_containing_folder(parent, None, None, None)


# --------------------------------------------------------------- строки настроек

def spin_row(title: str, lo: float, hi: float, value: float, step: float = 1, digits: int = 0,
             subtitle: str = "") -> Adw.SpinRow:
    row = Adw.SpinRow.new_with_range(lo, hi, step)
    row.set_title(title)
    if subtitle:
        row.set_subtitle(subtitle)
    row.set_digits(digits)
    row.set_value(value)
    return row


def switch_row(title: str, active: bool = False, subtitle: str = "") -> Adw.SwitchRow:
    row = Adw.SwitchRow(title=title, active=active)
    if subtitle:
        row.set_subtitle(subtitle)
    return row


def combo_row(title: str, options: list[str], selected: int = 0) -> Adw.ComboRow:
    row = Adw.ComboRow(title=title, model=Gtk.StringList.new(options))
    row.set_selected(selected)
    return row


def scale_row(title: str, lo: float, hi: float, value: float, on_change: Callable[[float], None]) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, 1)
    scale.set_value(value)
    scale.set_hexpand(True)
    scale.set_size_request(170, -1)
    scale.set_draw_value(True)
    scale.set_value_pos(Gtk.PositionType.RIGHT)
    scale.set_digits(0)
    scale.add_mark(value, Gtk.PositionType.BOTTOM, None)
    scale.connect("value-changed", lambda s: on_change(s.get_value()))
    row.add_suffix(scale)
    row.scale = scale  # чтобы можно было сбросить значение
    return row


def button_row(title: str, icon: str, on_click: Callable[[], None], subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, activatable=True)
    if subtitle:
        row.set_subtitle(subtitle)
    row.add_suffix(Gtk.Image.new_from_icon_name(icon_name(icon)))
    row.connect("activated", lambda _r: on_click())
    return row


# ------------------------------------------------------------ выделение мышью

class CropOverlay(Gtk.DrawingArea):
    """Прозрачный слой над картинкой или видео: протяните мышью, чтобы выделить область.

    Область хранится в долях исходного кадра (0…1), поэтому одинаково применяется к файлам
    разного размера. Картинка под слоем должна быть вписана с сохранением пропорций.
    """

    def __init__(self, on_change: Callable[[tuple[float, float, float, float] | None], None]):
        super().__init__()
        self.on_change = on_change
        self.media_w = 0.0
        self.media_h = 0.0
        self.crop: tuple[float, float, float, float] | None = None
        self.dragging: tuple[float, float, float, float] | None = None
        self.set_draw_func(self._draw)
        self.set_hexpand(True)
        self.set_vexpand(True)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.add_controller(drag)
        self.set_cursor(Gdk.Cursor.new_from_name("crosshair", None))
        self.set_active(False)

    def set_media_size(self, w: float, h: float) -> None:
        self.media_w, self.media_h = float(w), float(h)
        self.queue_draw()

    def set_active(self, active: bool) -> None:
        self.set_can_target(active)
        self.set_visible(active or self.crop is not None)
        self.active = active
        self.queue_draw()

    def set_crop(self, crop: tuple[float, float, float, float] | None) -> None:
        self.crop = crop
        self.set_visible(self.active or crop is not None)
        self.queue_draw()

    def _rect(self) -> tuple[float, float, float, float]:
        return fit_rect(self.get_width(), self.get_height(), self.media_w, self.media_h)

    def _begin(self, _g, x: float, y: float) -> None:
        self.dragging = (x, y, x, y)

    def _update(self, _g, dx: float, dy: float) -> None:
        if self.dragging:
            x0, y0, _x, _y = self.dragging
            self.dragging = (x0, y0, x0 + dx, y0 + dy)
            self.queue_draw()

    def _end(self, _g, dx: float, dy: float) -> None:
        if not self.dragging:
            return
        x0, y0, _x, _y = self.dragging
        self.dragging = None
        crop = drag_to_crop(self._rect(), x0, y0, x0 + dx, y0 + dy)
        if crop:
            self.crop = crop
            self.on_change(crop)
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        rx, ry, rw, rh = self._rect()
        if rw <= 0:
            return
        if self.dragging:
            x0, y0, x1, y1 = self.dragging
            sel = drag_to_crop((rx, ry, rw, rh), x0, y0, x1, y1) or (0, 0, 0, 0)
        else:
            sel = self.crop
        if not sel:
            if self.active:
                cr.set_source_rgba(1, 1, 1, 0.85)
                cr.set_line_width(1.5)
                cr.set_dash([6, 4])
                cr.rectangle(rx + 0.5, ry + 0.5, rw - 1, rh - 1)
                cr.stroke()
            return
        sx, sy = rx + sel[0] * rw, ry + sel[1] * rh
        sw, sh = sel[2] * rw, sel[3] * rh
        # затемняем всё вне выделения
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.rectangle(rx, ry, rw, rh)
        cr.rectangle(sx, sy, sw, sh)
        cr.set_fill_rule(1)  # EVEN_ODD
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.95)
        cr.set_line_width(2)
        cr.rectangle(sx, sy, sw, sh)
        cr.stroke()
        # сетка третей
        cr.set_source_rgba(1, 1, 1, 0.35)
        cr.set_line_width(1)
        for k in (1, 2):
            cr.move_to(sx + sw * k / 3, sy)
            cr.line_to(sx + sw * k / 3, sy + sh)
            cr.move_to(sx, sy + sh * k / 3)
            cr.line_to(sx + sw, sy + sh * k / 3)
        cr.stroke()


def file_switcher(files: list[Path], on_select: Callable[[int], None]) -> Gtk.Widget:
    """Заголовок окна: имя файла или выпадающий список, если файлов несколько."""
    if len(files) == 1:
        return Adw.WindowTitle(title=files[0].name, subtitle=str(files[0].parent))
    dropdown = Gtk.DropDown.new_from_strings([f.name for f in files])
    dropdown.connect("notify::selected", lambda d, _p: on_select(d.get_selected()))
    return dropdown
