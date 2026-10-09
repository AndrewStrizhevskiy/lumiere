"""Application start-up: platform quirks, theme, translations, window."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("LC_NUMERIC", "C")          # libmpv refuses to start under a non-C numeric locale


def install_theme(app) -> None:
    from PyQt6.QtWidgets import QStyleFactory
    from . import theme as T
    app.setStyle(QStyleFactory.create("Fusion"))
    app.setPalette(T.palette())
    app.setFont(T.app_font())
    app.setStyleSheet(T.qss())


def install_translations(app, language: str) -> None:
    """English strings are the source text; a translation is loaded from kino_stream_ui/i18n/kino_<lang>.qm if one exists."""
    from PyQt6.QtCore import QTranslator
    qm = Path(__file__).parent / "i18n" / f"kino_{language}.qm"
    if language != "en" and qm.exists():
        t = QTranslator(app)
        if t.load(str(qm)):
            app.installTranslator(t)
            app._kino_translator = t


def run(argv: list[str] | None = None) -> int:
    from PyQt6.QtWidgets import QApplication
    from kino_stream.settings import Settings
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("Kino Stream")
    app.setDesktopFileName("kino-stream")
    settings = Settings.load()
    install_theme(app)
    install_translations(app, settings.language)
    from .bridge import EngineBridge
    from .mainwindow import MainWindow
    bridge = EngineBridge(settings)
    win = MainWindow(bridge)
    win.show()
    win.maybe_show_tour()
    return app.exec()
