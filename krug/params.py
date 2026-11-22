"""Параметры редакторов и сборка аргументов для ImageMagick, FFmpeg и qpdf.

Модуль не зависит от GTK, поэтому проверяется тестами.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .util import OpError


# ---------------------------------------------------------------- изображение

@dataclass
class ImageParams:
    crop: tuple[float, float, float, float] | None = None  # x, y, ширина, высота в долях 0…1
    rotate: int = 0            # градусы по часовой: 0, 90, 180, 270
    flip: bool = False         # зеркально по горизонтали
    width: int = 0             # 0 — не менять
    height: int = 0
    keep_ratio: bool = True
    brightness: int = 0        # −100…100
    contrast: int = 0          # −100…100
    saturation: int = 100      # 0…200, 100 — без изменений
    border: int = 0            # белая рамка, px с каждой стороны
    quality: int = 90          # для JPEG/WebP/AVIF
    fmt: str = ""              # "" — как у оригинала

    def changed(self) -> bool:
        return self != ImageParams(quality=self.quality, keep_ratio=self.keep_ratio)


def image_args(p: ImageParams, src_w: int, src_h: int, scale: float = 1.0) -> list[str]:
    """Аргументы ImageMagick. scale < 1 используется для уменьшенного предпросмотра."""
    args: list[str] = []
    w, h = src_w * scale, src_h * scale
    if p.crop:
        cx, cy, cw, ch = p.crop
        cw, ch = max(cw, 0.01), max(ch, 0.01)
        args += ["-crop", f"{max(1, round(cw * w))}x{max(1, round(ch * h))}+{round(cx * w)}+{round(cy * h)}", "+repage"]
    if p.rotate % 360:
        args += ["-rotate", str(p.rotate % 360)]
    if p.flip:
        args += ["-flop"]
    if p.width or p.height:
        rw = max(1, round(p.width * scale)) if p.width else ""
        rh = max(1, round(p.height * scale)) if p.height else ""
        force = "!" if (p.width and p.height and not p.keep_ratio) else ""
        args += ["-resize", f"{rw}x{rh}{force}"]
    if p.brightness or p.contrast:
        args += ["-brightness-contrast", f"{p.brightness}x{p.contrast}"]
    if p.saturation != 100:
        args += ["-modulate", f"100,{p.saturation},100"]
    if p.border:
        args += ["-bordercolor", "white", "-border", str(max(1, round(p.border * scale)))]
    return args


def fit_rect(box_w: float, box_h: float, img_w: float, img_h: float) -> tuple[float, float, float, float]:
    """Где внутри области окажется картинка, вписанная с сохранением пропорций: x, y, ширина, высота."""
    if min(box_w, box_h, img_w, img_h) <= 0:
        return 0.0, 0.0, 0.0, 0.0
    k = min(box_w / img_w, box_h / img_h)
    w, h = img_w * k, img_h * k
    return (box_w - w) / 2, (box_h - h) / 2, w, h


def drag_to_crop(rect: tuple[float, float, float, float], x0: float, y0: float, x1: float, y1: float
                 ) -> tuple[float, float, float, float] | None:
    """Переводит протянутый мышью прямоугольник в доли картинки. None, если выделение слишком мало."""
    rx, ry, rw, rh = rect
    if rw <= 0 or rh <= 0:
        return None
    fx0, fx1 = sorted((min(max((x0 - rx) / rw, 0.0), 1.0), min(max((x1 - rx) / rw, 0.0), 1.0)))
    fy0, fy1 = sorted((min(max((y0 - ry) / rh, 0.0), 1.0), min(max((y1 - ry) / rh, 0.0), 1.0)))
    if fx1 - fx0 < 0.02 or fy1 - fy0 < 0.02:
        return None
    return fx0, fy0, fx1 - fx0, fy1 - fy0


# ------------------------------------------------------------ видео и звук

VIDEO_QUALITY = {"Высокое": 20, "Среднее": 24, "Компактное": 28}
VIDEO_HEIGHTS = {"Как в оригинале": 0, "1080p": 1080, "720p": 720, "480p": 480}
SPEEDS = {"×0.5": 0.5, "×1": 1.0, "×1.25": 1.25, "×1.5": 1.5, "×2": 2.0}
AUDIO_FORMATS = {
    "MP3": ("mp3", ["-c:a", "libmp3lame"]),
    "M4A": ("m4a", ["-c:a", "aac"]),
    "OGG": ("ogg", ["-c:a", "libvorbis"]),
    "OPUS": ("opus", ["-c:a", "libopus"]),
    "WAV": ("wav", []),
    "FLAC": ("flac", []),
}
BITRATES = ("96k", "128k", "192k", "256k", "320k")


@dataclass
class MediaParams:
    start: float = 0.0
    end: float = 0.0           # 0 — до конца
    speed: float = 1.0
    mute: bool = False
    height: int = 0            # 0 — как в оригинале
    crf: int = 24
    mono: bool = False
    bitrate: str = "192k"
    crop: tuple[float, float, float, float] | None = None  # доли кадра, как у изображений


def _trim(p: MediaParams, duration: float) -> list[str]:
    if p.start < 0 or (p.end and p.end <= p.start):
        raise OpError("Конец интервала должен быть позже начала")
    if duration and p.start >= duration:
        raise OpError("Начало интервала за пределами файла")
    args = []
    if p.start > 0:
        args += ["-ss", f"{p.start:.3f}"]
    if p.end and (not duration or p.end < duration):
        args += ["-to", f"{p.end:.3f}"]
    return args


def crop_filter(crop: tuple[float, float, float, float], src_w: int, src_h: int) -> str:
    """Фильтр crop для FFmpeg в пикселях исходного кадра; размеры чётные, как требует H.264."""
    cx, cy, cw, ch = crop
    w = max(2, int(cw * src_w) // 2 * 2)
    h = max(2, int(ch * src_h) // 2 * 2)
    x = min(max(0, round(cx * src_w)), max(0, src_w - w))
    y = min(max(0, round(cy * src_h)), max(0, src_h - h))
    return f"crop={w}:{h}:{x}:{y}"


def video_args(p: MediaParams, duration: float = 0.0, src_w: int = 0, src_h: int = 0
               ) -> tuple[list[str], list[str]]:
    """(аргументы до -i, аргументы после -i) для FFmpeg; результат всегда MP4 H.264."""
    vf, af = [], []
    if p.crop:
        if not (src_w and src_h):
            raise OpError("Не удалось определить размер кадра для обрезки")
        vf.append(crop_filter(p.crop, src_w, src_h))
    if p.height:
        vf.append(f"scale=-2:{p.height}")
    if p.speed != 1.0:
        vf.append(f"setpts=PTS/{p.speed:g}")
        af.append(f"atempo={p.speed:g}")
    out = ["-c:v", "libx264", "-preset", "medium", "-crf", str(p.crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if vf:
        out += ["-vf", ",".join(vf)]
    if p.mute:
        out += ["-an"]
    else:
        out += ["-c:a", "aac", "-b:a", "160k"]
        if af:
            out += ["-af", ",".join(af)]
    return _trim(p, duration), out


def audio_args(p: MediaParams, codec: list[str], lossless: bool, duration: float = 0.0) -> tuple[list[str], list[str]]:
    out = ["-vn", *codec]
    if not lossless:
        out += ["-b:a", p.bitrate]
    if p.mono:
        out += ["-ac", "1"]
    if p.speed != 1.0:
        out += ["-af", f"atempo={p.speed:g}"]
    return _trim(p, duration), out


def frame_args(position: float) -> tuple[list[str], list[str]]:
    return ["-ss", f"{max(position, 0):.3f}"], ["-frames:v", "1"]


# ------------------------------------------------------------------------ PDF

def parse_pages(text: str, total: int) -> str:
    """Проверяет строку вида «3,1,2» или «1-4,7» и возвращает её в виде, понятном qpdf."""
    cleaned = re.sub(r"\s+", "", text)
    if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", cleaned):
        raise OpError("Введите номера страниц через запятую, например 3,1,2 или 1-4,7")
    for number in re.findall(r"\d+", cleaned):
        if not 1 <= int(number) <= total:
            raise OpError(f"В документе {total} стр., страницы {number} нет")
    return cleaned
