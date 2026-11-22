"""Расширение «Файлов» (Nautilus) для krug.

1. Добавляет в правый клик по файлам подменю krug с тремя круглыми меню.
2. Запоминает текущее выделение, чтобы горячие клавиши Ctrl+Alt+1/2/3 знали,
   с какими файлами работать: на Wayland посторонняя программа выделение прочитать не может.
"""
import os
import subprocess

from gi.repository import GObject, Nautilus

LAUNCHER = os.path.expanduser("~/.local/bin/krug")
MENUS = (("convert", "Конвертация"), ("tools", "Инструменты"), ("actions", "Действия"))


def _selection_file():
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp/krug-%d" % os.getuid()
    folder = os.path.join(base, "krug")
    os.makedirs(folder, mode=0o700, exist_ok=True)
    return os.path.join(folder, "selection")


class KrugExtension(GObject.GObject, Nautilus.MenuProvider):
    def _launch(self, _item, menu, paths):
        subprocess.Popen([LAUNCHER, menu, *paths], start_new_session=True)

    def get_file_items(self, *args):
        files = args[-1]  # в старых версиях первым аргументом шло окно
        paths = []
        for f in files:
            location = f.get_location()
            path = location.get_path() if location else None
            if path:
                paths.append(path)
        try:
            with open(_selection_file(), "w", encoding="utf-8") as fh:
                fh.write("\0".join(paths))
        except OSError:
            pass
        if not paths:
            return []

        top = Nautilus.MenuItem(name="Krug::top", label="krug", tip="Круглое меню для файлов")
        submenu = Nautilus.Menu()
        top.set_submenu(submenu)
        for menu, label in MENUS:
            item = Nautilus.MenuItem(name="Krug::" + menu, label=label)
            item.connect("activate", self._launch, menu, paths)
            submenu.append_item(item)
        return [top]
