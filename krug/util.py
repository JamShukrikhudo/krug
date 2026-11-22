"""Общие помощники: имена результатов, запуск внешних программ, уведомления."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

APP_NAME = "krug"
TIMEOUT = 15 * 60  # секунд на одну внешнюю команду


class OpError(Exception):
    """Понятная пользователю ошибка операции."""


def which(*names: str) -> str | None:
    """Первый найденный в PATH исполняемый файл из списка."""
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def need(*names: str, hint: str = "") -> str:
    path = which(*names)
    if not path:
        raise OpError(f"Не найдена программа {names[0]}. {hint}".strip())
    return path


def unique_path(path: Path) -> Path:
    """Свободное имя: «файл.pdf», затем «файл (2).pdf» и так далее. Ничего не перезаписываем."""
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def out_path(src: Path, ext: str | None = None, suffix: str = "", directory: Path | None = None) -> Path:
    """Имя результата рядом с оригиналом: «имя<suffix>.<ext>»."""
    ext = src.suffix if ext is None else "." + ext.lstrip(".")
    base = src.name if src.is_dir() else src.stem
    return unique_path((directory or src.parent) / f"{base}{suffix}{ext}")


def run(cmd: list[str], cwd: Path | None = None, input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """Запускает внешнюю программу; при ошибке поднимает OpError с хвостом её вывода."""
    try:
        proc = subprocess.run(
            [str(c) for c in cmd],
            cwd=cwd,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        raise OpError(f"{Path(cmd[0]).name}: превышено время ожидания")
    except FileNotFoundError:
        raise OpError(f"Не найдена программа {cmd[0]}")
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).decode("utf-8", "replace").strip().splitlines()[-3:]
        raise OpError(f"{Path(cmd[0]).name}: " + " ".join(tail)[:300])
    return proc


def notify(title: str, body: str = "", error: bool = False) -> None:
    """Системное уведомление; без notify-send просто печатает в терминал."""
    tool = which("notify-send")
    if tool and os.environ.get("KRUG_NO_NOTIFY") != "1":
        icon = "dialog-error" if error else "emblem-ok-symbolic"
        subprocess.run([tool, "-a", APP_NAME, "-i", icon, title, body], check=False)
    else:
        print(f"{title}: {body}" if body else title)


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/{APP_NAME}-{os.getuid()}"
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def selection_file() -> Path:
    """Сюда расширение Nautilus пишет текущее выделение (для горячих клавиш)."""
    return runtime_dir() / "selection"


def read_selection() -> list[Path]:
    try:
        lines = selection_file().read_text(encoding="utf-8").split("\0")
    except OSError:
        return []
    return [Path(p) for p in lines if p and Path(p).exists()]


def copy_to_clipboard(text: str, mime: str | None = None) -> None:
    tool = which("wl-copy")
    if tool:
        cmd = [tool] + (["--type", mime] if mime else [])
        # wl-copy сам остаётся в фоне и держит буфер; ждать его завершения не нужно
        subprocess.run(cmd, input=text.encode(), check=False)
        return
    tool = which("xclip")
    if tool:
        cmd = [tool, "-selection", "clipboard"] + (["-t", mime] if mime else [])
        subprocess.run(cmd, input=text.encode(), check=False)
        return
    raise OpError("Нужен wl-clipboard: sudo apt install wl-clipboard")
