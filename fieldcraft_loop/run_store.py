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
        self.db.commit()

    def create(self, bid: str, config: dict, workdir: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (bid, json.dumps(config), workdir, "ready", 0, 0.0, "[]", "",
                             None, None, None, time.time(), time.time()))
            self.db.commit()

    def get(self, bid: str) -> dict | None:
        with self._lock:
            cur = self.db.execute(
                "SELECT brief_id,config,workdir,status,iteration,total_cost,trajectory,"
                "last_feedback,last_verdict,last_diff,approved_by FROM runs WHERE brief_id=?", (bid,))
            r = cur.fetchone()
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

    def list_status(self, status: str) -> list[str]:
        with self._lock:
            cur = self.db.execute("SELECT brief_id FROM runs WHERE status=?", (status,))
            return [r[0] for r in cur.fetchall()]
