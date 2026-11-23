// Ctrl+Alt+1/2/3 для значков рабочего стола.
//
// Значки рисует расширение Desktop Icons NG (DING); сочетаний скриптов «Файлов» оно не знает
// и превращает Ctrl+Alt+1 в поиск по «1». Поэтому, пока в фокусе окно рабочего стола, мы сами
// перехватываем эти клавиши и просим DING запустить скрипт krug через его действие
// onScriptClicked: DING передаёт скрипту выделенные значки так же, как «Файлы».
// Когда в фокусе любое другое окно, клавиши не перехватываются и достаются «Файлам».
//
// Второе: окно кольца krug (io.github.krug.Menu) ставится под указатель мыши и поверх
// остальных. Обычной программе на Wayland так делать нельзя, расширению можно.
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Mtk from 'gi://Mtk';
import Shell from 'gi://Shell';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

const DING_ID = 'com.desktop.ding';
const RING_ID = 'io.github.krug.Menu';
const KEYS = [
    ['<Control><Alt>1', 'krug — Конвертация'],
    ['<Control><Alt>2', 'krug — Инструменты'],
    ['<Control><Alt>3', 'krug — Действия'],
];

export default class KrugExtension extends Extension {
    enable() {
        this._grabbed = new Map();
        this._focusId = global.display.connect('notify::focus-window', () => this._sync());
        this._accelId = global.display.connect('accelerator-activated', (_display, action) => {
            const script = this._grabbed.get(action)?.script;
            if (script)
                this._runOnDesktop(script);
        });
        this._createdId = global.display.connect('window-created', (_display, window) => {
            if (window.get_gtk_application_id?.() === RING_ID)
                this._placeRing(window);
        });
        this._sync();
    }

    disable() {
        global.display.disconnect(this._focusId);
        global.display.disconnect(this._accelId);
        global.display.disconnect(this._createdId);
        this._ungrab();
        this._grabbed = null;
    }

    _desktopFocused() {
        const window = global.display.focus_window;
        return Boolean(window && window.get_gtk_application_id?.() === DING_ID);
    }

    _sync() {
        const want = this._desktopFocused();
        if (want && this._grabbed.size === 0)
            this._grab();
        else if (!want && this._grabbed.size > 0)
            this._ungrab();
    }

    _grab() {
        for (const [accel, script] of KEYS) {
            const action = global.display.grab_accelerator(accel, Meta.KeyBindingFlags.NONE);
            if (action === Meta.KeyBindingAction.NONE)
                continue;
            const name = Meta.external_binding_name_for_action(action);
            Main.wm.allowKeybinding(name, Shell.ActionMode.NORMAL);
            this._grabbed.set(action, {name, script});
        }
    }

    _ungrab() {
        for (const [action, {name}] of this._grabbed) {
            global.display.ungrab_accelerator(action);
            Main.wm.allowKeybinding(name, Shell.ActionMode.NONE);
        }
        this._grabbed.clear();
    }

    _placeRing(window) {
        // координаты указателя берём сразу, пока пользователь не сдвинул мышь
        const [px, py] = global.get_pointer();
        const actor = window.get_compositor_private();
        const move = () => {
            const rect = window.get_frame_rect();
            const monitor = global.display.get_monitor_index_for_rect(
                new Mtk.Rectangle({x: px, y: py, width: 1, height: 1}));
            const area = window.get_work_area_for_monitor(monitor >= 0 ? monitor : window.get_monitor());
            const x = Math.min(Math.max(px - rect.width / 2, area.x), area.x + area.width - rect.width);
            const y = Math.min(Math.max(py - rect.height / 2, area.y), area.y + area.height - rect.height);
            window.move_frame(true, Math.round(x), Math.round(y));
            window.make_above();
            Main.activateWindow(window);
        };
        // окно ещё без размера: ждём первый кадр (или показ), потом двигаем один раз
        let done = false;
        const once = () => {
            if (!done) {
                done = true;
                move();
            }
        };
        if (actor)
            actor.connect('first-frame', once);
        window.connect('shown', once);
    }

    _runOnDesktop(script) {
        const path = GLib.build_filenamev([GLib.get_user_data_dir(), 'nautilus', 'scripts', script]);
        const params = new GLib.Variant('(sava{sv})', ['onScriptClicked', [new GLib.Variant('s', path)], {}]);
        Gio.DBus.session.call(DING_ID, '/com/desktop/ding', 'org.gtk.Actions', 'Activate', params,
            null, Gio.DBusCallFlags.NONE, -1, null, (connection, result) => {
                try {
                    connection.call_finish(result);
                } catch (e) {
                    console.error(`krug: рабочий стол не запустил «${script}»: ${e.message}`);
                    Main.notify('krug', 'Рабочий стол не принял команду. Используйте правый клик → Скрипты');
                }
            });
    }
}
