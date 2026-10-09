"""Modal dialogs: opening overlay, error explanation, diagnostics, network check result."""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget)

from . import theme as T
from .icons import pixmap
from .messages import KIND_LABEL, VERDICTS, Message, tr
from .widgets import Spinner, button, divider, label


class OpeningOverlay(QWidget):
    """Covers the window while the torrent's details are being fetched; always cancellable."""
    cancelled = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("opening")
        self.setStyleSheet(f"QWidget#opening {{ background: rgba(14,15,18,225); }}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        box = QFrame()
        box.setProperty("card", "outlined")
        self.spin = Spinner(32)
        self.title = label(tr("Looking for sources…", "Opening"), "title", align=Qt.AlignmentFlag.AlignCenter)
        self.sub = label(tr("This usually takes a few seconds. Magnet links can take longer.", "Opening"), "secondary", wrap=True, align=Qt.AlignmentFlag.AlignCenter)
        cancel = button(tr("Cancel", "Opening"), "", name=tr("Cancel opening", "Opening"))
        cancel.clicked.connect(self.cancelled)
        bl = QVBoxLayout(box)
        bl.setContentsMargins(T.S8, T.S6, T.S8, T.S6)
        bl.setSpacing(T.S3)
        bl.addWidget(self.spin, 0, Qt.AlignmentFlag.AlignCenter)
        bl.addWidget(self.title)
        bl.addWidget(self.sub)
        bl.addSpacing(T.S2)
        bl.addWidget(cancel, 0, Qt.AlignmentFlag.AlignCenter)
        box.setMaximumWidth(460)
        lay = QVBoxLayout(self)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        self.hide()

    def open(self, title: str = "") -> None:
        self.sub.setText(title or tr("This usually takes a few seconds. Magnet links can take longer.", "Opening"))
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.setFocus()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()


class MessageDialog(QDialog):
    """Explains a problem in plain words and offers the next steps as buttons. Result: the chosen action key ('' = closed)."""

    def __init__(self, msg: Message, parent=None, technical: str = ""):
        super().__init__(parent)
        self.setWindowTitle(msg.title)
        self.setModal(True)
        self.choice = ""
        c = {"error": T.DANGER, "warning": T.WARNING, "success": T.SUCCESS}.get(msg.level, T.TEXT2)
        ic = label("")
        ic.setPixmap(pixmap("alert" if msg.level in ("error", "warning") else "info", c, 28, 2.0))
        title = label(msg.title, "title")
        text = label(msg.text, "secondary", wrap=True)
        text.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S6, T.S6, T.S6, T.S4)
        lay.setSpacing(T.S3)
        head = QHBoxLayout()
        head.setSpacing(T.S3)
        head.addWidget(ic)
        head.addWidget(title, 1)
        lay.addLayout(head)
        lay.addWidget(text)
        if technical:
            more = label(technical, "caption", wrap=True)
            more.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            lay.addWidget(more)
        row = QHBoxLayout()
        row.setSpacing(T.S2)
        row.addStretch(1)
        close = button(tr("Close", "Dialog"), "", name=tr("Close", "Dialog"))
        close.clicked.connect(self.reject)
        row.addWidget(close)
        for i, (key, text_) in enumerate(msg.actions):
            b = button(text_, "primary" if i == len(msg.actions) - 1 else "", name=text_)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            row.addWidget(b)
        lay.addSpacing(T.S2)
        lay.addLayout(row)

    def _pick(self, key: str) -> None:
        self.choice = key
        self.accept()


class NetworkResultDialog(QDialog):
    def __init__(self, report: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Connection check", "Network"))
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S6, T.S6, T.S6, T.S4)
        lay.setSpacing(T.S3)
        lay.addWidget(label(tr("Connection check", "Network"), "title"))
        if "error" in report:
            lay.addWidget(label(tr("The check could not run: %1", "Network").replace("%1", str(report["error"])), "secondary", wrap=True))
        else:
            lay.addWidget(label(tr("What this test could and could not show:", "Network"), "secondary"))
            colors = {"confirmed": T.SUCCESS, "observed": T.TEXT2, "hypothesis": T.WARNING, "not_measured": T.TEXT3}
            for kind, key in report.get("verdicts", []):
                k, text = VERDICTS.get(key, (kind, key))
                row = QHBoxLayout()
                row.setSpacing(T.S3)
                chip = label(tr(KIND_LABEL.get(k, k), "Network"), "")
                chip.setStyleSheet(f"color:{colors.get(k, T.TEXT2)}; font-weight:600; border:1px solid {colors.get(k, T.TEXT2)}; border-radius:10px; padding:2px 10px;")
                chip.setFixedWidth(110)
                chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
                row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
                row.addWidget(label(tr(text, "Network"), "", wrap=True), 1)
                lay.addLayout(row)
            lay.addWidget(label(tr("“Confirmed” means measured just now on this connection. “Possible” is a hypothesis, not a finding.", "Network"), "caption", wrap=True))
        close = button(tr("Close", "Dialog"), "primary", name=tr("Close", "Dialog"))
        close.clicked.connect(self.accept)
        lay.addSpacing(T.S2)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)


class DiagnosticsDialog(QDialog):
    runCheck = pyqtSignal()

    def __init__(self, snapshot: dict, ready: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("Diagnostics", "Diagnostics"))
        self.setMinimumSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(T.S6, T.S6, T.S6, T.S4)
        lay.setSpacing(T.S3)
        lay.addWidget(label(tr("Diagnostics", "Diagnostics"), "title"))
        lay.addWidget(label(tr("Technical details for troubleshooting. You can copy them when asking for help.", "Diagnostics"), "secondary", wrap=True))
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(f"background:{T.SURFACE}; border:1px solid {T.HAIRLINE}; border-radius:{T.R_CTRL}px; padding:8px; font-family:monospace; font-size:12px;")
        self.text.setPlainText(json.dumps({"engine": snapshot, "readiness": ready}, indent=2, default=str))
        lay.addWidget(self.text, 1)
        row = QHBoxLayout()
        chk = button(tr("Check my connection", "Diagnostics"), "", "activity", name=tr("Check my connection", "Diagnostics"))
        chk.clicked.connect(self.runCheck)
        cp = button(tr("Copy", "Diagnostics"), "", "paste", name=tr("Copy diagnostics", "Diagnostics"))
        cp.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        close = button(tr("Close", "Dialog"), "primary", name=tr("Close", "Dialog"))
        close.clicked.connect(self.accept)
        row.addWidget(chk)
        row.addWidget(cp)
        row.addStretch(1)
        row.addWidget(close)
        lay.addLayout(row)
