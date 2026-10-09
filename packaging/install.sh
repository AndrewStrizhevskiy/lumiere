#!/bin/sh
# Install Kino Stream for the current user. Needs no root, no network and no pip; touches only the paths listed below.
#   packaging/install.sh [--check] [--no-desktop-db]
#   --check           only verify the system dependencies and print what would be installed
#   --no-desktop-db   do not run update-desktop-database
# Installs into (all under $HOME unless XDG_* / KINO_STREAM_PREFIX say otherwise):
#   $DATA/kino-stream/app/            the Python packages (kino_stream, kino_stream_ui)
#   $BIN/kino-stream, $BIN/kino-stream-gui                 launchers
#   $DATA/applications/kino-stream.desktop                 menu entry + .torrent / magnet: association (does NOT change your defaults)
#   $DATA/icons/hicolor/scalable/apps/kino-stream.svg      icon
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="${KINO_STREAM_BIN:-$HOME/.local/bin}"
APP="$DATA/kino-stream/app"
CHECK=0; DESKTOP_DB=1
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --no-desktop-db) DESKTOP_DB=0 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done

missing=""
python3 - <<'PY' || missing="python"
import sys
sys.exit(0 if sys.version_info >= (3, 12) else 1)
PY
need() {  # need "<import statement>" "<apt package>"
  python3 -c "$1" >/dev/null 2>&1 || missing="$missing $2"
}
need "import libtorrent; assert libtorrent.__version__.startswith('2.0')" python3-libtorrent
need "import PyQt6.QtWidgets, PyQt6.QtOpenGLWidgets, PyQt6.QtNetwork" python3-pyqt6
need "import PyQt6.QtSvg" python3-pyqt6.qtsvg
need "import mpv" "python3-mpv libmpv2"
command -v mpv >/dev/null 2>&1 || missing="$missing mpv"
if [ -n "$missing" ]; then
  echo "Missing system packages (not installed by this script):$missing" >&2
  echo "Install them with:" >&2
  echo "  sudo apt install python3-libtorrent python3-pyqt6 python3-pyqt6.qtsvg python3-mpv libmpv2 mpv" >&2
  [ "$CHECK" = 1 ] || exit 1
fi

if [ "$CHECK" = 1 ]; then
  echo "app      -> $APP"
  echo "launcher -> $BIN/kino-stream, $BIN/kino-stream-gui"
  echo "desktop  -> $DATA/applications/kino-stream.desktop"
  echo "icon     -> $DATA/icons/hicolor/scalable/apps/kino-stream.svg"
  [ -z "$missing" ] && echo "dependencies: OK"
  exit 0
fi

mkdir -p "$APP" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
rm -rf "$APP/kino_stream" "$APP/kino_stream_ui"
cp -r "$HERE/kino_stream" "$HERE/kino_stream_ui" "$APP/"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +

for pair in "kino-stream:kino_stream" "kino-stream-gui:kino_stream_ui"; do
  name="${pair%%:*}"; mod="${pair##*:}"
  target="$BIN/$name"
  if [ -e "$target" ] && ! grep -q "kino-stream installer" "$target" 2>/dev/null; then
    echo "refusing to overwrite $target (not created by this installer)" >&2; exit 1
  fi
  cat > "$target" <<LAUNCHER
#!/bin/sh
# kino-stream installer: generated launcher, removed by packaging/uninstall.sh
PYTHONPATH="$APP\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m $mod "\$@"
LAUNCHER
  chmod 755 "$target"
done

sed "s|@BIN@|$BIN|" "$HERE/packaging/kino-stream.desktop.in" > "$DATA/applications/kino-stream.desktop"
cp "$HERE/packaging/kino-stream.svg" "$DATA/icons/hicolor/scalable/apps/kino-stream.svg"
if [ "$DESKTOP_DB" = 1 ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$DATA/icons/hicolor/index.theme" ] && gtk-update-icon-cache -q "$DATA/icons/hicolor" 2>/dev/null || true
fi
echo "Installed Kino Stream $(python3 -c "import sys; sys.path.insert(0,'$APP'); import kino_stream; print(kino_stream.__version__)")"
echo "  start it from the application menu, or run: $BIN/kino-stream-gui"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  note: $BIN is not on your PATH; the menu entry works regardless" ;; esac
echo "  your default apps for .torrent / magnet: links were NOT changed (see docs/INSTALL.md)"
