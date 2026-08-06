"""Invites — who may use this deployment, and who operates it.

`auth.py` answers "is this code valid"; this answers "is this *person* still
allowed, and are they the operator". It is the durable half of the trusted
preview: someone asks for access by email, the operator approves, a code is
generated once, and access can be taken away again immediately.

Design notes that matter:

* **Plaintext codes are never stored.** A row keeps an HMAC of the code
  (`auth.Auth.code_hash`, domain-separated from the tenant derivation) and the
  derived `user_id`. Login hashes the submitted code and looks the row up; the
  operator sees the code exactly once, at approval. A lost code is re-issued by
  revoking and approving again, not recovered.
* **`user_id` is still `hmac(salt, code)`**, unchanged from P0-2, so every code
  that worked before keeps pointing at the same tenant's data. Storing it here
  is what lets session validation check revocation without seeing the code.
* **Revocation is immediate.** `require_session` looks the session's `user_id`
  up on every request, so a revoked invite stops working on the next call — no
  waiting for the cookie to expire.
* **Seeding never resurrects.** Codes from `FC_INVITE_CODES` are seeded as
  active invites so they keep working and can be managed, but seeding is a
  no-op for a row that already exists. Revoking an env-listed code makes it stay
  revoked across restarts, which is the whole point of revocation.

Email delivery is **manual and out of band**. Nothing here sends mail: a request
is recorded, the operator reads it in the admin view, approves, and passes the
code to the person however they like. There is deliberately no SMTP dependency.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path

REQUESTED, ACTIVE, REVOKED = "requested", "active", "revoked"
STATUSES = (REQUESTED, ACTIVE, REVOKED)

EMAIL_MAX = 254
# Deliberately not RFC 5322 — that grammar accepts things no mail server will.
# This is the pragmatic subset: one @, a dot-bearing domain, no whitespace or
# control characters, nothing that could be mistaken for a header injection.
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+$")

_COLS = ("id", "email", "code_hash", "user_id", "status", "is_admin",
         "created_at", "approved_at", "last_used_at")
# How stale last_used_at may get before a request writes it again. Session checks
# happen on every call; without this the store would take a write per request.
TOUCH_INTERVAL_S = 60.0


def valid_email(email: str | None) -> bool:
    e = (email or "").strip()
    return bool(e) and len(e) <= EMAIL_MAX and bool(_EMAIL.match(e))


def normalise_email(email: str) -> str:
    """Lower-cased and trimmed. Case matters in the local part per the RFC, but
    treating Bob@ and bob@ as two people invites duplicate requests."""
    return (email or "").strip().lower()[:EMAIL_MAX]


class InviteStore:
    def __init__(self, path: str | Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.Lock()
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS invites(
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 email TEXT, code_hash TEXT, user_id TEXT,
                 status TEXT NOT NULL DEFAULT 'requested',
                 is_admin INTEGER NOT NULL DEFAULT 0,
                 created_at REAL NOT NULL, approved_at REAL, last_used_at REAL)""")
        self._migrate()
        self.db.commit()

    def _migrate(self) -> None:
        """Bring an older invites table up to the current shape, in place."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(invites)")}
        for name, decl in (("email", "TEXT"), ("code_hash", "TEXT"), ("user_id", "TEXT"),
                           ("status", "TEXT NOT NULL DEFAULT 'requested'"),
                           ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
                           ("approved_at", "REAL"), ("last_used_at", "REAL")):
            if name not in cols:
                self.db.execute(f"ALTER TABLE invites ADD COLUMN {name} {decl}")
        # One row per person and one per code. Partial indexes so the many
        # code-less 'requested' rows do not collide on a NULL code_hash.
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS invites_email "
                        "ON invites(email) WHERE email IS NOT NULL")
        self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS invites_hash "
                        "ON invites(code_hash) WHERE code_hash IS NOT NULL")
        self.db.execute("CREATE INDEX IF NOT EXISTS invites_user ON invites(user_id)")

    # -- writes ------------------------------------------------------------
    def record_request(self, email: str) -> dict:
        """Record an access request. Never grants anything: the row carries no
        code, and an existing invite is left exactly as it is (so re-requesting
        cannot reset a revocation or re-open an active account)."""
        e = normalise_email(email)
        now = time.time()
        with self._lock:
            row = self.db.execute("SELECT status FROM invites WHERE email=?", (e,)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO invites(email,status,is_admin,created_at) VALUES(?,?,0,?)",
                    (e, REQUESTED, now))
            elif row[0] == REQUESTED:
                self.db.execute("UPDATE invites SET created_at=? WHERE email=?", (now, e))
            self.db.commit()
        return self.by_email(e) or {}

    def approve(self, email: str, code_hash: str, user_id: str,
                is_admin: bool = False) -> dict:
        """Activate an invite for this email against a freshly generated code."""
        e = normalise_email(email)
        now = time.time()
        with self._lock:
            exists = self.db.execute("SELECT id FROM invites WHERE email=?", (e,)).fetchone()
            if exists:
                self.db.execute(
                    "UPDATE invites SET code_hash=?,user_id=?,status=?,is_admin=?,approved_at=? "
                    "WHERE email=?",
                    (code_hash, user_id, ACTIVE, int(is_admin), now, e))
            else:
                self.db.execute(
                    "INSERT INTO invites(email,code_hash,user_id,status,is_admin,created_at,"
                    "approved_at) VALUES(?,?,?,?,?,?,?)",
                    (e, code_hash, user_id, ACTIVE, int(is_admin), now, now))
            self.db.commit()
        return self.by_email(e) or {}

    def seed(self, code_hash: str, user_id: str, email: str | None = None,
             is_admin: bool = False) -> None:
        """Register an env-configured code as an active invite, once.

        A no-op when a row for this code already exists — including a revoked
        one. Revocation must survive a restart, so seeding must never resurrect.
        """
        now = time.time()
        with self._lock:
            row = self.db.execute("SELECT id,is_admin FROM invites WHERE code_hash=?",
                                  (code_hash,)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO invites(email,code_hash,user_id,status,is_admin,created_at,"
                    "approved_at) VALUES(?,?,?,?,?,?,?)",
                    (email, code_hash, user_id, ACTIVE, int(is_admin), now, now))
            elif is_admin and not row[1]:
                # FC_ADMIN_CODES may promote a code that was already seeded plain.
                self.db.execute("UPDATE invites SET is_admin=1 WHERE id=?", (row[0],))
            self.db.commit()

    def revoke(self, *, code_hash: str | None = None, email: str | None = None) -> dict | None:
        """Revoke by code hash or by email. Returns the row, or None if unknown."""
        with self._lock:
            if code_hash:
                cur = self.db.execute(
                    "UPDATE invites SET status=? WHERE code_hash=?", (REVOKED, code_hash))
            elif email:
                cur = self.db.execute(
                    "UPDATE invites SET status=? WHERE email=?", (REVOKED, normalise_email(email)))
            else:
                return None
            self.db.commit()
            if not cur.rowcount:
                return None
        return (self.by_hash(code_hash) if code_hash
                else self.by_email(normalise_email(email or "")))

    def touch(self, user_id: str, now: float | None = None) -> None:
        """Record that this tenant is active. Throttled — session checks run on
        every request and this must not become a write per request."""
        now = now or time.time()
        with self._lock:
            row = self.db.execute("SELECT last_used_at FROM invites WHERE user_id=?",
                                  (user_id,)).fetchone()
            if row is None or (row[0] and now - row[0] < TOUCH_INTERVAL_S):
                return
            self.db.execute("UPDATE invites SET last_used_at=? WHERE user_id=?", (now, user_id))
            self.db.commit()

    # -- reads -------------------------------------------------------------
    def by_hash(self, code_hash: str) -> dict | None:
        return self._one("code_hash=?", (code_hash,)) if code_hash else None

    def by_user(self, user_id: str) -> dict | None:
        return self._one("user_id=?", (user_id,)) if user_id else None

    def by_email(self, email: str) -> dict | None:
        return self._one("email=?", (normalise_email(email),)) if email else None

    def list_all(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                f"SELECT {','.join(_COLS)} FROM invites "
                f"ORDER BY (status='requested') DESC, created_at DESC LIMIT ?",
                (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def _one(self, where: str, args: tuple) -> dict | None:
        with self._lock:
            row = self.db.execute(
                f"SELECT {','.join(_COLS)} FROM invites WHERE {where}", args).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(r) -> dict:
        d = dict(zip(_COLS, r))
        d["is_admin"] = bool(d["is_admin"])
        # The hash is an internal lookup key, not something an endpoint should
        # ever hand back; drop it so it cannot leak by accident.
        d.pop("code_hash", None)
        return d
