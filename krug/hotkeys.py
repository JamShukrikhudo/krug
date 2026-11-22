"""Сочетания Ctrl+Alt+1/2/3 внутри «Файлов» (Nautilus).

Используются скрипты «Файлов»: каждому можно назначить сочетание в ~/.config/nautilus/scripts-accels,
а выделенные файлы «Файлы» передают скрипту сами (NAUTILUS_SCRIPT_SELECTED_FILE_PATHS).
Так программа получает настоящее выделение даже на Wayland.

Ранние версии krug вешали глобальные сочетания GNOME; они перехватывали клавиши раньше «Файлов»
и не знали выделения, поэтому при установке удаляются.
"""
from __future__ import annotations

import os
from pathlib import Path

KEYS = (
    ("convert", "krug — Конвертация", "<Control><Alt>1"),
    ("tools", "krug — Инструменты", "<Control><Alt>2"),
    ("actions", "krug — Действия", "<Control><Alt>3"),
)
SCRIPT = """#!/bin/sh
# Создано krug. «Файлы» передают выделенные файлы в NAUTILUS_SCRIPT_SELECTED_FILE_PATHS, по одному в строке.
set -f
IFS='
'
exec "{launcher}" {menu} $NAUTILUS_SCRIPT_SELECTED_FILE_PATHS
"""

# старые глобальные сочетания GNOME
SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
ITEM_SCHEMA = SCHEMA + ".custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def _config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def _data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def scripts_dir() -> Path:
    return _data() / "nautilus" / "scripts"


def accels_file() -> Path:
    return _config() / "nautilus" / "scripts-accels"


def merge_accels(text: str, install: bool) -> str:
    """Убирает строки krug из файла сочетаний и, если install, добавляет свежие. Чужие строки сохраняются."""
    names = {name for _m, name, _k in KEYS}
    keys = {key for _m, _n, key in KEYS}
    kept = []
    for line in text.splitlines():
        parts = line.strip().split(" ", 1)
        ours = len(parts) == 2 and (parts[1] in names or (install and parts[0] in keys))
        if not ours:
            kept.append(line)
    if install:
        kept += [f"{key} {name}" for _m, name, key in KEYS]
    return "\n".join(kept).strip("\n") + "\n" if kept else ""


def available() -> bool:
    return True


def installed() -> bool:
    try:
        lines = accels_file().read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return all(f"{key} {name}" in lines and (scripts_dir() / name).exists() for _m, name, key in KEYS)


def install() -> None:
    launcher = Path.home() / ".local" / "bin" / "krug"
    folder = scripts_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for menu, name, _key in KEYS:
        script = folder / name
        script.write_text(SCRIPT.format(launcher=launcher, menu=menu), encoding="utf-8")
        script.chmod(0o755)
    path = accels_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(merge_accels(old, install=True), encoding="utf-8")
    _remove_gnome_keys()
    print("Сочетания в «Файлах»: Ctrl+Alt+1 конвертация, Ctrl+Alt+2 инструменты, Ctrl+Alt+3 действия.")
    print("Перезапустите «Файлы» (nautilus -q), чтобы они подхватили сочетания.")


def remove() -> None:
    for _menu, name, _key in KEYS:
        (scripts_dir() / name).unlink(missing_ok=True)
    path = accels_file()
    if path.exists():
        path.write_text(merge_accels(path.read_text(encoding="utf-8"), install=False), encoding="utf-8")
    _remove_gnome_keys()
    print("Сочетания krug удалены")


def _remove_gnome_keys() -> None:
    """Убирает глобальные сочетания из версий 0.1–0.2, если они есть."""
    try:
        from gi.repository import Gio
        source = Gio.SettingsSchemaSource.get_default()
        if not (source and source.lookup(SCHEMA, True) and source.lookup(ITEM_SCHEMA, True)):
            return
        settings = Gio.Settings.new(SCHEMA)
        ours = {f"{BASE}krug-{menu}/" for menu, _n, _k in KEYS}
        paths = settings.get_strv("custom-keybindings")
        if not ours & set(paths):
            return
        settings.set_strv("custom-keybindings", [p for p in paths if p not in ours])
        for path in ours:
            item = Gio.Settings.new_with_path(ITEM_SCHEMA, path)
            for key in ("name", "command", "binding"):
                item.reset(key)
        Gio.Settings.sync()
    except Exception:  # noqa: BLE001 — старые сочетания не критичны
        pass
