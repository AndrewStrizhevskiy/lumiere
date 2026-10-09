# Files and settings Kino Stream creates

Paths follow the XDG variables; defaults shown.

| location | contents | created by | safe to delete? |
|---|---|---|---|
| `~/.config/kino-stream/settings.json` | your settings (cache size, network preset, encryption, on-close, cache folder, tutorial done, language). A damaged file is moved to `settings.json.bad`. | app | yes — settings reset to defaults |
| `~/.local/state/kino-stream/recent.json` | "Continue watching": titles, **the source you opened (a `.torrent` path or the full magnet link, which may contain tracker keys)**, resume position | app | yes — the list is emptied (Settings → Clear history does the same) |
| `~/.local/state/kino-stream/<infohash>.cache.json` (also holds the eviction journal), `<infohash>.resume` | the durable index of which pieces are in a cache | engine | **only together with that cache folder** (otherwise the cache folder is refused as "unmanaged" until you delete it too) |
| `~/.local/state/kino-stream/gui.log`, `crash.log` | warnings/errors and native crash stacks (rotating, ≤1 MB). Magnet links and peer addresses are not logged. | app | yes |
| `~/.cache/kino-stream/<infohash>/` | the streamed data (sparse file) plus the marker `.kino-stream-managed`; at most the cache limit | engine | yes, via Settings → "Saved data" (preferred) or by deleting the folder **and** its `<infohash>.*` files above |
| a folder you chose in Settings | same layout as above | engine | same; Kino Stream never deletes it by itself except the per-video folders it created, on your request |
| `$XDG_RUNTIME_DIR/kino-stream-gui.sock` (fallback: `~/.local/state/kino-stream/gui.sock`) | owner-only socket that hands a second launch to the running window; never in `/tmp`; a socket not owned by you is refused | app | removed on exit; a stale one is replaced at the next start |
| `$XDG_RUNTIME_DIR/kino-stream-<pid>.sock` | mpv control socket of the **command line tool** | CLI | removed on exit; leftovers after a crash/kill are harmless |
| install files | see [INSTALL.md](INSTALL.md) | `packaging/install.sh` | `packaging/uninstall.sh` |

What Kino Stream deletes by itself: data inside its own managed cache folders — old parts while streaming (that is the point of the limit),
and the whole per-video folder on close only if you set *When I close a video → delete*. Anything else is deleted only when you press
a delete button and confirm. Deletion is confined to direct children of the cache folder that carry Kino Stream's marker and a valid hash name.

Network: Kino Stream never asks your router to open ports (no UPnP/NAT-PMP). It opens a listening port for BitTorrent peers while a video is open.
