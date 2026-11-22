"""Окна редакторов с предпросмотром. Сохранение всегда создаёт копию рядом с оригиналом."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from .. import history
from ..ui import Adw, Gtk, Pango, file_switcher, in_thread, load_css, show_in_files
from ..util import OpError, need, run
from ..ops import HINT_FF


class EditorWindow(Adw.ApplicationWindow):
    """Каркас: заголовок с выбором файла, предпросмотр слева, настройки справа, кнопка снизу."""

    save_label = "Сохранить копию"

    def __init__(self, app: Adw.Application, files: list[Path], title: str):
        super().__init__(application=app, title=title, default_width=1180, default_height=760)
        load_css()
        self.files = files
        self.index = 0
        self.tmp = Path(tempfile.mkdtemp(prefix="krug-edit-"))
        self.connect("close-request", self._cleanup)

        header = Adw.HeaderBar()
        header.set_title_widget(file_switcher(files, self._select))
        self.header = header

        self.preview = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True, vexpand=True)
        self.settings = Adw.PreferencesPage()
        self.settings.set_size_request(390, -1)
        body = Gtk.Box(spacing=6, margin_start=12, margin_end=0, margin_top=6, margin_bottom=6)
        body.append(self.preview)
        body.append(self.settings)

        self.status = Gtk.Label(xalign=0, hexpand=True, css_classes=["dim-label"], ellipsize=Pango.EllipsizeMode.END)
        self.save_button = Gtk.Button(label=self.save_label, css_classes=["suggested-action", "pill"])
        self.save_button.connect("clicked", lambda _b: self.save())
        bottom = Gtk.Box(spacing=12, margin_start=16, margin_end=16, margin_top=8, margin_bottom=10)
        bottom.append(self.status)
        bottom.append(self.save_button)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(body)
        view.add_bottom_bar(bottom)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)

    # ----------------------------------------------------------- для потомков
    @property
    def current(self) -> Path:
        return self.files[self.index]

    def group(self, title: str, description: str = "") -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=title)
        if description:
            group.set_description(description)
        self.settings.add(group)
        return group

    def load_file(self) -> None:
        """Показать self.current в предпросмотре."""

    def save_one(self, src: Path) -> Path:
        """Сохранить копию одного файла с текущими настройками и вернуть её путь."""
        raise NotImplementedError

    def _select(self, index: int) -> None:
        if 0 <= index < len(self.files) and index != self.index:
            self.index = index
            self.load_file()

    def _cleanup(self, _window) -> bool:
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    # ------------------------------------------------------------ сохранение
    def toast(self, text: str, path: Path | None = None) -> None:
        toast = Adw.Toast(title=text, timeout=6)
        if path is not None:
            toast.set_button_label("Показать")
            toast.connect("button-clicked", lambda _t: show_in_files(path, self))
        self.toasts.add_toast(toast)

    def run_job(self, label: str, job: Callable[[], list[Path]], button: Gtk.Button | None = None) -> None:
        button = button or self.save_button
        old = button.get_label()
        button.set_sensitive(False)
        button.set_label("Обработка…")
        self.status.set_label("Обработка… окно можно не закрывать")

        def work():
            results, errors = [], []
            try:
                results = job()
            except OpError as e:
                errors.append(str(e))
            return results, errors

        def done(outcome, error) -> None:
            results, errors = outcome if outcome else ([], [str(error)])
            button.set_sensitive(True)
            button.set_label(old)
            history.add(label, results, errors)
            if errors:
                self.status.set_label("")
                self.toast("Ошибка: " + "; ".join(errors)[:200])
            else:
                self.status.set_label("Сохранено: " + ", ".join(p.name for p in results[:3]))
                self.toast(f"Готово: {results[0].name}" if len(results) == 1 else f"Готово, файлов: {len(results)}",
                           results[0] if results else None)

        in_thread(work, done)

    def prepare(self) -> None:
        """Прочитать настройки из виджетов. Вызывается в главном потоке перед сохранением."""

    def save(self) -> None:
        self.prepare()

        def job() -> list[Path]:
            results, errors = [], []
            for src in self.files:
                try:
                    results.append(self.save_one(src))
                except OpError as e:
                    errors.append(f"{src.name}: {e}")
            if errors:
                raise OpError("; ".join(errors))
            return results
        self.run_job(self.get_title(), job)


def probe(path: Path) -> tuple[float, int, int]:
    """Длительность в секундах и размер первого видеопотока (0, если его нет)."""
    out = run([need("ffprobe", hint=HINT_FF), "-v", "error", "-show_entries", "format=duration:stream=width,height",
               "-select_streams", "v:0", "-of", "json", path]).stdout
    data = json.loads(out or b"{}")
    try:
        duration = float(data.get("format", {}).get("duration") or 0)
    except ValueError:
        duration = 0.0
    streams = data.get("streams") or [{}]
    return duration, int(streams[0].get("width") or 0), int(streams[0].get("height") or 0)


def open_editor(app: Adw.Application, kind: str, files: list[Path]) -> EditorWindow:
    if kind == "image":
        from .image import ImageEditor
        window = ImageEditor(app, files)
    elif kind in ("video", "audio"):
        from .media import MediaEditor
        window = MediaEditor(app, files, video=(kind == "video"))
    elif kind == "pdf":
        from .pdf import PdfPagesEditor
        window = PdfPagesEditor(app, files[:1])
    else:
        raise ValueError(kind)
    window.present()
    return window
