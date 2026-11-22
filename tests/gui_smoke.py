"""Проверка интерфейса в CI: открывает каждое окно, снимает скриншот, сохраняет результаты редакторов.

Запуск (нужны GTK4, libadwaita, Xvfb и ImageMagick):
    xvfb-run -a -s "-screen 0 1366x850x24" env GDK_BACKEND=x11 python3 tests/gui_smoke.py ASSETS SHOTS
ASSETS должна содержать photo.jpg, clip.mp4, sound.mp3, doc.pdf.
"""
from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["KRUG_NO_NOTIFY"] = "1"
os.environ["XDG_STATE_HOME"] = str(Path(sys.argv[2]).resolve() / "state")

from krug import ops  # noqa: E402
from krug.app import MainWindow  # noqa: E402
from krug.editors import open_editor  # noqa: E402
from krug.menu import RadialMenu  # noqa: E402
from krug.ui import Adw, Gio, GLib, Gtk, load_css  # noqa: E402

ASSETS = Path(sys.argv[1]).resolve()
SHOTS = Path(sys.argv[2]).resolve()
SHOTS.mkdir(parents=True, exist_ok=True)
errors: list[str] = []


def excepthook(kind, value, tb):
    errors.append("".join(traceback.format_exception(kind, value, tb)))
    sys.__excepthook__(kind, value, tb)


sys.excepthook = excepthook
photo, clip, sound, pdf = (ASSETS / n for n in ("photo.jpg", "clip.mp4", "sound.mp3", "doc.pdf"))


def menu(app, name, files, then=None):
    items = ops.build_menu(name, files)
    window = RadialMenu(app, ops.MENU_TITLES[name], items, files)
    if then:
        GLib.timeout_add(900, lambda: then(window) and False)
    return window


def editor(app, kind, files, then=None):
    window = open_editor(app, kind, files)
    if then:
        GLib.timeout_add(1800, lambda: then(window) and False)
    return window


def open_submenu(window):
    index = next(i for i, item in enumerate(window.visible_items) if item.children)
    window.activate_item(index)


def tune_image(w):
    w.bright.scale.set_value(25)
    w.sat.scale.set_value(140)
    w.on_crop((0.1, 0.15, 0.7, 0.6))
    w.rotate(90)
    w.border.set_value(30)
    GLib.timeout_add(1500, lambda: w.save() and False)


def crop_mode(w):
    w.on_crop((0.2, 0.2, 0.5, 0.5))
    w.crop_toggle.set_active(True)


def tune_video(w):
    w.start.set_value(1)
    w.end.set_value(3)
    w.res.set_selected(2)
    w.crop_switch.set_active(True)
    w.on_crop((0.1, 0.1, 0.6, 0.6))
    w.save()


def tune_audio(w):
    w.end.set_value(2)
    w.mono.set_active(True)
    w.save()


def pick_pages(w):
    w.order.set_text("3,1")
    GLib.timeout_add(300, lambda: w.drop_pages() and False)


def icon_gallery(app):
    window = Gtk.ApplicationWindow(application=app, title="Иконки krug", default_width=900, default_height=600)
    flow = Gtk.FlowBox(max_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE, margin_start=12,
                       margin_end=12, margin_top=12)
    folder = ROOT / "krug" / "icons" / "hicolor" / "scalable" / "actions"
    for svg in sorted(folder.glob("krug-*-symbolic.svg")):
        name = svg.name[:-len(".svg")]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.append(Gtk.Image(icon_name=name, pixel_size=32))
        box.append(Gtk.Label(label=name[5:-9], css_classes=["caption"]))
        flow.append(box)
    window.set_child(Gtk.ScrolledWindow(child=flow))
    return window


STEPS = [
    ("00-icons", icon_gallery),
    ("01-main", lambda app: MainWindow(app)),
    ("02-main-components", lambda app: (lambda w: (w.stack.set_visible_child_name("components"), w)[1])(MainWindow(app))),
    ("03-menu-convert", lambda app: menu(app, "convert", [photo])),
    ("04-menu-tools", lambda app: menu(app, "tools", [photo])),
    ("05-menu-submenu", lambda app: menu(app, "tools", [photo], open_submenu)),
    ("06-menu-actions", lambda app: menu(app, "actions", [photo, pdf])),
    ("07-menu-video", lambda app: menu(app, "tools", [clip])),
    ("08-editor-image", lambda app: editor(app, "image", [photo], tune_image)),
    ("09-editor-image-crop", lambda app: editor(app, "image", [photo], crop_mode)),
    ("10-editor-video", lambda app: editor(app, "video", [clip], tune_video)),
    ("11-editor-audio", lambda app: editor(app, "audio", [sound], tune_audio)),
    ("12-editor-pdf", lambda app: editor(app, "pdf", [pdf], pick_pages)),
    ("13-main-history", lambda app: (lambda w: (w.stack.set_visible_child_name("history"), w)[1])(MainWindow(app))),
]
EXPECTED = ["photo-edited.jpg", "clip-edited.mp4", "sound-edited.mp3", "doc-trimmed.pdf"]


class SmokeApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.krug.Smoke", flags=Gio.ApplicationFlags.NON_UNIQUE)
        self.steps = list(STEPS)
        self.window = None

    def do_activate(self):
        load_css()
        self.hold()
        GLib.timeout_add(300, self.next)

    def next(self):
        for window in list(self.get_windows()):
            window.destroy()
        if not self.steps:
            self.release()
            self.quit()
            return False
        name, make = self.steps.pop(0)
        print("step", name, flush=True)
        try:
            self.window = make(self)
            self.window.present()
        except Exception:  # noqa: BLE001
            excepthook(*sys.exc_info())
        GLib.timeout_add(6000 if "editor" in name else 2500, self.shoot, name)
        return False

    def shoot(self, name):
        subprocess.run(["import", "-window", "root", str(SHOTS / f"{name}.png")], check=False)
        GLib.idle_add(self.next)
        return False


SmokeApp().run([])
missing = [n for n in EXPECTED if not (ASSETS / n).exists()]
print("created:", sorted(p.name for p in ASSETS.iterdir()))
if missing:
    errors.append(f"editors did not create: {missing}")
for e in errors:
    print("ERROR:", e, file=sys.stderr)
sys.exit(1 if errors else 0)
