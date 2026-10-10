# Troubleshooting

Start with **Help → Diagnostics** (or the connection button in the player) and **Help → Check my connection**. Results are labelled:
*confirmed* (measured just now), *observed* (seen, cause unknown), *possible* (a hypothesis — not a finding), *not measured*.

| what you see | what it means | what to try |
|---|---|---|
| "Looking for sources…" for a long time | no peer has answered yet | prefer a `.torrent` file over a magnet link; wait a minute for rarely shared videos; **Check my connection** |
| "Waiting for sources" during playback | the number of connected peers is 0 *right now* after having had some | wait; check your internet connection; if it persists, close and reopen the video |
| "Buffering…" / frequent pauses | data arrives slower than the video needs | normal for small or slow swarms; nothing to fix in the app. A different release of the video may have more sharers |
| "Fetching this part…" | you jumped to a part not downloaded yet | wait; the seek bar shows what is already on disk |
| "Can't limit the cache here" | the cache folder's filesystem does not free disk space on hole punching | choose another cache folder (Settings), e.g. on ext4; or use the explicit *temporary mode* (no size limit — read the warning) |
| "Cache folder not managed" | the folder contains files Lumière did not create | choose an empty folder; Lumière never adopts or deletes foreign data |
| "Cache too small" | the limit cannot hold the window ahead + behind | raise the cache size or lower *Keep what you watched* |
| "This video can't be played" | mpv could not decode the file (unsupported codec/container, corrupt data) | try the same file in `mpv` directly; check codecs |
| window doesn't start from the menu | | run `kino-stream-gui` in a terminal and read the output; see `~/.local/state/kino-stream/gui.log` |
| video area black/blank | OpenGL or hardware decoding problem | start with `kino-stream-gui` from a terminal; report the output. (A software-decoding switch is not exposed in the UI yet) |

## If peers never connect

1. `kino-stream doctor --network` — read-only checks of DNS, DHT, UDP trackers and BitTorrent handshakes. Interpret only what it labels *confirmed*.
2. Some networks (public Wi-Fi, mobile hotspots, campuses) block UDP, DHT or BitTorrent. A `.torrent` whose trackers use HTTP/TCP, or **Settings → Hide traffic
   from your network → Always on**, sometimes helps. A VPN can help or hurt; Lumière never changes your VPN, firewall or routes.
3. Lumière does not open router ports (no UPnP). Fewer inbound connections are possible behind NAT, but outbound peers normally suffice.

## Reporting a problem

Open an issue with: the version (`kino-stream-gui --version`), Ubuntu version, session type (Wayland/X11), the **Diagnostics** text (it hides your
home folder and tracker URLs; video titles remain), and `~/.local/state/kino-stream/gui.log` if relevant. Do **not** post magnet links
or `.torrent` files that contain private tracker keys.
