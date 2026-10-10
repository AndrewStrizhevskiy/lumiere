# Proposal: representing several videos of one torrent in "Continue watching"

Status: **PROPOSAL ONLY. Nothing here is implemented; `recent.json` is unchanged.** Needs owner approval before any persistent-data change. `last_played` is deliberately not proposed here.

## 1. Current behaviour (verified in code)
- `kino_stream/recent.py`: one entry per **infohash**; fields `infohash, title, source, size, last_opened, position_s, duration_s, watched`; file `{"version": 1, "items": [...]}`; at most 12 entries; atomic write.
- `touch()` runs on the engine thread when a stream is *opened* (`bridge._from_engine("opened")`), `update_position()` on the GUI thread. There is no lock between them (latent race; unchanged by the design work).
- The GUI never chooses a file: `StreamSession.open(..., file_index=None)` → `pick_video_file()` = the **largest video file** (largest file if none has a video extension). Only the CLI has `--file N`.
- `title` is the name of that file; `size` its size; `file_index` is not stored.
- Resume (`player.py`) looks up the entry by infohash and starts at `position_s` if `watched` is false and `position_s > 10`.

Consequences today:
- **Latent, not active:** for a multi-video torrent the GUI can only ever open one file, so one entry per infohash is consistent *as long as the selection rule does not change*. A season pack therefore shows one episode and the others are unreachable from the GUI.
- It becomes wrong the moment anything can open a different file of the same torrent (a file chooser, "next episode", a changed rule, the CLI `--file`): the saved position would be applied to the wrong video and the title overwritten.
- Failed opens create no entry (`touch` happens on the "opened" event); cache deletion does not touch history.

## 2. Proposed representation (additive)
- Entry identity becomes **(infohash, file_index)**. `file_index` is stable for an infohash (the file list is in the immutable info dictionary). Store also `file_path` (relative path inside the torrent) as a consistency check, not as identity.
- One entry per watched video; the 12-entry limit applies to entries; the UI stays a flat list ordered by `last_opened`. Cards for several files of one torrent are *not* merged and never merged by cleaned title.
- New fields only: `file_index`, `file_path`. Existing fields keep their meaning. Unknown fields are preserved on load/save (needs a round-trip test; the current code already keeps entry dicts whole).
- Not needed before a file chooser exists: until then, no second entry per infohash can be created. **Recommendation: approve the chooser/next-episode feature first, then this change with it.**

## 3. Is a migration necessary?
No bulk migration. **Lazy adoption** of legacy (v1, no `file_index`) entries:
- On open, the engine reports `(infohash, file_index, file_path)`. If a legacy entry with that infohash exists and (its `title` equals the opened file's name, or it is the only entry for that infohash), the entry is **updated in place** with `file_index`/`file_path`; position and `watched` are kept.
- If the match is ambiguous (several legacy candidates, different title), nothing is changed or deleted; the new file gets its own entry and the legacy entry stays as it was.
- A magnet-only legacy entry cannot be resolved offline, which is why a load-time migration is not proposed.
- Format number: keep `version: 1` readers working; bump to 2 only when the first v2 entry is written.

## 4. Duplicates and interrupted downloads
- Same torrent via magnet and via `.torrent`: same infohash → same entry (already true).
- Same film in two different torrents: two entries (different infohash). Never merged by title.
- Legacy + adopted duplicates: prevented by in-place adoption; if ambiguous both remain, nothing is deleted, the user can remove entries individually (existing behaviour).
- Interrupted download / cache removed: history is independent of the cache; opening re-adds the saved source. If the saved `file_index` is out of range or `file_path` differs (damaged file), fall back to `pick_video_file` and do **not** apply the stored position.
- Position and `watched` belong to the (infohash, file_index) entry only.
- Also fix, in the same change: serialise `touch()` / `update_position()` (queue `touch` to the GUI thread or add a lock).

## 5. Testing and safe reversal
- Fixtures: real-shaped v1 files (empty, one item, 12 items, duplicate infohash, extra unknown fields, corrupt JSON → existing `.bad` handling).
- Tests: adoption keeps position/watched; ambiguous adoption deletes nothing; two files of one torrent keep independent positions; round trip preserves unknown fields; out-of-range `file_index` falls back; the 12-item limit; old `RecentItems` (from the public HEAD) can still load a v2 file and show every entry (downgrade test).
- Reversal: before the first v2 write, copy `recent.json` to `recent.json.v1.bak` once (never overwritten). Changes are additive, so deleting the two new fields restores the v1 meaning; a small script can strip them. No data is removed at any step.
- Rollout: sandbox first, with a copy of the user's file only if the owner provides it; nothing is read from the real profile without consent.

## 6. Decisions requested
1. Approve (or not) a file chooser / next-episode feature, which is what makes this change necessary.
2. Approve additive fields `file_index`, `file_path` and lazy adoption as described.
3. Decide separately on `last_played`.
