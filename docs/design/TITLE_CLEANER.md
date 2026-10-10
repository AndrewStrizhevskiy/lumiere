# Offline title cleaner — rules and limitations

Module: `kino_stream/titles.py` (pure; imports only `re`, `unicodedata`, `dataclasses`, `datetime`). Tests: `tests/test_titles.py` (29), `tests/test_continue_watching.py` (14).
It reads the `title` field already stored in `recent.json` (the name of the video file that was played, without folder). It writes nothing and makes no network request.

## What it does
1. Strips a known video extension and shows dot/underscore separators as spaces (dots are kept as punctuation in names that already use spaces: `Dr. Strangelove 1964`).
2. Looks for **strong release tags** (resolution, source, codec, HDR, audio format). Text before the first strong tag is the title; text after it is noise.
3. Takes a **year** only when all hold: it is a plausible film year (1888 .. current year + 1), it sits directly before the release tags (or is the single parenthesised year, `Title (1999)`), and no other plausible year is adjacent.
4. Weak words (`EXTENDED`, `REMASTERED`, `PROPER`, …) are removed only after a year or a strong tag, so `The Final Cut` is kept intact.
5. Keeps spelling, case, accents and punctuation of the original. NFC-normalises Unicode for matching only.
6. Anything else falls back to the **readable filename** with no year. The original name is always available (`DisplayTitle.original`, shown in the card tooltip).

## Examples (from the tests)
| input | shown | year |
|---|---|---|
| `Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv` | Some Movie | 2024 |
| `Le.Fabuleux.Destin.d.Amelie.Poulain.2001.1080p…` | Le Fabuleux Destin d Amelie Poulain | 2001 |
| `Movie.Night.2024.2025.1080p.WEB-DL` | Movie Night 2024 2025 (tags cut, years kept in the title) | none |
| `IMG_2048.mov` | IMG 2048 | none |
| `Sintel.2010.mkv` (no release tags) | Sintel 2010 | none |
| `Show.S01E02.720p.HDTV.x264` | Show S01E02 720p HDTV x264 | none (declined) |
| `Show.S01.COMPLETE.1080p`, `Pixar.Collection.1995-2020.1080p` | whole name, readable | none (declined) |
| `Blade.Runner.2049.2017.2160p.UHD.BluRay.x265-GRP` | Blade Runner 2049 | 2017 |
| `Film.2019.VOSTFR.1080p.WEB-DL.x264` | Film 2019 VOSTFR (unknown tag left in) | none |
| empty / whitespace | empty (the UI then falls back to the stored name) | none |

## Known limitations (deliberate or inherent)
- **Ambiguous release names.** Two adjacent plausible years (`Film.2019.2020`), a year-like number in the title (`2001 A Space Odyssey`, `Blade Runner 2049` are handled only because a later plausible year follows; a title that is itself a year-like number *and* has no release year is not distinguishable), or no release tags at all, give no year and sometimes leave noise in the title. This is intended: an honest imperfect filename is preferred to a wrong identity.
- **Non-Latin and heavily decorated names** are kept as they are; only the extension and separators change. Group tags in the middle of a name and unusual tag spellings are not recognised.
- **Television episodes and season packs** are *recognised only to be declined*: the cleaner never presents them as a film, and does not extract show, season or episode. The card shows the readable filename.
- **Multi-file torrents.** The stored `title` is the file the player opened. The GUI always opens the *largest video file* (`pick_video_file`), so for a season pack the card names one episode (shown as a readable filename), and the other episodes cannot be reached from the GUI at all today. The cleaner cannot fix this; see `HISTORY_MODEL_PROPOSAL.md`.
- **No verification.** The cleaner does not know whether a film exists. It cannot correct a wrong filename, find alternate titles, or translate.
- **Language.** Release tags are English-centric. An unknown tag such as `VOSTFR` is not recognised: it stays in the title and, because it sits between the year and the release tags, also suppresses the year (`Film 2019 VOSTFR`, no year). `MULTi` is recognised.
- **A year is not verified** against any source; it is "the year written in the file name, in a position that is conventionally the release year".
- Real-world metadata (posters, synopses, correct titles) is **not** provided and not tested.
