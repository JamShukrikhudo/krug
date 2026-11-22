"""Тесты логики без GTK и без внешних программ: python3 -m unittest discover -s tests"""
import math
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["KRUG_NO_NOTIFY"] = "1"

from krug import ops, util  # noqa: E402
from krug.geometry import RADIUS, bubble_positions  # noqa: E402
from krug import history, params  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def make(self, name: str, data: bytes = b"x") -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class Names(Base):
    def test_unique_path_never_overwrites(self):
        a = self.make("a.pdf")
        self.assertEqual(util.unique_path(a).name, "a (2).pdf")
        self.make("a (2).pdf")
        self.assertEqual(util.unique_path(a).name, "a (3).pdf")
        self.assertEqual(util.unique_path(self.dir / "new.pdf").name, "new.pdf")

    def test_out_path(self):
        src = self.make("photo.v2.png")
        self.assertEqual(util.out_path(src, "jpg").name, "photo.v2.jpg")
        self.assertEqual(util.out_path(src, None, "-50").name, "photo.v2-50.png")
        self.assertEqual(util.out_path(src, "png").name, "photo.v2 (2).png")


class Kinds(Base):
    def test_kind_of(self):
        self.assertEqual(ops.kind_of([self.make("a.JPG"), self.make("b.heic")]), "image")
        self.assertEqual(ops.kind_of([self.make("a.docx")]), "doc")
        self.assertEqual(ops.kind_of([self.make("a.pdf"), self.make("b.png")]), "mixed")
        self.assertEqual(ops.kind_of([self.dir]), "dir")
        self.assertEqual(ops.kind_of([self.make("a.xyz")]), "other")

    def labels(self, menu, *names):
        return [i.label for i in ops.build_menu(menu, [self.make(n) for n in names])]

    def test_convert_skips_same_format(self):
        labels = self.labels("convert", "a.png")
        self.assertNotIn("PNG", labels)
        self.assertIn("JPEG", labels)
        self.assertIn("PDF", labels)
        self.assertIn("PNG", self.labels("convert", "a.png", "b.jpg"))
        self.assertNotIn("PDF", self.labels("convert", "a.docx", "b.pdf"))

    def test_menus_by_kind(self):
        self.assertEqual(self.labels("convert", "a.xlsx"), ["PDF", "ODS", "CSV"])
        self.assertIn("Объединить", self.labels("tools", "a.pdf", "b.pdf"))
        self.assertNotIn("Объединить", self.labels("tools", "a.pdf"))
        self.assertEqual(self.labels("tools", "a.zip"), ["Распаковать"])
        self.assertEqual(ops.build_menu("tools", [self.make("a.mp4")])[0].editor, "video")
        self.assertEqual(ops.build_menu("tools", [self.make("a.pdf")])[0].editor, "pdf")
        self.assertTrue(all(i.icon for i in ops.build_menu("actions", [self.make("a.png")])))
        self.assertEqual(self.labels("tools", "a.xyz"), ["Архив ZIP"])
        self.assertEqual(self.labels("convert", "a.xyz"), [])
        self.assertIn("Удалить фон", self.labels("actions", "a.png"))
        self.assertNotIn("Удалить фон", self.labels("actions", "a.pdf"))
        self.assertEqual(ops.build_menu("actions", []), [])


class Commands(Base):
    """Проверяем, какие команды уходят во внешние программы, подменив запуск."""

    def setUp(self):
        super().setUp()
        self.calls = []
        originals = (ops.run, ops.need, ops.which)

        def fake_run(cmd, **_kw):
            cmd = [str(c) for c in cmd]
            self.calls.append(cmd)
            for arg in cmd:  # создаём результат, как это сделала бы программа
                if arg.startswith("-sOutputFile="):
                    Path(arg.split("=", 1)[1]).write_bytes(b"out")
            if "--outdir" in cmd:
                Path(cmd[cmd.index("--outdir") + 1], "produced.pdf").write_bytes(b"out")

        ops.run, ops.need, ops.which = fake_run, (lambda *n, hint="": n[0]), (lambda *n: None)
        self.addCleanup(lambda: [setattr(ops, k, v) for k, v in zip(("run", "need", "which"), originals)])

    def test_image_to_jpeg_flattens_alpha(self):
        src = self.make("a.png")
        dst = ops.image_convert("jpg")(src)
        cmd = self.calls[0]
        self.assertEqual((cmd[0], cmd[1], cmd[-1]), ("magick", str(src), str(dst)))
        self.assertIn("remove", cmd)
        self.assertEqual(dst.name, "a.jpg")

    def test_office_convert_moves_result_next_to_source(self):
        src = self.make("report.docx")
        self.make("report.pdf")
        dst = ops.office_convert("pdf")(src)
        self.assertEqual(dst.name, "report (2).pdf")
        self.assertTrue(dst.exists())
        self.assertEqual([p.name for p in self.dir.iterdir() if p.name.startswith("krug-tmp-")], [])
        self.assertIn("--headless", self.calls[0])

    def test_pdf_merge_and_ffmpeg(self):
        a, b = self.make("a.pdf"), self.make("b.pdf")
        (dst,) = ops.pdf_merge([a, b])
        self.assertEqual(self.calls[0], ["qpdf", "--empty", "--pages", str(a), str(b), "--", str(dst)])
        with self.assertRaises(util.OpError):
            ops.pdf_merge([a])
        video = self.make("clip.mov")
        out = ops.ffmpeg_op(ops.VIDEO_ARGS["mp4"], "mp4")(video)
        self.assertEqual(self.calls[-1][-1], str(out))
        self.assertIn(str(video), self.calls[-1])

    def test_execute_collects_errors_per_file(self):
        def boom(src):
            raise util.OpError("сломалось")
        results, errors = ops.execute(ops.Item("X", each=boom), [self.make("a.png"), self.make("b.png")])
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 2)
        self.assertEqual(ops.execute(ops.Item("X", missing="поставьте Y"), [self.dir]), ([], ["поставьте Y"]))


class Files(Base):
    def test_zip_roundtrip(self):
        folder = self.dir / "docs"
        self.make("docs/a.txt", b"A")
        self.make("docs/sub/b.txt", b"B")
        (archive,) = ops.zip_files([folder])
        self.assertEqual(archive.name, "docs.zip")
        out = ops.unzip(archive)
        self.assertEqual(out.name, "docs (2)")
        self.assertEqual((out / "docs/sub/b.txt").read_bytes(), b"B")

    def test_unzip_rejects_path_traversal(self):
        bad = self.dir / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../evil.txt", "x")
        with self.assertRaises(util.OpError):
            ops.unzip(bad)
        self.assertFalse((self.dir / "bad").exists())
        self.assertFalse((self.dir.parent / "evil.txt").exists())

    def test_unzip_rejects_symlinks(self):
        bad = self.dir / "link.zip"
        info = zipfile.ZipInfo("link")
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr(info, "/etc/passwd")
        with self.assertRaises(util.OpError):
            ops.unzip(bad)

    def test_copy_move_duplicate_keep_originals(self):
        src = self.make("a.txt", b"data")
        target = self.dir / "to"
        target.mkdir()
        self.make("to/a.txt", b"old")
        (copied,) = ops.copy_to([src], target)
        self.assertEqual(copied.name, "a (2).txt")
        self.assertEqual((target / "a.txt").read_bytes(), b"old")
        self.assertEqual(ops.duplicate(src).name, "a (копия).txt")
        (moved,) = ops.move_to([src], target)
        self.assertFalse(src.exists())
        self.assertEqual(moved.read_bytes(), b"data")


class Ring(unittest.TestCase):
    def test_bubble_positions(self):
        pts = bubble_positions(4, 500, 400)
        expected = [(500, 400 - RADIUS), (500 + RADIUS, 400), (500, 400 + RADIUS), (500 - RADIUS, 400)]
        for (x, y), (ex, ey) in zip(pts, expected):
            self.assertAlmostEqual(x, ex)
            self.assertAlmostEqual(y, ey)
        for count in range(1, 9):
            for x, y in bubble_positions(count, 0, 0):
                self.assertAlmostEqual(math.hypot(x, y), RADIUS)


class Params(unittest.TestCase):
    def test_image_args(self):
        p = params.ImageParams(crop=(0.25, 0.5, 0.5, 0.25), rotate=90, brightness=10, saturation=150, border=20)
        args = params.image_args(p, 2000, 1000)
        self.assertEqual(args[:3], ["-crop", "1000x250+500+500", "+repage"])
        self.assertIn("-rotate", args)
        self.assertIn("10x0", args)
        self.assertIn("100,150,100", args)
        self.assertEqual(args[-1], "20")
        preview = params.image_args(p, 2000, 1000, scale=0.5)
        self.assertEqual(preview[1], "500x125+250+250")
        self.assertEqual(preview[-1], "10")
        self.assertEqual(params.image_args(params.ImageParams(), 10, 10), [])
        self.assertEqual(params.image_args(params.ImageParams(width=800), 10, 10)[-1], "800x")
        self.assertEqual(params.image_args(params.ImageParams(width=800, height=600, keep_ratio=False), 10, 10)[-1],
                         "800x600!")

    def test_fit_and_drag(self):
        self.assertEqual(params.fit_rect(400, 400, 200, 100), (0, 100, 400, 200))
        rect = (0, 100, 400, 200)
        self.assertEqual(params.drag_to_crop(rect, 300, 250, 100, 150), (0.25, 0.25, 0.5, 0.5))
        self.assertEqual(params.drag_to_crop(rect, -50, 0, 500, 900), (0.0, 0.0, 1.0, 1.0))
        self.assertIsNone(params.drag_to_crop(rect, 10, 110, 12, 112))

    def test_video_args(self):
        p = params.MediaParams(start=2, end=5, speed=2.0, height=720, crf=24, crop=(0.1, 0.1, 0.5, 0.5))
        pre, post = params.video_args(p, duration=10, src_w=1920, src_h=1080)
        self.assertEqual(pre, ["-ss", "2.000", "-to", "5.000"])
        vf = post[post.index("-vf") + 1]
        self.assertEqual(vf, "crop=960:540:192:108,scale=-2:720,setpts=PTS/2")
        self.assertIn("atempo=2", post)
        pre, post = params.video_args(params.MediaParams(end=10, mute=True), duration=10)
        self.assertEqual(pre, [])
        self.assertIn("-an", post)
        with self.assertRaises(util.OpError):
            params.video_args(params.MediaParams(start=5, end=3))
        with self.assertRaises(util.OpError):
            params.video_args(params.MediaParams(crop=(0, 0, 1, 1)))
        self.assertEqual(params.crop_filter((0.9, 0.9, 0.5, 0.5), 101, 101), "crop=50:50:51:51")

    def test_audio_args(self):
        pre, post = params.audio_args(params.MediaParams(mono=True, bitrate="128k", speed=1.5), ["-c:a", "libmp3lame"],
                                      lossless=False)
        self.assertEqual(post, ["-vn", "-c:a", "libmp3lame", "-b:a", "128k", "-ac", "1", "-af", "atempo=1.5"])
        _pre, post = params.audio_args(params.MediaParams(), [], lossless=True)
        self.assertNotIn("-b:a", post)

    def test_parse_pages(self):
        self.assertEqual(params.parse_pages(" 3, 1 ,2 ", 3), "3,1,2")
        self.assertEqual(params.parse_pages("1-4,7", 9), "1-4,7")
        for bad in ("", "a", "1,,2", "0", "10"):
            with self.assertRaises(util.OpError):
                params.parse_pages(bad, 9)


class History(Base):
    def test_history_roundtrip(self):
        os.environ["XDG_STATE_HOME"] = str(self.dir)
        self.addCleanup(os.environ.pop, "XDG_STATE_HOME")
        self.assertEqual(history.load(), [])
        history.add("PDF", [self.dir / "a.pdf"], [])
        history.add("Сжать", [], ["ошибка"])
        history.add("Ничего", [], [])
        entries = history.load()
        self.assertEqual([e["label"] for e in entries], ["Сжать", "PDF"])
        self.assertEqual(entries[0]["error"], "ошибка")
        history.history_file().write_text("{broken", encoding="utf-8")
        self.assertEqual(history.load(), [])
        history.clear()
        self.assertFalse(history.history_file().exists())


if __name__ == "__main__":
    unittest.main()
