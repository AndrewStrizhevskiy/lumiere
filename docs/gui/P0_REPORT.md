# P0: libmpv inside a QOpenGLWidget on Ubuntu 24.04 / GNOME / Wayland

Result: **works reliably** -> the GUI embeds libmpv (render API) instead of driving a separate mpv window.

Stack: PyQt6 6.6.1 (Qt 6.4.2), python-mpv 1.0.4, libmpv 2.2 (mpv 0.37), Qt platform `wayland`, apt packages only.
Spike: `spikes/p0_qt_mpv.py` (play, pause, resume, seek forward/back, resize, fullscreen, window again; grabs the real GL
framebuffer after every step and checks it is not blank and that frames change after a seek).

| run | decode | result |
|---|---|---|
| 3x 120 s 640x360 test video | software | exit 0, 25.0 fps, frames correct after every step |
| same | `hwdec=auto-safe` (vaapi-copy on the Intel GPU) | exit 0, 25.0 fps |
| 25 GB-class 720p CBR 28 Mbit/s file | software and vaapi-copy | exit 0, 25.0 fps |

Dropped frames over a whole 20 s run including two seeks, a resize and a fullscreen toggle: 30-45 (mostly at those transitions).
Notes: `flip_y=True` is required for `QOpenGLWidget`; `LC_NUMERIC=C` is required by libmpv; `update_cb` is called from an mpv thread and
may only emit a Qt signal; the harmless `Cannot load libcuda.so.1` message comes from ffmpeg probing for NVIDIA.
Not covered by P0: playback from the engine's HTTP URL (done in P3), audio output (disabled in the spike).
