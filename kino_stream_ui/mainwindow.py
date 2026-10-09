"""Main window: screens, navigation, menus, and the glue between user actions and the engine bridge."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from kino_stream import events as ev
from kino_stream.settings import Settings

from . import theme as T
from .bridge import EngineBridge
from .dialogs import DiagnosticsDialog, MessageDialog, NetworkResultDialog, OpeningOverlay, redact
from .home import HomeScreen, StatusStrip, looks_like_magnet
from .messages import for_code, tr
from .player import PlayerScreen
from .tour import TourOverlay
from .settings_screen import SettingsScreen
from .widgets import Banner, Toast, fade_in


class MainWindow(QMainWindow):
    HOME, PLAYER, SETTINGS = 0, 1, 2

    def __init__(self, bridge: EngineBridge, mpv_options: dict | None = None):
        super().__init__()
        self.bridge = bridge
        self.setWindowTitle("Kino Stream")
        self.setMinimumSize(720, 480)
        self.resize(1100, 720)
        self.ready_info: dict | None = None
        self._pending: tuple[str, str] | None = None
        self.home = HomeScreen()
        self.player = PlayerScreen(bridge, mpv_options)
        self.settings_screen = SettingsScreen(bridge.settings)
        self.stack = QStackedWidget()
        for w in (self.home, self.player, self.settings_screen):
            self.stack.addWidget(w)
        self.strip = StatusStrip()
        self.banner = Banner()
        self.banner.setContentsMargins(0, 0, 0, 0)
        central = QWidget()
        central.setObjectName("root")
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.banner)
        lay.addWidget(self.stack, 1)
        lay.addWidget(self.strip)
        self.setCentralWidget(central)
        self.overlay = OpeningOverlay(central)
        self.toast = Toast(central)
        self.tour = TourOverlay(central, bridge.settings.cache_gb)
        self.tour.finished.connect(self._tour_finished)
        self._menus()
        self._wire()
        self.home.set_recent(bridge.recent.items)
        bridge.check_ready()

    # --------------------------------------------------------------------------------------------------- menus
    def _menus(self) -> None:
        mb = self.menuBar()
        f = mb.addMenu(tr("&File", "Menu"))
        self.act_open = QAction(tr("Open torrent file…", "Menu"), self, shortcut=QKeySequence("Ctrl+O"), triggered=self.home.drop.choose_file)
        self.act_magnet = QAction(tr("Open magnet link…", "Menu"), self, shortcut=QKeySequence("Ctrl+L"), triggered=self.focus_magnet)
        quit_ = QAction(tr("Quit", "Menu"), self, shortcut=QKeySequence("Ctrl+Q"), triggered=self.close)
        f.addActions([self.act_open, self.act_magnet])
        f.addSeparator()
        f.addAction(quit_)
        v = mb.addMenu(tr("&View", "Menu"))
        v.addAction(QAction(tr("Settings", "Menu"), self, shortcut=QKeySequence("Ctrl+,"), triggered=lambda: self.go(self.SETTINGS)))
        h = mb.addMenu(tr("&Help", "Menu"))
        self.act_tour = QAction(tr("Show Tutorial Again", "Menu"), self, triggered=self.show_tour)
        h.addAction(self.act_tour)
        h.addAction(QAction(tr("Diagnostics…", "Menu"), self, triggered=self.show_diagnostics))
        h.addAction(QAction(tr("Check my connection", "Menu"), self, triggered=self.bridge.network_check))
        h.addSeparator()
        h.addAction(QAction(tr("About Kino Stream", "Menu"), self, triggered=self.about))

    def focus_magnet(self) -> None:
        self.go(self.HOME)
        self.home.drop.magnet.setFocus()
        self.home.drop.magnet.selectAll()

    def about(self) -> None:
        QMessageBox.about(self, tr("About Kino Stream", "Menu"),
                          tr("Kino Stream plays videos from torrents while they download, using a cache of a size you choose.", "Menu"))

    # ---------------------------------------------------------------------------------------------------- wiring
    def _wire(self) -> None:
        b = self.bridge
        self.home.openRequested.connect(self.start_open)
        self.home.settingsRequested.connect(lambda: self.go(self.SETTINGS))
        self.home.helpRequested.connect(self.show_tour)
        self.home.removeRecent.connect(self._remove_recent)
        self.settings_screen.backRequested.connect(lambda: self.go(self.HOME))
        self.settings_screen.tourRequested.connect(self.show_tour)
        self.settings_screen.changed.connect(b.apply_settings)
        self.settings_screen.clearHistoryRequested.connect(self._clear_history)
        self.settings_screen.deleteCacheRequested.connect(self._delete_cache)
        self.player.backRequested.connect(self.stop_and_home)
        self.player.fullscreenRequested.connect(self.set_fullscreen)
        self.player.diagnosticsRequested.connect(self.show_diagnostics)
        self.player.networkCheckRequested.connect(self.bridge.network_check)
        self.overlay.cancelled.connect(self._cancel_open)
        self.banner.dismissed.connect(self.banner.hide)
        self.banner.action.connect(self._banner_action)
        b.status.connect(self.on_status)
        b.event.connect(self.on_event)
        b.opened.connect(self.on_opened)
        b.openFailed.connect(self.on_open_failed)
        b.closed.connect(self.on_closed)
        b.ready.connect(self.on_ready)
        b.networkChecked.connect(lambda r: NetworkResultDialog(r, self).exec())
        b.settingsChanged.connect(lambda s: self.refresh_saved_data())

    def go(self, index: int) -> None:
        if index == self.SETTINGS:
            self.refresh_saved_data()
        self.stack.setCurrentIndex(index)
        if index != self.PLAYER:                     # a graphics effect on the parent of the GL video widget breaks its rendering
            fade_in(self.stack.currentWidget(), T.DUR_BASE)
        if index != self.PLAYER:
            self.banner.hide() if index == self.HOME and not self._banner_sticky() else None

    def _banner_sticky(self) -> bool:
        return False

    # -------------------------------------------------------------------------------------------------- opening
    def start_open(self, source: str, title: str = "", temporary: bool = False) -> None:
        if not source:
            self.toast.say(tr("This item has no link saved. Open its torrent file or paste its link again.", "Home"))
            return
        if not (looks_like_magnet(source) or Path(source).is_file()):
            self.toast.say(tr("That file can't be found any more.", "Home"))
            return
        self._pending = (source, title)
        self.banner.hide()
        self.overlay.open()
        self.bridge.open_source(source, temporary=temporary, title=title or None)

    def _cancel_open(self) -> None:
        self.bridge.cancel_open()
        self.overlay.hide()
        self.toast.say(tr("Cancelled", "Opening"))

    def on_opened(self, media) -> None:
        self.overlay.hide()
        self.player.start(media)
        self.home.set_recent(self.bridge.recent.items)
        self.go(self.PLAYER)
        if media.temporary:
            self.banner.show_message("warning", tr("Temporary mode", "Banner"),
                                     tr("There is no cache size limit in this mode. The data is deleted when you close the video.", "Banner"))

    def on_open_failed(self, code: str, detail: str) -> None:
        self.overlay.hide()
        msg = for_code(code) or for_code(ev.OPEN_FAILED)
        dlg = MessageDialog(msg, self, technical=redact(detail) if code in (ev.STORE_FAILED, ev.OPEN_FAILED) else "")
        dlg.exec()
        self._handle_action(dlg.choice)

    def _handle_action(self, key: str) -> None:
        if key == "retry" and self._pending:
            self.start_open(*self._pending)
        elif key == "settings":
            self.go(self.SETTINGS)
        elif key == "network_check":
            self.bridge.network_check()
        elif key == "diagnostics":
            self.show_diagnostics()
        elif key == "open_other":
            self.stop_and_home()
            self.home.drop.choose_file()
        elif key == "play_temporary" and self._pending:
            r = QMessageBox.warning(self, tr("Temporary mode", "Banner"),
                                    tr("In temporary mode the cache has NO size limit and may grow as large as the video. Its data is deleted when you close the video. Continue?", "Banner"),
                                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
            if r == QMessageBox.StandardButton.Yes:
                self.start_open(self._pending[0], self._pending[1], temporary=True)

    def _banner_action(self, key: str) -> None:
        self._handle_action(key)

    # -------------------------------------------------------------------------------------------- engine events
    def on_status(self, s: dict) -> None:
        self.strip.set_status(s)

    def on_event(self, e) -> None:
        if e.code in (ev.READY,) or self.overlay.isVisible() and e.level == ev.ERROR:
            return
        m = for_code(e.code, e.detail)
        if m is None:
            return
        if m.level in ("success", "info"):
            self.toast.say(m.title + " – " + m.text if m.level == "success" else m.text, 4500)
        else:
            self.banner.show_message(m.level, m.title, m.text, m.actions)

    def on_ready(self, r: dict) -> None:
        self.ready_info = r
        used = int(r.get("cache_bytes", 0))
        if r.get("ok"):
            self.strip.set_ready(True)
        else:
            m = for_code((r.get("problems") or ["CACHE_DIR_UNUSABLE"])[0])
            self.strip.set_ready(False, m.title if m else tr("Not ready", "StatusStrip"))
            if m:
                self.banner.show_message(m.level if m.level != "error" else "warning", m.title, m.text, m.actions)
        self.strip.set_idle(r, used, self.bridge.settings.cache_gb * (1 << 30))

    def on_closed(self) -> None:
        self.bridge.check_ready()

    def stop_and_home(self) -> None:
        if self.isFullScreen():
            self.set_fullscreen(False)
        self.player.stop()
        self.bridge.close_media()
        self.go(self.HOME)
        self.home.set_recent(self.bridge.recent.items)

    # ---------------------------------------------------------------------------------------- settings helpers
    def refresh_saved_data(self) -> None:
        from kino_stream.caches import list_caches
        titles = {i["infohash"]: i.get("title", "") for i in self.bridge.recent.items}
        caches = list_caches(self.bridge.settings.cache_root_path)
        self.settings_screen.set_saved_data(caches, titles, self.bridge.media.infohash if self.bridge.media else None)

    def _delete_cache(self, infohash: str) -> None:
        freed = self.bridge.delete_cache(infohash)
        self.toast.say(tr("Deleted. %1 freed.", "Settings").replace("%1", f"{freed / 1e6:.0f} MB") if freed else tr("Nothing was deleted.", "Settings"))
        self.refresh_saved_data()
        self.bridge.check_ready()

    def _remove_recent(self, infohash: str) -> None:
        self.bridge.recent.remove(infohash)
        self.home.set_recent(self.bridge.recent.items)

    def _clear_history(self) -> None:
        self.bridge.recent.clear()
        self.home.set_recent([])
        self.toast.say(tr("History cleared", "Settings"))

    # -------------------------------------------------------------------------------------------------- dialogs
    def show_diagnostics(self) -> None:
        d = DiagnosticsDialog(self.bridge.service.snapshot(), self.ready_info, self)
        d.runCheck.connect(self.bridge.network_check)
        d.exec()

    def set_fullscreen(self, on: bool) -> None:
        if on:
            self.showFullScreen()
        else:
            self.showNormal()
        self.menuBar().setVisible(not on)
        self.strip.setVisible(not on)
        self.player.set_fullscreen_icon(on)
        self.player.setFocus()

    def maybe_show_tour(self) -> None:
        if not self.bridge.settings.tour_done:
            QTimer.singleShot(250, self.show_tour)

    def handle_external(self, source: str) -> None:
        """A file or magnet handed over by the desktop (or by a second launch). Never interrupts the tutorial or hides an error."""
        self.showNormal() if self.isMinimized() else None
        self.raise_()
        self.activateWindow()
        if not source:
            return
        if self.tour.isVisible():
            self._after_tour = source
            return
        if self.overlay.isVisible():
            self.toast.say(tr("Already opening a video. Cancel it first to open another.", "Home"))
            return
        if self.stack.currentIndex() == self.PLAYER:
            self.stop_and_home()
        self.start_open(source)

    def show_tour(self) -> None:
        self.tour.open(self.bridge.settings.cache_gb)

    _after_tour = ""

    def _tour_finished(self, completed: bool) -> None:
        """Finish and Skip both count as done, so the tutorial never nags; Help reopens it. Only the flag changes."""
        if not self.bridge.settings.tour_done:
            from dataclasses import replace
            self.bridge.apply_settings(replace(self.bridge.settings, tour_done=True))
            self.settings_screen.load(self.bridge.settings)
        if self._after_tour:
            src, self._after_tour = self._after_tour, ""
            QTimer.singleShot(0, lambda: self.start_open(src))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.overlay.isVisible():
            self.overlay.setGeometry(self.centralWidget().rect())
        if self.tour.isVisible():
            self.tour.setGeometry(self.centralWidget().rect())

    def closeEvent(self, e):
        self.hide()
        try:
            self.player.shutdown()
        finally:
            self.bridge.shutdown()
        e.accept()
