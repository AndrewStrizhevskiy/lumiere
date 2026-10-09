# SPDX-License-Identifier: GPL-3.0-or-later
"""Application start-up: platform quirks, theme, translations, window."""
from __future__ import annotations

import logging
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


APP_ID = "kino-stream"


def parse_target(arg: str) -> str:
    """What a launcher hands us (%U): a path, a file:// URL or a magnet link. Returns '' for anything else."""
    from urllib.parse import unquote, urlparse
    arg = (arg or "").strip()
    if arg.lower().startswith("magnet:?"):
        return arg
    if arg.lower().startswith("file://"):
        arg = unquote(urlparse(arg).path)
    return arg if arg.lower().endswith(".torrent") else ""


def instance_socket_path() -> str:
    """Per-user, private location for the hand-over socket. NOT /tmp: it is world-writable, so another local user could pre-create the
    socket and receive the magnet links we forward. $XDG_RUNTIME_DIR (0700, ours) is preferred, the state directory (made 0700) is the fallback."""
    rt = os.environ.get("XDG_RUNTIME_DIR")
    if rt and _private_dir_ok(Path(rt)):
        return str(Path(rt) / "kino-stream-gui.sock")
    from kino_stream.settings import state_dir
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return str(d / "gui.sock")


def _private_dir_ok(d: Path) -> bool:
    try:
        st = d.stat()
        return d.is_dir() and st.st_uid == os.getuid() and (st.st_mode & 0o077) == 0
    except OSError:
        return False


def socket_is_ours(path: str) -> bool:
    """Only talk to a socket that we own: a squatter's socket is refused rather than handed a magnet link."""
    import stat
    try:
        st = os.stat(path)
    except OSError:
        return False
    return stat.S_ISSOCK(st.st_mode) and st.st_uid == os.getuid()


def forward_to_running_instance(target: str, timeout_ms: int = 800) -> bool:
    """Two instances must never share a cache: if one is already running, hand it the request and let this one exit."""
    from PyQt6.QtNetwork import QLocalSocket
    path = instance_socket_path()
    if not socket_is_ours(path):
        return False
    sock = QLocalSocket()
    sock.connectToServer(path)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write((target or "\x00show").encode("utf-8", "replace"))
    sock.waitForBytesWritten(timeout_ms)
    sock.disconnectFromServer()
    return True


class InstanceServer:
    """Listens for requests from later launches (e.g. clicking a magnet link while the app is open). Owner-only socket; input is size-capped
    and reduced to a .torrent path or magnet link by parse_target()."""
    MAX_REQUEST = 16 * 1024

    def __init__(self, on_request):
        from PyQt6.QtNetwork import QLocalServer
        self.on_request = on_request
        self.path = instance_socket_path()
        if os.path.lexists(self.path) and not socket_is_ours(self.path):
            self.server, self.ok = QLocalServer(), False          # something foreign sits there: never replace or trust it
            logging.getLogger("kino.ui").warning("single-instance socket path is not ours; running without hand-over")
            return
        QLocalServer.removeServer(self.path)                       # stale socket of a crashed run
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.ok = self.server.listen(self.path)
        if not self.ok:
            logging.getLogger("kino.ui").warning("single-instance socket unavailable: %s", self.server.errorString())
        self.server.newConnection.connect(self._new)

    def _new(self):
        while self.server.hasPendingConnections():
            c = self.server.nextPendingConnection()
            c.waitForReadyRead(500)
            data = bytes(c.read(self.MAX_REQUEST)).decode("utf-8", "replace")
            c.disconnectFromServer()
            self.on_request("" if data == "\x00show" else parse_target(data))


def setup_logging() -> None:
    """Warnings and errors go to ~/.local/state/kino-stream/gui.log (a desktop launch has no terminal). Magnet links, peer addresses
    and file contents are never logged by the code base."""
    import faulthandler
    import logging
    from logging.handlers import RotatingFileHandler
    from kino_stream.settings import state_dir
    d = state_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(d / "gui.log", maxBytes=512 * 1024, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root = logging.getLogger()
        root.addHandler(h)
        root.setLevel(logging.WARNING)
        faulthandler.enable(open(d / "crash.log", "a"))
    except OSError:
        pass


def run(argv: list[str] | None = None) -> int:
    import argparse
    argv = list(sys.argv if argv is None else argv)
    ap = argparse.ArgumentParser(prog="kino-stream-gui", description="Kino Stream - watch a torrent while it downloads.")
    ap.add_argument("target", nargs="*", help="a .torrent file or magnet link to open")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--smoke", action="store_true", help=argparse.SUPPRESS)       # start, draw one frame, exit 0 (packaging test)
    args, qt_args = ap.parse_known_args(argv[1:])
    if args.version:
        from kino_stream import __version__
        print(f"kino-stream {__version__}")
        return 0
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication
    from kino_stream.settings import Settings
    from .mpvwidget import set_default_surface_format
    set_default_surface_format()
    app = QApplication([argv[0]] + qt_args)
    app.setApplicationName("Kino Stream")
    app.setDesktopFileName(APP_ID)
    target = next((t for t in map(parse_target, args.target) if t), "")
    if not args.smoke and forward_to_running_instance(target):
        return 0
    setup_logging()
    settings = Settings.load()
    install_theme(app)
    install_translations(app, settings.language)
    from .bridge import EngineBridge
    from .mainwindow import MainWindow
    bridge = EngineBridge(settings)
    win = MainWindow(bridge)
    server = None if args.smoke else InstanceServer(win.handle_external)
    win.show()
    if args.smoke:
        QTimer.singleShot(600, app.quit)
        code = app.exec()
        win.close()
        return code
    win.maybe_show_tour()
    if target:
        QTimer.singleShot(400, lambda: win.handle_external(target))
    code = app.exec()
    del server
    return code
