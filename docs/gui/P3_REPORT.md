# P3 — embedded player

- `kino_stream_ui/mpvwidget.py`: libmpv in a `QOpenGLWidget` (flip_y, `LC_NUMERIC=C`, update callback only emits a signal, render context freed with GL current). `NullVideo` replaces it on the `offscreen`/`minimal` Qt platforms, which have no GL widgets.
- `kino_stream_ui/player.py`: controls (play/pause, volume/mute, fullscreen, audio and subtitle menus from mpv's `track-list`), a seek bar with three layers (dark = not on disk, grey = on disk per the engine, amber = played), auto-hiding controls, buffering card, connection panel, resume position, keyboard shortcuts (Space/K, ←/→ 5 s, Shift+←/→ 30 s, ↑/↓ volume, M, F/F11, C, Esc).
- Engine link: the player is polled on the GUI thread every 250 ms and feeds `PlayerState` to `EngineService.update_player` (queued onto the engine thread). Availability for the seek bar comes from `EngineService.availability_async`, evaluated on the engine thread. The UI never imports libtorrent.
- Seek bar caveat: the grey layer is by file position while the bar is by time, so it is exact for constant-bitrate video and approximate for variable bitrate.
- Wording is limited to what is measured: "Waiting for sources" (zero peers right now, after having had some), "Looking for sources…" (never had any), "Fetching this part…" (the engine reports the target region as missing), "Buffering…". No message names a cause such as throttling.
- Tests: `tests/test_ui_player.py` (real libmpv, local swarm, `QT_QPA_PLATFORM=wayland`, a window briefly appears).
