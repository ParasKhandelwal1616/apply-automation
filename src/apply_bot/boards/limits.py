"""Per-day application counter (persisted) and human-like pacing for job boards."""
from __future__ import annotations

import json
import random
from datetime import date
from pathlib import Path


class DailyCounter:
    def __init__(self, path: Path, today: date | None = None):
        self.path = Path(path)
        self.today = (today or date.today()).isoformat()
        self.data: dict[str, dict[str, int]] = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8")) or {}
            except Exception:
                self.data = {}

    def count(self, source: str) -> int:
        return int(self.data.get(self.today, {}).get(source, 0))

    def remaining(self, source: str, daily_limit: int) -> int:
        return max(0, daily_limit - self.count(source))

    def increment(self, source: str) -> int:
        day = self.data.setdefault(self.today, {})
        day[source] = int(day.get(source, 0)) + 1
        # keep two weeks of history
        for key in sorted(self.data)[:-14]:
            self.data.pop(key, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        return day[source]


def run_budget(counter: DailyCounter, source: str, daily_limit: int, batch_size: int) -> int:
    """How many applications this run may make: min(batch, what's left today)."""
    return max(0, min(batch_size, counter.remaining(source, daily_limit)))


def next_gap_seconds(min_s: float, max_s: float, rng: random.Random | None = None) -> float:
    rng = rng or random
    lo, hi = sorted((float(min_s), float(max_s)))
    return rng.uniform(lo, hi)
