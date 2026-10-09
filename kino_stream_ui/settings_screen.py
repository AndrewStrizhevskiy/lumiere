"""Settings: few controls, each explained in one plain sentence. Every change is saved automatically."""
from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt, pyqtSignal
from PyQt6.QtWidgets import (QFileDialog, QHBoxLayout, QMessageBox, QScrollArea, QSlider, QVBoxLayout, QWidget)

from . import theme as T
from .messages import tr
from .widgets import Segmented, button, card, divider, fmt_bytes, icon_button, label

CACHE_STEPS = [1, 2, 3, 4, 5, 8, 10, 15, 20, 30, 50, 100, 200]


def _row(title: str, hint: str, control: QWidget, extra: QWidget | None = None) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(T.S1)
    t = label(title, "")
    t.setStyleSheet("font-weight:600;")
    lay.addWidget(t)
    lay.addWidget(label(hint, "secondary", wrap=True))
    lay.addSpacing(T.S1)
    lay.addWidget(control)
    if extra is not None:
        lay.addWidget(extra)
    return w


class SettingsScreen(QWidget):
    backRequested = pyqtSignal()
    tourRequested = pyqtSignal()
    changed = pyqtSignal(object)            # Settings
    clearHistoryRequested = pyqtSignal()
    deleteCacheRequested = pyqtSignal(str)  # infohash

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self._s = settings
        self._loading = True
        back = icon_button("arrow-left", tr("Back", "Settings"), T.TEXT, 22)
        back.clicked.connect(self.backRequested)
        title = label(tr("Settings", "Settings"), "title")
        self.saved = label("", "caption")
        top = QHBoxLayout()
        top.setContentsMargins(T.S4, T.S4, T.S6, 0)
        top.addWidget(back)
        top.addWidget(title)
        top.addStretch(1)
        top.addWidget(self.saved)

        # --- cache size
        self.cache = QSlider(Qt.Orientation.Horizontal)
        self.cache.setRange(0, len(CACHE_STEPS) - 1)
        self.cache.setAccessibleName(tr("Cache size", "Settings"))
        self.cache_val = label("", "")
        self.cache_val.setMinimumWidth(70)
        self.cache_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        crow = QWidget()
        cl = QHBoxLayout(crow)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(self.cache, 1)
        cl.addWidget(self.cache_val)
        self.cache_note = label("", "caption", wrap=True)
        # --- keep watched
        self.keep = QSlider(Qt.Orientation.Horizontal)
        self.keep.setRange(0, 60)
        self.keep.setAccessibleName(tr("Keep what you watched", "Settings"))
        self.keep_val = label("", "")
        self.keep_val.setMinimumWidth(70)
        self.keep_val.setAlignment(Qt.AlignmentFlag.AlignRight)
        krow = QWidget()
        kl = QHBoxLayout(krow)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.addWidget(self.keep, 1)
        kl.addWidget(self.keep_val)
        # --- choices
        self.network = Segmented([("patient", tr("Patient", "Settings")), ("balanced", tr("Balanced", "Settings")), ("quick", tr("Quick to give up", "Settings"))], "patient")
        self.encryption = Segmented([("auto", tr("Automatic", "Settings")), ("always", tr("Always on", "Settings")), ("off", tr("Off", "Settings"))], "auto")
        self.on_close = Segmented([("keep", tr("Keep it for resuming", "Settings")), ("delete", tr("Delete it", "Settings"))], "keep")
        # --- location + saved videos + start-up
        self.folder = label("", "caption", wrap=True)
        self.folder_btn = button(tr("Change folder…", "Settings"), "", "folder-open")
        self.folder_btn.clicked.connect(self.choose_folder)
        frow = QWidget()
        fl = QHBoxLayout(frow)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.addWidget(self.folder, 1)
        fl.addWidget(self.folder_btn)
        self.saved_list = QVBoxLayout()
        self.saved_list.setSpacing(T.S2)
        saved_host = QWidget()
        saved_host.setLayout(self.saved_list)
        tour_btn = button(tr("Show the tutorial", "Settings"), "", "help")
        tour_btn.clicked.connect(self.tourRequested)
        hist_btn = button(tr("Clear watch history", "Settings"), "", "trash")
        hist_btn.clicked.connect(self.confirm_clear_history)
        srow = QWidget()
        sl = QHBoxLayout(srow)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(tour_btn)
        sl.addWidget(hist_btn)
        sl.addStretch(1)

        form = QVBoxLayout()
        form.setSpacing(T.S6)
        form.setContentsMargins(T.S6, T.S4, T.S6, T.S8)
        sections = [
            (tr("Cache size", "Settings"), tr("How much disk space streaming may use. Older parts are removed automatically so this limit is never exceeded.", "Settings"), crow, self.cache_note),
            (tr("Keep what you watched", "Settings"), tr("How much of the video behind you stays on disk, so you can jump back without downloading it again.", "Settings"), krow, None),
            (tr("When the connection is poor", "Settings"), tr("How long Kino Stream waits for a missing part before trying again. “Patient” suits slow or unstable connections.", "Settings"), self.network, None),
            (tr("Hide traffic from your network", "Settings"), tr("BitTorrent encryption. Some networks treat plain BitTorrent differently. “Automatic” is right for most people.", "Settings"), self.encryption, None),
            (tr("When I close a video", "Settings"), tr("Streaming data is temporary. Keep it to resume quickly later, or delete it right away to free the space.", "Settings"), self.on_close, None),
            (tr("Cache folder", "Settings"), tr("Where streaming data is stored. Changing it does not move or delete data in the old folder.", "Settings"), frow, None),
            (tr("Saved streaming data", "Settings"), tr("Nothing is deleted unless you ask. Delete saved data for a video to free its space.", "Settings"), saved_host, None),
            (tr("Tutorial and history", "Settings"), tr("Reopen the short tutorial any time, or clear the list of recent videos.", "Settings"), srow, None),
        ]
        for i, (t, h, c, e) in enumerate(sections):
            if i:
                form.addWidget(divider())
            form.addWidget(_row(t, h, c, e))
        form.addStretch(1)
        holder = QWidget()
        holder.setMaximumWidth(760)
        holder.setLayout(form)
        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(holder, 100)
        center.addStretch(1)
        inner = QWidget()
        inner.setLayout(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(inner)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(top)
        lay.addWidget(scroll, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._commit)
        for sig in (self.cache.valueChanged, self.keep.valueChanged):
            sig.connect(self._edited)
        for seg in (self.network, self.encryption, self.on_close):
            seg.changed.connect(lambda _k: self._edited())
        self.load(settings)

    # --------------------------------------------------------------------------------------------------- state
    def load(self, s) -> None:
        self._loading = True
        self._s = s
        gb = min(CACHE_STEPS, key=lambda v: abs(v - s.cache_gb))
        self.cache.setValue(CACHE_STEPS.index(gb))
        self.keep.setValue(int(s.keep_minutes))
        self.network.set(s.network)
        self.encryption.set(s.encryption)
        self.on_close.set(s.on_close)
        self.folder.setText(str(s.cache_root_path))
        self._labels()
        self._loading = False

    def _labels(self) -> None:
        self.cache_val.setText(f"{CACHE_STEPS[self.cache.value()]} GB")
        m = self.keep.value()
        self.keep_val.setText(tr("Nothing", "Settings") if m == 0 else f"{m} min")
        free = shutil.disk_usage(self._s.cache_root_path if Path(self._s.cache_root_path).exists() else Path.home()).free
        self.cache_note.setText(tr("%1 is free on this disk.", "Settings").replace("%1", fmt_bytes(free)))

    def current(self):
        return replace(self._s, cache_gb=float(CACHE_STEPS[self.cache.value()]), keep_minutes=float(self.keep.value()), network=self.network.value(),
                       encryption=self.encryption.value(), on_close=self.on_close.value())

    def _edited(self) -> None:
        self._labels()
        if not self._loading:
            self._timer.start()

    def _commit(self) -> None:
        s = self.current().normalized()
        self._s = s
        self.changed.emit(s)
        self.saved.setText(tr("Saved", "Settings"))
        QTimer.singleShot(1800, lambda: self.saved.setText(""))

    def choose_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, tr("Choose a cache folder", "Settings"), str(self._s.cache_root_path))
        if d:
            self._s = replace(self._s, cache_root=d)
            self.folder.setText(d)
            self._commit()

    def confirm_clear_history(self) -> None:
        r = QMessageBox.question(self, tr("Clear watch history", "Settings"),
                                 tr("Remove all videos from the “Continue watching” list? Saved streaming data is not deleted.", "Settings"),
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel)
        if r == QMessageBox.StandardButton.Yes:
            self.clearHistoryRequested.emit()

    def set_saved_data(self, caches: list[dict], titles: dict[str, str], open_infohash: str | None) -> None:
        while self.saved_list.count():
            it = self.saved_list.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not caches:
            self.saved_list.addWidget(label(tr("No saved streaming data.", "Settings"), "caption"))
            return
        for c in caches:
            row = card(True)
            lay = QHBoxLayout(row)
            lay.setContentsMargins(T.S3, T.S2, T.S3, T.S2)
            name = titles.get(c["infohash"]) or tr("Video (%1)", "Settings").replace("%1", c["infohash"][:8])
            if c.get("temporary"):
                name += " – " + tr("temporary", "Settings")
            lay.addWidget(label(name, ""), 1)
            lay.addWidget(label(fmt_bytes(c["bytes"]), "secondary"))
            b = button(tr("Delete", "Settings"), "danger", "trash", T.DANGER, name=tr("Delete saved data for %1", "Settings").replace("%1", name))
            b.setEnabled(c["infohash"] != open_infohash)
            b.setToolTip(tr("Close the video first", "Settings") if not b.isEnabled() else "")
            b.clicked.connect(lambda _=False, ih=c["infohash"], n=name, size=c["bytes"]: self._confirm_delete(ih, n, size))
            lay.addWidget(b)
            self.saved_list.addWidget(row)

    def _confirm_delete(self, infohash: str, name: str, size: int) -> None:
        box = QMessageBox(QMessageBox.Icon.Question, tr("Delete saved data", "Settings"), "", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, self)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setText(tr("Delete the saved streaming data for “%1”? This frees %2. The video stays in your list and will download again when you play it.", "Settings")
                     .replace("%1", name).replace("%2", fmt_bytes(size)))
        r = box.exec()
        if r == QMessageBox.StandardButton.Yes:
            self.deleteCacheRequested.emit(infohash)
