# Release readiness — Lumière 0.3.0-rc.2 (release candidate)

**Assessment: a pre-1.0 release candidate** for people who run Ubuntu 24.04 (GNOME on Wayland) and are willing to report problems. It is not claimed to be stable, crash-free or fully verified. Earlier assessments are kept in [archive/RELEASE_READINESS_2026-10_pre-rc2.md](archive/RELEASE_READINESS_2026-10_pre-rc2.md).

## What the evidence covers
| evidence | result | covers |
|---|---|---|
| full suite `python3 -X faulthandler -m unittest discover -s tests -t . -v` | exit 0, **360 tests, 8 skipped** (real-display player tests skip offscreen), 993 s | the code of 0.3.0-rc.1, i.e. before the rename of packages and folders |
| real-display player tests `python3 -X faulthandler -m unittest -v tests.test_ui_player` | exit 0, **10 tests OK** | playback of a torrent file and a magnet link, seeks, failures, keyboard shortcuts (local swarms) |
| targeted tests after the rename and the folder migration | `test_migration` (16), `test_packaging` (14), `test_cache` (20), `test_service`, `test_theme`, `test_craft`, `test_ui`, `test_tour`, `test_launch`, `test_continue_watching`, `test_titles`, `test_piecemap`, `test_scheduler`, `test_release_config`: all OK; every test module imports | the renamed packages, the migration (rename, recovery after interruption, relocated folders, legacy cache marker), the installer upgrade path, cache integrity |
| installation check on a real profile | install, desktop-entry launch, second launch hands over to the running window, uninstall without `--purge-data`: OK; settings, history and caches survived the migration | `packaging/install.sh`, `packaging/uninstall.sh`, `lumiere/migrate.py` |
The full suite was **not** rerun after the rename; the rename and migration changed names, paths and the installer, not the streaming logic. Not run at all: `tests/realswarm.py` (needs the internet) and `tests/large_scenarios.py` (25 GB).

## Open items
* **Unexplained native crash** (once in 18 full test runs, never reproduced) and **lightly verified real-internet streaming**: see [KNOWN_ISSUES.md](KNOWN_ISSUES.md) §1. These are the reasons the release stays a pre-release.
* **Name:** "Lumière" is a working name and is **not legally cleared** ([NAMING.md](NAMING.md)). The decision to keep it was taken on a proportionate search, not on a trademark register search.
* **Packaging names:** `lumiere` is taken on PyPI and in the AUR by unrelated projects; publishing there would need another distribution name.
* **Licence:** GPL-3.0-or-later, collective copyright "the Lumière contributors" ([LICENSING.md](LICENSING.md)); no font or artwork is bundled ([THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)). The compatibility reasoning is documentation, not legal advice.
* **Reports:** security issues via GitHub's private vulnerability reporting; no e-mail address is published.

## Limitations in short
Single test machine and local swarms; no screen-reader, X11, HiDPI or high-contrast testing; fonts not bundled; one Continue-Watching entry per torrent; conservative offline title cleaner. Full list: [KNOWN_ISSUES.md](KNOWN_ISSUES.md) §2.

The earlier per-criterion checklist is archived: [archive/RELEASE_CRITERIA_2026-10-10.md](archive/RELEASE_CRITERIA_2026-10-10.md).
