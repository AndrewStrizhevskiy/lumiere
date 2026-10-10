# SPDX-License-Identifier: GPL-3.0-or-later
"""One-time, recoverable migration of the user's folders from the former name `kino-stream` to `lumiere`.

    ~/.config/kino-stream      -> ~/.config/lumiere        (settings.json)
    ~/.local/state/kino-stream -> ~/.local/state/lumiere   (recent.json, cache indexes/journals, logs)
    ~/.cache/kino-stream       -> ~/.cache/lumiere         (the default streaming cache)

(the `XDG_*_HOME` variables are honoured). Nothing is copied and nothing is deleted: each folder is *renamed* (one atomic operation on the same file system, so a large cache is not
duplicated) and a symbolic link `kino-stream -> lumiere` is left in its place, so every absolute path stored in older data (resume data, an old settings.json, an older installed copy of the
application that is still running) keeps working. The data is therefore retained, intact, under both names.

Safety rules
* Only when the new folder does not exist (or is an empty folder) and the old one is a real folder. If both hold data, nothing is touched and the new folder is used (the old one is left alone).
* A small journal (`.lumiere-migration.json` next to the folders) records the step in progress. If the process dies between the rename and the creation of the link, the next start
  completes the link; if it dies before the rename, nothing has changed and the migration simply runs again.
* Any error is logged and ignored: a failed migration never prevents the application from starting (the old folder then stays where it is and the new one is created empty).
* Reverting is `rm <base>/kino-stream && mv <base>/lumiere <base>/kino-stream` for each base folder.
"""
from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from pathlib import Path

log = logging.getLogger("lumiere.migrate")

LEGACY, CURRENT = "kino-stream", "lumiere"
JOURNAL = ".lumiere-migration.json"
_done: set[str] = set()


def base_dirs(env: Mapping | None = None, home: Path | None = None) -> dict[str, Path]:
    """The three base folders (XDG-aware): config, state, cache."""
    env = os.environ if env is None else env
    home = Path(home) if home else Path.home()
    return {
        "config": Path(env.get("XDG_CONFIG_HOME") or home / ".config"),
        "state": Path(env.get("XDG_STATE_HOME") or home / ".local" / "state"),
        "cache": Path(env.get("XDG_CACHE_HOME") or home / ".cache"),
    }


def migrate_base(base: Path) -> str:
    """Migrate `<base>/kino-stream` to `<base>/lumiere`. Returns what happened: 'none', 'migrated', 'recovered', 'kept-both', 'skipped' or 'failed'."""
    old, new, journal = base / LEGACY, base / CURRENT, base / JOURNAL
    try:
        if journal.exists():                                                    # an earlier run was interrupted
            res = _recover(old, new, journal)
            if res:
                return res
        if old.is_symlink():
            return _follow_user_symlink(old, new)                                # already migrated, or the user had relocated the old folder
        if not old.is_dir():
            return "none"                                                        # never existed
        if new.exists() or new.is_symlink():
            if new.is_dir() and not new.is_symlink() and not any(new.iterdir()):
                new.rmdir()                                                      # an empty folder created by an earlier start: the rename may replace it
            else:
                log.warning("both %s and %s exist: not migrating, using %s (the old folder is left untouched)", old, new, new)
                return "kept-both"
        _write_journal(journal, old, new, "rename")
        os.rename(old, new)                                                      # atomic: the data is now at the new name
        _link(old)
        journal.unlink(missing_ok=True)
        log.info("migrated %s -> %s (link left at the old name)", old, new)
        return "migrated"
    except Exception:
        log.exception("migration of %s failed; leaving things as they are", old)
        return "failed"


def _follow_user_symlink(old: Path, new: Path) -> str:
    """`kino-stream` was itself a link chosen by the user (for example to a bigger disk): the new name gets a link to the same place, so the data stays where they put it."""
    target = os.readlink(old)
    if target == CURRENT or new.exists() or new.is_symlink() or not old.exists():
        return "none"                                                            # our own link, an existing new folder, or a dangling link: nothing to follow
    os.symlink(target, new, target_is_directory=True)
    log.info("%s was a link to %s: %s now links to the same place", old, target, new)
    return "linked"


def _link(old: Path) -> None:
    try:
        os.symlink(CURRENT, old, target_is_directory=True)                      # relative target: survives moving the whole home folder
    except FileExistsError:
        pass


def _write_journal(journal: Path, old: Path, new: Path, step: str) -> None:
    tmp = journal.with_name(journal.name + ".tmp")
    tmp.write_text(json.dumps({"from": str(old), "to": str(new), "step": step}))
    os.replace(tmp, journal)


def _recover(old: Path, new: Path, journal: Path) -> str | None:
    """Finish an interrupted migration. Returns a result string if the migration is settled, None to run it normally."""
    if new.is_dir() and not new.is_symlink() and not (old.exists() or old.is_symlink()):
        _link(old)                                                          # died between the rename and the link
        journal.unlink(missing_ok=True)
        log.info("recovered an interrupted migration: link %s -> %s created", old, new)
        return "recovered"
    if old.is_dir() and not old.is_symlink() and not new.exists():
        journal.unlink(missing_ok=True)                                          # died before the rename: nothing changed; run again
        return None
    journal.unlink(missing_ok=True)                                              # settled (link exists) or ambiguous (both exist): never guess
    return "skipped" if old.is_symlink() else None


def migrate_user_dirs(env: Mapping | None = None, home: Path | None = None, force: bool = False) -> dict[str, str]:
    """Migrate the three base folders once per process (per distinct base). Safe to call from anywhere, any number of times."""
    result = {}
    for kind, base in base_dirs(env, home).items():
        key = str(base)
        if key in _done and not force:
            continue
        _done.add(key)
        result[kind] = migrate_base(base)
    return result
