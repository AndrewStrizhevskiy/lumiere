#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Lumière (command and folders keep the name kino-stream) for the current user. Needs no root, no network and no pip; touches only the paths listed below.
#   packaging/install.sh [--check] [--no-desktop-db]
#   --check           only verify the system dependencies and print what would be installed
#   --no-desktop-db   do not run update-desktop-database
# Installs into (all under $HOME unless XDG_* / KINO_STREAM_BIN say otherwise):
#   $DATA/kino-stream/app/            the Python packages (kino_stream, kino_stream_ui)
#   $BIN/kino-stream, $BIN/kino-stream-gui                 launchers
#   $DATA/applications/kino-stream.desktop                 menu entry + .torrent / magnet: association (does NOT change your defaults)
#   $DATA/icons/hicolor/scalable/apps/kino-stream.svg      icon
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="${KINO_STREAM_BIN:-$HOME/.local/bin}"
APP="$DATA/kino-stream/app"

# Quoting helpers: the install paths are user-controlled and end up in a shell script and in a .desktop file.
# Desktop Entry spec: the executable is written inside "...", inside the quotes  "  `  $  \  need a backslash, "%" is written "%%",
# and because string values are unescaped first, every literal backslash is doubled again (one backslash becomes four).
# This was verified by really launching entries with GIO for paths with spaces, quotes, $, backticks, backslashes, & | ; * ? # ( ) < > ~
# and non-ASCII characters. Not representable: control characters (tab, newline...; desktop-file-validate fails) and "%" (valid per spec,
# but GIO, which GNOME uses, rejects such an entry) - those are refused instead of installing a launcher that silently does not start.
desktop_exec_quote() {
  printf '%s' "$1" | sed -e 's/\\/\\\\\\\\/g' -e 's/"/\\\\"/g' -e 's/`/\\\\`/g' -e 's/\$/\\\\$/g' -e 's/%/%%/g'
}
sh_quote() {   # POSIX single quoting
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"
}
for p in "$BIN" "$APP" "$DATA"; do
  case "$p" in
    *[[:cntrl:]]*) echo "refusing to install: the path contains a control character (tab, newline, ...): it cannot be used in a desktop entry" >&2; exit 1 ;;
  esac
done
case "$BIN" in
  *%*) echo "refusing to install: the launcher directory contains a '%' character, which GNOME's launcher rejects in desktop entries: $BIN" >&2
       echo "choose another directory with KINO_STREAM_BIN=<dir without %>" >&2; exit 1 ;;
esac
CHECK=0; DESKTOP_DB=1
for a in "$@"; do
  case "$a" in
    --check) CHECK=1 ;;
    --no-desktop-db) DESKTOP_DB=0 ;;
    -h|--help) sed -n '3,13p' "$0"; exit 0 ;;
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
  {
    printf '%s\n' '#!/bin/sh' '# kino-stream installer: generated launcher, removed by packaging/uninstall.sh'
    printf '%s\n' "PYTHONPATH=$(sh_quote "$APP")\"\${PYTHONPATH:+:\$PYTHONPATH}\" exec python3 -m $mod \"\$@\""
  } > "$target"
  chmod 755 "$target"
done

exec_line="Exec=\"$(desktop_exec_quote "$BIN/kino-stream-gui")\" -- %U"       # "--": a file name can never be read as an option
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "Exec=@EXEC@") printf '%s\n' "$exec_line" ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$HERE/packaging/kino-stream.desktop.in" > "$DATA/applications/kino-stream.desktop"
cp "$HERE/packaging/kino-stream.svg" "$DATA/icons/hicolor/scalable/apps/kino-stream.svg"
if [ "$DESKTOP_DB" = 1 ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$DATA/icons/hicolor/index.theme" ] && gtk-update-icon-cache -q "$DATA/icons/hicolor" 2>/dev/null || true
fi
echo "Installed Lumière (kino-stream) $(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import kino_stream; print(kino_stream.__version__)' "$APP")"
echo "  start it from the application menu, or run: $BIN/kino-stream-gui"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  note: $BIN is not on your PATH; the menu entry works regardless" ;; esac
echo "  your default apps for .torrent / magnet: links were NOT changed (see docs/INSTALL.md)"
