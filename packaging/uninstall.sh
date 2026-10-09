#!/bin/sh
# Remove what packaging/install.sh created. Your settings, history and downloaded cache data are KEPT unless you pass --purge-data.
#   packaging/uninstall.sh [--purge-data] [--dry-run] [--no-desktop-db]
# --purge-data removes ONLY: $XDG_CONFIG_HOME/kino-stream, $XDG_STATE_HOME/kino-stream and the cache folder from settings.json when it is
# the default one ($XDG_CACHE_HOME/kino-stream). A custom cache folder is never deleted by this script; it is printed so you can decide.
set -eu
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="${KINO_STREAM_BIN:-$HOME/.local/bin}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/kino-stream"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/kino-stream"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/kino-stream"
PURGE=0; DRY=0; DESKTOP_DB=1
for a in "$@"; do
  case "$a" in
    --purge-data) PURGE=1 ;;
    --dry-run) DRY=1 ;;
    --no-desktop-db) DESKTOP_DB=0 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
rm_() { if [ -e "$1" ] || [ -L "$1" ]; then echo "remove $1"; [ "$DRY" = 1 ] || rm -rf -- "$1"; fi; }

for n in kino-stream kino-stream-gui; do
  if [ -f "$BIN/$n" ] && grep -q "kino-stream installer" "$BIN/$n"; then rm_ "$BIN/$n"
  elif [ -e "$BIN/$n" ]; then echo "skip $BIN/$n (not created by this installer)"; fi
done
rm_ "$DATA/applications/kino-stream.desktop"
rm_ "$DATA/icons/hicolor/scalable/apps/kino-stream.svg"
rm_ "$DATA/kino-stream/app"
[ "$DRY" = 1 ] || rmdir "$DATA/kino-stream" 2>/dev/null || true
if [ "$DRY" = 0 ] && [ "$DESKTOP_DB" = 1 ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
fi

if [ "$PURGE" = 1 ]; then
  custom="$(python3 - "$CONF/settings.json" "$CACHE" <<'PY' 2>/dev/null || true
import json, sys
try:
    root = json.load(open(sys.argv[1])).get("cache_root") or ""
except Exception:
    root = ""
if root and root != sys.argv[2]:
    print(root)
PY
)"
  rm_ "$CONF"
  rm_ "$STATE"
  rm_ "$CACHE"
  [ -n "$custom" ] && echo "kept your custom cache folder: $custom  (delete it yourself if you want the space back)"
else
  echo "kept your settings, history and cache data (use --purge-data to remove them; see docs/FILES_AND_DATA.md)"
fi
echo "Uninstalled. other applications and system settings were not touched."
