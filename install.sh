#!/usr/bin/env bash
# Установка krug для текущего пользователя Ubuntu (GNOME).
# Ставит только в домашнюю папку; sudo нужен лишь для недостающих системных пакетов.
set -euo pipefail

[[ "$EUID" != 0 ]] || { echo "Запускайте от обычного пользователя, без sudo."; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/krug"
BIN="$HOME/.local/bin/krug"
EXT_DIR="$HOME/.local/share/nautilus-python/extensions"

PACKAGES=(python3-gi python3-gi-cairo gir1.2-gtk-4.0 python3-nautilus libnotify-bin wl-clipboard
          imagemagick ffmpeg poppler-utils qpdf ghostscript img2pdf libreoffice-core
          libreoffice-writer libreoffice-calc libreoffice-impress)

missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
    echo "Не установлены пакеты: ${missing[*]}"
    read -r -p "Установить их через apt? [y/N] " answer
    if [[ "$answer" =~ ^[YyДд]$ ]]; then
        sudo apt install -y "${missing[@]}"
    else
        echo "Пропускаю. Без них часть пунктов меню будет серой с подсказкой."
    fi
fi

mkdir -p "$APP_DIR" "$(dirname "$BIN")" "$EXT_DIR"
rm -rf "$APP_DIR/krug"
cp -r "$HERE/krug" "$APP_DIR/krug"
find "$APP_DIR" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$HERE/nautilus/krug_nautilus.py" "$EXT_DIR/krug_nautilus.py"

cat >"$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$APP_DIR" exec /usr/bin/python3 -m krug "\$@"
EOF
chmod +x "$BIN"

"$BIN" hotkeys install || echo "Горячие клавиши настроить не удалось (не GNOME?). Правый клик в «Файлах» всё равно работает."
nautilus -q >/dev/null 2>&1 || true

echo
echo "Готово. Проверка внешних программ:"
"$BIN" check
echo
echo "Как пользоваться: выделите файл в «Файлах» и нажмите Ctrl+Alt+1, 2 или 3,"
echo "либо правый клик по файлу → krug."
echo "Необязательно: удаление фона — pipx install \"rembg[cpu,cli]\"; отправка на телефон — sudo apt install kdeconnect"
