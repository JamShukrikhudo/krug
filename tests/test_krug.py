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
from krug.geometry import R_IN, R_OUT, sector_index  # noqa: E402


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
    def test_sector_index(self):
        mid = (R_IN + R_OUT) / 2
        self.assertEqual(sector_index(0, 0, 4), -1)
        self.assertIsNone(sector_index(R_OUT + 5, 0, 4))
        self.assertIsNone(sector_index(mid, 0, 0))
        self.assertEqual(sector_index(0, -mid, 4), 0)  # сверху
        self.assertEqual(sector_index(mid, 0, 4), 1)   # справа
        self.assertEqual(sector_index(0, mid, 4), 2)   # снизу
        self.assertEqual(sector_index(-mid, 0, 4), 3)  # слева
        self.assertEqual(sector_index(mid * math.cos(1), mid * math.sin(1), 1), 0)
        for count in range(1, 9):
            for deg in range(0, 360, 7):
                i = sector_index(mid * math.cos(math.radians(deg)), mid * math.sin(math.radians(deg)), count)
                self.assertTrue(0 <= i < count)


if __name__ == "__main__":
    unittest.main()
