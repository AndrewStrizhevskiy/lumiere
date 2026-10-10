#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Remove what packaging/install.sh created. Your settings, history and downloaded cache data are KEPT unless you pass --purge-data.
#   packaging/uninstall.sh [--purge-data] [--dry-run] [--no-desktop-db]
# --purge-data removes ONLY: $XDG_CONFIG_HOME/lumiere, $XDG_STATE_HOME/lumiere and the cache folder from settings.json when it is
# the default one ($XDG_CACHE_HOME/lumiere) - plus the same folders of the former name (kino-stream: a link, or the data if never migrated). A custom cache folder is never deleted by this script; it is printed so you can decide.
set -eu
DATA="${XDG_DATA_HOME:-$HOME/.local/share}"
BIN="${LUMIERE_BIN:-$HOME/.local/bin}"
CONF="${XDG_CONFIG_HOME:-$HOME/.config}/lumiere"
STATE="${XDG_STATE_HOME:-$HOME/.local/state}/lumiere"
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/lumiere"
OLD_CONF="${XDG_CONFIG_HOME:-$HOME/.config}/kino-stream"      # the former folders (a link to the new ones after the first start of the new version, or the real data if never migrated)
OLD_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/kino-stream"
OLD_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/kino-stream"
PURGE=0; DRY=0; DESKTOP_DB=1
for a in "$@"; do
  case "$a" in
    --purge-data) PURGE=1 ;;
    --dry-run) DRY=1 ;;
    --no-desktop-db) DESKTOP_DB=0 ;;
    -h|--help) sed -n '3,9p' "$0"; exit 0 ;;
    *) echo "unknown option: $a" >&2; exit 2 ;;
  esac
done
rm_() { if [ -e "$1" ] || [ -L "$1" ]; then echo "remove $1"; [ "$DRY" = 1 ] || rm -rf -- "$1"; fi; }

for n in lumiere lumiere-gui kino-stream kino-stream-gui; do        # the last two: compatibility launchers (or a former installation)
  if [ -f "$BIN/$n" ] && grep -q "lumiere installer\|kino-stream installer" "$BIN/$n"; then rm_ "$BIN/$n"
  elif [ -e "$BIN/$n" ]; then echo "skip $BIN/$n (not created by this installer)"; fi
done
rm_ "$DATA/applications/lumiere.desktop"
rm_ "$DATA/icons/hicolor/scalable/apps/lumiere.svg"
rm_ "$DATA/lumiere/app"
rm_ "$DATA/applications/kino-stream.desktop"                      # former installation, if still there
rm_ "$DATA/icons/hicolor/scalable/apps/kino-stream.svg"
rm_ "$DATA/kino-stream/app"
[ "$DRY" = 1 ] || rmdir "$DATA/kino-stream" 2>/dev/null || true
[ "$DRY" = 1 ] || rmdir "$DATA/lumiere" 2>/dev/null || true
if [ "$DRY" = 0 ] && [ "$DESKTOP_DB" = 1 ]; then
  command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$DATA/applications" 2>/dev/null || true
fi

if [ "$PURGE" = 1 ]; then
  custom="$(python3 - "$CONF/settings.json" "$CACHE" "$OLD_CACHE" <<'PY' 2>/dev/null || true
import json, sys
try:
    root = json.load(open(sys.argv[1])).get("cache_root") or ""
except Exception:
    root = ""
if root and root not in (sys.argv[2], sys.argv[3]):
    print(root)
PY
)"
  rm_ "$OLD_CONF"; rm_ "$OLD_STATE"; rm_ "$OLD_CACHE"        # links (or the unmigrated data) of the former name first
  rm_ "$CONF"
  rm_ "$STATE"
  rm_ "$CACHE"
  [ -n "$custom" ] && echo "kept your custom cache folder: $custom  (delete it yourself if you want the space back)"
else
  echo "kept your settings, history and cache data (use --purge-data to remove them; see docs/FILES_AND_DATA.md)"
fi
echo "Uninstalled. other applications and system settings were not touched."
