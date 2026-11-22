"""Главное окно krug: как пользоваться, журнал операций, компоненты и настройки."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from . import __version__, history, hotkeys
from .ui import Adw, Gdk, Gio, GLib, Gtk, button_row, icon_name, load_css, show_in_files, switch_row
from .util import which

MENUS = (
    ("convert", "Конвертация", "Ctrl+Alt+1", "Изменить формат файла", "emblem-synchronizing-symbolic"),
    ("tools", "Инструменты", "Ctrl+Alt+2", "Сжать, обрезать или отредактировать", "applications-utilities-symbolic"),
    ("actions", "Действия", "Ctrl+Alt+3", "Скопировать, переместить, удалить фон", "folder-symbolic"),
)
COMPONENTS = (
    (("magick", "convert"), "ImageMagick", "Изображения и редактор фото", "imagemagick"),
    (("ffmpeg",), "FFmpeg", "Аудио, видео и их редактор", "ffmpeg"),
    (("soffice", "libreoffice"), "LibreOffice", "Документы, таблицы, презентации",
     "libreoffice-writer libreoffice-calc libreoffice-impress"),
    (("pdftoppm",), "Poppler", "PDF в текст и картинки, миниатюры страниц", "poppler-utils"),
    (("qpdf",), "qpdf", "Объединение, разделение и страницы PDF", "qpdf"),
    (("gs",), "Ghostscript", "Сжатие PDF", "ghostscript"),
    (("img2pdf",), "img2pdf", "Изображения в PDF без потери качества", "img2pdf"),
    (("wl-copy",), "wl-clipboard", "Копирование путей и файлов в буфер", "wl-clipboard"),
    (("kdeconnect-cli",), "KDE Connect", "Отправка файлов на телефон", "kdeconnect"),
)


def launch_menu(menu: str, files: list[Path]) -> None:
    subprocess.Popen([sys.executable, "-m", "krug", menu, *map(str, files)], start_new_session=True,
                     env=None, cwd=str(Path(__file__).resolve().parent.parent))


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, title="krug", default_width=760, default_height=720)
        self.groups: dict[Adw.PreferencesPage, list[Adw.PreferencesGroup]] = {}
        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(self.page_start(), "start", "Начало", "go-home-symbolic")
        self.history_page = Adw.PreferencesPage()
        self.stack.add_titled_with_icon(self.history_page, "history", "Журнал", "document-open-recent-symbolic")
        self.components_page = Adw.PreferencesPage()
        self.stack.add_titled_with_icon(self.components_page, "components", "Компоненты",
                                        "application-x-addon-symbolic")
        self.stack.connect("notify::visible-child-name", lambda *_: self.refresh())

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE))
        view = Adw.ToolbarView(content=self.stack)
        view.add_top_bar(header)
        self.toasts = Adw.ToastOverlay(child=view)
        self.set_content(self.toasts)
        self.refresh()

    # ---------------------------------------------------------------- начало
    def page_start(self) -> Gtk.Widget:
        page = Adw.PreferencesPage()
        intro = Adw.PreferencesGroup()
        status = Adw.StatusPage(icon_name="io.github.krug", title="krug всегда под рукой",
                                description="Выделите файл в «Файлах» и нажмите сочетание клавиш — "
                                            "возле указателя появится круглое меню. Всё выполняется локально, "
                                            "оригиналы не меняются, результат появится рядом.")
        status.add_css_class("compact")
        intro.add(status)
        page.add(intro)

        g = Adw.PreferencesGroup(title="Три меню", description="Или правый клик по файлу → krug")
        for menu, title, keys, subtitle, icon in MENUS:
            row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
            row.add_prefix(Gtk.Image.new_from_icon_name(icon_name(icon)))
            row.add_suffix(Gtk.Label(label=keys, css_classes=["keycap"], valign=Gtk.Align.CENTER))
            row.set_tooltip_text("Выбрать файлы и открыть это меню")
            row.connect("activated", lambda _r, m=menu: self.pick_files(m))
            g.add(row)
        page.add(g)

        g = Adw.PreferencesGroup(title="Управление кольцом")
        for title, subtitle in (
            ("Щелчок по кнопке", "Запускает действие; кнопка с точками открывает список"),
            ("Середина кольца", "Назад или следующая страница"),
            ("Esc, правая кнопка, щелчок мимо", "Закрыть меню"),
            ("Клавиши 1–8, ←/→, Enter", "Выбор с клавиатуры"),
        ):
            g.add(Adw.ActionRow(title=title, subtitle=subtitle))
        page.add(g)

        g = Adw.PreferencesGroup(title="Настройки")
        self.keys_switch = switch_row("Сочетания Ctrl+Alt+1/2/3", self.hotkeys_on(),
                                      "Работают в GNOME для файлов, выделенных в «Файлах»")
        self.keys_switch.connect("notify::active", self.on_hotkeys)
        g.add(self.keys_switch)
        page.add(g)

        about = Gtk.Label(label=f"krug {__version__} · открытый код, лицензия MIT", css_classes=["dim-label"],
                          margin_bottom=12)
        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        page.set_vexpand(True)
        page_box.append(page)
        page_box.append(about)
        return page_box

    def pick_files(self, menu: str) -> None:
        dialog = Gtk.FileDialog(title="Выберите файлы")

        def done(d, result) -> None:
            try:
                files = d.open_multiple_finish(result)
            except Exception:  # noqa: BLE001 — окно выбора закрыто
                return
            paths = [Path(files.get_item(i).get_path()) for i in range(files.get_n_items())]
            if paths:
                launch_menu(menu, paths)
        dialog.open_multiple(self, None, done)

    @staticmethod
    def hotkeys_on() -> bool:
        try:
            return hotkeys.installed()
        except Exception:  # noqa: BLE001 — не GNOME
            return False

    def on_hotkeys(self, row, _param) -> None:
        try:
            hotkeys.install() if row.get_active() else hotkeys.remove()
            self.toast("Сочетания включены" if row.get_active() else "Сочетания выключены")
        except Exception as e:  # noqa: BLE001
            self.toast(f"Не удалось изменить сочетания: {e}")

    # ---------------------------------------------------------------- журнал
    def refresh(self) -> None:
        name = self.stack.get_visible_child_name()
        if name == "history":
            self.fill_history()
        elif name == "components":
            self.fill_components()

    def clear_page(self, page: Adw.PreferencesPage) -> None:
        for group in self.groups.pop(page, []):
            page.remove(group)

    def add_group(self, page: Adw.PreferencesPage, group: Adw.PreferencesGroup) -> None:
        page.add(group)
        self.groups.setdefault(page, []).append(group)

    def fill_history(self) -> None:
        self.clear_page(self.history_page)
        entries = history.load()
        g = Adw.PreferencesGroup(title="Последние операции")
        if entries:
            clear = Gtk.Button(label="Очистить", css_classes=["flat"], valign=Gtk.Align.CENTER)
            clear.connect("clicked", lambda _b: (history.clear(), self.fill_history()))
            g.set_header_suffix(clear)
        else:
            g.set_description("Здесь появятся созданные файлы")
        for e in entries:
            when = time.strftime("%d.%m %H:%M", time.localtime(e.get("time", 0)))
            results = [Path(p) for p in e.get("results", [])]
            if e.get("error"):
                subtitle = "Ошибка: " + e["error"]
            else:
                subtitle = ", ".join(p.name for p in results[:3]) + (" …" if len(results) > 3 else "")
            row = Adw.ActionRow(title=f"{e.get('label', '')} · {when}", subtitle=subtitle, subtitle_lines=2)
            row.add_prefix(Gtk.Image.new_from_icon_name(
                "dialog-error-symbolic" if e.get("error") else "emblem-ok-symbolic"))
            existing = [p for p in results if p.exists()]
            if existing:
                show = Gtk.Button(icon_name="folder-open-symbolic", tooltip_text="Показать в «Файлах»",
                                  valign=Gtk.Align.CENTER, css_classes=["flat"])
                show.connect("clicked", lambda _b, p=existing[0]: show_in_files(p, self))
                row.add_suffix(show)
            g.add(row)
        self.add_group(self.history_page, g)

    # ------------------------------------------------------------ компоненты
    def fill_components(self) -> None:
        self.clear_page(self.components_page)
        missing = []
        g = Adw.PreferencesGroup(title="Внешние программы",
                                 description="krug вызывает их для обработки. Без программы её пункты меню серые.")
        for names, title, what, package in COMPONENTS:
            found = which(*names)
            row = Adw.ActionRow(title=title, subtitle=what if found else f"{what} · не установлено")
            row.add_prefix(Gtk.Image.new_from_icon_name("emblem-ok-symbolic" if found else "dialog-warning-symbolic"))
            if not found:
                missing.append(package)
            g.add(row)
        self.add_group(self.components_page, g)

        g = Adw.PreferencesGroup(title="Удаление фона")
        rembg = which("rembg")
        g.add(Adw.ActionRow(title="rembg", subtitle="Установлено" if rembg else
                            'Не установлено: pipx install "rembg[cpu,cli]"'))
        self.add_group(self.components_page, g)

        if missing:
            command = "sudo apt install " + " ".join(missing)
            g = Adw.PreferencesGroup(title="Установить недостающее", description="Скопируйте и выполните в терминале")
            row = Adw.ActionRow(title=command, title_selectable=True)
            row.set_title_lines(3)
            copy = Gtk.Button(icon_name="edit-copy-symbolic", tooltip_text="Копировать", valign=Gtk.Align.CENTER,
                              css_classes=["flat"])
            copy.connect("clicked", lambda _b: self.copy_text(command))
            row.add_suffix(copy)
            g.add(row)
            g.add(button_row("Проверить снова", "view-refresh-symbolic", self.fill_components))
            self.add_group(self.components_page, g)

    def copy_text(self, text: str) -> None:
        provider = Gdk.ContentProvider.new_for_bytes("text/plain;charset=utf-8", GLib.Bytes.new(text.encode()))
        self.get_clipboard().set_content(provider)
        self.toast("Команда скопирована")

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text))


class KrugApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.krug", flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self) -> None:
        load_css()
        window = self.get_active_window() or MainWindow(self)
        window.present()


def run_app() -> int:
    return KrugApp().run([])


def run_editor(kind: str, files: list[Path]) -> int:
    from .editors import open_editor

    class EditorApp(Adw.Application):
        def __init__(self):
            super().__init__(application_id="io.github.krug.Editor", flags=Gio.ApplicationFlags.NON_UNIQUE)

        def do_activate(self) -> None:
            load_css()
            open_editor(self, kind, files)

    return EditorApp().run([])

