"""Recently opened items ("Continue watching"). Toolkit-agnostic, atomic JSON in the state directory."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .settings import state_dir

LIMIT = 12


class RecentItems:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or state_dir() / "recent.json")
        self.items: list[dict] = []
        self.load()

    def load(self) -> None:
        try:
            d = json.loads(self.path.read_text())
            self.items = [i for i in d.get("items", []) if isinstance(i, dict) and i.get("infohash")]
        except FileNotFoundError:
            self.items = []
        except Exception:
            try:
                os.replace(self.path, str(self.path) + ".bad")
            except OSError:
                pass
            self.items = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps({"version": 1, "items": self.items}, indent=1))
        os.replace(tmp, self.path)

    def touch(self, infohash: str, title: str, source: str, size: int = 0) -> dict:
        it = next((i for i in self.items if i["infohash"] == infohash), None)
        if it is None:
            it = {"infohash": infohash, "position_s": 0.0, "duration_s": 0.0, "watched": False}
        else:
            self.items.remove(it)
        it.update(title=title, source=source, size=size, last_opened=time.time())
        self.items.insert(0, it)
        del self.items[LIMIT:]
        self.save()
        return it

    def update_position(self, infohash: str, position_s: float, duration_s: float) -> None:
        for it in self.items:
            if it["infohash"] == infohash:
                it["position_s"] = max(0.0, float(position_s))
                it["duration_s"] = max(0.0, float(duration_s or 0))
                it["watched"] = bool(duration_s and position_s >= 0.92 * duration_s)
                self.save()
                return

    def remove(self, infohash: str) -> None:
        self.items = [i for i in self.items if i["infohash"] != infohash]
        self.save()

    def clear(self) -> None:
        self.items = []
        self.save()
