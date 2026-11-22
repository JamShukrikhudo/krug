"""Редактор фото: обрезка мышью, поворот, размер, яркость/контраст/насыщенность, рамка, формат."""
from __future__ import annotations

from pathlib import Path

from ..ops import HINT_IM
from ..params import ImageParams, image_args
from ..ui import CropOverlay, GLib, Gtk, combo_row, in_thread, scale_row, spin_row, switch_row
from ..util import need, out_path, run
from . import EditorWindow

PREVIEW_MAX = 1400
FORMATS = {"Как в оригинале": "", "JPEG": "jpg", "PNG": "png", "WebP": "webp", "AVIF": "avif", "TIFF": "tiff"}
KEEP_EXT = {"jpg", "jpeg", "png", "webp", "avif", "tif", "tiff", "bmp", "gif"}


def magick() -> str:
    return need("magick", "convert", hint=HINT_IM)


def oriented_size(src: Path) -> tuple[int, int]:
    out = run([magick(), f"{src}[0]", "-auto-orient", "-format", "%w %h", "info:"]).stdout.decode().split()
    return int(out[0]), int(out[1])


class ImageEditor(EditorWindow):
    def __init__(self, app, files: list[Path]):
        super().__init__(app, files, "Редактор фото")
        self.p = ImageParams()
        self.src_w = self.src_h = 0
        self.base: Path | None = None
        self.result: Path | None = None
        self.generation = 0
        self.render_pending = False
        self.syncing = False

        # --- предпросмотр
        bar = Gtk.Box(spacing=6)
        self.crop_toggle = Gtk.ToggleButton(child=self._icon_label("krug-select-symbolic", "Выделить область"))
        self.crop_toggle.connect("toggled", lambda _b: self.refresh_view())
        reset_crop = Gtk.Button(child=self._icon_label("krug-clear-symbolic", "Сбросить область"))
        reset_crop.connect("clicked", lambda _b: self.on_crop(None))
        self.original_toggle = Gtk.ToggleButton(child=self._icon_label("krug-compare-symbolic", "Оригинал"))
        self.original_toggle.connect("toggled", lambda _b: self.refresh_view())
        for widget in (self.crop_toggle, reset_crop):
            bar.append(widget)
        bar.append(Gtk.Box(hexpand=True))
        bar.append(self.original_toggle)
        self.preview.append(bar)

        stage = Gtk.Overlay(css_classes=["krug-preview"], hexpand=True, vexpand=True)
        self.picture = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True, hexpand=True, vexpand=True)
        stage.set_child(self.picture)
        self.cropper = CropOverlay(self.on_crop)
        stage.add_overlay(self.cropper)
        self.preview.append(stage)

        # --- настройки
        g = self.group("Поворот")
        row = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        for icon, tip, fn in (("krug-rotate-left-symbolic", "Влево на 90°", lambda: self.rotate(-90)),
                              ("krug-rotate-right-symbolic", "Вправо на 90°", lambda: self.rotate(90)),
                              ("krug-flip-symbolic", "Зеркально", self.flip)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, css_classes=["circular", "flat"])
            b.connect("clicked", lambda _b, fn=fn: fn())
            row.append(b)
        g.add(row)

        g = self.group("Размер")
        self.resize = switch_row("Изменить размер")
        self.width = spin_row("Ширина, px", 1, 16000, 1)
        self.keep = switch_row("Сохранять пропорции", True)
        self.height = spin_row("Высота, px", 1, 16000, 1)
        for w in (self.resize, self.width, self.keep, self.height):
            g.add(w)
        self.resize.connect("notify::active", lambda *_: self.on_size())
        self.keep.connect("notify::active", lambda *_: self.on_size())
        self.width.connect("notify::value", lambda *_: self.on_width())
        self.height.connect("notify::value", lambda *_: self.on_size())

        g = self.group("Коррекция")
        self.bright = scale_row("Яркость", -100, 100, 0, lambda v: self.set_param("brightness", int(v)))
        self.contrast = scale_row("Контраст", -100, 100, 0, lambda v: self.set_param("contrast", int(v)))
        self.sat = scale_row("Насыщенность", 0, 200, 100, lambda v: self.set_param("saturation", int(v)))
        for w in (self.bright, self.contrast, self.sat):
            g.add(w)
        reset = Gtk.Button(label="Сбросить", css_classes=["flat"], valign=Gtk.Align.CENTER)
        reset.connect("clicked", lambda _b: self.reset_colors())
        g.set_header_suffix(reset)

        g = self.group("Рамка")
        self.border = spin_row("Белая рамка, px", 0, 2000, 0, step=5, subtitle="С каждой стороны")
        self.border.connect("notify::value", lambda r, _p: self.set_param("border", int(r.get_value())))
        g.add(self.border)

        g = self.group("Сохранение", "Оригинал не меняется: копия появится рядом с ним")
        self.fmt = combo_row("Формат", list(FORMATS))
        self.fmt.connect("notify::selected", lambda *_: self.on_format())
        self.quality = spin_row("Качество", 10, 100, 90, step=5, subtitle="Для JPEG, WebP и AVIF")
        self.quality.connect("notify::value", lambda r, _p: setattr(self.p, "quality", int(r.get_value())))
        g.add(self.fmt)
        g.add(self.quality)

        self.on_size()
        self.load_file()

    @staticmethod
    def _icon_label(icon: str, text: str) -> Gtk.Widget:
        box = Gtk.Box(spacing=6)
        box.append(Gtk.Image.new_from_icon_name(icon))
        box.append(Gtk.Label(label=text))
        return box

    # ------------------------------------------------------------- загрузка
    def load_file(self) -> None:
        src = self.current
        self.status.set_label(f"Открываю {src.name}…")
        base = self.tmp / f"base-{self.index}.png"
        first = self.src_w == 0

        def work():
            if not base.exists():
                run([magick(), f"{src}[0]", "-auto-orient", "-resize", f"{PREVIEW_MAX}x{PREVIEW_MAX}>", "-strip", base])
            return oriented_size(src)

        def done(size, error) -> None:
            if error:
                self.status.set_label(f"Не удалось открыть {src.name}: {error}")
                return
            self.src_w, self.src_h = size
            self.base = base
            self.cropper.set_media_size(*size)
            self.status.set_label(f"{src.name} · {self.src_w}×{self.src_h}")
            if first:
                self.syncing = True
                self.width.set_value(self.src_w)
                self.height.set_value(self.src_h)
                self.syncing = False
            self.result = None
            self.schedule_render()
            self.refresh_view()

        in_thread(work, done)

    # ------------------------------------------------------------ параметры
    def set_param(self, name: str, value) -> None:
        setattr(self.p, name, value)
        self.schedule_render()

    def rotate(self, angle: int) -> None:
        self.set_param("rotate", (self.p.rotate + angle) % 360)

    def flip(self) -> None:
        self.set_param("flip", not self.p.flip)

    def on_crop(self, crop) -> None:
        self.cropper.set_crop(crop)
        self.set_param("crop", crop)

    def reset_colors(self) -> None:
        self.bright.scale.set_value(0)
        self.contrast.scale.set_value(0)
        self.sat.scale.set_value(100)

    def on_width(self) -> None:
        if self.keep.get_active() and self.src_w and not self.syncing:
            self.syncing = True
            self.height.set_value(round(self.width.get_value() * self.src_h / self.src_w))
            self.syncing = False
        self.on_size()

    def on_size(self) -> None:
        on = self.resize.get_active()
        self.width.set_sensitive(on)
        self.keep.set_sensitive(on)
        self.height.set_sensitive(on and not self.keep.get_active())
        if self.syncing:
            return
        self.p.width = int(self.width.get_value()) if on else 0
        self.p.height = int(self.height.get_value()) if on and not self.keep.get_active() else 0
        self.p.keep_ratio = self.keep.get_active()
        self.schedule_render()

    def on_format(self) -> None:
        self.p.fmt = list(FORMATS.values())[self.fmt.get_selected()]

    # -------------------------------------------------------- предпросмотр
    def schedule_render(self) -> None:
        if not self.render_pending:
            self.render_pending = True
            GLib.timeout_add(140, self.render)

    def render(self) -> bool:
        self.render_pending = False
        if self.base is None or not self.src_w:
            return False
        self.generation += 1
        gen = self.generation
        scale = min(1.0, PREVIEW_MAX / max(self.src_w, self.src_h))
        out = self.tmp / f"preview-{gen}.png"
        args = image_args(self.p, self.src_w, self.src_h, scale)
        base = self.base

        def work():
            run([magick(), base, *args, out])
            return out

        def done(path, error) -> None:
            if gen != self.generation:
                return
            if error:
                self.status.set_label(f"Предпросмотр: {error}")
                return
            previous, self.result = self.result, path
            self.refresh_view()
            if previous and previous != path:
                previous.unlink(missing_ok=True)

        in_thread(work, done)
        return False

    def refresh_view(self) -> None:
        cropping = self.crop_toggle.get_active()
        self.cropper.set_active(cropping)
        self.cropper.set_visible(cropping)
        show_base = cropping or self.original_toggle.get_active() or self.result is None
        path = self.base if show_base else self.result
        if path is not None:
            self.picture.set_filename(str(path))

    # ------------------------------------------------------------ сохранение
    def save_one(self, src: Path) -> Path:
        ext = self.p.fmt or (src.suffix.lower().lstrip(".") if src.suffix.lower().lstrip(".") in KEEP_EXT else "jpg")
        w, h = oriented_size(src)
        dst = out_path(src, ext, "-edited")
        cmd = [magick(), f"{src}[0]", "-auto-orient", *image_args(self.p, w, h)]
        if ext in ("jpg", "jpeg", "bmp"):
            cmd += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
        if ext in ("jpg", "jpeg", "webp", "avif"):
            cmd += ["-quality", str(self.p.quality)]
        run(cmd + [dst])
        return dst
