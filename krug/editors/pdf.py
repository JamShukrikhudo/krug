"""Страницы PDF: миниатюры, выбор щелчком в нужном порядке, извлечение, удаление и поворот."""
from __future__ import annotations

import re
from pathlib import Path

from ..ops import HINT_POPPLER, HINT_QPDF
from ..params import parse_pages
from ..ui import Adw, Gtk, in_thread
from ..util import OpError, need, out_path, run
from . import EditorWindow

THUMB_LIMIT = 300


def page_count(src: Path) -> int:
    out = run([need("qpdf", hint=HINT_QPDF), "--show-npages", src]).stdout.decode().strip()
    return int(out or 0)


def page_list(text: str) -> list[int]:
    """Номера страниц из поля ввода; диапазоны «2-5» раскрываются."""
    numbers: list[int] = []
    for part in re.findall(r"\d+(?:-\d+)?", text):
        a, _, b = part.partition("-")
        numbers += list(range(int(a), int(b) + 1)) if b else [int(a)]
    return numbers


class PdfPagesEditor(EditorWindow):
    save_label = "Извлечь в новый PDF"

    def __init__(self, app, files: list[Path]):
        super().__init__(app, files, "Страницы PDF")
        self.total = 0
        self.toggles: list[Gtk.ToggleButton] = []
        self.syncing = False

        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=8,
                                column_spacing=6, row_spacing=6, valign=Gtk.Align.START)
        scroller = Gtk.ScrolledWindow(child=self.flow, hexpand=True, vexpand=True, css_classes=["krug-preview"])
        self.preview.append(Gtk.Label(label="Щёлкайте страницы в нужном порядке. Номер порядка появится под миниатюрой.",
                                      xalign=0, css_classes=["dim-label"]))
        self.preview.append(scroller)

        g = self.group("Выбранные страницы", "Можно вписать вручную: 3,1,2 или 1-4,7")
        self.order = Adw.EntryRow(title="Порядок страниц")
        self.order.connect("changed", lambda _e: self.sync_marks())
        g.add(self.order)
        clear = Gtk.Button(label="Очистить", css_classes=["flat"], valign=Gtk.Align.CENTER)
        clear.connect("clicked", lambda _b: self.order.set_text(""))
        g.set_header_suffix(clear)

        g = self.group("Действия", "Каждое действие создаёт новый PDF рядом с оригиналом")
        for title, subtitle, icon, fn in (
            ("Удалить выбранные", "Новый PDF без этих страниц", "edit-delete-symbolic", self.drop_pages),
            ("Повернуть выбранные вправо", "На 90°, остальные без изменений", "object-rotate-right-symbolic",
             lambda: self.rotate_pages("+90")),
            ("Повернуть выбранные влево", "На 90°", "object-rotate-left-symbolic", lambda: self.rotate_pages("-90")),
        ):
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
            row.connect("activated", lambda _r, fn=fn: fn())
            g.add(row)

        self.load_file()

    # ------------------------------------------------------------- загрузка
    def load_file(self) -> None:
        src = self.current
        self.status.set_label(f"Читаю {src.name}…")

        def work():
            total = page_count(src)
            folder = self.tmp / "thumbs"
            folder.mkdir(exist_ok=True)
            run([need("pdftoppm", hint=HINT_POPPLER), "-png", "-scale-to", "220", "-l", str(min(total, THUMB_LIMIT)),
                 src, folder / "p"])
            thumbs = sorted(folder.glob("p-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
            return total, thumbs

        def done(result, error) -> None:
            if error:
                self.status.set_label(f"{src.name}: {error}")
                return
            self.total, thumbs = result
            for i, thumb in enumerate(thumbs, start=1):
                self.flow.append(self.make_thumb(i, thumb))
            more = f", показаны первые {THUMB_LIMIT}" if self.total > THUMB_LIMIT else ""
            self.status.set_label(f"{src.name} · страниц: {self.total}{more}")

        in_thread(work, done)

    def make_thumb(self, number: int, image: Path) -> Gtk.ToggleButton:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        picture = Gtk.Picture.new_for_filename(str(image))
        picture.set_size_request(120, 160)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        box.append(picture)
        caption = Gtk.Label(label=str(number))
        mark = Gtk.Label(label="", css_classes=["order"])
        line = Gtk.Box(spacing=6, halign=Gtk.Align.CENTER)
        line.append(caption)
        line.append(mark)
        box.append(line)
        toggle = Gtk.ToggleButton(child=box, css_classes=["flat", "krug-thumb"])
        toggle.number, toggle.mark = number, mark
        toggle.connect("toggled", self.on_toggle)
        self.toggles.append(toggle)
        return toggle

    # ------------------------------------------------------------ выбор
    def on_toggle(self, toggle: Gtk.ToggleButton) -> None:
        if self.syncing:
            return
        pages = page_list(self.order.get_text())
        if toggle.get_active():
            pages.append(toggle.number)
        else:
            pages = [p for p in pages if p != toggle.number]
        self.order.set_text(",".join(str(p) for p in pages))

    def sync_marks(self) -> None:
        pages = page_list(self.order.get_text())
        self.syncing = True
        for toggle in self.toggles:
            positions = [str(i + 1) for i, p in enumerate(pages) if p == toggle.number]
            toggle.set_active(bool(positions))
            toggle.mark.set_label(("→ " + ",".join(positions)) if positions else "")
        self.syncing = False

    def selected(self) -> str:
        text = self.order.get_text().strip()
        if not text:
            raise OpError("Сначала выберите страницы")
        return parse_pages(text, self.total)

    # ------------------------------------------------------------ действия
    def qpdf(self, label: str, build) -> None:
        """build(src) возвращает (аргументы qpdf, путь результата); ошибки выбора показываются сразу."""
        src = self.current
        try:
            args, dst = build(src)
        except OpError as e:
            self.toast(str(e))
            return

        def job() -> list[Path]:
            run([need("qpdf", hint=HINT_QPDF), *args])
            return [dst]
        self.run_job(label, job)

    def save(self) -> None:
        def build(src: Path):
            dst = out_path(src, "pdf", "-pages")
            return ["--empty", "--pages", src, self.selected(), "--", dst], dst
        self.qpdf("Извлечь страницы", build)

    def drop_pages(self) -> None:
        def build(src: Path):
            remove = set(page_list(self.selected()))
            keep = [str(n) for n in range(1, self.total + 1) if n not in remove]
            if not keep:
                raise OpError("Нельзя удалить все страницы")
            dst = out_path(src, "pdf", "-trimmed")
            return ["--empty", "--pages", src, ",".join(keep), "--", dst], dst
        self.qpdf("Удалить страницы", build)

    def rotate_pages(self, angle: str) -> None:
        def build(src: Path):
            dst = out_path(src, "pdf", "-rotated")
            return [src, dst, f"--rotate={angle}:{self.selected()}"], dst
        self.qpdf("Повернуть страницы", build)
