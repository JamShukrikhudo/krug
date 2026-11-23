#!/usr/bin/env bash
# Удаляет krug из домашней папки. Системные пакеты (ffmpeg и другие) не трогает.
set -euo pipefail

BIN="$HOME/.local/bin/krug"
[[ -x "$BIN" ]] && "$BIN" hotkeys remove || true
rm -f "$BIN" "$HOME/.local/share/nautilus-python/extensions/krug_nautilus.py"
rm -rf "$HOME/.local/share/krug" "$HOME/.cache/krug" "$HOME/.local/state/krug"
rm -f "$HOME/.local/share/applications/io.github.krug.desktop" \
      "$HOME/.local/share/icons/hicolor/scalable/apps/io.github.krug.svg"
SHELL_EXT="krug@krug.github.io"
rm -rf "$HOME/.local/share/gnome-shell/extensions/$SHELL_EXT"
if command -v gsettings >/dev/null && enabled="$(gsettings get org.gnome.shell enabled-extensions 2>/dev/null)"; then
    cleaned="$(printf '%s' "$enabled" | sed "s/, '$SHELL_EXT'//; s/'$SHELL_EXT', //; s/'$SHELL_EXT'//")"
    [[ "$cleaned" == "$enabled" ]] || gsettings set org.gnome.shell enabled-extensions "$cleaned"
fi
nautilus -q >/dev/null 2>&1 || true
echo "krug удалён."
