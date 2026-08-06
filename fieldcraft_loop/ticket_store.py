"""Board tickets — a development task as a first-class, durable object.

A ticket is the unit the product layer is built around: a dev task you can park in
a column, then (in the run phase) point at a repo, give PDF context, and run
through the governed loop several ways to compare them.

The columns for that later work exist **now** and are nullable, so adding those
phases is a write path rather than a migration:

* `repo_url` / `repo_task_handle` — the connected public repo and the handle
  `/api/repos/connect` hands back (`github_source.py`).
* `pdf_context_ids` — JSON list of ids for the context documents attached to the
  ticket.
* `runs` — JSON list of the loop runs this ticket has produced, each tagged with
  the mode it ran in, so three modes over one ticket can be compared side by side:
  `{"brief_id": "BRIEF-…", "mode": "hitl_comments", "provider": "claude",
    "at": 1770000000.0}`.

Tenancy follows `run_store.py`: every read takes an optional `user_id` and a
ticket owned by anyone else is simply not there, so a caller 404s rather than
learning it exists.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

STATUSES = ("backlog", "in_progress", "review", "done")
# How a run was driven — the comparison axis the run phase is built around.
RUN_MODES = ("hitl_no_comments", "hitl_comments", "autonomous")

TITLE_MAX = 200
DESCRIPTION_MAX = 8000

_JSON_COLS = {"pdf_context_ids", "runs"}
_COLS = ("id", "user_id", "title", "description", "status", "created_at", "updated_at",
         "repo_url", "repo_task_handle", "pdf_context_ids", "runs")
# Columns a later phase may add to an existing database, applied in place.
_ADDABLE = {"repo_url": "TEXT", "repo_task_handle": "TEXT",
            "pdf_context_ids": "TEXT", "runs": "TEXT"}


def clamp(text: str | None, limit: int) -> str:
    return (text or "").strip()[:limit]


class TicketStore:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS tickets(
                 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                 description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'backlog',
                 created_at REAL NOT NULL, updated_at REAL NOT NULL,
                 repo_url TEXT, repo_task_handle TEXT, pdf_context_ids TEXT, runs TEXT)""")
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Bring an older tickets table up to the current shape, in place."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(tickets)")}
        for name, decl in _ADDABLE.items():
            if name not in cols:
                self.db.execute(f"ALTER TABLE tickets ADD COLUMN {name} {decl}")
        self.db.execute("CREATE INDEX IF NOT EXISTS tickets_user ON tickets(user_id,status)")

    # -- writes ------------------------------------------------------------
    def create(self, user_id: str, title: str, description: str = "",
               status: str = "backlog") -> dict:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        tid = "TCK-" + uuid.uuid4().hex[:8]
        now = time.time()
        with self._lock:
            self.db.execute(
                "INSERT INTO tickets(id,user_id,title,description,status,created_at,updated_at,"
                "repo_url,repo_task_handle,pdf_context_ids,runs) "
                "VALUES(?,?,?,?,?,?,?,NULL,NULL,'[]','[]')",
                (tid, user_id, clamp(title, TITLE_MAX), clamp(description, DESCRIPTION_MAX),
                 status, now, now))
            self.db.commit()
        return self.get(tid, user_id)

    def update(self, tid: str, user_id: str, **fields) -> dict | None:
        """Patch the fields given. Returns the updated ticket, or None if this
        user does not own it (so the caller can 404 without probing existence)."""
        if not self.get(tid, user_id):
            return None
        clean: dict = {}
        if "title" in fields and fields["title"] is not None:
            clean["title"] = clamp(fields["title"], TITLE_MAX)
        if "description" in fields and fields["description"] is not None:
            clean["description"] = clamp(fields["description"], DESCRIPTION_MAX)
        if "status" in fields and fields["status"] is not None:
            if fields["status"] not in STATUSES:
                raise ValueError(f"status must be one of {', '.join(STATUSES)}")
            clean["status"] = fields["status"]
        for k in ("repo_url", "repo_task_handle", "pdf_context_ids", "runs"):
            if k in fields:
                clean[k] = json.dumps(fields[k]) if k in _JSON_COLS else fields[k]
        if clean:
            cols = ",".join(f"{k}=?" for k in clean) + ",updated_at=?"
            with self._lock:
                self.db.execute(f"UPDATE tickets SET {cols} WHERE id=? AND user_id=?",
                                (*clean.values(), time.time(), tid, user_id))
                self.db.commit()
        return self.get(tid, user_id)

    def attach_run(self, tid: str, user_id: str, brief_id: str, mode: str,
                   provider: str = "") -> dict | None:
        """Record a loop run against this ticket. The run phase calls this once per
        run so the three modes can be compared over one ticket."""
        if mode not in RUN_MODES:
            raise ValueError(f"mode must be one of {', '.join(RUN_MODES)}")
        t = self.get(tid, user_id)
        if not t:
            return None
        runs = list(t["runs"]) + [{"brief_id": brief_id, "mode": mode,
                                   "provider": provider, "at": time.time()}]
        return self.update(tid, user_id, runs=runs)

    def delete(self, tid: str, user_id: str) -> bool:
        with self._lock:
            cur = self.db.execute("DELETE FROM tickets WHERE id=? AND user_id=?", (tid, user_id))
            self.db.commit()
            return cur.rowcount > 0

    # -- reads -------------------------------------------------------------
    def get(self, tid: str, user_id: str | None = None) -> dict | None:
        sql = f"SELECT {','.join(_COLS)} FROM tickets WHERE id=?"
        args: tuple = (tid,)
        if user_id is not None:
            sql += " AND user_id=?"
            args += (user_id,)
        with self._lock:
            row = self.db.execute(sql, args).fetchone()
        return self._row(row) if row else None

    def list_for(self, user_id: str, limit: int = 200) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                f"SELECT {','.join(_COLS)} FROM tickets WHERE user_id=? "
                f"ORDER BY created_at DESC LIMIT ?", (user_id, limit)).fetchall()
        return [self._row(r) for r in rows]

    @staticmethod
    def _row(r) -> dict:
        t = dict(zip(_COLS, r))
        for col in _JSON_COLS:
            try:
                t[col] = json.loads(t[col]) if t[col] else []
            except (TypeError, ValueError):
                t[col] = []
        return t
