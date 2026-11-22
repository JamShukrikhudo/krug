"""Операции над файлами и сборка трёх меню: convert, tools, actions.

Оригиналы никогда не изменяются: каждый результат получает новое имя рядом с исходным файлом.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .util import OpError, copy_to_clipboard, need, out_path, run, unique_path, which

IMAGE = {"png", "jpg", "jpeg", "heic", "heif", "tif", "tiff", "bmp", "webp", "avif", "gif"}
DOC = {"doc", "docx", "odt", "rtf", "txt", "md"}
SHEET = {"xls", "xlsx", "ods", "csv", "tsv"}
SLIDES = {"ppt", "pptx", "odp"}
AUDIO = {"mp3", "wav", "flac", "ogg", "oga", "m4a", "aac", "opus", "wma"}
VIDEO = {"mp4", "mov", "mkv", "webm", "avi", "m4v", "mpg", "mpeg", "wmv", "3gp"}
PDF = {"pdf"}
ZIP = {"zip"}

HINT_IM = "Установите: sudo apt install imagemagick"
HINT_FF = "Установите: sudo apt install ffmpeg"
HINT_LO = "Установите: sudo apt install libreoffice"
HINT_POPPLER = "Установите: sudo apt install poppler-utils"
HINT_QPDF = "Установите: sudo apt install qpdf"
HINT_GS = "Установите: sudo apt install ghostscript"
HINT_REMBG = 'Установите: pipx install "rembg[cpu,cli]"'
HINT_KDE = "Установите: sudo apt install kdeconnect и свяжите телефон"

MENU_TITLES = {"convert": "Конвертация", "tools": "Инструменты", "actions": "Действия"}


@dataclass
class Item:
    """Пункт круглого меню: либо действие, либо подменю."""

    label: str
    each: Callable[[Path], Path | None] | None = None  # вызывается для каждого файла
    batch: Callable[[list[Path]], list[Path]] | None = None  # вызывается один раз для всех
    folder: Callable[[list[Path], Path], list[Path]] | None = None  # сначала спросить папку
    children: list["Item"] = field(default_factory=list)
    missing: str = ""  # подсказка, если не хватает внешней программы
    quiet: bool = False  # не показывать «Готово» (мгновенные действия)
    icon: str = ""  # символьная иконка; без неё в кнопке крупно пишется название
    editor: str = ""  # открыть окно редактора: image, video, audio, pdf


def ext(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def kind_of(files: list[Path]) -> str:
    """Общий тип выделенных файлов или 'mixed'."""
    kinds = set()
    for f in files:
        if f.is_dir():
            kinds.add("dir")
            continue
        e = ext(f)
        for name, group in (
            ("image", IMAGE), ("doc", DOC), ("sheet", SHEET), ("slides", SLIDES),
            ("audio", AUDIO), ("video", VIDEO), ("pdf", PDF), ("zip", ZIP),
        ):
            if e in group:
                kinds.add(name)
                break
        else:
            kinds.add("other")
    return kinds.pop() if len(kinds) == 1 else "mixed"


# ---------------------------------------------------------------- изображения

def _magick() -> str:
    return need("magick", "convert", hint=HINT_IM)


def image_convert(target: str) -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        dst = out_path(src, target)
        cmd = [_magick(), f"{src}[0]" if ext(src) == "gif" and target != "gif" else src, "-auto-orient"]
        if target in ("jpg", "bmp"):
            cmd += ["-background", "white", "-alpha", "remove", "-alpha", "off"]
        if target in ("jpg", "webp", "avif"):
            cmd += ["-quality", "90"]
        run(cmd + [dst])
        return dst
    return op


def image_tool(args: list[str], suffix: str, target: str | None = None) -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        dst = out_path(src, target, suffix)
        run([_magick(), src, "-auto-orient", *args, dst])
        return dst
    return op


def image_compress(src: Path) -> Path:
    if ext(src) == "png":
        dst = out_path(src, "png", "-compressed")
        run([_magick(), src, "-strip", "-colors", "256", "-define", "png:compression-level=9", dst])
    else:
        dst = out_path(src, "jpg", "-compressed")
        run([_magick(), src, "-auto-orient", "-strip", "-background", "white", "-alpha", "remove",
             "-alpha", "off", "-quality", "75", dst])
    return dst


def images_to_pdf(files: list[Path]) -> list[Path]:
    """Все выделенные изображения в один PDF, по странице на изображение."""
    first = files[0]
    dst = out_path(first, "pdf", "-album" if len(files) > 1 else "")
    img2pdf = which("img2pdf")
    if not img2pdf:
        run([_magick(), *files, "-auto-orient", "-background", "white", "-alpha", "remove", dst])
        return [dst]
    with tempfile.TemporaryDirectory(prefix="krug-") as tmp:
        pages = []
        for i, src in enumerate(files):
            if ext(src) in ("jpg", "jpeg"):
                pages.append(src)
                continue
            # img2pdf не принимает прозрачность и редкие форматы: готовим PNG без альфа-канала
            page = Path(tmp) / f"{i:04d}.png"
            run([_magick(), f"{src}[0]", "-auto-orient", "-background", "white", "-alpha", "remove",
                 "-alpha", "off", page])
            pages.append(page)
        run([img2pdf, *pages, "-o", dst])
    return [dst]


def remove_background(src: Path) -> Path:
    tool = need("rembg", hint=HINT_REMBG)
    dst = out_path(src, "png", "-no-background")
    run([tool, "i", src, dst])
    return dst


# ------------------------------------------------------------------------ PDF

def pdf_to_text(src: Path) -> Path:
    dst = out_path(src, "txt")
    run([need("pdftotext", hint=HINT_POPPLER), "-layout", src, dst])
    return dst


def pdf_to_images(fmt: str) -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        tool = need("pdftoppm", hint=HINT_POPPLER)
        folder = unique_path(src.parent / f"{src.stem}-pages")
        folder.mkdir()
        flag = "-png" if fmt == "png" else "-jpeg"
        run([tool, flag, "-r", "150", src, folder / src.stem])
        return folder
    return op


def pdf_merge(files: list[Path]) -> list[Path]:
    if len(files) < 2:
        raise OpError("Для объединения выделите хотя бы два PDF")
    dst = out_path(files[0], "pdf", "-merged")
    run([need("qpdf", hint=HINT_QPDF), "--empty", "--pages", *files, "--", dst])
    return [dst]


def pdf_split(src: Path) -> Path:
    folder = unique_path(src.parent / f"{src.stem}-split")
    folder.mkdir()
    run([need("qpdf", hint=HINT_QPDF), "--split-pages", src, folder / f"{src.stem}-%d.pdf"])
    return folder


def pdf_rotate(angle: str) -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        dst = out_path(src, "pdf", "-rotated")
        run([need("qpdf", hint=HINT_QPDF), src, dst, f"--rotate={angle}"])
        return dst
    return op


def pdf_compress(src: Path) -> Path:
    dst = out_path(src, "pdf", "-compressed")
    run([need("gs", hint=HINT_GS), "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", "-dPDFSETTINGS=/ebook",
         "-dNOPAUSE", "-dBATCH", "-dQUIET", f"-sOutputFile={dst}", src])
    return dst


# --------------------------------------------------------------------- офис

LO_FILTERS = {
    "csv": "csv:Text - txt - csv (StarCalc):44,34,76,1",
    "txt": "txt:Text (encoded):UTF8",
}


def office_convert(target: str) -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        soffice = need("soffice", "libreoffice", hint=HINT_LO)
        profile = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "krug" / "lo-profile"
        profile.mkdir(parents=True, exist_ok=True)
        # временная папка рядом с файлом: LibreOffice пишет «имя.<ext>», а мы даём уникальное имя
        tmp = Path(tempfile.mkdtemp(prefix="krug-tmp-", dir=src.parent))
        try:
            cmd = [soffice, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore"]
            if ext(src) in ("txt", "md"):
                cmd.append("--infilter=Text (encoded):UTF8,LF,,,")
            cmd += ["--convert-to", LO_FILTERS.get(target, target), "--outdir", tmp, src]
            run(cmd)
            produced = [p for p in tmp.iterdir() if p.is_file()]
            if not produced:
                raise OpError(f"LibreOffice не смог преобразовать {src.name}")
            dst = out_path(src, target)
            shutil.move(str(produced[0]), dst)
            return dst
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return op


# ------------------------------------------------------------- аудио и видео

AUDIO_ARGS = {
    "mp3": ["-vn", "-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-vn"],
    "flac": ["-vn"],
    "ogg": ["-vn", "-c:a", "libvorbis", "-q:a", "5"],
    "m4a": ["-vn", "-c:a", "aac", "-b:a", "192k"],
    "opus": ["-vn", "-c:a", "libopus", "-b:a", "128k"],
}
X264 = ["-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart"]
VIDEO_ARGS = {
    "mp4": [*X264, "-crf", "22", "-b:a", "160k"],
    "webm": ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus"],
    "mkv": ["-c", "copy"],
    "gif": ["-vf", "fps=12,scale=480:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"],
}


def ffmpeg_op(args: list[str], target: str | None = None, suffix: str = "") -> Callable[[Path], Path]:
    def op(src: Path) -> Path:
        dst = out_path(src, target, suffix)
        run([need("ffmpeg", hint=HINT_FF), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
             "-i", src, *args, dst])
        return dst
    return op


# ------------------------------------------------------------------- архивы

def zip_files(files: list[Path]) -> list[Path]:
    first = files[0]
    name = first.name if first.is_dir() else first.stem
    dst = unique_path(first.parent / (f"{name}.zip" if len(files) == 1 else "archive.zip"))
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            if f.is_dir():
                for sub in sorted(f.rglob("*")):
                    if sub.is_file() and not sub.is_symlink():
                        zf.write(sub, sub.relative_to(f.parent))
            elif f.is_file():
                zf.write(f, f.name)
    return [dst]


def unzip(src: Path) -> Path:
    """Распаковка в новую папку. Архивы со ссылками и путями наружу отклоняются."""
    folder = unique_path(src.parent / src.stem)
    with zipfile.ZipFile(src) as zf:
        root = folder.resolve()
        for info in zf.infolist():
            target = (folder / info.filename).resolve()
            if target != root and root not in target.parents:
                raise OpError(f"{src.name}: небезопасный путь в архиве")
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise OpError(f"{src.name}: архив содержит ссылки")
        folder.mkdir()
        zf.extractall(folder)
    return folder


# ----------------------------------------------------------------- действия

def copy_paths(files: list[Path]) -> list[Path]:
    copy_to_clipboard("\n".join(str(f) for f in files))
    return []


def copy_names(files: list[Path]) -> list[Path]:
    copy_to_clipboard("\n".join(f.name for f in files))
    return []


def copy_files(files: list[Path]) -> list[Path]:
    """Кладёт сами файлы в буфер: после этого в «Файлах» работает «Вставить»."""
    copy_to_clipboard("copy\n" + "\n".join(f.as_uri() for f in files), "x-special/gnome-copied-files")
    return []


def _transfer(files: list[Path], folder: Path, move: bool) -> list[Path]:
    done = []
    for f in files:
        dst = unique_path(folder / f.name)
        if move:
            shutil.move(str(f), dst)
        elif f.is_dir():
            shutil.copytree(f, dst, symlinks=True)
        else:
            shutil.copy2(f, dst)
        done.append(dst)
    return done


def copy_to(files: list[Path], folder: Path) -> list[Path]:
    return _transfer(files, folder, move=False)


def move_to(files: list[Path], folder: Path) -> list[Path]:
    return _transfer(files, folder, move=True)


def duplicate(src: Path) -> Path:
    name = src.name if src.is_dir() else src.stem
    dst = unique_path(src.parent / f"{name} (копия){'' if src.is_dir() else src.suffix}")
    if src.is_dir():
        shutil.copytree(src, dst, symlinks=True)
    else:
        shutil.copy2(src, dst)
    return dst


def open_terminal(files: list[Path]) -> list[Path]:
    first = files[0]
    folder = first if first.is_dir() else first.parent
    for tool, args in (
        ("ptyxis", ["--new-window", "-d", str(folder)]),
        ("gnome-terminal", ["--working-directory", str(folder)]),
        ("kgx", ["--working-directory", str(folder)]),
        ("x-terminal-emulator", []),
    ):
        path = which(tool)
        if path:
            subprocess.Popen([path, *args], cwd=folder, start_new_session=True)
            return []
    raise OpError("Не найден терминал")


def send_to_phone(files: list[Path]) -> list[Path]:
    tool = need("kdeconnect-cli", hint=HINT_KDE)
    devices = run([tool, "-a", "--id-only"]).stdout.decode().split()
    if not devices:
        raise OpError("Нет доступного телефона. Откройте KDE Connect на телефоне в той же сети Wi-Fi")
    for f in files:
        if f.is_file():
            run([tool, "-d", devices[0], "--share", f])
    return []


# --------------------------------------------------------------- сборка меню

def _missing(*tools_and_hint: str) -> str:
    *tools, hint = tools_and_hint
    return "" if which(*tools) else hint


def _convert_menu(files: list[Path], kind: str) -> list[Item]:
    exts = {ext(f) for f in files}
    items: list[Item] = []
    if kind == "image":
        miss = _missing("magick", "convert", HINT_IM)
        for label, target, same in (("PNG", "png", {"png"}), ("JPEG", "jpg", {"jpg", "jpeg"}),
                                    ("WebP", "webp", {"webp"}), ("AVIF", "avif", {"avif"}),
                                    ("TIFF", "tiff", {"tif", "tiff"}), ("BMP", "bmp", {"bmp"})):
            if not exts <= same:
                items.append(Item(label, each=image_convert(target), missing=miss))
        items.append(Item("PDF", batch=images_to_pdf, missing=miss))
    elif kind in ("doc", "sheet", "slides"):
        miss = _missing("soffice", "libreoffice", HINT_LO)
        targets = {
            "doc": ("pdf", "docx", "odt", "rtf", "txt"),
            "sheet": ("pdf", "xlsx", "ods", "csv"),
            "slides": ("pdf", "pptx", "odp"),
        }[kind]
        for target in targets:
            if exts != {target}:
                items.append(Item(target.upper(), each=office_convert(target), missing=miss))
    elif kind == "pdf":
        miss = _missing("pdftoppm", HINT_POPPLER)
        items += [
            Item("Текст TXT", each=pdf_to_text, missing=miss),
            Item("Страницы PNG", each=pdf_to_images("png"), missing=miss),
            Item("Страницы JPEG", each=pdf_to_images("jpg"), missing=miss),
        ]
    elif kind == "audio":
        miss = _missing("ffmpeg", HINT_FF)
        for target, args in AUDIO_ARGS.items():
            if exts != {target}:
                items.append(Item(target.upper(), each=ffmpeg_op(args, target), missing=miss))
    elif kind == "video":
        miss = _missing("ffmpeg", HINT_FF)
        for target, args in VIDEO_ARGS.items():
            if exts != {target}:
                items.append(Item(target.upper(), each=ffmpeg_op(args, target), missing=miss))
        items.append(Item("Звук в MP3", each=ffmpeg_op(AUDIO_ARGS["mp3"], "mp3"), missing=miss))
    return items


def _tools_menu(files: list[Path], kind: str) -> list[Item]:
    items: list[Item] = []
    if kind == "image":
        miss = _missing("magick", "convert", HINT_IM)
        items += [
            Item("Редактор", editor="image", missing=miss),
            Item("Сжать", each=image_compress, missing=miss),
            Item("Размер", missing=miss, children=[
                Item("50 %", each=image_tool(["-resize", "50%"], "-50")),
                Item("25 %", each=image_tool(["-resize", "25%"], "-25")),
                Item("до 2560 px", each=image_tool(["-resize", "2560x2560>"], "-2560")),
                Item("до 1920 px", each=image_tool(["-resize", "1920x1920>"], "-1920")),
                Item("до 1280 px", each=image_tool(["-resize", "1280x1280>"], "-1280")),
                Item("до 800 px", each=image_tool(["-resize", "800x800>"], "-800")),
            ]),
            Item("Повернуть", missing=miss, children=[
                Item("Вправо 90°", each=image_tool(["-rotate", "90"], "-rotated")),
                Item("Влево 90°", each=image_tool(["-rotate", "-90"], "-rotated")),
                Item("На 180°", each=image_tool(["-rotate", "180"], "-rotated")),
                Item("Зеркально", each=image_tool(["-flop"], "-mirrored")),
            ]),
            Item("Белая рамка", each=image_tool(["-bordercolor", "white", "-border", "5%"], "-border"), missing=miss),
            Item("Ч/б", each=image_tool(["-colorspace", "Gray"], "-gray"), missing=miss),
            Item("Убрать метаданные", each=image_tool(["-strip"], "-clean"), missing=miss),
        ]
    elif kind == "pdf":
        miss = _missing("qpdf", HINT_QPDF)
        if len(files) == 1:
            items.append(Item("Страницы", editor="pdf", missing=miss or _missing("pdftoppm", HINT_POPPLER)))
        if len(files) > 1:
            items.append(Item("Объединить", batch=pdf_merge, missing=miss))
        items += [
            Item("Разделить по страницам", each=pdf_split, missing=miss),
            Item("Сжать", each=pdf_compress, missing=_missing("gs", HINT_GS)),
            Item("Повернуть", missing=miss, children=[
                Item("Вправо 90°", each=pdf_rotate("+90")),
                Item("Влево 90°", each=pdf_rotate("-90")),
                Item("На 180°", each=pdf_rotate("+180")),
            ]),
        ]
    elif kind == "video":
        miss = _missing("ffmpeg", HINT_FF)
        items += [
            Item("Редактор", editor="video", missing=miss),
            Item("Сжать", each=ffmpeg_op([*X264, "-crf", "28", "-b:a", "128k"], "mp4", "-compressed"), missing=miss),
            Item("720p", each=ffmpeg_op([*X264, "-vf", "scale=-2:720", "-crf", "24", "-b:a", "128k"], "mp4", "-720p"), missing=miss),
            Item("Убрать звук", each=ffmpeg_op(["-an", "-c:v", "copy"], None, "-mute"), missing=miss),
            Item("Скорость ×2", each=ffmpeg_op([*X264, "-vf", "setpts=0.5*PTS", "-af", "atempo=2.0", "-crf", "23"], "mp4", "-x2"), missing=miss),
            Item("Кадр в PNG", each=ffmpeg_op(["-frames:v", "1"], "png", "-frame"), missing=miss),
        ]
    elif kind == "audio":
        miss = _missing("ffmpeg", HINT_FF)
        items += [
            Item("Редактор", editor="audio", missing=miss),
            Item("Сжать MP3 128k", each=ffmpeg_op(["-vn", "-c:a", "libmp3lame", "-b:a", "128k"], "mp3", "-128k"), missing=miss),
            Item("Моно", each=ffmpeg_op(["-vn", "-ac", "1"], None, "-mono"), missing=miss),
            Item("Скорость ×1.5", each=ffmpeg_op(["-vn", "-af", "atempo=1.5"], None, "-x1.5"), missing=miss),
        ]
    elif kind == "zip":
        items.append(Item("Распаковать", each=unzip))
    if kind != "zip":
        items.append(Item("Архив ZIP", batch=zip_files))
    return items


def _actions_menu(files: list[Path], kind: str) -> list[Item]:
    items = [
        Item("Копировать путь", batch=copy_paths, quiet=True),
        Item("Копировать имя", batch=copy_names, quiet=True),
        Item("Копировать файл", batch=copy_files, quiet=True),
        Item("Копировать в…", folder=copy_to),
        Item("Переместить в…", folder=move_to),
        Item("Дубликат", each=duplicate),
        Item("Терминал здесь", batch=open_terminal, quiet=True),
        Item("На телефон", batch=send_to_phone, missing=_missing("kdeconnect-cli", HINT_KDE)),
    ]
    if kind == "image":
        items.insert(0, Item("Удалить фон", each=remove_background, missing=_missing("rembg", HINT_REMBG)))
    return items


ICONS = {
    "Редактор": "document-edit-symbolic",
    "Страницы": "view-grid-symbolic",
    "Сжать": "package-x-generic-symbolic",
    "Сжать MP3 128k": "package-x-generic-symbolic",
    "Размер": "view-fullscreen-symbolic",
    "Повернуть": "object-rotate-right-symbolic",
    "Вправо 90°": "object-rotate-right-symbolic",
    "Влево 90°": "object-rotate-left-symbolic",
    "На 180°": "view-refresh-symbolic",
    "Зеркально": "object-flip-horizontal-symbolic",
    "Белая рамка": "view-paged-symbolic",
    "Ч/б": "color-select-symbolic",
    "Убрать метаданные": "edit-clear-all-symbolic",
    "Объединить": "list-add-symbolic",
    "Разделить по страницам": "edit-cut-symbolic",
    "720p": "video-display-symbolic",
    "Убрать звук": "audio-volume-muted-symbolic",
    "Скорость ×2": "media-seek-forward-symbolic",
    "Скорость ×1.5": "media-seek-forward-symbolic",
    "Кадр в PNG": "camera-photo-symbolic",
    "Моно": "audio-speakers-symbolic",
    "Архив ZIP": "package-x-generic-symbolic",
    "Распаковать": "folder-open-symbolic",
    "Удалить фон": "image-x-generic-symbolic",
    "Копировать путь": "edit-copy-symbolic",
    "Копировать имя": "insert-text-symbolic",
    "Копировать файл": "edit-paste-symbolic",
    "Копировать в…": "folder-symbolic",
    "Переместить в…": "folder-download-symbolic",
    "Дубликат": "edit-copy-symbolic",
    "Терминал здесь": "utilities-terminal-symbolic",
    "На телефон": "phone-symbolic",
    "Текст TXT": "text-x-generic-symbolic",
    "Страницы PNG": "image-x-generic-symbolic",
    "Страницы JPEG": "image-x-generic-symbolic",
    "Звук в MP3": "audio-x-generic-symbolic",
}


def _with_icons(items: list[Item]) -> list[Item]:
    for item in items:
        if not item.icon:
            item.icon = ICONS.get(item.label, "")
        _with_icons(item.children)
    return items


def build_menu(menu: str, files: list[Path]) -> list[Item]:
    if not files:
        return []
    kind = kind_of(files)
    builder = {"convert": _convert_menu, "tools": _tools_menu, "actions": _actions_menu}[menu]
    return _with_icons(builder(files, kind))


def execute(item: Item, files: list[Path], folder: Path | None = None) -> tuple[list[Path], list[str]]:
    """Выполняет пункт меню. Возвращает (созданные файлы, тексты ошибок)."""
    if item.missing:
        return [], [item.missing]
    results: list[Path] = []
    errors: list[str] = []
    try:
        if item.folder:
            if folder is None:
                raise OpError("Папка не выбрана")
            results += item.folder(files, folder)
        elif item.batch:
            results += item.batch(files)
    except (OpError, OSError, zipfile.BadZipFile) as e:
        errors.append(str(e))
    if item.each:
        for f in files:
            try:
                produced = item.each(f)
                if produced:
                    results.append(produced)
            except (OpError, OSError, zipfile.BadZipFile) as e:
                errors.append(f"{f.name}: {e}")
    return results, errors
