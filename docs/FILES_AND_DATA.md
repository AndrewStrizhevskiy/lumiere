# Files and settings Lumière creates

Paths follow the XDG variables; defaults shown.

| location | contents | created by | safe to delete? |
|---|---|---|---|
| `~/.config/lumiere/settings.json` | your settings (cache size, network preset, encryption, on-close, cache folder, tutorial done, language). A damaged file is moved to `settings.json.bad`. | app | yes — settings reset to defaults |
| `~/.local/state/lumiere/recent.json` | "Continue watching": titles, **the source you opened (a `.torrent` path or the full magnet link, which may contain tracker keys)**, resume position | app | yes — the list is emptied (Settings → Clear history does the same) |
| `~/.local/state/lumiere/<infohash>.cache.json` (also holds the eviction journal), `<infohash>.resume` | the durable index of which pieces are in a cache | engine | **only together with that cache folder** (otherwise the cache folder is refused as "unmanaged" until you delete it too) |
| `~/.local/state/lumiere/gui.log`, `crash.log` | warnings/errors and native crash stacks (rotating, ≤1 MB). Magnet links and peer addresses are not logged. | app | yes |
| `~/.cache/lumiere/<infohash>/` | the streamed data (sparse file) plus the marker `.lumiere-managed` (folders made by the former version carry `.kino-stream-managed`, which is still recognised and never rewritten); at most the cache limit | engine | yes, via Settings → "Saved data" (preferred) or by deleting the folder **and** its `<infohash>.*` files above |
| a folder you chose in Settings | same layout as above | engine | same; Lumière never deletes it by itself except the per-video folders it created, on your request |
| `$XDG_RUNTIME_DIR/lumiere-gui.sock` (fallback: `~/.local/state/lumiere/gui.sock`) | owner-only socket that hands a second launch to the running window; never in `/tmp`; a socket not owned by you is refused | app | removed on exit; a stale one is replaced at the next start |
| `$XDG_RUNTIME_DIR/lumiere-<pid>.sock` | mpv control socket of the **command line tool** | CLI | removed on exit; leftovers after a crash/kill are harmless |
| install files | see [INSTALL.md](INSTALL.md) | `packaging/install.sh` | `packaging/uninstall.sh` |

What Lumière deletes by itself: data inside its own managed cache folders — old parts while streaming (that is the point of the limit),
and the whole per-video folder on close only if you set *When I close a video → delete*. Anything else is deleted only when you press
a delete button and confirm. Deletion is confined to direct children of the cache folder that carry Lumière's marker and a valid hash name.

Network: Lumière never asks your router to open ports (no UPnP/NAT-PMP). It opens a listening port for BitTorrent peers while a video is open.

## Migration from the former name
Versions up to 0.3.0-rc.1 used the folder name `kino-stream`. When the application (GUI or command line) starts it checks `~/.config`, `~/.local/state` and `~/.cache` (or the `XDG_*_HOME` folders):
* if `kino-stream` is a real folder and `lumiere` does not exist (or is empty), the folder is **renamed** to `lumiere` — one atomic operation, so nothing is copied (a multi-gigabyte cache is not duplicated) and nothing is deleted — and a link `kino-stream -> lumiere` is left at the old name, so every path stored in older data and any older copy of the program that is still running keep working;
* a small journal `.lumiere-migration.json` is written next to the folders for the moment between the rename and the link. If the process dies in that moment, the next start completes the link; if it dies earlier, nothing had changed and the migration simply runs again;
* if both folders hold data, **nothing is touched** (the new folder is used, the old one is left alone); if `kino-stream` was itself a link you made (for example to a bigger disk), `lumiere` becomes a link to the same place;
* a `settings.json` that names the former default cache folder is read as "the default" (the custom cache folder you chose is never changed);
* any error is logged and ignored: the application always starts.
To undo it by hand: `rm ~/.config/kino-stream && mv ~/.config/lumiere ~/.config/kino-stream` (likewise for the state and cache folders). `packaging/uninstall.sh --purge-data` removes both the new folders and the old name's links (or unmigrated data). Settings, `recent.json` formats, cache indexes and cache contents are unchanged by the migration (covered by `tests/test_migration.py`).
