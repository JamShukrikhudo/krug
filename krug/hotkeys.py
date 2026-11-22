"""Горячие клавиши GNOME: Ctrl+Alt+1/2/3 открывают три меню для выделенных файлов."""
from __future__ import annotations

from pathlib import Path

from gi.repository import Gio

SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
ITEM_SCHEMA = SCHEMA + ".custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
KEYS = (
    ("convert", "krug: конвертация", "<Control><Alt>1"),
    ("tools", "krug: инструменты", "<Control><Alt>2"),
    ("actions", "krug: действия", "<Control><Alt>3"),
)


def available() -> bool:
    """Есть ли настройки сочетаний GNOME. Без проверки Gio.Settings аварийно завершает процесс."""
    source = Gio.SettingsSchemaSource.get_default()
    return bool(source and source.lookup(SCHEMA, True) and source.lookup(ITEM_SCHEMA, True))


def _require() -> None:
    if not available():
        raise RuntimeError("сочетания клавиш настраиваются только в GNOME")


def _path(menu: str) -> str:
    return f"{BASE}krug-{menu}/"


def installed() -> bool:
    if not available():
        return False
    paths = Gio.Settings.new(SCHEMA).get_strv("custom-keybindings")
    return all(_path(menu) in paths for menu, _n, _b in KEYS)


def install() -> None:
    _require()
    launcher = Path.home() / ".local" / "bin" / "krug"
    settings = Gio.Settings.new(SCHEMA)
    paths = list(settings.get_strv("custom-keybindings"))
    for menu, name, binding in KEYS:
        item = Gio.Settings.new_with_path(ITEM_SCHEMA, _path(menu))
        item.set_string("name", name)
        item.set_string("command", f"{launcher} {menu}")
        item.set_string("binding", binding)
        if _path(menu) not in paths:
            paths.append(_path(menu))
    settings.set_strv("custom-keybindings", paths)
    Gio.Settings.sync()
    print("Горячие клавиши: Ctrl+Alt+1 конвертация, Ctrl+Alt+2 инструменты, Ctrl+Alt+3 действия")


def remove() -> None:
    _require()
    settings = Gio.Settings.new(SCHEMA)
    ours = {_path(menu) for menu, _n, _b in KEYS}
    settings.set_strv("custom-keybindings", [p for p in settings.get_strv("custom-keybindings") if p not in ours])
    for menu, _n, _b in KEYS:
        item = Gio.Settings.new_with_path(ITEM_SCHEMA, _path(menu))
        for key in ("name", "command", "binding"):
            item.reset(key)
    Gio.Settings.sync()
    print("Горячие клавиши krug удалены")
