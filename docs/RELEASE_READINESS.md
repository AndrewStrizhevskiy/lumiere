# Release readiness — Kino Stream 0.3.0 (pre-1.0)

## 0. Status of release candidate 0.3.0-rc.1 (2026-10-10) — supersedes §1–§10 below where they differ

**Assessment: a pre-1.0 release candidate, published as a GitHub pre-release.** It is meant for people who run Ubuntu 24.04 (GNOME/Wayland) and are willing to report problems. It is not claimed to be crash-free or fully verified.

### 0.1 What this is
* Lumière 0.3.0 (display name; previously "Kino Stream"): a desktop app (PyQt6 + libmpv) and a command-line tool over one libtorrent streaming engine with a hard-bounded disk cache. Commands, packages and data folders keep the name `kino-stream` for compatibility.
* The history starts from an earlier sanitised development history (15 commits) and adds three commits: the earlier engineering fixes (installer quoting, stall detector, docs), the interface work, and stabilisation fixes + the rename + the release configuration. Commits use a neutral project identity (no personal e-mail).
* Development evidence (crash-investigation logs and scripts, design deltas, recovery archives) is kept locally by the maintainer and is not part of this repository.

### 0.2 Tests (Ubuntu 24.04, GNOME/Wayland, ext4, Python 3.12.3, PyQt6 6.6.1 on Qt 6.4.2, libmpv 0.37, libtorrent 2.0.10)
| command | exit | result |
|---|---|---|
| `python3 -X faulthandler -m unittest discover -s tests -t . -v` | 0 | **360 tests, OK, 8 skipped** (the real-display player tests skip offscreen), 993 s — run on the tree just before the rename and the release configuration |
| `python3 -X faulthandler -m unittest -v tests.test_ui_player` (real libmpv + OpenGL, Wayland) | 0 | **10 tests, OK**, 58 s |
| after the rename: `test_theme test_tour test_launch test_packaging test_ui test_craft test_continue_watching test_accessibility`, then `test_release_config` | OK | 136 tests, 120 s; 4 tests |
Not run: `tests/realswarm.py` (internet), `tests/large_scenarios.py`. The release documentation changes after the full run touch no code except `kino_stream_ui/brand.py`, `home.py`, `app.py` (display name) and `tools/release_config.py`.

### 0.3 Defects found and fixed while preparing the release (regression tests red before, green after)
1. Eviction journal left open after a clean exit (`close()` cancelled an eviction mid-transaction): see `docs/KNOWN_ISSUES.md` 0c.
2. Zeros served for a completed piece under heavy CPU load (libtorrent's "piece finished" can precede the bytes being readable): each in-file piece is now verified against its SHA-1 the first time it is served: `docs/KNOWN_ISSUES.md` 0d. Real-swarm behaviour of this check is not measured.

### 0.4 Intermittent native crash — UNRESOLVED (do not call the application crash-free)
One SIGSEGV (exit 139) in 18 full runs of the interface work's automated tests (earlier code state, no stack, other Qt processes running). Not reproduced in: 4 core-enabled full runs, 2 heap-checked full runs, ≈ 165 GUI-module iterations (60 with an aggressive garbage collector, 11 under gdb) and ≈ 440 CLI/mpv test runs under load. Cause unknown; a link to the interface changes is neither shown nor excluded; a defect in PyQt6/Qt is plausible and unproven. It has only ever been seen inside the test harness. The cache and its journal are crash-safe (tested with real SIGKILL), so the worst plausible outcome is the application closing. Native stacks, if any, go to `~/.local/state/kino-stream/crash.log`. Reading a stack would need Qt/Python debug symbols (system packages), which were not installed.

### 0.5 Open items (not blockers for a labelled pre-release)
* **Name:** "Lumière" is the intended display name but is **not legally cleared**. A proportionate search (2026-10-10) found other software with that name (a dormant GNOME media player from the 2000s, a prototype MPV/Slint player, a 1990s Corel video suite, a text-to-video research model, an image-generation product), `lumiere.app` and `lumiere.video` are registered, and the PyPI name `lumiere` is taken (this project is not published to PyPI). No trademark register (USPTO/EUIPO/other) was searched. A proper clearance is required before the name is treated as final; the name can be reverted with `KINO_STREAM_BRAND=kino` and the display strings are centralised in `kino_stream_ui/brand.py`.
* **Wordmark artwork** (`kino_stream_ui/assets/lumiere-wordmark.svg`, outlines of an OFL font) is optional and off by default (`KINO_STREAM_WORDMARK_ART=1`); see `THIRD_PARTY_NOTICES.md`.
* **Copyright holder** is the collective "Lumière contributors" (`docs/LICENSING.md`).
* **Security and conduct reports** go through GitHub's private advisories; no e-mail address is published.

### 0.6 Known limitations that remain (details in `docs/KNOWN_ISSUES.md`)
Verified on one machine (Ubuntu 24.04/GNOME/Wayland/ext4); no screen reader, X11, HiDPI/fractional scaling or high-contrast testing; real-internet GUI playback unverified (two of three first real torrents never started streaming, cause not established, §7a); fonts not bundled; Continue Watching has one entry per torrent; the title cleaner is deliberately conservative and offline; no wheel/sdist build was tested.

---

## Earlier assessment (2026-10-09; kept as history — its test numbers and recommendation are superseded by §0)

**Recommendation: NOT READY to publish; ready for the maintainer's further review.** Since the previous assessment the installer defect has been fixed and tested, and the real-internet investigation found and fixed one genuine
engine defect — but it did **not** explain why two real torrents never started, and the mandatory release configuration is still missing. Details and the path to "ready" are below.

Conventions: **[V]** verified in the 2026-10-09 evening verification session against the actual repository; **[P]** reported by an earlier session and *not* re-verified;
**[A]** an assumption; **[X]** could not be completed.

## 1. Release candidate

| item | value |
|---|---|
| repository | `kino-stream-public` (local only; **no remote**, no tags pushed) |
| branch / commit [V] | `main` @ `e353b24` (15 commits, neutral author `Kino Stream contributors <noreply@invalid>`) |
| working tree | the repository history (see §0.1); the text of this section was written before publication and is kept as the record of that assessment |

## 2. Tests (run on the working tree described in §1, [V])

Environment: Ubuntu 24.04, GNOME/Wayland session, ext4, Python 3.12.3, PyQt6 6.6.1, libmpv 0.37, python3-libtorrent 2.0.10.

| command | exit | result | time |
|---|---|---|---|
| `python3 -m unittest discover -s tests -t .` (offscreen Qt) | 0 | **179 tests, OK, 7 skipped** (171 before + 8 new: 4 installer-path, 4 stall-detector) | 706.8 s |
| `python3 -m unittest tests.test_ui_player` (real libmpv + OpenGL, Wayland) | 0 | **9 tests, OK** | 51.6 s |
| earlier run on `e353b24` (before these changes) [P] | 0 / 0 | 171 OK, 7 skipped / 9 OK | 702.6 s / 51.8 s |

* The 7 skipped tests in the discovery run are the OpenGL player tests (they skip themselves on the offscreen platform and are covered by the second command); no other test was skipped.
* Dependencies: the player tests need a graphical session with OpenGL (a window flashes up); the engine and CLI tests need `mpv` and `ffmpeg`; the suite is local (loopback swarms) and needs no internet.
* **Intermittent failures, not reproduced in this run, root causes unknown (unresolved):**
  * `tests/test_stalls.py::LostRequests::test_black_holed_seeder_requests_are_cancelled_and_reissued` — failed in 2 of 6 earlier runs [P]; 8 of 8 repeat runs with extra diagnostics passed [P]; passed in the two full runs of this session [V]. Not fixed.
    (The engine fix in §7 touches the same stall-detection code; it is not claimed to affect this test, and the test passed after it.)
  * `tests/test_ui_player.py::test_magnet_link_plays_end_to_end` — failed in 2 of ~14 early runs [P]; not seen in 40+ later runs [P] and passed in this run [V]. Not fixed.
  A green run does not prove either is fixed.
* Not run: `tests/realswarm.py` (internet), `tests/large_scenarios.py` (25 GB).
* Test isolation: tests use temporary `XDG_*`/`HOME` directories and never touch a real user profile.

## 3. Installation and uninstallation

* **Disposable-profile tests [V]** (`tests/test_packaging.py`, 8 tests, part of the 171): repeatable install; only documented files created; other applications' files and `mimeapps.list` unchanged; foreign launcher never overwritten or removed;
  uninstall removes only what was installed and keeps user data; `--purge-data` never removes a custom cache folder; clear message for missing dependencies; `--dry-run` changes nothing.
* **Desktop entry [V]:** `Exec=<launcher> -- %U` (options cannot be injected through file names); `MimeType` declares `.torrent` and `magnet:` support; the installer does not change default applications.
* **Desktop launch and second-launch hand-over [P]** (disposable profile, real Wayland session, earlier sessions).
* **Installer defect found [V] and FIXED [V] (approved by the maintainer):** an install path containing a space (or other special characters) produced an unquoted `Exec=` line that `desktop-file-validate` accepts but GIO rejects, so the
  menu entry would silently not launch (the maintainer's own path has no space and was never affected). The generated launcher script also embedded the path unsafely (double quotes, `$`, backticks).
  * *Quoting rules, checked by really launching entries through GIO* with stub executables that record their argv: the executable goes inside double quotes; inside them `"`, `` ` ``, `$` and `\` need a backslash, every
    literal backslash is doubled again by the string-value rule, and `%` is written `%%`. Verified to launch correctly for paths containing spaces, `'`, `"`, `$`, backticks, backslashes, `& | ; * ? # ( ) < > ~` and non-ASCII characters.
  * *Final choice:* **escape everything that can be escaped; reject only what cannot be represented or is not accepted by the platform.** Control characters (tab, newline…) cannot be expressed and make `desktop-file-validate` fail; a `%` in the
    launcher directory is valid per the specification but GIO (GNOME) rejects such an entry, so the installer refuses with an explanation and `KINO_STREAM_BIN=<dir>` as the way out. A `%` elsewhere (data directory) is fine because only the launcher
    directory appears in the desktop entry. The launcher script now single-quotes the application directory, and the version banner no longer interpolates the path into Python code.
  * *Tests:* `tests/test_packaging.py::PathHandling` (4 tests, 14 path variants): install, `desktop-file-validate`, launcher scripts run, the entry is launched through GIO and the stub receives exactly `[launcher, "--", path]`, uninstall leaves no file behind;
    refused paths write nothing. **Red-green verified:** against the original installer the new tests fail (12 failures, 4 errors); against the fixed installer all 12 packaging tests pass.
  * Not verified: launchers other than GIO (KDE, XFCE…), and `desktop-file-validate`-style checks on the template itself (it contains a placeholder line).
* **Magnet/file handling [V by code review + tests]:** launcher arguments are reduced to a `.torrent` path or a `magnet:?` link, magnet links must contain a BitTorrent info-hash, missing files are reported instead of opened, file names/titles are rendered as plain text; the single-instance socket is in `$XDG_RUNTIME_DIR` (or the 0700 state directory), owner-only, ownership-checked, request-size-capped. Residual: any process running as the same user can ask the app to open a `.torrent` path (same trust boundary).
* Uninstall while the app is running is not specifically handled/tested [X].

## 4. Privacy and Git-history audit

Scope [V]: all 15 reachable revisions, 253 distinct blobs (text and binary), commit metadata, tags and refs, `.git` config/hooks/reflog, unreachable objects (none), tracked files (none untracked), docs, test fixtures, screenshots (PNG text metadata), packaging scripts, `.github` files (there are **no workflows**).
Method: category scans (e-mail addresses, IP addresses, MAC/IPv6, home paths/user names, developer-identity terms, carrier/university/VPN terms, internal tool names, credential patterns, interface names) over every revision, plus manual review of context. Sensitive values are not reproduced here.

Findings:
* **Genuine personal data: none found** (no personal e-mail, address, name, credential, token, key, real network address). Commit author/committer identities are the neutral placeholder only.
* **Residual identifiers (low risk, decision needed):**
  1. All commit dates carry the **+03:00 offset** — a coarse location hint. Removing it needs another history rewrite (not performed).
  2. `docs/NETWORK_FINDINGS.md` describes measurements generically ("a mobile carrier hotspot", "a university Wi-Fi network", "a VPN with a hosted exit abroad"). No names or addresses, but the combination with the time zone narrows who the author might be.
  3. The design docs and one docstring refer to "Prizma" (a third-party product name used as a design reference) — a trademark/locale hint to review.
  4. The local tag `pre-gui-baseline` (see §1).
* **Intentional/synthetic:** documentation-range addresses (`203.0.113.x`), loopback and public resolver addresses, fake e-mails in tests, `/home/otheruser` in a redaction test, interface names `wlan0`/`tun0` used as generic examples, the product name "Kino Stream".
* **Assessment of the residual identifiers (recommendations, nothing changed):**
  * *"Prizma"* (design doc title, one docstring): reveals only that the author used a third-party streaming product as a design reference. I could not verify what that product is, who owns the name, or whether the name points to a language or region.
    It has little technical value and a small trademark/locale hint → **recommend generalizing** ("a bounded cache in the style of some streaming players") in the design doc title and the docstring.
  * *Generic network descriptions* ("mobile carrier hotspot", "university Wi-Fi", "VPN with a hosted exit abroad"): no names or addresses, but together with the +03:00 commit offset they narrow who or where the author is. The technical content
    does not depend on "university" or "abroad" → **recommend generalizing** to "a mobile hotspot", "a managed institutional Wi-Fi network" and "a VPN" (or keep as is if you accept the small hint).
  * *Timestamps*: only a history rewrite can change them (proposal and consequences are for you to approve; see §10).
* **Privacy [P]:** before publication the history was sanitised (raw network measurements, identifying network details, personal addresses and e-mail removed; references to private tools generalised) and scanned by pattern; the scan was repeated on the final commits (see the release notes).
* **Uncertain / not verifiable:** a scan returning zero matches is not proof; unknown identifiers (for example identifying phrasing in prose or screenshots) cannot be excluded by pattern. Screenshots were visually reviewed in earlier sessions [P]; this session verified only that PNG metadata is clean [V]. `docs/real_swarm_report.json` (79 KB) was checked for URLs, addresses and paths by pattern only.

## 5. Licensing and third-party review

* [V] `LICENSE` is byte-identical to the distribution's GPL-3 text; all 73 tracked `.py`/`.sh` files carry `SPDX-License-Identifier: GPL-3.0-or-later`; `pyproject.toml`, README, CONTRIBUTING and `docs/LICENSING.md` agree; the old decision memo is no longer in the tree.
* [V] Dependency licenses re-read from the installed Ubuntu copyright files: PyQt6 GPL-3 (or commercial); libmpv binaries GPL-3+ (source GPL-2+/LGPL-2.1+); python-mpv GPL-2+ or LGPL-2.1+; libtorrent BSD-3-Clause with additional Boost/zlib/Expat/public-domain **and GPL-2+** components (now noted in `docs/LICENSING.md`). Nothing third-party is bundled.
* **Resolved by repository inspection [V]:** the `LICENSE` text is the standard GPL-3; SPDX headers are complete and consistent; the documented dependency licenses match the installed Ubuntu copyright files; nothing third-party is bundled; the old decision memo is gone.
* **Cannot be resolved by inspection — needs the maintainer and/or a qualified reviewer (not legal advice, no legal certainty claimed):**
  1. The project's authority to license its own code under GPL-3.0-or-later: the code was written with substantial AI assistance; the maintainer must confirm they hold, and can license, the copyright, and that no third-party code was copied in. Copyrightability of AI-assisted output varies by jurisdiction.
  2. Icon provenance: the icons were drawn "in the style of" Feather/Lucide and some paths may coincide. The Feather (MIT) and Lucide (ISC) notices are included as a **precaution**; their wording was written from memory and not compared with upstream. This is not proof of compliance.
  3. Whether the "or later" grant is acceptable given PyQt6 is GPL-3 only (the combined work is effectively GPL-3).
  4. Redistribution of binaries (not planned) would bring GPL source-offer duties.
  5. The copyright-holder line ("Kino Stream contributors") has no named holder.

## 6. Security considerations

Covered by tests [V]: cache deletion confined to marked, hash-named children of the cache root; untrusted torrent names/titles rendered as plain text; diagnostics text hides the home directory, URLs, magnet links (except info-hash) and IP addresses; the local HTTP server binds to `127.0.0.1` with a host-header check; single-instance socket safety (see §3).
Not covered: sandboxing of mpv/libtorrent parsing of hostile media or torrents; recent history stores full magnet links in plain text (documented in `docs/FILES_AND_DATA.md`); screen-reader security/accessibility; no independent security review beyond the automated reviews of earlier sessions [P].

## 7. Known issues and limits (see `docs/KNOWN_ISSUES.md`)

* **Two of the first three real-internet torrents did not start streaming in the GUI; the cause is not established** — see §7a for what was verified, what was fixed and what remains hypothesis.
* Tested only on Ubuntu 24.04 / GNOME / Wayland / ext4 / Intel graphics, one machine. X11, other GPUs, filesystems and distributions untested.
* The two intermittent test failures above; every cache eviction briefly drops peer connections (not measured on real swarms); smooth playback is never guaranteed.

## 7a. Real-internet streaming investigation (offline only; no external network test was run)

Inputs: the app's own log (`gui.log`), the history file's structural fields (sources, sizes, durations, positions — not printed), the three `.torrent` files' metadata (aggregates only), the source code and local-swarm experiments.

**Verified [V]**
1. *Sequence of events:* three public torrents were opened in one app session (started 18:56): ≈7.0 GB (13 files, largest an `.mkv` of 7.0 GB) at 19:02, ≈22.8 GB (one `.mkv`) at 19:09:46, ≈4.3 GB (one `.mkv`) at 19:10:52. The first has a recorded duration (≈55 min) and a saved
   position of 84 s, i.e. it streamed; the log has no warnings before 19:10:11. Neither of the other two ever wrote data (no data file in either cache; empty retained-piece maps).
2. *The three torrents are structurally alike:* public (not private), 15 trackers using http/https/udp, no web seeds, 4 MiB pieces. Structure therefore does not explain the difference.
3. *The 25–30 s restart rule* (code, `_sampler`/`_payload_stalled` in `lt_store.py`): every 0.25 s, if peers are connected **and** data is wanted **and** the payload rate stays below ≈1 kB/s for 25 s (`restart_after_cold`, used while nothing has ever been
   downloaded) or 30 s (`stuck_after`, afterwards) **and** ≥15 s have passed since the last restart, the torrent is removed and re-added (all connections drop; reconnection takes ≈1 s locally). The logged intervals (≈25 s) match the cold limit.
4. *Log bug:* the message always printed `stuck_after` ("30s") even when the 25 s cold limit applied. **Fixed** (the message now reports the limit actually used).
5. **Engine defect found by code review and reproduced locally: false stall detection after any re-add.** The payload counter of a new libtorrent handle restarts at zero, but the detector kept the old high-water mark. On a local swarm, after one restart,
   a download flowing at ≈100 kB per 5 s was declared "no payload" and restarted again at +30 s and +60 s. The same applies after every bounded-cache eviction (they re-add the torrent too).
   **Fix:** rebase the mark when the counter has been reset (a fresh observation window for the new handle); thresholds and the 15 s minimum gap are unchanged. **Tests:** `tests/test_stalls.py::NoFalseStuckAfterRestart` (4 deterministic tests). Red-green verified:
   without the rebase a healthy download is flagged at +29.75, 59.75, 89.75, 119.75 s; with it, never; a silent peer is still flagged at 30 s; nothing wanted / no peers is not a stall. The original experiment shows 0 spurious restarts over 70 s after the fix.
   **This defect did not cause the two failed openings** (nothing had ever been downloaded for them, so the mark was 0). It may explain some restarts seen in earlier real-swarm runs (hypothesis, unverified).
6. *Sequential opens work:* on a local swarm, opening torrent A, closing it, opening a different torrent B with the same fixed listen address, then A again all streamed correctly. No state carry-over between openings was found.
7. *Restarts do not block data once a seeder unchokes us:* with a libtorrent seeder that chokes every peer for 40 s (resp. 70 s), the first data arrived 0.4 s after the unchoke, with one (resp. two) restarts in between.

**Hypotheses, not established [A]**
* H1: the connected peers (22–27, resp. 3–5) were choking us or lacked the requested pieces (a swarm-side cause). Consistent with the symptoms; the engine does not record choke/interest state, so the existing logs cannot confirm or exclude it.
* H2: a network-path cause (for example a filter or VPN effect on BitTorrent traffic). Less likely if the network state was unchanged between 19:02 and 19:10, but that is unknown; no external test was run.
* H3: with non-libtorrent peers whose optimistic-unchoke interval is ≥30 s, a 25 s restart cadence could keep resetting our place in the queue. Not supported by item 7 (libtorrent seeder only); untested against other clients. **The timeouts were not changed.**

**Proposed, not implemented (needs approval):** include a one-line peer summary in the restart message (how many connected peers choke us, how many have none of the wanted pieces). It changes no behaviour and would turn the next occurrence into evidence.
**Not performed:** `kino-stream doctor --network`, any external probe or download, a re-run of the failing torrents, instrumentation of the running application.

## 8. Release gate and reproducibility

* [V] `python3 tools/release_config.py check` exits 1 and `git hook run pre-push` exits 1: unfilled placeholders — the GITHUB_REPO placeholder (5 files: issue-template config, CONTRIBUTING, README, SECURITY, `docs/INSTALL.md`), the SECURITY_EMAIL placeholder (SECURITY.md), the CONDUCT_EMAIL placeholder (CODE_OF_CONDUCT.md).
* The gate has limits: the hook is a per-clone setting (`core.hooksPath`) that fresh clones do not have, `git push --no-verify` bypasses it, and it checks placeholders and `LICENSE` only — not author identity, tags or history.
* Reproducibility: no build step; the tree installs from source with `./packaging/install.sh`; test results depend on the machine (timing-sensitive engine tests).

## 9. Remaining manual checks [X]
* Launch from the GNOME application menu (click-through); `xdg-mime` default-handler flow; behaviour on X11, other GPUs/filesystems; launchers other than GIO.
* A real-internet torrent end to end through the GUI **with the engine fix**, and diagnosis of the two torrents that never started (needs the proposed diagnostic and/or an approved external test).
* Screen readers; multi-monitor fullscreen; many-track audio/subtitle menus; uninstall while running.
* Qualified licensing review (§5). Independent look at screenshots for identifying content.

## 10. Blockers and decisions before publication
1. Provide the GitHub `owner/name`, the security e-mail and the conduct e-mail; they will then be applied with `tools/release_config.py apply`, and `check` re-run. (Not invented; placeholders intact.)
2. Decide the public commit identity (current: `Kino Stream contributors <noreply@invalid>`) and whether to normalise the +03:00 timestamps (another history rewrite; needs explicit approval of the proposal and consequences).
3. Approve committing the finished, tested changes (installer fix, engine stall-detector fix, tests, documentation). Nothing has been committed.
4. Decide how to proceed on the unexplained real-internet failure: approve the proposed diagnostic (§7a) and/or an approved external test (hosts, exposure and purpose are listed in the verification report), or publish only as an explicitly experimental pre-release.
5. Decide about the local tag `pre-gui-baseline`, the "Prizma" references and the generalization of the network descriptions (§4 recommendations).
6. Confirm the licensing questions in §5 with a qualified reviewer, including the icon notices and the copyright-holder line.
7. Explicit, separate approval for creating the repository, pushing and tagging. None of this has been done.

## Addendum (design sandbox, 2026-10-09 evening): intermittent native crash — UNRESOLVED
In the design sandbox, 1 of 8 full discovery runs died with a native crash (SIGSEGV, exit 139) in a GUI test that passes alone, in its module and in 94 loop iterations; its stack trace was not captured (tracer off). The other 7 full runs passed (the later ones with the tracer on, core dumps enabled and, in two runs, deliberate concurrent Qt load). The cause is **unknown**, the failure has **not** been reproduced and is **not** fixed, and a relation to the design changes can be neither shown nor excluded.
This does not change the recommendation: the project must not be described as reliably passing the full regression. Evidence and method: `docs/design/PHASE0_AND_INTERACTION_IMPLEMENTATION.md` §5 (sandbox) and the preserved logs in the maintainer's local crash-investigation archive (not part of this repository). The public candidate itself has not shown this crash (its earlier full runs did not include the design code).
Update (2026-10-10): the sandbox has now had 9 full discovery runs (1 crash, 8 passes; latest: 316 tests, 7 skipped, exit 0) and about 165 further clean GUI-module iterations, including 60 with an aggressive garbage collector and 11 under gdb. Still no stack, still not reproduced, cause still **unknown**. Assessment and next-step recommendation: the maintainer's local crash-investigation archive (not part of this repository).
Update (2026-10-10, later): two further full runs under glibc heap checking in an isolated copy (316 tests, exit 0 both) were clean. The crash is still unreproduced and its cause unknown; see the maintainer's local crash-investigation archive (not part of this repository).
