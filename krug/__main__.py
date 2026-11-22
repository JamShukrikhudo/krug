"""Командная строка krug.

krug                                   главное окно: инструкция, журнал, компоненты
krug convert|tools|actions [ФАЙЛЫ...]   круглое меню; без файлов берётся выделение из «Файлов»
krug edit ФАЙЛЫ...                      редактор с предпросмотром (фото, видео, звук, страницы PDF)
krug list convert|tools|actions ФАЙЛЫ  показать пункты меню текстом (без окна)
krug hotkeys install|remove            сочетания Ctrl+Alt+1/2/3 в «Файлах»
krug check                             какие внешние программы найдены
"""
from __future__ import annotations

import sys
from pathlib import Path

from . import __version__, ops
from .util import notify, read_selection, which

MENUS = ("convert", "tools", "actions")
TOOLS = (
    ("magick", "convert"), ("ffmpeg",), ("soffice", "libreoffice"), ("pdftoppm",), ("qpdf",), ("gs",),
    ("img2pdf",), ("wl-copy",), ("notify-send",), ("rembg",), ("kdeconnect-cli",),
)


def print_items(items: list[ops.Item], indent: str = "") -> None:
    for item in items:
        note = f"   [{item.missing}]" if item.missing else ""
        print(f"{indent}{item.label}{note}")
        print_items(item.children, indent + "    ")


def main(argv: list[str]) -> int:
    if not argv:
        from .app import run_app
        return run_app()
    if argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    command, args = argv[0], argv[1:]
    if command in ("-V", "--version"):
        print(__version__)
    elif command == "check":
        for names in TOOLS:
            print(f"{'OK     ' if which(*names) else 'НЕТ    '} {names[0]}")
    elif command == "hotkeys" and args and args[0] in ("install", "remove"):
        from . import hotkeys
        try:
            hotkeys.install() if args[0] == "install" else hotkeys.remove()
        except RuntimeError as e:
            print(f"Горячие клавиши: {e}", file=sys.stderr)
            return 1
    elif command == "edit" and args:
        files = [Path(a).absolute() for a in args if Path(a).is_file()]
        kind = ops.kind_of(files) if files else ""
        editor = {"image": "image", "video": "video", "audio": "audio", "pdf": "pdf"}.get(kind)
        if not editor:
            print("Редактор открывается для изображений, видео, звука или одного PDF одного типа", file=sys.stderr)
            return 2
        from .app import run_editor
        return run_editor(editor, files)
    elif command == "list" and args and args[0] in MENUS:
        print_items(ops.build_menu(args[0], [Path(a).absolute() for a in args[1:]]))
    elif command in MENUS:
        files = [Path(a).absolute() for a in args if Path(a).exists()] or read_selection()
        if not files:
            notify("krug", "Выделите файл в «Файлах» и нажмите сочетание там же, или правый клик → krug")
            return 1
        if not ops.build_menu(command, files):
            notify("krug", "Для этих файлов здесь нет операций. Выделите файлы одного типа")
            return 1
        from . import menu
        return menu.show(command, files)
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
