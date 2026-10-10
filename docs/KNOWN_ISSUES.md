# Known issues and limitations

Lumière is a **pre-1.0 release candidate**. This page lists what is not resolved, what is not verified, and what was found and fixed, in that order. The detailed engineering record (measurements, root-cause analyses, older wording) is kept in [archive/KNOWN_ISSUES_2026-10-10_detailed.md](archive/KNOWN_ISSUES_2026-10-10_detailed.md).

## 1. Unresolved

### One unexplained native crash (seen once, in the automated tests)
* **What happened.** During development, one run of the complete automated test suite (1 of 18 full runs of the interface work) was killed by a segmentation fault while a GUI test (`tests.test_ui.Window.test_open_failure_maps_to_dialog_and_hides_overlay`) was running. No stack trace was captured (crash reporting and core dumps were off), and the run used an earlier development state of the interface code.
* **What we know.** It has not happened again: not in the later full runs (including runs with crash reporting and core dumps enabled, and two under glibc heap checking), nor in roughly 165 repeated GUI-test runs (60 with an aggressive garbage collector, 11 under a debugger), nor in about 440 loaded command-line/mpv test runs. It has only been seen inside the test run, never while using the application.
* **What we do not know.** The cause: this project's code, PyQt6/Qt, or the test setup are all possible, and a link to the interface changes is neither shown nor excluded. That later runs passed shows the crash is rare, **not** that the application is crash-free.
* **What it could mean for you.** The worst plausible outcome is the application closing. The cache and its journal are designed to survive that and are tested with real `SIGKILL`, so downloaded data should not be corrupted (tested, not guaranteed).
* **If it happens to you,** please open an issue and attach `~/.local/state/lumiere/crash.log` (native stack traces are written there; it was empty in all our application runs). A readable stack would need Qt/Python debug symbols, which were deliberately not installed.

### Real-internet streaming is only lightly verified
In the first real use, three public torrents (about 4.3, 7.0 and 22.8 GB) were opened: the 7 GB one played; the other two never received data ("connected to N peers but no payload", restarted every ~25 s). The cause was not established: the engine does not log whether peers choke us or lack the wanted pieces, so a swarm-side cause cannot be told from a network-side one. A diagnostic for this (peer choke/interest summary) was proposed but is **not implemented**. Everything else was verified against local swarms only. Details: [archive](archive/KNOWN_ISSUES_2026-10-10_detailed.md) §0.

## 2. Not verified / limitations
* **Platform:** developed and tested on one machine: Ubuntu 24.04, GNOME on Wayland, ext4, Python 3.12, PyQt6 6.6.1 on Qt 6.4.2, libmpv 0.37. X11, NVIDIA/AMD graphics, other distributions and other filesystems are untested. No wheel/sdist build exists.
* **Accessibility and display:** keyboard focus, contrast, reduced motion and small windows are covered by automated tests, but **no screen reader**, high-contrast theme, fractional/HiDPI scaling beyond the development display, right-to-left language or multi-monitor fullscreen was tested. Screenshots in `docs/design/screens/` are offscreen renders with made-up titles. Fonts are not bundled: without the named serif/sans families the interface uses generic ones and may look and wrap differently. The theme is chosen with `LUMIERE_THEME=dark|light` (no Settings toggle); GNOME's "reduce animations" is read once at start (`LUMIERE_REDUCE_MOTION` overrides it).
* **Continue watching:** one entry per torrent, and the app opens the largest video of a torrent, so a season pack is one file. The offline title cleaner is deliberately conservative: it cannot identify a film, leaves unknown tags (for example `VOSTFR`) in the title, and declines TV episodes, season packs and collections (the readable file name is shown). See `docs/design/TITLE_CLEANER.md` and `docs/design/HISTORY_MODEL_PROPOSAL.md` (a proposal, not implemented).
* **Audio/subtitle tracks:** exercised on files with one audio track and no subtitles; menus for many tracks are unit-level only.
* **Bounded cache** (details: `docs/HOW_IT_WORKS.md`): needs a file system that releases blocks on hole punching (ext4 tested; others are refused or untested); every eviction re-adds the torrent, so peer connections drop briefly (measured on loopback only); under pressure playback can pause while room is made (the limit is hard, read-ahead is not); startup verifies only a random sample of stored pieces (damage elsewhere is detected when served); power loss was tested with simulated crashes, not real power cuts; one torrent per process.
* **Streaming speed** depends on the swarm and your network: real-swarm cold start was 2–22 s to the first frame and seeks into undownloaded regions 2–12 s on a healthy swarm, much longer on slow ones.
* **Names:** commands and folders were renamed from `kino-stream` to `lumiere` after rc.1; the old names survive only as documented compatibility items (see [NAMING.md](NAMING.md)). The product name is a working name and **not legally cleared**.

## 3. Historical test failures that no longer reproduce (cause unknown)
Two timing-sensitive automated tests failed occasionally early in development and have not failed since. They are **not** known to be fixed; if either recurs, please report it with the full log.
* `tests.test_ui_player … test_magnet_link_plays_end_to_end`: failed in 2 of about 14 early runs (mpv did not reach 2 s of playback within 60 s). Not seen in at least 8 later real-display runs or in dozens of earlier loaded/solo repeats.
* `tests.test_stalls.LostRequests … test_black_holed_seeder_requests_are_cancelled_and_reissued`: failed in some early runs (a stall was not counted within 15 s). Passed in more than 10 later full runs.

## 4. Found and fixed (regression tests in `tests/`)
* **libtorrent `wait_for_alert()` crash** (use-after-free in the Python binding; crashed 3 of 3 in a controlled stress test): the engine now only uses `pop_alerts()`; a test forbids `wait_for_alert` in the package. Root cause and proof: archive §1.
* **False "no payload" restarts after a torrent re-add** (stale high-water mark in the stall detector): fixed by rebasing the mark (`tests/test_stalls.py`).
* **Eviction journal left open after a clean shutdown** (`close()` cancelled an eviction half-way; never exceeded the limit or served wrong data, recovery would finish it): `close()` now lets an in-flight eviction finish.
* **Zeros served for a completed piece under heavy CPU load** (libtorrent's "piece finished" can precede the bytes being readable; seen in 4 of 100 runs at 10-way overload): each piece inside the streamed file is now verified against its SHA-1 the first time it is served. Not measured on real swarms; boundary pieces shared with another file and pure v2 torrents are not checked.
* **Option smuggling through a video's title** (GUI): a torrent file name containing commas could add options to mpv's `loadfile` command; the title is now set as a property (`tests/test_mpv_load.py`).
* **Installer:** launcher paths with spaces or special characters produced a desktop entry GNOME refused to launch: now quoted per the Desktop Entry specification (`%` and control characters are refused with an explanation).
* Earlier engine fixes (peer hints, pieces finishing during eviction) are described in the archive §4.
