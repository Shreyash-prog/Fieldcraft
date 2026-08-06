"""In-memory deployment guards.

`Concurrency` is still what the server uses: it bounds live threads in *this*
process, so there is nothing to carry across a restart.

`RateLimiter` and `CostTracker` have been **superseded by `ledger.py`**, which
does the same accounting durably and transactionally (HARDENING P0-4) — a
restart no longer resets the daily spend cap. They are kept as the in-memory
reference implementation and are no longer wired into the server.
"""
from __future__ import annotations

import threading
import time
from datetime import date


class RateLimiter:
    """Fixed-window-ish per-key limiter over a rolling hour."""

    def __init__(self, per_hour: int):
        self.per_hour = per_hour
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        cutoff = now - 3600
        with self._lock:
            q = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(q) >= self.per_hour:
                self._hits[key] = q
                return False
            q.append(now)
            self._hits[key] = q
            return True


class CostTracker:
    """Tracks total live spend for the current day; resets at date rollover."""

    def __init__(self):
        self._day = date.today()
        self._total = 0.0
        self._lock = threading.Lock()

    def _roll(self):
        if date.today() != self._day:
            self._day = date.today()
            self._total = 0.0

    def add(self, cost: float) -> None:
        with self._lock:
            self._roll()
            self._total = round(self._total + max(0.0, cost or 0.0), 4)

    def remaining(self, cap: float) -> float:
        with self._lock:
            self._roll()
            return round(cap - self._total, 4)


class Concurrency:
    def __init__(self, limit: int):
        self.limit = limit
        self._n = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            if self._n >= self.limit:
                return False
            self._n += 1
            return True

    def release(self) -> None:
        with self._lock:
            self._n = max(0, self._n - 1)

    @property
    def active(self) -> int:
        return self._n
