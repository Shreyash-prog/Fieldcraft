"""Durable spend + rate accounting — the money guard that survives a restart.

`limits.py` held all three guards in process memory, so a crash-loop reset the
daily spend cap (HARDENING P0-4). This is the same accounting in SQLite next to
the other stores, with the check and the write in **one transaction** so parallel
reserves cannot oversell a cap.

Model: a *reservation* is taken before a run starts and *settled* to the actual
cost when it ends (or *released* if the run never started). One reservation
writes one row per window it counts against — global day, user day, and the
caller's rolling-hour rate slot — sharing a `reservation_id`. A row counts while
it is `reserved` or `settled`; `released` rows count for nothing.

Windows: UTC calendar day for cost, a rolling hour for rate. Rows older than two
days are pruned on write.

**What this is:** durable, transactional, **single-node** accounting. One process
(or several on the same machine and volume) cannot oversell a cap, and a restart
resumes from the ledger rather than from zero.

**What this is not:**
* **Not multi-instance safe.** Correctness rests on SQLite `BEGIN IMMEDIATE` over
  one file. Two Fly Machines with separate volumes would each enforce their own
  cap and double-spend; that needs the ledger in a shared store (Postgres/Redis).
* **Not authoritative on real cost.** We settle what the loop reports the agent
  spent; the provider's own accounting is the truth. A reservation bounds what we
  will *start*, and a settle records what we were *told* — an under-reported turn
  is under-recorded here.
* **Not a per-call meter.** Enforcement happens once per brief, not per API call
  inside a turn, so a single run can overshoot its reservation before it settles.
  The per-run budget clamp in the engine is what bounds that overshoot.
"""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

GLOBAL, USER, RATE = "global", "user", "rate"
# A row counts while it is reserved or settled; 'released' counts for nothing.
_LIVE = "state IN ('reserved','settled')"
_PRUNE_AFTER_S = 2 * 86400


@dataclass(frozen=True)
class Reservation:
    id: str
    amount: float
    ok: bool = True


@dataclass(frozen=True)
class Denied:
    limit: str                              # global_daily | user_daily | rate
    message: str
    ok: bool = False


def utc_day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


class Ledger:
    def __init__(self, path: str | Path, *, global_cap: float = 5.0, user_cap: float = 1.0,
                 rate_per_hour: int = 10, clock=time.time):
        self.global_cap = global_cap
        self.user_cap = user_cap
        self.rate_per_hour = rate_per_hour
        self.clock = clock
        # isolation_level=None: we drive BEGIN IMMEDIATE / COMMIT ourselves, so
        # the check and the insert of a reserve are one atomic step.
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS ledger(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 reservation_id TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL,
                 window TEXT NOT NULL, amount REAL NOT NULL, state TEXT NOT NULL,
                 at REAL NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS ledger_window ON ledger(scope,key,window)")
        self.db.execute("CREATE INDEX IF NOT EXISTS ledger_res ON ledger(reservation_id)")

    # -- accounting --------------------------------------------------------
    def reserve(self, user_id: str, ip: str, estimated_cost: float,
                *, enforce_cost: bool = True) -> Reservation | Denied:
        """Check every applicable cap and take the reservation in one transaction.

        `enforce_cost=False` records the spend without enforcing the money caps —
        used for offline mock runs, whose costs are simulated. The rate limit
        always applies.
        """
        est = max(0.0, float(estimated_cost or 0.0))
        now = self.clock()
        day = utc_day(now)
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._prune(now)
                if self.rate_per_hour and self._rate_used(ip, now) >= self.rate_per_hour:
                    self.db.execute("ROLLBACK")
                    return Denied("rate", "rate limit: too many briefs from your IP, try later")
                if enforce_cost:
                    if self._spent(GLOBAL, "", day) + est > self.global_cap:
                        self.db.execute("ROLLBACK")
                        return Denied("global_daily",
                                      "daily spend cap reached; live runs paused until tomorrow")
                    if self._spent(USER, user_id, day) + est > self.user_cap:
                        self.db.execute("ROLLBACK")
                        return Denied("user_daily",
                                      "your daily spend cap is reached; try again tomorrow")
                rid = "RSV-" + uuid.uuid4().hex[:12]
                self.db.executemany(
                    "INSERT INTO ledger(reservation_id,scope,key,window,amount,state,at) "
                    "VALUES(?,?,?,?,?,'reserved',?)",
                    [(rid, GLOBAL, "", day, est, now),
                     (rid, USER, user_id, day, est, now),
                     (rid, RATE, ip, "", 0.0, now)])
                self.db.execute("COMMIT")
                return Reservation(rid, est)
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def hit(self, key: str) -> bool:
        """Count one rate-limited action (a login attempt, say) against `key`'s
        rolling hour. False — and nothing recorded — once the budget is used."""
        now = self.clock()
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self._prune(now)
                if self.rate_per_hour and self._rate_used(key, now) >= self.rate_per_hour:
                    self.db.execute("ROLLBACK")
                    return False
                self.db.execute(
                    "INSERT INTO ledger(reservation_id,scope,key,window,amount,state,at) "
                    "VALUES('',?,?,'',0.0,'settled',?)", (RATE, key, now))
                self.db.execute("COMMIT")
                return True
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def settle(self, reservation_id: str, actual_cost: float) -> bool:
        """Reconcile a reservation to what was actually spent (up or down).
        Idempotent: settling an already settled/released reservation is a no-op
        and returns False."""
        if not reservation_id:
            return False
        actual = max(0.0, float(actual_cost or 0.0))
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                cur = self.db.execute(
                    "UPDATE ledger SET amount=CASE WHEN scope='rate' THEN amount ELSE ? END,"
                    " state='settled' WHERE reservation_id=? AND state='reserved'",
                    (actual, reservation_id))
                self.db.execute("COMMIT")
                return cur.rowcount > 0
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def release(self, reservation_id: str) -> bool:
        """Cancel an unused reservation, freeing the amount and the rate slot."""
        if not reservation_id:
            return False
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                cur = self.db.execute(
                    "UPDATE ledger SET state='released' WHERE reservation_id=? AND state='reserved'",
                    (reservation_id,))
                self.db.execute("COMMIT")
                return cur.rowcount > 0
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    # -- views -------------------------------------------------------------
    def spent_global(self) -> float:
        with self._lock:
            return self._spent(GLOBAL, "", utc_day(self.clock()))

    def spent_user(self, user_id: str) -> float:
        with self._lock:
            return self._spent(USER, user_id, utc_day(self.clock()))

    def remaining_global(self) -> float:
        return round(self.global_cap - self.spent_global(), 4)

    def remaining_user(self, user_id: str) -> float:
        return round(self.user_cap - self.spent_user(user_id), 4)

    def rate_used(self, ip: str) -> int:
        with self._lock:
            return self._rate_used(ip, self.clock())

    # -- internals (call with the lock held, inside a transaction) ---------
    def _spent(self, scope: str, key: str, day: str) -> float:
        row = self.db.execute(
            f"SELECT COALESCE(SUM(amount),0) FROM ledger "
            f"WHERE scope=? AND key=? AND window=? AND {_LIVE}", (scope, key, day)).fetchone()
        return round(row[0], 6)

    def _rate_used(self, ip: str, now: float) -> int:
        row = self.db.execute(
            f"SELECT COUNT(*) FROM ledger WHERE scope=? AND key=? AND at>? AND {_LIVE}",
            (RATE, ip, now - 3600)).fetchone()
        return int(row[0])

    def _prune(self, now: float) -> None:
        self.db.execute("DELETE FROM ledger WHERE at<?", (now - _PRUNE_AFTER_S,))
