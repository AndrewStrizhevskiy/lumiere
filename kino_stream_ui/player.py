"""Playback screen: embedded libmpv video, controls, availability seek bar, track menus, buffering feedback, connection panel."""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QActionGroup, QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QMenu, QSlider, QToolTip, QVBoxLayout, QWidget

from kino_stream.scheduler import PlayerState

from . import theme as T
from .icons import icon
from .messages import tr
from .mpvwidget import MPV_IMPORT_ERROR, make_video
from .widgets import AnimatedBar, Spinner, button, fmt_bytes, fmt_speed, fmt_time, icon_button, label

POLL_MS = 250
HIDE_AFTER_MS = 3000
SAVE_EVERY_S = 5.0
AVAIL_EVERY_S = 1.5
SHOW_WAIT_AFTER_S = 0.4          # a wait shorter than this is not worth a message


def menu_text(s: str) -> str:
    return (s or "").replace("&", "&&")        # titles come from the file: never let them define mnemonics


class SeekBar(QWidget):
    """Seek bar with three layers: track (not downloaded) / grey (on disk, from the engine) / amber (played). The grey layer is
    by FILE position, the bar is by TIME, so it is exact for constant-bitrate video and approximate otherwise."""
    seekRequested = pyqtSignal(float)              # fraction 0..1
    hoverText = pyqtSignal(str)

    H = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.value = 0.0
        self.bins: list[float] = []
        self.duration = 0.0
        self._drag = False
        self._hover: float | None = None
        self.setAccessibleName(tr("Seek bar", "Player"))
        self.setAccessibleDescription(tr("Grey parts of the bar are already downloaded; the dark parts still have to be fetched.", "Player"))

    def set_bins(self, bins: list[float]) -> None:
        self.bins = list(bins)
        self.update()

    def set_value(self, v: float) -> None:
        if not self._drag:
            self.value = min(max(v, 0.0), 1.0)
            self.update()

    def on_disk(self, frac: float) -> float | None:
        if not self.bins:
            return None
        return self.bins[min(len(self.bins) - 1, max(0, int(frac * len(self.bins))))]

    def _frac(self, x: float) -> float:
        return min(max((x - 8) / max(self.width() - 16, 1), 0.0), 1.0)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self.value = self._frac(e.position().x())
            self.update()

    def mouseMoveEvent(self, e):
        f = self._frac(e.position().x())
        self._hover = f
        if self._drag:
            self.value = f
        d = self.on_disk(f)
        t = fmt_time(f * self.duration) if self.duration else ""
        note = "" if d is None else (tr("downloaded", "Player") if d >= 0.99 else tr("partly downloaded", "Player") if d > 0 else tr("not downloaded yet", "Player"))
        QToolTip.showText(e.globalPosition().toPoint(), f"{t}  ·  {note}" if note else t, self)
        self.update()

    def mouseReleaseEvent(self, e):
        if self._drag and e.button() == Qt.MouseButton.LeftButton:
            self._drag = False
            self.seekRequested.emit(self._frac(e.position().x()))

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x0, w = 8.0, max(self.width() - 16.0, 1.0)
        cy, th = self.height() / 2, 6.0 if self._hover is None and not self._drag else 8.0
        track = QRectF(x0, cy - th / 2, w, th)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(T.TRACK))
        p.drawRoundedRect(track, th / 2, th / 2)
        if self.bins:                                   # downloaded sections
            n = len(self.bins)
            p.save()
            clip = __import__("PyQt6.QtGui", fromlist=["QPainterPath"]).QPainterPath()
            clip.addRoundedRect(track, th / 2, th / 2)
            p.setClipPath(clip)
            for i, f in enumerate(self.bins):
                if f <= 0:
                    continue
                c = QColor(T.AVAILABLE)
                c.setAlphaF(1.0 if f >= 0.99 else 0.35 + 0.4 * f)
                p.setBrush(c)
                a = x0 + w * i / n
                p.drawRect(QRectF(a, track.top(), w / n + 0.6, th))
            p.restore()
        px = x0 + w * self.value
        p.setBrush(QColor(T.ACCENT))
        p.drawRoundedRect(QRectF(x0, track.top(), max(px - x0, 0), th), th / 2, th / 2)
        p.setBrush(QColor(T.TEXT))
        p.drawEllipse(QPointF(px, cy), 7 if (self._hover is not None or self._drag) else 5.5, 7 if (self._hover is not None or self._drag) else 5.5)


class OverlayBar(QFrame):
    """Translucent strip over the video."""

    def __init__(self, top: bool, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        a, b = ("rgba(14,15,18,215)", "rgba(14,15,18,0)") if top else ("rgba(14,15,18,0)", "rgba(14,15,18,225)")
        self.setStyleSheet(f"OverlayBar {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {a}, stop:1 {b}); border:none; }}")


class PlayerScreen(QWidget):
    backRequested = pyqtSignal()
    fullscreenRequested = pyqtSignal(bool)
    diagnosticsRequested = pyqtSignal()
    networkCheckRequested = pyqtSignal()

    def __init__(self, bridge=None, mpv_options: dict | None = None, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.setObjectName("root")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.media = None
        self.snap: dict = {}
        self.fetch_hint = False
        self._wait_since: float | None = None
        self._last_save = 0.0
        self._last_avail = 0.0
        self._ended = False
        self._active = False
        self._muted = False
        self._volume = 80

        self.video = make_video(mpv_options, self)
        self.video.setMouseTracking(True)
        self.video.fileEnded.connect(self._on_file_ended)
        self.video.installEventFilter(self)

        # ---- top bar
        self.top = OverlayBar(True, self)
        self.back = button(tr("Back", "Player"), "", "arrow-left", name=tr("Back to start", "Player"))
        self.back.clicked.connect(self.backRequested)
        self.title = label("", "lead")
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(T.S4, T.S3, T.S4, T.S6)
        tl.setSpacing(T.S3)
        tl.addWidget(self.back)
        tl.addWidget(self.title, 1)

        # ---- bottom bar
        self.bottom = OverlayBar(False, self)
        self.seek = SeekBar()
        self.seek.seekRequested.connect(self.seek_fraction)
        self.play_btn = icon_button("pause", tr("Play / Pause (Space)", "Player"), T.TEXT, 22)
        self.play_btn.clicked.connect(self.toggle_pause)
        self.time_lbl = label("0:00 / 0:00", "secondary")
        self.mute_btn = icon_button("volume", tr("Mute (M)", "Player"), T.TEXT, 20)
        self.mute_btn.clicked.connect(self.toggle_mute)
        self.vol = QSlider(Qt.Orientation.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(self._volume)
        self.vol.setFixedWidth(96)
        self.vol.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.vol.setAccessibleName(tr("Volume", "Player"))
        self.vol.valueChanged.connect(self.set_volume)
        self.audio_btn = icon_button("audio", tr("Audio track", "Player"), T.TEXT, 20)
        self.audio_btn.clicked.connect(lambda: self._track_menu("audio", self.audio_btn))
        self.subs_btn = icon_button("captions", tr("Subtitles", "Player"), T.TEXT, 20)
        self.subs_btn.clicked.connect(lambda: self._track_menu("sub", self.subs_btn))
        self.conn_btn = icon_button("activity", tr("Connection details", "Player"), T.TEXT, 20)
        self.conn_btn.setCheckable(True)
        self.conn_btn.clicked.connect(self.toggle_panel)
        self.fs_btn = icon_button("fullscreen", tr("Fullscreen (F)", "Player"), T.TEXT, 20)
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        for b in (self.play_btn, self.mute_btn, self.audio_btn, self.subs_btn, self.conn_btn, self.fs_btn, self.back):
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        row = QHBoxLayout()
        row.setSpacing(T.S2)
        for w in (self.play_btn, self.time_lbl):
            row.addWidget(w)
        row.addStretch(1)
        for w in (self.mute_btn, self.vol, self.audio_btn, self.subs_btn, self.conn_btn, self.fs_btn):
            row.addWidget(w)
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(T.S4, T.S6, T.S4, T.S3)
        bl.setSpacing(T.S1)
        bl.addWidget(self.seek)
        bl.addLayout(row)

        # ---- waiting card (centre)
        self.wait = QFrame(self)
        self.wait.setProperty("card", "outlined")
        self.wait.setObjectName("waitcard")
        self.wait.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.wait_spin = Spinner(28)
        self.wait_title = label("", "lead", align=Qt.AlignmentFlag.AlignCenter)
        self.wait_sub = label("", "secondary", wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        wl = QVBoxLayout(self.wait)
        wl.setContentsMargins(T.S6, T.S4, T.S6, T.S4)
        wl.setSpacing(T.S2)
        wl.addWidget(self.wait_spin, 0, Qt.AlignmentFlag.AlignCenter)
        wl.addWidget(self.wait_title)
        wl.addWidget(self.wait_sub)
        self.wait.setFixedWidth(400)
        self.wait.hide()

        # ---- connection panel (right)
        self.panel = QFrame(self)
        self.panel.setObjectName("connpanel")
        self.panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.panel.setStyleSheet(f"QFrame#connpanel {{ background: rgba(22,24,29,238); border-left:1px solid {T.OUTLINE}; }}")
        self.panel.setFixedWidth(320)
        pl = QVBoxLayout(self.panel)
        pl.setContentsMargins(T.S4, T.S4, T.S4, T.S4)
        pl.setSpacing(T.S3)
        head = QHBoxLayout()
        head.addWidget(label(tr("Connection", "Player"), "lead"), 1)
        close = icon_button("x", tr("Close panel", "Player"), T.TEXT2, 18)
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        close.clicked.connect(lambda: self.toggle_panel(False))
        head.addWidget(close)
        pl.addLayout(head)
        self.vals: dict[str, object] = {}
        for key, text in (("state", tr("Status", "Player")), ("sources", tr("Sources", "Player")), ("speed", tr("Download speed", "Player")),
                          ("ahead", tr("Ready ahead", "Player")), ("progress", tr("Downloaded", "Player")), ("cache", tr("Disk used", "Player")),
                          ("mode", tr("Cache mode", "Player")), ("evict", tr("Old parts removed", "Player"))):
            r = QHBoxLayout()
            r.addWidget(label(text, "secondary"), 1)
            v = label("–")
            v.setAlignment(Qt.AlignmentFlag.AlignRight)
            r.addWidget(v)
            self.vals[key] = v
            pl.addLayout(r)
            if key == "cache":
                self.cache_bar = AnimatedBar(T.ACCENT, T.TRACK, 6)
                pl.addWidget(self.cache_bar)
        pl.addWidget(label(tr("On the seek bar, grey parts are already on disk and dark parts still have to be fetched.", "Player"), "caption", wrap=True))
        pl.addStretch(1)
        d = button(tr("Diagnostics", "Player"), "", "info", name=tr("Open diagnostics", "Player"))
        d.clicked.connect(self.diagnosticsRequested)
        c = button(tr("Check my connection", "Player"), "", "activity", name=tr("Check my connection", "Player"))
        c.clicked.connect(self.networkCheckRequested)
        pl.addWidget(d)
        pl.addWidget(c)
        self.panel.hide()

        self.poll = QTimer(self)
        self.poll.timeout.connect(self._poll)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._maybe_hide_controls)
        for w in (self.top, self.bottom, self.panel, self.wait, self.seek):
            w.setMouseTracking(True)
            w.installEventFilter(self)
        if bridge is not None:
            bridge.status.connect(self._on_status)
            bridge.availability.connect(self.seek.set_bins)

    # ------------------------------------------------------------------------------------------------- lifecycle
    def start(self, media) -> None:
        self.media = media
        self.snap = {}
        self.fetch_hint = False
        self._ended = False
        self._active = True
        self._wait_since = time.monotonic()
        self.title.setText(media.title)
        self.seek.set_bins([])
        self.seek.set_value(0)
        self.seek.duration = 0.0
        self.time_lbl.setText("0:00 / 0:00")
        start = 0.0
        if self.bridge is not None:
            it = next((i for i in self.bridge.recent.items if i["infohash"] == media.infohash), None)
            if it and not it.get("watched") and it.get("position_s", 0) > 10:
                start = float(it["position_s"])
        if not self.video.available:
            self._show_wait(tr("The video player is not available", "Player"), self.video.error or MPV_IMPORT_ERROR, spin=False)
            return
        self.video.set("volume", self._volume)
        self.video.set("mute", self._muted)
        self.video.set("pause", False)
        self.video.load(media.url, start, media.title)
        self.poll.start(POLL_MS)
        self.show_controls()
        self.setFocus()

    def stop(self) -> None:
        if not self._active:
            return
        self._save_position(force=True)
        self._active = False
        self.poll.stop()
        self.video.stop()
        self.wait.hide()
        self.toggle_panel(False)
        self.media = None

    def shutdown(self) -> None:
        self.stop()
        self.video.shutdown()

    # ------------------------------------------------------------------------------------------------- commands
    def toggle_pause(self) -> None:
        if self._ended:
            self.video.command("seek", 0, "absolute")
            self._ended = False
        self.video.set("pause", not bool(self.video.get("pause", False)))
        self._refresh_play_icon()
        self.show_controls()

    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self.video.set("mute", self._muted)
        self._refresh_volume_icon()

    def set_volume(self, v: int) -> None:
        self._volume = int(v)
        self.video.set("volume", self._volume)
        if v > 0 and self._muted:
            self.toggle_mute()
        self._refresh_volume_icon()

    def seek_fraction(self, f: float) -> None:
        dur = float(self.video.get("duration", 0) or 0)
        if dur <= 0:
            return
        self._seek_to(f * dur, f)

    def seek_relative(self, seconds: float) -> None:
        pos = float(self.video.get("time-pos", 0) or 0)
        dur = float(self.video.get("duration", 0) or 0)
        t = max(0.0, pos + seconds)
        if dur:
            t = min(t, max(dur - 1, 0))
        self._seek_to(t, t / dur if dur else 0.0)

    def _seek_to(self, t: float, f: float) -> None:
        d = self.seek.on_disk(f)
        self.fetch_hint = d is not None and d < 0.99      # honest: only claim a fetch when the engine says the part is missing
        self._ended = False
        self.video.command("seek", round(t, 2), "absolute")
        self.seek.value = f
        self.seek.update()
        self.show_controls()

    def toggle_fullscreen(self) -> None:
        self.fullscreenRequested.emit(not self.window().isFullScreen())

    def set_fullscreen_icon(self, on: bool) -> None:
        self.fs_btn.setIcon(icon("fullscreen-exit" if on else "fullscreen", T.TEXT, 20))

    def toggle_panel(self, on: bool | None = None) -> None:
        on = (not self.panel.isVisible()) if on is None else bool(on)
        self.panel.setVisible(on)
        self.conn_btn.setChecked(on)
        self._layout_overlays()
        if on:
            self.panel.raise_()
            self._fill_panel()

    # ------------------------------------------------------------------------------------------------------ menus
    def _track_menu(self, kind: str, anchor) -> None:
        tracks = [t for t in (self.video.get("track-list", []) or []) if t.get("type") == kind]
        m = QMenu(self)
        g = QActionGroup(m)
        g.setExclusive(True)
        if kind == "sub":
            a = m.addAction(tr("Off", "Player"))
            a.setCheckable(True)
            a.setChecked(not any(t.get("selected") for t in tracks))
            g.addAction(a)
            a.triggered.connect(lambda: self.video.set("sid", "no"))
        if not tracks:
            n = m.addAction(tr("No tracks in this file", "Player"))
            n.setEnabled(False)
        for t in tracks:
            lang = t.get("lang") or ""
            ttl = t.get("title") or ""
            codec = t.get("codec") or ""
            name = " – ".join(x for x in (ttl, lang.upper() if lang else "", codec) if x) or tr("Track %1", "Player").replace("%1", str(t.get("id")))
            a = m.addAction(menu_text(name))
            a.setCheckable(True)
            a.setChecked(bool(t.get("selected")))
            g.addAction(a)
            tid = t.get("id")
            a.triggered.connect(lambda _=False, i=tid: self.video.set("aid" if kind == "audio" else "sid", i))
        m.exec(anchor.mapToGlobal(anchor.rect().topLeft()) - __import__("PyQt6.QtCore", fromlist=["QPoint"]).QPoint(0, m.sizeHint().height()))

    # ----------------------------------------------------------------------------------------------- state / poll
    def _poll(self) -> None:
        if not self._active or not self.video.available:
            return
        now = time.monotonic()
        pos = self.video.get("time-pos")
        dur = self.video.get("duration")
        paused = bool(self.video.get("pause", False))
        pfc = bool(self.video.get("paused-for-cache", False))
        seeking = bool(self.video.get("seeking", False))
        dcs = self.video.get("demuxer-cache-state", {}) or {}
        fw = dcs.get("fw-bytes") if isinstance(dcs, dict) else None
        if self.bridge is not None:
            self.bridge.feed_player(PlayerState(ts=now, time_pos=pos, duration=dur, fw_bytes=fw, paused=paused, paused_for_cache=pfc,
                                                seeking=seeking, cache_speed=self.video.get("cache-speed")))
        if dur:
            self.seek.duration = float(dur)
            self.seek.set_value((pos or 0) / dur)
        self.time_lbl.setText(f"{fmt_time(pos)} / {fmt_time(dur)}")
        self._refresh_play_icon()
        waiting = pfc or seeking or (pos is None and not self._ended)
        if waiting:
            self._wait_since = self._wait_since or now
            if now - self._wait_since >= SHOW_WAIT_AFTER_S:
                self._update_wait(pos is None)
        else:
            self._wait_since = None
            self.fetch_hint = False
            self.wait.hide()
        if self.panel.isVisible():
            self._fill_panel()
        if self.bridge is not None and self.media is not None and now - self._last_avail >= AVAIL_EVERY_S:
            self._last_avail = now
            self.bridge.request_availability(240)
        self._save_position()

    def _on_status(self, s: dict) -> None:
        self.snap = s

    def _update_wait(self, starting: bool) -> None:
        s = self.snap
        peers = int(s.get("peers") or 0)
        if peers == 0 and s.get("ever_connected"):
            title, sub = tr("Waiting for sources", "Player"), tr("The connection to every source was lost. Playback continues when one comes back.", "Player")
        elif peers == 0:
            title, sub = tr("Looking for sources…", "Player"), tr("No one has answered yet. This can take a while for rarely shared videos.", "Player")
        else:
            title = tr("Starting…", "Player") if starting else tr("Fetching this part…", "Player") if self.fetch_hint else tr("Buffering…", "Player")
            sub = tr("%1 · %2", "Player").replace("%1", tr("%1 sources", "Player").replace("%1", str(peers)) if peers != 1 else tr("1 source", "Player")).replace("%2", fmt_speed(s.get("down_Bps", 0)))
            if self.fetch_hint:
                sub += "\n" + tr("This part of the video was not downloaded yet.", "Player")
        self._show_wait(title, sub)

    def _show_wait(self, title: str, sub: str, spin: bool = True) -> None:
        self.wait_title.setText(title)
        self.wait_sub.setText(sub)
        self.wait_spin.setVisible(spin)
        self.wait.show()
        self.wait.adjustSize()
        self._layout_overlays()
        self.wait.raise_()

    def _fill_panel(self) -> None:
        s = self.snap
        if not s:
            return
        v = self.vals
        names = {"starting": tr("Starting", "Player"), "playing": tr("Playing", "Player"), "paused": tr("Paused", "Player"), "buffering": tr("Waiting for data", "Player")}
        v["state"].setText(names.get(s.get("phase"), "–"))
        peers = int(s.get("peers") or 0)
        v["sources"].setText(f"{peers}" + (f"  ({s.get('seeds')} full)" if s.get("seeds") else ""))
        v["speed"].setText(fmt_speed(s.get("down_Bps", 0)))
        a = s.get("ahead_seconds")
        v["ahead"].setText(f"≈ {fmt_time(a)}" if a else (fmt_bytes(s.get("ahead_bytes", 0)) if s.get("ahead_bytes") else "–"))
        pt = s.get("pieces_total") or 0
        v["progress"].setText(f"{100 * s.get('pieces_have', 0) / pt:.0f}%" if pt else "–")
        used, lim = int(s.get("cache_used") or 0), int(s.get("cache_limit") or 0)
        v["cache"].setText(f"{fmt_bytes(used)} / {fmt_bytes(lim)}" if lim else fmt_bytes(used))
        frac = used / lim if lim else 0
        self.cache_bar.setValue(frac)
        self.cache_bar.setColor(T.WARNING if frac > 0.9 else T.ACCENT)
        v["mode"].setText(tr("Temporary, no limit", "Player") if not s.get("bounded") else tr("Limited", "Player"))
        v["evict"].setText(str(s.get("evictions", 0)))

    def _refresh_play_icon(self) -> None:
        playing = not bool(self.video.get("pause", False)) and not self._ended
        self.play_btn.setIcon(icon("pause" if playing else "play", T.TEXT, 22))

    def _refresh_volume_icon(self) -> None:
        self.mute_btn.setIcon(icon("volume-off" if self._muted or self._volume == 0 else "volume", T.TEXT, 20))

    def _on_file_ended(self, reason: str, error: str) -> None:
        if not self._active:
            return
        if reason == "error":
            self._active = True
            if self.bridge is not None:
                self.bridge.player_event("file-error", {"reason": error or "loading failed"})
            self._show_wait(tr("This video can't be played", "Player"), error or "", spin=False)
        elif reason == "eof":
            self._ended = True
            self._save_position(force=True)
            self.wait.hide()
            self._refresh_play_icon()
            self.show_controls()

    def _save_position(self, force: bool = False) -> None:
        now = time.monotonic()
        if self.bridge is None or self.media is None or (not force and now - self._last_save < SAVE_EVERY_S):
            return
        self._last_save = now
        dur = float(self.video.get("duration", 0) or 0)
        pos = dur if self._ended else float(self.video.get("time-pos", 0) or 0)
        if dur > 0:
            self.bridge.save_position(self.media.infohash, pos, dur)

    # -------------------------------------------------------------------------------- controls visibility / input
    def show_controls(self) -> None:
        self.top.show()
        self.bottom.show()
        self.top.raise_()
        self.bottom.raise_()
        if self.panel.isVisible():
            self.panel.raise_()
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.video.setCursor(Qt.CursorShape.ArrowCursor)
        self.hide_timer.start(HIDE_AFTER_MS)

    def _maybe_hide_controls(self) -> None:
        if not self._active or bool(self.video.get("pause", False)) or self._ended or self._wait_since is not None:
            return
        if self.bottom.underMouse() or self.top.underMouse() or self.panel.underMouse():
            self.hide_timer.start(HIDE_AFTER_MS)
            return
        self.top.hide()
        self.bottom.hide()
        self.video.setCursor(Qt.CursorShape.BlankCursor)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Type.MouseMove:
            self.show_controls()
        elif obj is self.video and t == QEvent.Type.MouseButtonRelease and ev.button() == Qt.MouseButton.LeftButton:
            self.toggle_pause()
        elif obj is self.video and t == QEvent.Type.MouseButtonDblClick:
            self.toggle_fullscreen()
        return super().eventFilter(obj, ev)

    def keyPressEvent(self, e):
        k, m = e.key(), e.modifiers()
        big = bool(m & Qt.KeyboardModifier.ShiftModifier)
        if k == Qt.Key.Key_Space or k == Qt.Key.Key_K:
            self.toggle_pause()
        elif k == Qt.Key.Key_Left:
            self.seek_relative(-30 if big else -5)
        elif k == Qt.Key.Key_Right:
            self.seek_relative(30 if big else 5)
        elif k == Qt.Key.Key_Up:
            self.vol.setValue(min(100, self.vol.value() + 5))
        elif k == Qt.Key.Key_Down:
            self.vol.setValue(max(0, self.vol.value() - 5))
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        elif k == Qt.Key.Key_F or k == Qt.Key.Key_F11:
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.fullscreenRequested.emit(False)
            elif self.panel.isVisible():
                self.toggle_panel(False)
            else:
                self.backRequested.emit()
        elif k == Qt.Key.Key_C:
            self.toggle_panel()
        else:
            return super().keyPressEvent(e)
        self.show_controls()

    # ------------------------------------------------------------------------------------------------------ layout
    def _layout_overlays(self) -> None:
        w, h = self.width(), self.height()
        self.video.setGeometry(0, 0, w, h)
        th = self.top.sizeHint().height()
        bh = self.bottom.sizeHint().height()
        pw = self.panel.width() if self.panel.isVisible() else 0
        self.top.setGeometry(0, 0, w - pw, th)                 # the side panel never hides a control
        self.bottom.setGeometry(0, h - bh, w - pw, bh)
        self.panel.setGeometry(w - 320, 0, 320, h)
        self.wait.move((w - pw - self.wait.width()) // 2, (h - self.wait.height()) // 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout_overlays()
