"""Governance — a scoped-credential model (least privilege, auditable).

A working model of the enterprise/forward-deployed credential story: a run never
holds long-lived secrets; it requests only the capabilities it needs, and the
broker issues a **scoped, short-lived grant**. Every access is checked against
the grant (capability in scope, not expired, not revoked) and written to an
audit trail. This is a capability model, not an integration with a real cloud
IAM — but the scoping, expiry, revocation, and audit semantics are real.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class Grant:
    grant_id: str
    issued_for: str
    capabilities: frozenset[str]
    issued_at: float
    expires_at: float
    revoked: bool = False

    def valid(self, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        return (not self.revoked) and now < self.expires_at


@dataclass
class CredentialBroker:
    audit: list[dict] = field(default_factory=list)
    _grants: dict[str, Grant] = field(default_factory=dict)

    def issue(self, issued_for: str, capabilities: list[str], ttl_s: float = 300.0) -> Grant:
        now = time.time()
        g = Grant(grant_id="G-" + uuid.uuid4().hex[:8], issued_for=issued_for,
                  capabilities=frozenset(capabilities), issued_at=now, expires_at=now + ttl_s)
        self._grants[g.grant_id] = g
        self._log("issue", g.grant_id, issued_for, list(g.capabilities))
        return g

    def check(self, grant_id: str, capability: str, now: float | None = None) -> bool:
        g = self._grants.get(grant_id)
        ok = bool(g) and g.valid(now) and capability in g.capabilities
        reason = ("ok" if ok else
                  "unknown grant" if not g else
                  "revoked" if g.revoked else
                  "expired" if (now if now is not None else time.time()) >= g.expires_at else
                  "out of scope")
        self._log("check", grant_id, capability, ok, reason)
        return ok

    def revoke(self, grant_id: str) -> None:
        g = self._grants.get(grant_id)
        if g:
            g.revoked = True
        self._log("revoke", grant_id, None, g is not None)

    def _log(self, action, grant_id, subject, result, reason: str = "") -> None:
        self.audit.append({"at": round(time.time(), 3), "action": action,
                           "grant": grant_id, "subject": subject, "result": result,
                           "reason": reason})
