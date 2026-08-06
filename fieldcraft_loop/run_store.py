"""Durable run state for the resumable engine.

Everything needed to resume a run lives here (iteration, cost, trajectory,
pending feedback, last verdict/diff) — so any process can pick a run up after a
restart. The event log (EventStore) is the history; this is the current cursor.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_JSON_COLS = {"config", "trajectory", "last_verdict"}

# Rows written before tenancy existed have user_id NULL; they belong to the
# reserved 'legacy' tenant, which is also every visitor when auth is disabled.
LEGACY_USER = "legacy"
_OWNER = "COALESCE(user_id,'legacy')"


class RunStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS runs(
                 brief_id TEXT PRIMARY KEY, config TEXT, workdir TEXT, status TEXT,
                 iteration INTEGER, total_cost REAL, trajectory TEXT, last_feedback TEXT,
                 last_verdict TEXT, last_diff TEXT, approved_by TEXT, created REAL, updated REAL)""")
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Add the tenant column to a pre-tenancy database, in place."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(runs)")}
        if "user_id" not in cols:
            self.db.execute("ALTER TABLE runs ADD COLUMN user_id TEXT")
        self.db.execute("CREATE INDEX IF NOT EXISTS runs_user ON runs(user_id)")

    def create(self, bid: str, config: dict, workdir: str, user_id: str = LEGACY_USER) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO runs(brief_id,config,workdir,status,iteration,"
                "total_cost,trajectory,last_feedback,last_verdict,last_diff,approved_by,"
                "created,updated,user_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bid, json.dumps(config), workdir, "ready", 0, 0.0, "[]", "",
                 None, None, None, time.time(), time.time(), user_id or LEGACY_USER))
            self.db.commit()

    def get(self, bid: str, user_id: str | None = None) -> dict | None:
        """With a user_id, a run owned by anyone else is simply not there."""
        sql = ("SELECT brief_id,config,workdir,status,iteration,total_cost,trajectory,"
               "last_feedback,last_verdict,last_diff,approved_by FROM runs WHERE brief_id=?")
        args: tuple = (bid,)
        if user_id is not None:
            sql += f" AND {_OWNER}=?"
            args += (user_id,)
        with self._lock:
            r = self.db.execute(sql, args).fetchone()
        if not r:
            return None
        return {"brief_id": r[0], "config": json.loads(r[1]), "workdir": r[2], "status": r[3],
                "iteration": r[4], "total_cost": r[5], "trajectory": json.loads(r[6]),
                "last_feedback": r[7], "last_verdict": json.loads(r[8]) if r[8] else None,
                "last_diff": r[9], "approved_by": r[10]}

    def update(self, bid: str, **fields) -> None:
        if not fields:
            return
        cols = ",".join(f"{k}=?" for k in fields) + ",updated=?"
        vals = [json.dumps(v) if k in _JSON_COLS else v for k, v in fields.items()] + [time.time()]
        with self._lock:
            self.db.execute(f"UPDATE runs SET {cols} WHERE brief_id=?", (*vals, bid))
            self.db.commit()

    def list_status(self, status: str, user_id: str | None = None) -> list[str]:
        sql, args = "SELECT brief_id FROM runs WHERE status=?", (status,)
        if user_id is not None:
            sql += f" AND {_OWNER}=?"
            args += (user_id,)
        with self._lock:
            return [r[0] for r in self.db.execute(sql, args).fetchall()]

    def list_all(self, limit: int = 50, user_id: str | None = None) -> list[dict]:
        sql = ("SELECT brief_id,status,iteration,total_cost,config,created,updated FROM runs")
        args: tuple = ()
        if user_id is not None:
            sql += f" WHERE {_OWNER}=?"
            args += (user_id,)
        with self._lock:
            rows = self.db.execute(sql + " ORDER BY created DESC LIMIT ?",
                                   args + (limit,)).fetchall()
        out = []
        for r in rows:
            cfg = json.loads(r[4])
            out.append({"brief_id": r[0], "status": r[1], "iteration": r[2],
                        "total_cost": r[3], "config": cfg,
                        "created": r[5], "updated": r[6]})
        return out
