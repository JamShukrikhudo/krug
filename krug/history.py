"""Журнал последних операций: что сделано и какие файлы созданы."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

LIMIT = 50


def history_file() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "krug" / "history.json"


def load() -> list[dict]:
    try:
        data = json.loads(history_file().read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def add(label: str, results: list[Path], errors: list[str]) -> None:
    if not results and not errors:
        return
    entry = {
        "time": int(time.time()),
        "label": label,
        "results": [str(p) for p in results[:20]],
        "error": "; ".join(errors[:3])[:300],
    }
    entries = [entry, *load()][:LIMIT]
    path = history_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass


def clear() -> None:
    try:
        history_file().unlink()
    except OSError:
        pass
