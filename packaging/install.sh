#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Install Lumière for the current user. Needs no root, no network and no pip; touches only the paths listed below.
#   packaging/install.sh [--check] [--no-desktop-db]
#   --check           only verify the system dependencies and print what would be installed
#   --no-desktop-db   do not run update-desktop-database
# Installs into (all under $HOME unless XDG_* / LUMIERE_BIN say otherwise):
#   $DATA/lumiere/app/            the Python packages (lumiere, lumiere_ui)
#   $BIN/lumiere, $BIN/lumiere-gui                 launchers
#   $DATA/applications/lumiere.desktop                 menu entry + .torrent / magnet: association (does NOT change your defaults)
#   $DATA/icons/hicolor/scalable/apps/lumiere.svg      icon
#   $BIN/kino-stream, $BIN/kino-stream-gui         small compatibility launchers for the former name (they just run the new ones)
# A former installation (name kino-stream) is replaced: its app folder, menu entry and icon are removed; your settings, history and cache are NOT touched here
# (the application itself migrates its folders on first start, see docs/FILES_AND_DATA.md).
set -eu
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="${LUMIERE_BIN:-$HOME/.local/bin}"
APP="$DATA/lumiere/app"

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
       echo "choose another directory with LUMIERE_BIN=<dir without %>" >&2; exit 1 ;;
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
  echo "launcher -> $BIN/lumiere, $BIN/lumiere-gui (+ compatibility launchers kino-stream, kino-stream-gui)"
  echo "desktop  -> $DATA/applications/lumiere.desktop"
  echo "icon     -> $DATA/icons/hicolor/scalable/apps/lumiere.svg"
  [ -z "$missing" ] && echo "dependencies: OK"
  exit 0
fi

mkdir -p "$APP" "$BIN" "$DATA/applications" "$DATA/icons/hicolor/scalable/apps"
rm -rf "$APP/lumiere" "$APP/lumiere_ui"
cp -r "$HERE/lumiere" "$HERE/lumiere_ui" "$APP/"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +

for pair in "lumiere:lumiere" "lumiere-gui:lumiere_ui"; do
  name="${pair%%:*}"; mod="${pair##*:}"
  target="$BIN/$name"
  if [ -e "$target" ] && ! grep -q "lumiere installer\|kino-stream installer" "$target" 2>/dev/null; then
    echo "refusing to overwrite $target (not created by this installer)" >&2; exit 1
  fi
  {
    printf '%s\n' '#!/bin/sh' '# lumiere installer: generated launcher, removed by packaging/uninstall.sh'
    printf '%s\n' "PYTHONPATH=$(sh_quote "$APP")\"\${PYTHONPATH:+:\$PYTHONPATH}\" exec python3 -m $mod \"\$@\""
  } > "$target"
  chmod 755 "$target"
done

# Compatibility launchers for the former command names (no duplicate implementation: they exec the new launchers). Never overwrite something we did not create.
for pair in "kino-stream:lumiere" "kino-stream-gui:lumiere-gui"; do
  old="${pair%%:*}"; new="${pair##*:}"
  target="$BIN/$old"
  if [ -e "$target" ] && ! grep -q "lumiere installer\|kino-stream installer" "$target" 2>/dev/null; then
    echo "  note: $target exists and was not created by this installer: left alone" >&2; continue
  fi
  {
    printf '%s\n' '#!/bin/sh' '# lumiere installer: compatibility launcher for the former name, removed by packaging/uninstall.sh'
    printf '%s\n' "exec $(sh_quote "$BIN/$new") \"\$@\""
  } > "$target"
  chmod 755 "$target"
done

exec_line="Exec=\"$(desktop_exec_quote "$BIN/lumiere-gui")\" -- %U"       # "--": a file name can never be read as an option
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    "Exec=@EXEC@") printf '%s\n' "$exec_line" ;;
    *) printf '%s\n' "$line" ;;
  esac
done < "$HERE/packaging/lumiere.desktop.in" > "$DATA/applications/lumiere.desktop"
cp "$HERE/packaging/lumiere.svg" "$DATA/icons/hicolor/scalable/apps/lumiere.svg"
# A former installation: only what this installer created (menu entry, icon, app folder). User data is never touched.
OLD_DESKTOP="$DATA/applications/kino-stream.desktop"
if [ -f "$OLD_DESKTOP" ] && grep -q "kino-stream-gui" "$OLD_DESKTOP" 2>/dev/null; then
  rm -f "$OLD_DESKTOP" "$DATA/icons/hicolor/scalable/apps/kino-stream.svg"
  echo "  replaced the former menu entry (kino-stream.desktop)"
fi
if [ -d "$DATA/kino-stream/app" ]; then rm -rf "$DATA/kino-stream/app"; rmdir "$DATA/kino-stream" 2>/dev/null || true; echo "  removed the former application folder"; fi
if [ "$DESKTOP_DB" = 1 ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
  command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$DATA/icons/hicolor/index.theme" ] && gtk-update-icon-cache -q "$DATA/icons/hicolor" 2>/dev/null || true
fi
echo "Installed Lumière $(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import lumiere; print(lumiere.__version__)' "$APP")"
echo "  start it from the application menu, or run: $BIN/lumiere-gui"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "  note: $BIN is not on your PATH; the menu entry works regardless" ;; esac
echo "  your default apps for .torrent / magnet: links were NOT changed (see docs/INSTALL.md)"
