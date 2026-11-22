"""Редактор видео и звука: воспроизведение, интервал, обрезка кадра мышью, скорость, качество."""
from __future__ import annotations

from pathlib import Path

from ..ops import HINT_FF
from ..params import (AUDIO_FORMATS, BITRATES, SPEEDS, VIDEO_HEIGHTS, VIDEO_QUALITY, MediaParams, audio_args,
                      frame_args, video_args)
from ..ui import CropOverlay, GLib, Gtk, button_row, combo_row, in_thread, spin_row, switch_row
from ..util import need, out_path, run
from . import EditorWindow, probe

FFMPEG_HEAD = ["-nostdin", "-hide_banner", "-loglevel", "error", "-y"]


def ffmpeg(pre: list[str], src: Path, post: list[str], dst: Path) -> Path:
    run([need("ffmpeg", hint=HINT_FF), *FFMPEG_HEAD, *pre, "-i", src, *post, dst])
    return dst


class MediaEditor(EditorWindow):
    def __init__(self, app, files: list[Path], video: bool):
        super().__init__(app, files, "Редактор видео" if video else "Редактор звука")
        self.video = video
        self.p = MediaParams()
        self.duration = 0.0
        self.size = (0, 0)
        self.stream: Gtk.MediaFile | None = None
        self.stop_at = 0.0
        self.connect("close-request", lambda _w: self.stream.pause() if self.stream else None)

        # --- предпросмотр
        if video:
            stage = Gtk.Overlay(css_classes=["krug-preview"], hexpand=True, vexpand=True)
            self.player = Gtk.Video(autoplay=False, hexpand=True, vexpand=True)
            stage.set_child(self.player)
            self.cropper = CropOverlay(self.on_crop)
            stage.add_overlay(self.cropper)
            self.preview.append(stage)
            hint = "Если видео не воспроизводится, системе не хватает кодека: sudo apt install gstreamer1.0-libav"
            self.preview.append(Gtk.Label(label=hint, css_classes=["dim-label", "caption"], wrap=True, xalign=0))
        else:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, valign=Gtk.Align.CENTER, vexpand=True,
                          css_classes=["krug-preview"])
            icon = Gtk.Image(icon_name="audio-x-generic-symbolic", pixel_size=128, css_classes=["dim-label"])
            box.append(icon)
            self.controls = Gtk.MediaControls(margin_start=24, margin_end=24, margin_bottom=24)
            box.append(self.controls)
            self.preview.append(box)

        # --- интервал
        g = self.group("Интервал", "Сохраняется только выбранный отрезок")
        self.start = spin_row("Начало, с", 0, 86400, 0, step=0.5, digits=1)
        self.end = spin_row("Конец, с", 0, 86400, 0, step=0.5, digits=1, subtitle="0 — до конца файла")
        for row, setter in ((self.start, "start"), (self.end, "end")):
            take = Gtk.Button(icon_name="find-location-symbolic", tooltip_text="Взять текущий момент",
                              valign=Gtk.Align.CENTER, css_classes=["flat"])
            take.connect("clicked", lambda _b, r=row: r.set_value(self.position()))
            row.add_suffix(take)
            row.connect("notify::value", lambda r, _p, s=setter: self.on_interval(s, r.get_value()))
            g.add(row)
        g.add(button_row("Воспроизвести интервал", "media-playback-start-symbolic", self.play_interval))

        if video:
            g = self.group("Кадр")
            self.crop_switch = switch_row("Выделить область мышью", subtitle="Протяните рамку поверх видео")
            self.crop_switch.connect("notify::active", lambda r, _p: self.cropper.set_active(r.get_active()))
            g.add(self.crop_switch)
            g.add(button_row("Сбросить область", "edit-clear-symbolic", lambda: self.on_crop(None)))
            g.add(button_row("Сохранить текущий кадр в PNG", "camera-photo-symbolic", self.snapshot))

            g = self.group("Видео", "Результат сохраняется в MP4 (H.264)")
            self.res = combo_row("Разрешение", list(VIDEO_HEIGHTS))
            self.qual = combo_row("Качество", list(VIDEO_QUALITY), 1)
            self.speed = combo_row("Скорость", list(SPEEDS), 1)
            self.mute = switch_row("Убрать звук")
            for w in (self.res, self.qual, self.speed, self.mute):
                g.add(w)
        else:
            g = self.group("Звук")
            self.fmt = combo_row("Формат", list(AUDIO_FORMATS))
            self.bitrate = combo_row("Битрейт", list(BITRATES), 2)
            self.speed = combo_row("Скорость", list(SPEEDS), 1)
            self.mono = switch_row("Свести в моно")
            for w in (self.fmt, self.bitrate, self.speed, self.mono):
                g.add(w)

        self.load_file()

    # ------------------------------------------------------------- загрузка
    def load_file(self) -> None:
        src = self.current
        if self.stream:
            self.stream.pause()
        self.stream = Gtk.MediaFile.new_for_filename(str(src))
        if self.video:
            self.player.set_media_stream(self.stream)
        else:
            self.controls.set_media_stream(self.stream)
        self.status.set_label(f"Открываю {src.name}…")

        def done(info, error) -> None:
            if error:
                self.status.set_label(f"{src.name}: {error}")
                return
            self.duration, w, h = info
            self.size = (w, h)
            if self.video and w and h:
                self.cropper.set_media_size(w, h)
            if self.duration:
                for row in (self.start, self.end):
                    row.get_adjustment().set_upper(self.duration)
            dims = f" · {w}×{h}" if w else ""
            self.status.set_label(f"{src.name} · {self.fmt_time(self.duration)}{dims}")

        in_thread(lambda: probe(src), done)

    @staticmethod
    def fmt_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def position(self) -> float:
        return self.stream.get_timestamp() / 1e6 if self.stream else 0.0

    # ------------------------------------------------------------ параметры
    def on_interval(self, which: str, value: float) -> None:
        setattr(self.p, which, value)

    def on_crop(self, crop) -> None:
        self.p.crop = crop
        self.cropper.set_crop(crop)

    def play_interval(self) -> None:
        if not self.stream:
            return
        self.stream.seek(int(self.start.get_value() * 1e6))
        self.stream.play()
        self.stop_at = self.end.get_value()
        if self.stop_at > self.start.get_value():
            GLib.timeout_add(100, self._watch_end)

    def _watch_end(self) -> bool:
        if not self.stream or not self.stream.get_playing():
            return False
        if self.position() >= self.stop_at:
            self.stream.pause()
            return False
        return True

    def prepare(self) -> None:
        self.ready = self.collect()
        if not self.video:
            self.ready_format = AUDIO_FORMATS[list(AUDIO_FORMATS)[self.fmt.get_selected()]]

    def collect(self) -> MediaParams:
        p = MediaParams(**vars(self.p))
        p.speed = list(SPEEDS.values())[self.speed.get_selected()]
        if self.duration and p.end >= self.duration - 0.05:
            p.end = 0.0
        if self.video:
            p.height = list(VIDEO_HEIGHTS.values())[self.res.get_selected()]
            p.crf = list(VIDEO_QUALITY.values())[self.qual.get_selected()]
            p.mute = self.mute.get_active()
        else:
            p.bitrate = BITRATES[self.bitrate.get_selected()]
            p.mono = self.mono.get_active()
        return p

    # ------------------------------------------------------------ сохранение
    def snapshot(self) -> None:
        src, pos = self.current, self.position()

        def job() -> list[Path]:
            pre, post = frame_args(pos)
            return [ffmpeg(pre, src, post, out_path(src, "png", f"-frame-{int(pos)}s"))]
        self.run_job("Кадр в PNG", job, self.save_button)

    def save_one(self, src: Path) -> Path:
        p = self.ready
        duration, w, h = probe(src)
        if self.video:
            pre, post = video_args(p, duration, w, h)
            return ffmpeg(pre, src, post, out_path(src, "mp4", "-edited"))
        ext, codec = self.ready_format
        pre, post = audio_args(p, codec, ext in ("wav", "flac"), duration)
        return ffmpeg(pre, src, post, out_path(src, ext, "-edited"))
