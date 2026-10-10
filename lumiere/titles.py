# SPDX-License-Identifier: GPL-3.0-or-later
"""Readable titles for "Continue watching" - offline, pure, conservative.

`clean_release_name()` turns a release/file name such as ``Some.Movie.2024.1080p.WEB-DL.x264-GROUP.mkv`` into ``Some Movie`` + year 2024 when the evidence is clear,
and otherwise returns a *readable* version of the name (extension dropped, dots/underscores shown as spaces) without a year. It is a pure function: no I/O, no network,
no Qt, no clock (the plausible-year ceiling is a parameter). It never invents anything: spelling, case, accents and punctuation of the original are kept; it never
adds a year that is not in the name; it declines to treat likely episodes, season packs and collections as a single film.

`DisplayTitle` / `for_recent_item()` are the one small boundary the interface uses. Today the only source is the file name; a future metadata source could return the same
structure with another `source` value without any change in the UI. Nothing here is persisted, and the original name is always kept in `DisplayTitle.original`."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

EARLIEST_YEAR = 1888                      # first film; nothing earlier can be a release year

_EXT = re.compile(r"\.(?:mkv|mp4|m4v|avi|mov|wmv|webm|ts|m2ts|mpg|mpeg|flv|torrent)$", re.I)
_SEP = re.compile(r"[._]+")
_BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_PAREN_YEAR = re.compile(r"[(\[]\s*((?:18|19|20)\d{2})\s*[)\]]")
_YEAR = re.compile(r"(?:18|19|20)\d{2}")
_LEADING_SITE = re.compile(r"^\s*(?:www\.)?[A-Za-z0-9-]+\.(?:com|org|net|info|to|cc|tv|me|io)\s*[-–—]\s*", re.I)

# Strong release tags: resolution, source, video/audio codec, HDR. A tag of this kind is evidence that the text before it is a title (and the text after it noise).
_STRONG = re.compile(
    r"^(?:(?:360|480|576|720|1080|1440|2160|4320)[pi]|4k|8k|uhd|hdr10?\+?|dolby[ ._-]?vision|dv|sdr|"
    r"blu-?ray|bd(?:rip|remux)|brrip|remux|web-?dl|web-?rip|webrip|webdl|hdtv|pdtv|dvdrip|dvd-?r|dvdscr|hdrip|hdcam|cam(?:rip)?|telesync|"
    r"x26[45]|h\.?26[45]|hevc|avc|xvid|divx|av1|vp9|"
    r"aac\d?|ac-?3|e-?ac-?3|ddp?\d?|dd\+|dts(?:-?hd)?|truehd|atmos|flac|opus|10-?bit|8-?bit)$", re.I)
# Weak words only count as noise AFTER a strong tag or a year; before that they may be part of a title ("The Final Cut").
_WEAK = re.compile(r"^(?:extended|unrated|remastered|restored|proper|repack|internal|imax|uncut|theatrical|directors?|cut|multi|dual|subs?|nf|amzn|dsnp|hmax|atvp|yify|yts|rarbg)$", re.I)
# Things that are not a single film.
_EPISODE = re.compile(r"(?:\bS\d{1,2}[ ._-]?E\d{1,3}\b|\b\d{1,2}x\d{2,3}\b|\bE\d{2,3}\b|\bep(?:isode)?[ ._-]?\d{1,3}\b)", re.I)
_SEASON = re.compile(r"(?:\bS\d{1,2}\b(?![ ._-]?E\d)|\bseasons?[ ._-]?\d+\b|\bcomplete[ ._-](?:series|season)\b|\bseries[ ._-]\d+\b)", re.I)
_COLLECTION = re.compile(r"\b(?:collection|trilogy|tetralogy|anthology|box[ ._-]?set|complete[ ._-]series|\d+[ ._-]?movie[ ._-]?pack)\b", re.I)

KIND_CLEANED = "cleaned"       # release noise was removed on clear evidence
KIND_READABLE = "readable"     # no confident cleaning: the file name made readable, no year
KIND_DECLINED = "declined"     # looks like an episode, season pack or collection - not presented as a film


@dataclass(frozen=True)
class CleanedTitle:
    original: str              # exactly what was passed in
    display: str               # what to show
    year: int | None           # only when clear; never guessed
    kind: str                  # KIND_CLEANED | KIND_READABLE | KIND_DECLINED


def _default_max_year() -> int:
    import datetime
    return datetime.date.today().year + 1


def _spaced(s: str) -> str:
    """Show separators as spaces. Dots are separators only in dot-separated names (``Some.Movie.2024``); in a name that already uses spaces
    (``Dr. Strangelove 1964``) a dot is punctuation and is kept. Underscores are always separators."""
    if " " in s.strip() and s.count(" ") >= s.count("."):
        return re.sub(r"_+", " ", s)
    return _SEP.sub(" ", s)


def _readable(s: str) -> str:
    s = _spaced(_EXT.sub("", s))
    return re.sub(r"\s{2,}", " ", s).strip(" -–—")


def _is_strong(tok: str) -> bool:
    head = tok.split("-", 1)[0] if not _STRONG.match(tok) else tok
    return bool(_STRONG.match(tok) or _STRONG.match(head))


def clean_release_name(name: str | None, max_year: int | None = None) -> CleanedTitle:
    original = name or ""
    if not original.strip():
        return CleanedTitle(original, "", None, KIND_READABLE)
    max_year = max_year or _default_max_year()
    s = unicodedata.normalize("NFC", original)                      # macOS-style decomposed accents compare equal to composed ones
    base = _EXT.sub("", s)
    if _EPISODE.search(base) or _SEASON.search(base) or _COLLECTION.search(base):
        return CleanedTitle(original, _readable(s), None, KIND_DECLINED)

    paren = [int(m.group(1)) for m in _PAREN_YEAR.finditer(base) if EARLIEST_YEAR <= int(m.group(1)) <= max_year]
    work = _LEADING_SITE.sub("", base)
    work = re.sub(r"^(?:\s*\[[^\]]*\]\s*)+", " ", work)             # leading [site] / [group] tags
    # a parenthesised year is explicit evidence: the title is what precedes it
    pm = _PAREN_YEAR.search(work)
    if pm and len(paren) == 1:
        title = _readable(work[:pm.start()])
        if title:
            return CleanedTitle(original, title, paren[0], KIND_CLEANED)
    work = _BRACKETS.sub(" ", work)
    work = re.sub(r"[()]", " ", work)
    work = _spaced(work)
    toks = [t for t in re.split(r"\s+", work) if t]
    if not toks:
        return CleanedTitle(original, _readable(s), None, KIND_READABLE)

    strong_at = next((i for i, t in enumerate(toks) if i > 0 and _is_strong(t)), None)
    if strong_at is None:
        # no release tag at all: nothing proves this is a release name, so no year and no cutting ("Sintel.2010.mkv" stays "Sintel 2010")
        return CleanedTitle(original, _readable(s), None, KIND_READABLE)

    dash = re.compile(r"^[-–—]+$")
    head = toks[:strong_at]
    while head and dash.match(head[-1]):                            # " - " separators right before the release tags
        head = head[:-1]
    # words such as EXTENDED / REMASTERED between the year and the first strong tag are noise - but only when a year precedes them
    j = len(head)
    while j > 0 and (_WEAK.match(head[j - 1]) or dash.match(head[j - 1])):
        j -= 1
    if j > 0 and j < len(head) and _YEAR.fullmatch(head[j - 1]) and EARLIEST_YEAR <= int(head[j - 1]) <= max_year:
        head = head[:j]
    cand = [i for i, t in enumerate(head) if _YEAR.fullmatch(t) and EARLIEST_YEAR <= int(t) <= max_year]
    year = None
    title_toks = head
    if cand and cand[-1] == len(head) - 1 and cand[-1] > 0:         # the year sits directly before the release tags
        last = cand[-1]
        prev = head[last - 1]
        if (last - 1) in cand or (dash.match(prev) and (last - 2) in cand):   # two plausible years in a row: cannot tell title from year
            year = None
        else:
            year, title_toks = int(head[last]), head[:last]
    while title_toks and dash.match(title_toks[-1]):
        title_toks = title_toks[:-1]
    title = " ".join(title_toks).strip(" -–—")
    title = re.sub(r"\s{2,}", " ", title)
    if not title:
        return CleanedTitle(original, _readable(s), None, KIND_READABLE)
    return CleanedTitle(original, title, year, KIND_CLEANED)


# ------------------------------------------------------------------------------------------------ the boundary used by the interface
@dataclass(frozen=True)
class DisplayTitle:
    text: str                  # primary line
    year: int | None           # secondary detail, only when clear
    original: str              # the untouched stored name (tooltips, diagnostics)
    source: str                # "filename-cleaned" | "filename" - a future metadata source would use another value


def for_name(name: str | None, max_year: int | None = None) -> DisplayTitle:
    c = clean_release_name(name, max_year)
    source = "filename-cleaned" if c.kind == KIND_CLEANED else "filename"
    return DisplayTitle(c.display or "", c.year, c.original, source)


def for_recent_item(item: dict, max_year: int | None = None) -> DisplayTitle:
    """Display title for one entry of the recent list. Reads only the existing `title` field; the item is never modified."""
    return for_name(str(item.get("title") or ""), max_year)
