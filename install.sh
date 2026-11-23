#!/usr/bin/env bash
# Установка krug для текущего пользователя Ubuntu (GNOME).
# Ставит только в домашнюю папку; sudo нужен лишь для недостающих системных пакетов.
set -euo pipefail

[[ "$EUID" != 0 ]] || { echo "Запускайте от обычного пользователя, без sudo."; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$HOME/.local/share/krug"
BIN="$HOME/.local/bin/krug"
EXT_DIR="$HOME/.local/share/nautilus-python/extensions"

PACKAGES=(python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 librsvg2-common python3-nautilus libnotify-bin wl-clipboard
          gstreamer1.0-plugins-good gstreamer1.0-libav
          imagemagick ffmpeg poppler-utils qpdf ghostscript img2pdf libreoffice-core
          libreoffice-writer libreoffice-calc libreoffice-impress)

# С GTK 4.19.2 воспроизведение видео встроено в сам libgtk-4-1, отдельный пакет
# libgtk-4-media-gstreamer с ним конфликтует. Нужен только на старых GTK (Ubuntu 24.04 и т.п.).
gtk_version="$(dpkg-query -W -f='${Version}' libgtk-4-1 2>/dev/null || true)"
if [[ -n "$gtk_version" ]] && dpkg --compare-versions "$gtk_version" lt 4.19.2; then
    PACKAGES+=(libgtk-4-media-gstreamer)
fi

missing=()
for pkg in "${PACKAGES[@]}"; do
    dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
done
if ((${#missing[@]})); then
    echo "Не установлены пакеты: ${missing[*]}"
    read -r -p "Установить их через apt? [y/N] " answer
    if [[ "$answer" =~ ^[YyДд]$ ]]; then
        if ! sudo apt install -y "${missing[@]}"; then
            echo
            echo "apt не смог установить пакеты разом. Пробую по одному, чтобы поставить всё, что получится."
            for pkg in "${missing[@]}"; do
                sudo apt install -y "$pkg" >/dev/null 2>&1 && echo "  установлен: $pkg" || echo "  НЕ установлен: $pkg"
            done
        fi
    else
        echo "Пропускаю. Без них часть пунктов меню будет серой с подсказкой."
    fi
fi

mkdir -p "$APP_DIR" "$(dirname "$BIN")" "$EXT_DIR"
rm -rf "$APP_DIR/krug"
cp -r "$HERE/krug" "$APP_DIR/krug"
find "$APP_DIR" -name __pycache__ -type d -prune -exec rm -rf {} +
cp "$HERE/nautilus/krug_nautilus.py" "$EXT_DIR/krug_nautilus.py"

# значок и пункт в списке приложений
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$ICON_DIR" "$APPS_DIR"
cp "$HERE/data/io.github.krug.svg" "$ICON_DIR/"
sed "s|@BIN@|$BIN|" "$HERE/data/io.github.krug.desktop" >"$APPS_DIR/io.github.krug.desktop"
gtk4-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database -q "$APPS_DIR" 2>/dev/null || true

cat >"$BIN" <<EOF
#!/bin/sh
PYTHONPATH="$APP_DIR" exec /usr/bin/python3 -m krug "\$@"
EOF
chmod +x "$BIN"

# расширение GNOME Shell: те же Ctrl+Alt+1/2/3 на значках рабочего стола
SHELL_EXT="krug@krug.github.io"
SHELL_DIR="$HOME/.local/share/gnome-shell/extensions/$SHELL_EXT"
rm -rf "$SHELL_DIR"
mkdir -p "$SHELL_DIR"
cp "$HERE/gnome-shell/$SHELL_EXT/"* "$SHELL_DIR/"
desktop_note=""
if command -v gsettings >/dev/null && gsettings get org.gnome.shell enabled-extensions >/dev/null 2>&1; then
    enabled="$(gsettings get org.gnome.shell enabled-extensions)"
    if [[ "$enabled" != *"'$SHELL_EXT'"* ]]; then
        if [[ "$enabled" == "@as []" || "$enabled" == "[]" ]]; then
            gsettings set org.gnome.shell enabled-extensions "['$SHELL_EXT']"
        else
            gsettings set org.gnome.shell enabled-extensions "${enabled%]}, '$SHELL_EXT']"
        fi
        desktop_note="Чтобы сочетания заработали и на рабочем столе, выйдите из сеанса и войдите снова (один раз)."
    fi
fi

"$BIN" hotkeys install || echo "Сочетания клавиш настроить не удалось. Правый клик в «Файлах» всё равно работает."
nautilus -q >/dev/null 2>&1 || true

echo
echo "Готово. Проверка внешних программ:"
"$BIN" check
echo
echo "Как пользоваться: выделите файл в «Файлах» и нажмите Ctrl+Alt+1, 2 или 3,"
echo "либо правый клик по файлу → krug. Главное окно — «krug» в списке приложений."
[[ -n "$desktop_note" ]] && echo "$desktop_note"
echo "Необязательно: удаление фона — pipx install \"rembg[cpu,cli]\"; отправка на телефон — sudo apt install kdeconnect"
