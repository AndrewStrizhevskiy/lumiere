"""Playback screen (P3 replaces this placeholder with the embedded libmpv player)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from . import theme as T
from .messages import tr
from .widgets import button, label


class PlayerScreen(QWidget):
    backRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("root")
        self.title = label("", "title")
        self.note = label(tr("The player arrives in the next step.", "Player"), "lead")
        back = button(tr("Back", "Player"), "", "arrow-left")
        back.clicked.connect(self.backRequested)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S6, T.S6, T.S6, T.S6)
        lay.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch(1)
        lay.addWidget(self.title, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.note, 0, Qt.AlignmentFlag.AlignCenter)
        lay.addStretch(2)

    def start(self, media) -> None:
        self.title.setText(media.title)

    def stop(self) -> None:
        pass
