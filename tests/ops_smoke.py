"""Реальные операции с настоящими программами (ImageMagick, FFmpeg, qpdf, LibreOffice…).

    python3 tests/ops_smoke.py ASSETS
Каждый пункт меню выполняется на копии файла во временной папке; печатается сводка.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["KRUG_NO_NOTIFY"] = "1"
from krug import ops  # noqa: E402

ASSETS = Path(sys.argv[1]).resolve()
SKIP = {"Копировать путь", "Копировать имя", "Копировать файл", "Копировать в…", "Переместить в…",
        "Терминал здесь", "На телефон", "Удалить фон"}
CASES = [("convert", ["photo.jpg"]), ("tools", ["photo.jpg"]), ("convert", ["photo.jpg", "photo2.png"]),
         ("convert", ["doc.pdf"]), ("tools", ["doc.pdf"]), ("tools", ["doc.pdf", "doc2.pdf"]),
         ("convert", ["clip.mp4"]), ("tools", ["clip.mp4"]), ("convert", ["sound.mp3"]), ("tools", ["sound.mp3"]),
         ("convert", ["note.docx"]), ("convert", ["table.csv"]), ("actions", ["photo.jpg"])]


def leaves(items, prefix=""):
    for item in items:
        if item.children:
            yield from leaves(item.children, f"{prefix}{item.label} › ")
        else:
            yield f"{prefix}{item.label}", item


failed = 0
for menu, names in CASES:
    sources = [ASSETS / n for n in names if (ASSETS / n).exists()]
    if len(sources) != len(names):
        print(f"SKIP {menu} {names}: нет файла")
        continue
    for label, item in leaves(ops.build_menu(menu, sources)):
        if item.label in SKIP or item.editor:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            copies = [Path(shutil.copy2(s, tmp)) for s in sources]
            before = {p.name for p in Path(tmp).iterdir()}
            results, errors = ops.execute(item, copies)
            created = sorted({p.name for p in Path(tmp).iterdir()} - before)
            originals_ok = all(c.read_bytes() == s.read_bytes() for c, s in zip(copies, sources))
            ok = not errors and created and originals_ok
            failed += not ok
            status = "OK  " if ok else "FAIL"
            detail = "; ".join(errors) if errors else ", ".join(created)
            print(f"{status} {menu:8} {'+'.join(names):22} {label:28} {detail[:110]}")
print(f"\nfailed: {failed}")
sys.exit(1 if failed else 0)
