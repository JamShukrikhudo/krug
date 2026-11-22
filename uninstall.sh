#!/usr/bin/env bash
# Удаляет krug из домашней папки. Системные пакеты (ffmpeg и другие) не трогает.
set -euo pipefail

BIN="$HOME/.local/bin/krug"
[[ -x "$BIN" ]] && "$BIN" hotkeys remove || true
rm -f "$BIN" "$HOME/.local/share/nautilus-python/extensions/krug_nautilus.py"
rm -rf "$HOME/.local/share/krug" "$HOME/.cache/krug"
nautilus -q >/dev/null 2>&1 || true
echo "krug удалён."
