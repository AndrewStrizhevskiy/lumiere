# Stage 1 proposal — interaction quality and a film-aware "Continue watching"

> **Status (updated after the owner's review): Phase 0 (offline titles) and the low-risk interaction refinements were approved and are implemented in the sandbox — see `PHASE0_AND_INTERACTION_IMPLEMENTATION.md`. No online provider was selected; Phase 1/2 (any network metadata, posters, a persistent setting) remain unapproved and unimplemented. The text below is the original Stage 1 proposal; where it was wrong, it is corrected and marked.**
> *(Original status line:* proposal for owner review, nothing implemented.*)* No external metadata request has been made by the application, no persistent data format was changed, and no setting was added.
> Work stays in the sandbox (a local working copy (not part of this repository)); the public candidate, the private original and the release-work clone are untouched; the baseline patch and hash manifest (a local recovery baseline (not part of this repository)) are intact and the 11 files carrying the earlier installer/engine work are byte-identical to the public candidate.
> Provider facts below were read from the providers' own pages on 2026-10-09 (summarised by a tool; **verify them before relying on them for a decision**). Nothing here is legal advice.

**How to read this document.** Every section carries one of these labels.
**[VERIFIED]** — read in the code or measured/run in this session on this machine. **[SOURCE]** — taken from a provider's own page as retrieved on 2026-10-09 and summarised by a tool; re-check before relying on it.
**[PROPOSED]** — a design for your review; nothing of it exists. **[ASSUMPTION]** — believed but not verified. **[DECISION]** — needs you. The *Assumptions* and *Unresolved decisions* are collected at the end.

## Part A — what exists today **[VERIFIED]**

### A1. Continue watching: data model and persistence (verified in code)
| aspect | current behaviour |
|---|---|
| storage | `~/.local/state/kino-stream/recent.json`, written atomically (temp file + replace), a damaged file is moved to `recent.json.bad`; `{"version": 1, "items": [...]}`; at most 12 items; `version` is written but not checked on load |
| identity | **`infohash` only** — one entry per *torrent*, not per film or file. A multi-file torrent (a 13-file pack was seen in real use) has a single entry; the engine plays the largest video file each time, and the played file's index/path is **not stored** |
| fields | `infohash`, `title`, `source` (a `.torrent` path or the full magnet link), `size`, `last_opened`, `position_s`, `duration_s`, `watched` (true at ≥92 % played) |
| title | `MediaInfo.title = opts.title or Path(file).stem or torrent name` — i.e. the **file stem of the chosen video file**, e.g. `Some.Movie.2024.1080p.WEB-DL.x264-GROUP`. The torrent name is available (`torrent_name`) but not persisted |
| "last watched" | **not stored.** `last_opened` is set when a video is opened; playback does not update it. A "last watched 12 minutes ago" line would really mean "last opened" unless a `last_played` timestamp is added |
| who writes | `touch()` runs on the **engine thread** (bridge callback), `update_position()`/`remove()`/`clear()` on the **GUI thread**, with no lock — a latent race that a metadata writer must not make worse |
| display | `RecentCard`: initials tile, title (elided), "Watched / Resume at m:ss / Not started", progress bar. The whole card list is rebuilt on every change (`set_recent`) |
| settings / migration | `Settings` dataclass in `settings.json`; unknown keys are ignored on load, new fields take defaults (so adding a field is backward compatible; an *older* app would drop the new key when it saves). No migration framework exists or is needed for additive fields |
| existing metadata / library code | **none** (the word "metadata" in the code means torrent metadata fetched through libtorrent) |
| playback cache | `~/.cache/kino-stream/<infohash>/…` under a hard size limit; only marker-bearing, hash-named children of the cache root are ever deleted by the program |

### A2. Interaction audit **[VERIFIED]** (code read; timings measured on this machine, offscreen software rendering)
*Animated today:* screen changes fade in over 200 ms (`fade_in`, opacity effect; **not** applied to the playback screen); the tutorial fades in and cross-fades between steps (120/200 ms); toasts fade; progress bars ease over 200 ms. Reduced motion is honoured by `fade_in` and the tutorial.
*Instant today (no transition):* button hover/pressed/checked (style-sheet rules, 5 `:hover` rules); the recent-video cards had an **instant** hover (set through `enterEvent` and a per-event style sheet, which re-polishes the card on every enter/leave) — **correction: an earlier version of this audit said the cards had no hover at all, which was wrong**; banners appear and disappear instantly (a layout jump that pushes the whole page), playback controls and the "fetching" card show/hide instantly, dialogs and the opening overlay appear instantly, the recent list is rebuilt wholesale.
*Observations:* (1) the busy spinner repaints continuously (33 repaints/s measured) and its rotation does not consult the reduced-motion setting, which every other animation does; (2) the style sheet cannot animate, so hover transitions would need small custom painting; (3) banners and the playback controls appear instantly, so the content below a banner jumps. **These are observations, not verdicts:** a 33 Hz spinner on a desktop is not a problem in itself, and a 200 ms fade is not wasteful at the measured cost. The recommendations in Part C are based on usability (affordance on cards, no layout jump, reduced-motion consistency), not on animation for its own sake, and every one of them can be declined without affecting the rest.

| measurement | result |
|---|---|
| `grab()` of Home, plain vs with the opacity effect that `fade_in` applies | 2.84 ms → 4.27 ms (+1.4 ms per frame) |
| `grab()` of Settings, plain vs with the effect | 1.86 ms → 2.08 ms |
| longest event-loop gap during a Home→Settings change with the 200 ms fade | 9.8 ms (under one 60 Hz frame) |
| spinner repaint rate | 33 /s while visible |
These are relative costs on a fast desktop with software rendering. They say nothing about slow hardware, and they neither show that the fade needs changing (+1.4 ms per frame is well inside a 16.7 ms frame here) nor that animation improves responsiveness. Any addition would be measured against this baseline (Part C).

## Part B — metadata architecture **[PROPOSED]**

### B1. Phases (each independently shippable; each needs your approval to start)
* **Phase 0 — readable titles without any network.** A pure, offline function turns a release name into a display title and year (`Some.Movie.2024.1080p.WEB-DL.x264-GROUP` → **Some Movie · 2024**) and *declines* what is not a film (episodes, season packs, camera files). No external request, no new setting, no stored data (the result is computed when the card is drawn). Honest labelling: this is "cleaned from the file name", not identification.
* **Phase 1 — optional online identification** by a provider you approve, off by default, behind one persistent setting, with a local metadata store separate from the playback cache.
* **Phase 2 — optional artwork and synopsis**, only if a provider's terms allow caching and display in a GPL desktop application.
* *Not planned in this work:* library view, collections, watch-lists, recommendations, library-wide search.

### B2. Phase 0 prototype result **[VERIFIED for the prototype only]** (scratch code, not in the repository; 22 deliberately awkward names; the production function does not exist)
| kind of name | result |
|---|---|
| standard releases (year + quality tags + group), titles containing numbers ("Blade Runner 2049 2017", "2001 A Space Odyssey 1968", "1917 2019", "12 Years a Slave"), non-ASCII ("Amélie"), bracketed tags, same title different year ("Crash 1996/2004") | handled correctly |
| no year and no release tags ("Tears of Steel.mkv", "holiday_video_final_v2.mp4") | shown as a cleaned file name, flagged *unidentified* |
| episode markers (`S01E03`) | declined |
| **failures found by the prototype** — each becomes a required test | `IMG_2048.mov` read as title "IMG", year 2048 (needs a plausible-year range); a season pack `S01.Complete` was accepted (needs a standalone-season rule); `Movie.2020.2021` — two year tokens, the choice is a guess (must be flagged ambiguous) |
Conclusion: a rule-based cleaner is good enough for display and wrong often enough that it must (a) never invent a year it did not read, (b) decline or flag instead of guessing, and (c) be tested against a fixture list that includes these failures.

### B3. Phase 1 pipeline
`open (existing workflow, unchanged)` → `playback starts` → **in the background, only if online metadata is enabled:** candidate = Phase-0 title + year → provider search → **match evaluation** → store → update the card.
* Runs in a worker thread (queued signal back to the GUI thread). Playback never waits for it, never depends on it, and a failure is silent apart from the card keeping its cleaned title.
* **Match rule (strict, explainable):** accept only when the normalised title (case, accents, punctuation) is equal **and** the year equals the file's year (when the file has none: accept only if exactly one candidate has that title and it is a feature film; otherwise `ambiguous`). No fuzzy acceptance. The reason for the decision is stored (`match_rule`).
* **Decline** instead of looking up: episode/season patterns, several video files that look like a series, more than one plausible title, names that are not release names. A torrent with several films is looked up per *file*, never as one.
* Lookups happen when an item is **opened**, never at application start, never for the whole library. Results (including "no match") are cached so the same title is not queried twice; "no match" expires after a long period, a positive result after the provider's permitted cache time.

### B4. Data model (separate from playback state; additive)
`metadata.json` (new, in the state directory — **not** under the playback cache root, so it cannot touch cache-size guarantees or cache deletion; removed by `uninstall --purge-data` like the other state files), atomic writes, `version` field, entries keyed by a stable media key `infohash + ":" + file index` (the *file*, not just the torrent):
`display_title`, `original_title?`, `year?`, `synopsis?`, `provider`, `provider_id` (stable identifier; two films with similar names never merge because identity is the provider id plus the media key), `status` (`unresolved | local | matched | ambiguous | declined | failed | disabled`), `match_rule`, `looked_up_at`, `poster_file?`.
`recent.json` gains only additive optional keys: `file_index`, `file_name`, `last_played`. Older versions of the app keep these keys when they re-save the list (items are free-form dictionaries).
*Single-writer rule:* all metadata and recent-list writes move to the GUI thread (fixing the engine-thread write noted in A1).

### B5. Candidate providers **[SOURCE]** for terms, **[PROPOSED]** for the recommendation
| option | key / account | licence and terms (as read) | what it can give | privacy / other implications |
|---|---|---|---|---|
| **Phase 0 only: no provider** | none | — | cleaned title + year from the file name | nothing leaves the machine |
| **Wikidata** (Action API `wbsearchentities` / SPARQL) | none | structured data is CC0; API etiquette requires an **identifying User-Agent with contact information** and asks clients to respect rate limits (429/Retry-After) | title, original title, year, stable item id; short descriptions; **no free poster artwork** (film posters are generally not freely licensed) | the query (title [+ year]), your IP address and the User-Agent go to Wikimedia. The User-Agent policy needs a contact address — **the project has none yet and none is invented here** |
| **TMDB** | **API key required** | free for **non-commercial** use only, attribution text and logo required, **data may not be cached longer than six months**, no derivatives of the API/content, no ML training, TMDB may change/terminate at any time | best coverage: titles, years, synopses, posters | each lookup and each image download reveals the film and your IP to TMDB/its CDN. A GPL application cannot ship a secret shared key safely; options are a key per user (a **new key requirement for users — to be discussed, not assumed**) or a proxy service (privacy and operating burden — not recommended). Whether TMDB's terms are compatible with a freely redistributable GPL application needs qualified review |
| **OMDb** | key required (free keys exist; the page states no daily limit) | content under **CC BY-NC 4.0**; the poster API is for patrons only | titles, years, plot | same exposure as TMDB; non-commercial data licence |
| **IMDb non-commercial datasets** (offline TSV files) | none | "personal and non-commercial use"; the page does not address software/redistribution; refreshed daily | title, original title, year, type, id; **no posters or synopsis** | no per-title request at all, but the files are large and cannot be shipped with the application; the user would have to download them — much heavier, and licence compatibility with a GPL project is unclear |
*Not considered:* scraping websites, services needing user accounts/OAuth.
**Recommendation (for your decision):** approve **Phase 0 now** (no network, no setting). For Phase 1, **Wikidata** is the only option that needs no key and no per-user credential and whose data licence is unrestricted, at the price of no artwork/synopsis and the User-Agent contact requirement; TMDB gives the richest result but brings a key requirement, non-commercial and cache-time limits and attribution duties that should be reviewed before any commitment. I would not start Phase 2 (artwork) until that review.

### B6. Privacy design (applies to every provider)
| rule | how |
|---|---|
| minimum data | only the cleaned title string (and year) is sent — never a path, magnet link, info-hash, tracker, peer, position, library list, user name or setting |
| no URLs from torrents | requests go only to a fixed, code-defined host list; a poster URL is accepted only from the provider's own response and only for an allow-listed image host; redirects to other hosts are refused |
| nothing on start-up | no request when the app starts or when it merely shows the list; requests only for an item the user opens, only if the user enabled the feature |
| off by default, clearly disableable | one setting (Settings → "Film information"), default **off**; the settings text states what is sent to whom; turning it off stops requests immediately and optionally clears stored metadata |
| no repeated queries | positive and negative results cached locally; one in-flight request per title |
| failures never matter | short timeouts (a few seconds), at most one retry later, no user-visible error, playback unaffected |
| secrets | no credential in the repository, in logs or in `settings.json`; if a key were ever needed it would be read from the environment or the system keyring and never logged; query strings are not logged |
| viewing activity | a title lookup *does* reveal that this IP is interested in that film; this cannot be removed, only minimised and made opt-in — the settings text must say so |

**What an external provider would receive, and when** (Wikidata or TMDB alike): when you open a film with the feature enabled and no cached answer exists — one HTTPS request containing the cleaned title and year, your IP address, a generic application User-Agent and (TMDB) the API key; and, only in Phase 2, one image request per poster (revealing the same film to the image host). Nothing else, at no other time.

### B7. User-facing states
* *Opening a film:* unchanged (the existing opening overlay), with calmer stage text from the engine's phase ("Opening the torrent file", "Looking for sources", "Preparing playback") — no metadata wording there; metadata is never a loading step.
* *Card, no information yet:* the **cleaned title** immediately (Phase 0); if even that fails, the cleaned file name. Never an empty label, a placeholder poster or an invented year.
* *Card, matched:* title (serif), then one quiet line `2024 · Resume at 5:00`, with "Opened 12 minutes ago" only where the data supports it (the card says *opened*, not *watched*, unless `last_played` is added). If the title arrives while the film plays, the text changes in place with a short cross-fade; the card keeps its size, so nothing shifts.
* *Ambiguous / declined / offline / provider error:* the card simply keeps the cleaned title. No banner, no spinner, no error dialog. A small "Wrong title? Use file name" action (context menu) is proposed for matched entries.
* *Artwork (Phase 2 only):* a small poster thumbnail inside the existing card; the current wide initials tile stays as the fallback. Not a poster wall.

## Part C — interaction and animation strategy **[PROPOSED]** (baseline numbers in A2 are **[VERIFIED]**)
Principles: respond immediately (no animation ever delays an action); animate only state changes people notice; reuse Qt's property animations; durations 120/200/320 ms with ease-out; one shared helper, not a framework; **measure every addition against the baseline in A2**; reduced motion = instant.
| area | proposal | cost / risk to measure |
|---|---|---|
| hover / pressed / focus on buttons, cards, inputs | a tiny `QVariantAnimation` (≈120 ms) driving a hover-progress value that `ActionButton`/`RecentCard` paint (the style sheet cannot animate); focus ring appears immediately (no delay) | one widget repaint per frame while it changes |
| recent cards | hover lift-free: surface tone change + hairline, animated by the same helper (no per-event style sheet any more); keyboard focus = ring around the content; pressed state | repaint of one card |
| screen changes | keep the 200 ms fade (measured +1.4 ms/frame); make it interruptible (rapid navigation restarts from the current opacity); never on the playback screen (GL surface) | frame gaps during rapid changes |
| banner / toast | animate the banner's height (≈160 ms) instead of an instant jump; content below moves smoothly; instant under reduced motion | relayout per frame of a few widgets |
| opening / waiting feedback | calm spinner at a lower repaint rate, **static under reduced motion** (today it ignores the setting); stage text from engine phases | repaint rate |
| playback controls | fade the control bars by animating the gradient's alpha in `paintEvent` (not an opacity effect over the GL widget, which can force offscreen rendering); controls must stay visible while the pointer or keyboard focus is on them, in fullscreen and when paused; the fade never delays play/pause or seek | needs a real-display measurement first |
| layout stability | fixed card height and single-line elided text; cross-fade text in place; no wholesale rebuild of the card list when one entry changes | layout-shift test |
| window resize during transitions | animations act on opacity/height only, never on geometry that the resize also changes | resize-while-animating test |
All animation callbacks only update a number and request a repaint; no I/O, no metadata or engine calls. Playback and opening never wait for an animation.

## Part D — files likely to change (after approval)
*UI refinements:* `kino_stream_ui/widgets.py` (hover animation helper, banner animation, spinner), `home.py` (RecentCard, list update without rebuild), `player.py` (control fade), `mainwindow.py` (interruptible screen change), `theme.py` (motion tokens), `motion.py`; tests `test_accessibility.py` (extended), new `test_motion.py`.
*Phase 0:* new `kino_stream/releasename.py` (pure function, toolkit-free), `home.py` (use it), tests with a fixture list. *Phase 1 (only after approval):* new `kino_stream/metadata/` (store, provider interface, matcher, worker), `kino_stream/settings.py` (+1 field), `kino_stream/recent.py` (additive keys, single-writer), `kino_stream_ui/bridge.py` (signals), `settings_screen.py` (one section), `docs/FILES_AND_DATA.md`, `packaging/uninstall.sh` (nothing new if the store lives in the state directory).
*Not touched:* the playback engine, the cache code, the installer/engine fixes already recorded.

## Part E — testing strategy
No live internet in ordinary tests: the HTTP layer is an injected callable; a fake provider and local JSON fixtures in each provider's response shape drive the tests.
*Metadata:* successful match; no match; ambiguous (two candidates, same title different years); incorrect candidate (wrong year) rejected; timeout; provider error status; malformed/truncated JSON; unexpected types; repeated lookup served from the cache; negative-result caching; update of an existing recent entry; **position, progress and watched flag preserved**; fallback to a readable file name; multi-file torrent (per-file keys, series pack declined); feature disabled → the transport is asserted never called; **a provider that blocks forever does not delay opening or playback**; metadata failure leaves file and magnet workflows intact; poster host allow-list and redirect refusal (Phase 2); no secret in logs.
*Interaction:* hover/focus/pressed/disabled pixel states in both themes; animation completion and interruption; rapid navigation; resize during a transition; reduced-motion makes every animation instant and the spinner static; keyboard focus order and visibility; playback controls stay visible under pointer/focus/fullscreen/pause; a measurement test that fails if the per-frame cost of the screen fade exceeds a stated budget.

## Part F — persistent changes, migrations, risks **[PROPOSED]**, all additive; none made
| change | effect on existing data | compatibility |
|---|---|---|
| new `Settings.online_metadata` (default `false`) | none for existing users; absent key = off | an older app ignores it and drops it when it saves — the feature simply stays off there |
| `recent.json` optional keys `file_index`, `file_name`, `last_played` | existing items unchanged | older apps preserve unknown keys when re-saving |
| new `metadata.json` (+ optional poster files) in the state directory | new files only | removed by `uninstall --purge-data`; outside the cache size limit by design |
| Phase 0 | no persistent change | — |
Risks: wrong identification (mitigated by strict matching, decline-when-unsure, "Use file name"); provider terms changing (TMDB can change or terminate); non-commercial licences versus a GPL project (needs review); the Wikimedia User-Agent contact requirement; engine/GUI thread race in the recent list (fixed as part of the work); animation cost on slow hardware (measured and reduced-motion honoured).

## Assumptions **[ASSUMPTION]** (not verified)
1. Provider terms are as summarised from their pages on 2026-10-09; the summarising tool can err and the terms can change (TMDB states it may). Nothing was checked against the providers' full legal documents or privacy policies.
2. That film posters are generally not freely licensed (so Wikidata/Wikimedia would give no usable artwork) is general knowledge, not checked on a provider page here.
3. That a rule-based cleaner reaches useful accuracy on *real* release names rests on 22 hand-picked names; real-world accuracy is unmeasured.
4. That animation costs on slower hardware are acceptable is unmeasured (all timings are from one fast machine, offscreen software rendering; real-display GL playback was not measured for control fades).
5. That an older version of the application keeps unknown `recent.json` keys is **verified in the code** (`load`/`touch`/`save` keep the dictionaries); that it drops an unknown `settings.json` key on save is also verified in the code. Behaviour of third-party tools reading these files is unknown.
6. That a GPL application can use TMDB or OMDb within their terms is **unknown** and needs qualified review.

## Unresolved decisions **[DECISION]**
Phase 0 go/no-go; provider for Phase 1 (or none); the persistent setting and additive keys; which UI refinements may start; the "opened" vs "watched" wording; whether a maintainer contact exists for a Wikimedia User-Agent (none is invented here); whether any legal review of provider terms is wanted before Phase 1/2.

## Decisions requested from you
1. Approve **Phase 0** (offline readable titles, no setting, no network)?
2. Provider for Phase 1: **Wikidata** (no key, no artwork), **TMDB** (key + non-commercial/attribution/cache limits + legal review), or none for now?
3. Persistent setting `online_metadata` (default off) and the additive `recent.json` keys: approve the migration approach?
4. Approve the low-risk UI refinements in Part C (hover/focus transitions, interruptible screen fade, banner height animation, spinner fix) to start now, with the playback-control fade only after a real-display measurement?
5. "Last watched" wording: add a `last_played` timestamp, or keep the honest "opened"?

## Decision log (owner's answers to this proposal)
| decision | answer |
|---|---|
| Phase 0 offline titles | **Approved and implemented** (`kino_stream/titles.py`); a title and year are shown only on clear evidence, otherwise a readable file name |
| online provider | **none selected**. Wikidata is a possible future candidate, *not* approved; TMDB/OMDb out of scope until their terms are reviewed |
| persistent setting / data-model change | **not approved**: no `online_metadata` setting, no new keys in `recent.json`, no `last_played`, identity stays the infohash |
| "Last watched" wording | stays honest: the timestamp is when the item was **opened**; it is only shown in the tooltip, labelled "Last opened" |
| UI refinements | approved: card hover/pressed/focus, interruptible screen fade, animated banner, reduced-motion spinner; **playback-control fade conditional** — measured, not implemented (see the implementation document) |
