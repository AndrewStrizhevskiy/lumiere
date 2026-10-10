# SPDX-License-Identifier: GPL-3.0-or-later
"""libmpv rendered into a QOpenGLWidget (validated in P0 on Ubuntu 24.04 / GNOME / Wayland).

Rules that keep it stable: LC_NUMERIC=C before mpv is created; flip_y=True; mpv's update callback runs on mpv's own thread and
only emits a Qt signal; the render context is freed with the GL context current. mpv is only ever read from the GUI thread
(polling), never from its callbacks, except the end-file hook that just emits a signal."""
from __future__ import annotations

import ctypes
import logging
import os

from PyQt6.QtCore import QByteArray, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QOpenGLContext, QSurfaceFormat
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtWidgets import QWidget

os.environ.setdefault("LC_NUMERIC", "C")
log = logging.getLogger("lumiere.ui.mpv")

try:
    import mpv
except Exception as _e:                                  # python-mpv or libmpv missing
    mpv = None
    MPV_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"
else:
    MPV_IMPORT_ERROR = ""


def set_default_surface_format() -> None:
    """Must run before the QApplication exists."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(fmt)


class MpvWidget(QOpenGLWidget):
    frameReady = pyqtSignal()
    fileEnded = pyqtSignal(str, str)               # reason ("eof", "error", "stop"...), error text

    def __init__(self, options: dict | None = None, parent=None):
        super().__init__(parent)
        self.mpv = None
        self.ctx = None
        self.error = MPV_IMPORT_ERROR
        self.renders = 0
        self.logs: list[str] = []
        self.frameReady.connect(self.update)
        if mpv is None:
            return
        opts = dict(vo="libmpv", hwdec="auto-safe", input_default_bindings=False, input_vo_keyboard=False, osc=False, idle="yes",
                    keep_open="yes", log_handler=self._log, loglevel="warn")
        opts.update(options or {})
        try:
            self.mpv = mpv.MPV(**opts)
            self.mpv.event_callback("end-file")(self._on_end_file)
        except Exception as e:
            self.mpv = None
            self.error = f"{type(e).__name__}: {e}"

    @property
    def available(self) -> bool:
        return self.mpv is not None

    def _log(self, level, prefix, text):
        if level in ("error", "fatal", "warn"):
            self.logs = (self.logs + [f"{level}:{prefix}:{text.strip()}"[:200]])[-30:]

    def _on_end_file(self, event):                 # mpv's thread: extract plain values, emit a signal, nothing else
        try:
            d = event.as_dict() if hasattr(event, "as_dict") else {}
            ev = d
            reason = ev.get("reason", b"")
            reason = reason.decode() if isinstance(reason, bytes) else str(reason)
            err = ev.get("file_error", "")
            err = err.decode() if isinstance(err, bytes) else str(err or "")
            self.fileEnded.emit(reason.lower(), err)
        except Exception:
            log.exception("end-file handler")

    # -------------------------------------------------------------------------------------------------- GL
    def initializeGL(self):
        if self.mpv is None:
            return

        def get_proc(_ctx, name):
            gl = QOpenGLContext.currentContext()
            return ctypes.cast(int(gl.getProcAddress(QByteArray(name))), ctypes.c_void_p).value
        self._get_proc = mpv.MpvGlGetProcAddressFn(get_proc)
        self.ctx = mpv.MpvRenderContext(self.mpv, "opengl", opengl_init_params={"get_proc_address": self._get_proc})
        self.ctx.update_cb = self.frameReady.emit

    def paintGL(self):
        if self.ctx is None:
            return
        r = self.devicePixelRatioF()
        self.ctx.render(flip_y=True, opengl_fbo={"w": int(self.width() * r), "h": int(self.height() * r), "fbo": self.defaultFramebufferObject()})
        self.renders += 1

    # ----------------------------------------------------------------------------------------------- control
    def get(self, name: str, default=None):
        if self.mpv is None:
            return default
        try:
            v = getattr(self.mpv, name.replace("-", "_"))
            return default if v is None else v
        except Exception:
            return default

    def set(self, name: str, value) -> None:
        if self.mpv is not None:
            try:
                setattr(self.mpv, name.replace("-", "_"), value)
            except Exception:
                log.exception("set %s", name)

    def command(self, *args) -> None:
        if self.mpv is not None:
            try:
                self.mpv.command(*args)
            except Exception:
                log.exception("command %s", args)

    def load(self, url: str, start: float = 0.0, title: str = "") -> None:
        opts = {}
        if start > 1:
            opts["start"] = f"{start:.1f}"
        if title:
            opts["force-media-title"] = title
        if self.mpv is not None:
            self.mpv.loadfile(url, **{k.replace("-", "_"): v for k, v in opts.items()})

    def stop(self) -> None:
        self.command("stop")

    def shutdown(self) -> None:
        if self.mpv is None:
            return
        try:
            self.makeCurrent()
            if self.ctx is not None:
                self.ctx.free()
                self.ctx = None
            self.doneCurrent()
        except Exception:
            log.exception("freeing render context")
        try:
            self.mpv.terminate()
        finally:
            self.mpv = None


class NullVideo(QWidget):
    """Stands in where OpenGL video cannot work (the 'offscreen'/'minimal' Qt platforms used for headless GUI tests)."""
    fileEnded = pyqtSignal(str, str)
    available = False
    renders = 0
    logs: list = []

    def __init__(self, options=None, parent=None):
        super().__init__(parent)
        self.error = "OpenGL video output is not available on this display platform."

    def get(self, name, default=None):
        return default

    def set(self, name, value):
        pass

    def command(self, *a):
        pass

    def load(self, *a, **k):
        pass

    def stop(self):
        pass

    def shutdown(self):
        pass


def make_video(options: dict | None, parent=None):
    if QGuiApplication.platformName() in ("offscreen", "minimal"):
        return NullVideo(options, parent)
    return MpvWidget(options, parent)
