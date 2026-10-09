#!/usr/bin/env python3
"""P0 spike: does libmpv rendering into a QOpenGLWidget work reliably on this machine (Ubuntu 24.04, GNOME, Wayland)?

    python3 spikes/p0_qt_mpv.py FILE_OR_URL [--hwdec no|auto-safe] [--platform wayland|xcb|offscreen] [--seconds 20] [--out DIR]

Plays, pauses, resumes, seeks forward/back, resizes, toggles fullscreen; after each step grabs the real GL framebuffer to a PNG
and checks that it is not blank and that frames differ after a seek. Prints one JSON result line. Audio output is disabled.
"""
import argparse, ctypes, json, os, sys, time
os.environ.setdefault("LC_NUMERIC", "C")                      # libmpv requires the C numeric locale
p = argparse.ArgumentParser(); p.add_argument("src"); p.add_argument("--hwdec", default="no"); p.add_argument("--platform", default="")
p.add_argument("--seconds", type=float, default=20); p.add_argument("--out", default="/tmp/p0"); a = p.parse_args()
if a.platform:
    os.environ["QT_QPA_PLATFORM"] = a.platform
from PyQt6.QtCore import QByteArray, QTimer, pyqtSignal, Qt
from PyQt6.QtGui import QImage, QSurfaceFormat, QOpenGLContext
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QApplication, QMainWindow
import mpv

fmt = QSurfaceFormat(); fmt.setVersion(3, 3); fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile); fmt.setSwapInterval(1)
QSurfaceFormat.setDefaultFormat(fmt)


class MpvWidget(QOpenGLWidget):
    frame_ready = pyqtSignal()

    def __init__(self, hwdec):
        super().__init__()
        self.mpv = mpv.MPV(vo="libmpv", ao="null", hwdec=hwdec, input_default_bindings=False, input_vo_keyboard=False, osc=False,
                           keep_open="yes", log_handler=self._log, loglevel="warn")
        self.ctx = None
        self.logs = []
        self.frame_ready.connect(self.update)
        self.renders = 0

    def _log(self, level, prefix, text):
        if level in ("error", "fatal", "warn"):
            self.logs.append(f"{level}:{prefix}:{text.strip()}"[:160])

    def initializeGL(self):
        def get_proc(_ctx, name):
            gl = QOpenGLContext.currentContext()
            return ctypes.cast(int(gl.getProcAddress(QByteArray(name))), ctypes.c_void_p).value
        self._get_proc = mpv.MpvGlGetProcAddressFn(get_proc)          # keep a reference: mpv calls it later
        self.ctx = mpv.MpvRenderContext(self.mpv, "opengl", opengl_init_params={"get_proc_address": self._get_proc})
        self.ctx.update_cb = self.frame_ready.emit                    # called from mpv's thread: must only emit a signal

    def paintGL(self):
        if self.ctx is None:
            return
        r = self.devicePixelRatioF()
        self.ctx.render(flip_y=True, opengl_fbo={"w": int(self.width() * r), "h": int(self.height() * r), "fbo": self.defaultFramebufferObject()})
        self.renders += 1

    def shutdown(self):
        self.makeCurrent()
        if self.ctx is not None:
            self.ctx.free(); self.ctx = None
        self.mpv.terminate()


def stats(img: QImage):
    img = img.convertToFormat(QImage.Format.Format_RGB32)
    w, h = img.width(), img.height(); step = max(1, w // 64)
    px = [img.pixel(x, y) & 0xFFFFFF for y in range(0, h, step) for x in range(0, w, step)]
    nonblack = sum(1 for v in px if v > 0x0A0A0A) / len(px)
    return nonblack, hash(tuple(px[::7]))


app = QApplication(sys.argv)
win = QMainWindow(); win.setWindowTitle("P0 libmpv spike"); w = MpvWidget(a.hwdec); win.setCentralWidget(w); win.resize(800, 450); win.show()
os.makedirs(a.out, exist_ok=True)
res = {"platform": app.platformName(), "hwdec": a.hwdec, "src": a.src, "steps": {}, "ok": True}
t0 = time.time()


def snap(name):
    img = w.grabFramebuffer(); nb, hsh = stats(img); img.save(f"{a.out}/{name}.png")
    pos = w.mpv.time_pos
    res["steps"][name] = {"nonblack": round(nb, 2), "hash": hsh, "time_pos": None if pos is None else round(pos, 2), "size": [img.width(), img.height()],
                          "renders": w.renders, "dropped": w.mpv.frame_drop_count, "vo_delayed": w.mpv.vo_delayed_frame_count}


seq = []
def at(sec, fn):
    seq.append((sec, fn))

state = {"h": None}
at(0.5, lambda: w.mpv.play(a.src))
at(5, lambda: snap("1_playing"))
at(5.2, lambda: setattr(w.mpv, "pause", True))
at(6.2, lambda: snap("2_paused"))
at(6.3, lambda: setattr(w.mpv, "pause", False))
at(6.4, lambda: w.mpv.command("seek", 60, "absolute"))
at(9, lambda: snap("3_after_seek_fwd"))
at(9.1, lambda: w.mpv.command("seek", 10, "absolute"))
at(11.5, lambda: snap("4_after_seek_back"))
at(11.6, lambda: win.resize(1000, 560))
at(13, lambda: snap("5_resized"))
at(13.1, win.showFullScreen)
at(15, lambda: snap("6_fullscreen"))
at(15.1, win.showNormal)
at(17, lambda: snap("7_back_to_window"))
at(a.seconds - 0.5, lambda: res.update(fps=w.mpv.estimated_vf_fps, vo=str(w.mpv.current_vo), hwdec_current=str(w.mpv.hwdec_current),
                                       logs=w.logs[:6], renders=w.renders))


def tick():
    el = time.time() - t0
    while seq and seq[0][0] <= el:
        _, fn = seq.pop(0)
        try:
            fn()
        except Exception as e:
            res["ok"] = False; res.setdefault("errors", []).append(f"{type(e).__name__}: {e}")
    if el > a.seconds:
        timer.stop(); finish()


def finish():
    s = res["steps"]
    if not s:
        res["ok"] = False
    for k, v in s.items():
        if v["nonblack"] < 0.05 and k != "2_paused":
            res["ok"] = False; res.setdefault("errors", []).append(f"{k}: blank frame")
    if "1_playing" in s and "3_after_seek_fwd" in s and s["1_playing"]["hash"] == s["3_after_seek_fwd"]["hash"]:
        res["ok"] = False; res.setdefault("errors", []).append("frame did not change after seek")
    if "3_after_seek_fwd" in s and (s["3_after_seek_fwd"]["time_pos"] or 0) < 58:
        res["ok"] = False; res.setdefault("errors", []).append("seek forward did not land")
    res["seconds"] = round(time.time() - t0, 1)
    w.shutdown(); print("RESULT " + json.dumps(res), flush=True); app.quit()


timer = QTimer(); timer.timeout.connect(tick); timer.start(50)
sys.exit(app.exec())
