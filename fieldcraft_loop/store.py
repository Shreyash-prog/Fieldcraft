"""Append-only event store (SQLite). This is the spine: every state transition
is an immutable event, so the run is reconstructable/auditable and the
measurement layer derives from it rather than needing separate instrumentation.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

from .models import State


class EventStore:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS events(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 brief_id TEXT, turn INTEGER, state TEXT, type TEXT,
                 payload TEXT, cost_usd REAL, at REAL)"""
        )
        self.db.commit()

    def append(self, brief_id: str, turn: int, state: State, type_: str,
               payload: dict, cost: float = 0.0) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO events(brief_id,turn,state,type,payload,cost_usd,at) "
                "VALUES(?,?,?,?,?,?,?)",
                (brief_id, turn, state.value, type_, json.dumps(payload), cost, time.time()),
            )
            self.db.commit()

    def events(self, brief_id: str) -> list[dict]:
        with self._lock:
            cur = self.db.execute(
                "SELECT turn,state,type,payload,cost_usd FROM events "
                "WHERE brief_id=? ORDER BY id", (brief_id,))
            rows = cur.fetchall()
        return [{"turn": t, "state": s, "type": ty,
                 "payload": json.loads(p), "cost_usd": c}
                for (t, s, ty, p, c) in rows]
