# P4 — first-run tutorial

- `kino_stream_ui/tour.py`: `TourOverlay` (dimmed layer + card), five steps — Watch while it downloads, Open a video, How buffering works, Your disk stays under control, You're ready. Painted illustrations (`Illustration`), cross-fade between steps (120/200 ms), Back / Next / Skip / Finish, dots, "Step n of 5".
- Keyboard: ← / → navigate, Esc skips, Enter/Space activate the focused button; Tab order Skip → Back → Next. The card's accessible name and description follow the step. (This PyQt6 build exposes no `QAccessible` class, so no explicit screen-reader event is sent; the accessible name changes are all Qt gets.)
- Persistence: `Settings.tour_done`. Finish and Skip both set it, so the tutorial never nags; Help → Show Tutorial Again, the Home "?" button and Settings reopen it at step 1. The settings screen reloads the flag so a later settings edit cannot reset it.
- Reduced motion: `motion.reduced_motion()` — `KINO_REDUCE_MOTION=1|0` overrides, otherwise GNOME `enable-animations` (read-only). With it on: no fades, no step transitions, illustrations rest on their final frame. `fade_in` everywhere obeys it too.
- Wording: streaming quality is described as depending on peers, network and speed, "cannot be guaranteed"; the disk-limit step uses the configured limit.
- Isolation: the module imports nothing from `kino_stream`; tests assert the bridge is never called while the tutorial runs.
