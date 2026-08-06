"""Invite-code sessions and the tenant boundary.

Right-sized for a solo-operated deployment: an operator sets one or more invite
codes (`FC_INVITE_CODES`), hands them out, and each code buys a signed, expiring
session cookie carrying a stable `user_id`. That `user_id` is the tenant key for
briefs, events, and connected repos.

Be clear about what this is **not**: no email, no OAuth/SSO, no identity
provider, no roles or permissions, no per-user rate/spend accounting, and no way
to revoke one session short of rotating the code or the signing key. It stops
strangers from driving your deployment and stops one code-holder from reading
another's runs. That is the whole claim (HARDENING P0-2).

Two deliberate choices:

* **No hand-rolled crypto.** Signing is `itsdangerous.URLSafeTimedSerializer`
  (a vetted signer, expiry checked on load); code comparison is
  `hmac.compare_digest` against every configured code with no early exit, so a
  wrong code costs the same time as a right one.
* **Open stays open, but loudly.** With no codes configured the app behaves
  exactly as it did before — every visitor shares the reserved `legacy` tenant —
  but it logs a warning at startup and reports `auth_enabled: false` on
  /healthz. Silent insecurity is worse than obvious insecurity.

Codes and the signing key are read straight from the environment and are never
logged, never returned by an endpoint, and deliberately not stored on the shared
`Settings` object where they could be serialised into a response by accident.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

from fastapi import HTTPException, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

log = logging.getLogger(__name__)

COOKIE = "fc_session"
# Tenant for pre-auth rows and for every visitor when auth is disabled.
LEGACY_USER = "legacy"
DEFAULT_TTL_S = 7 * 24 * 3600


def load_or_create_salt(data_dir: Path) -> bytes:
    """A per-deployment salt so user_ids can't be derived from a code alone.
    Persisted next to the databases: restarts must keep users pointing at their
    own data."""
    p = Path(data_dir) / "session_salt"
    try:
        if p.exists():
            return p.read_bytes()
        p.parent.mkdir(parents=True, exist_ok=True)
        salt = secrets.token_bytes(32)
        p.write_bytes(salt)
        p.chmod(0o600)
        return salt
    except OSError:                      # read-only volume: fall back to memory
        log.warning("auth: could not persist the session salt; user ids reset on restart")
        return secrets.token_bytes(32)


class Auth:
    def __init__(self, codes: str = "", secret: str = "", ttl_s: int = DEFAULT_TTL_S,
                 salt: bytes | None = None):
        self._codes = tuple(c.strip() for c in codes.split(",") if c.strip())
        self._salt = salt or secrets.token_bytes(32)
        self.ttl_s = ttl_s
        self._signer = URLSafeTimedSerializer(secret or secrets.token_urlsafe(32),
                                              salt="fieldcraft-session")

    @property
    def enabled(self) -> bool:
        return bool(self._codes)

    def user_id(self, code: str) -> str:
        return "u-" + hmac.new(self._salt, code.encode(), hashlib.sha256).hexdigest()[:12]

    def user_for_code(self, code: str) -> str | None:
        """The tenant this code belongs to, or None. Constant-time and no early
        exit, so timing does not reveal which code matched."""
        matched = ""
        for c in self._codes:
            if hmac.compare_digest(c, code or ""):
                matched = c
        return self.user_id(matched) if matched else None

    def issue(self, user_id: str) -> str:
        return self._signer.dumps(user_id)

    def verify(self, token: str) -> str | None:
        try:
            uid = self._signer.loads(token, max_age=self.ttl_s)
        except BadSignature:             # also covers SignatureExpired
            return None
        return uid if isinstance(uid, str) and uid else None

    def current_user(self, request: Request) -> str | None:
        """The caller's tenant, or None when a session is required and absent."""
        if not self.enabled:
            return LEGACY_USER
        token = request.cookies.get(COOKIE)
        return self.verify(token) if token else None


def from_env(data_dir: Path) -> Auth:
    codes = os.environ.get("FC_INVITE_CODES", "")
    secret = os.environ.get("FC_SECRET_KEY", "")
    try:
        ttl = int(os.environ.get("FC_SESSION_TTL_S", DEFAULT_TTL_S))
    except ValueError:
        ttl = DEFAULT_TTL_S
    auth = Auth(codes, secret, ttl, load_or_create_salt(data_dir))
    if not auth.enabled:
        log.warning("AUTH DISABLED — FC_INVITE_CODES is unset, so every visitor shares the "
                    "'%s' tenant and can read every brief. Set FC_INVITE_CODES (and "
                    "FC_SECRET_KEY) before exposing this deployment.", LEGACY_USER)
    elif not secret:
        log.warning("FC_SECRET_KEY is unset — sessions are signed with a random key and "
                    "every user is logged out on restart.")
    return auth


def secure_cookie(request: Request) -> bool:
    """https in front (directly or via Fly's proxy) => mark the cookie Secure."""
    return (request.url.scheme == "https"
            or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https")


def unauthorized() -> HTTPException:
    return HTTPException(401, "authentication required: POST /api/session with an access code")
