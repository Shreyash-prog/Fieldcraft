"""Access requests and the operator-only invite admin.

This is a privileged surface, so the tests are written from the attacker's side
first: a perfectly valid invited user must not be able to reach, discover, or
influence anything under /api/admin, and a revoked code must stop working the
moment it is revoked.
"""
import pytest
from fastapi.testclient import TestClient

from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from fieldcraft_web.invite_store import (ACTIVE, REQUESTED, REVOKED, InviteStore,
                                         normalise_email, valid_email)
from fieldcraft_web.ledger import Ledger

USER_CODE, ADMIN_CODE = "user-code", "operator-code"

ADMIN_ROUTES = [
    ("get", "/api/admin/invites", None),
    ("post", "/api/admin/invites/approve", {"email": "x@example.com"}),
    ("post", "/api/admin/invites/revoke", {"email": "x@example.com"}),
]


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """A fresh invite store per test — otherwise revoking a shared code here
    would break every other test file that logs in with it."""
    monkeypatch.setattr(server, "invites", InviteStore(tmp_path / "invites.db"))
    return server.invites


@pytest.fixture
def secured(monkeypatch, store):
    """Auth on, with one ordinary invite code and one operator code."""
    a = Auth(codes=USER_CODE, secret="test-signing-key", salt=b"fixed-test-salt",
             admin_codes=ADMIN_CODE)
    monkeypatch.setattr(server, "auth", a)
    server.seed_env_invites(a, store)
    return a


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    r = c.post("/api/session", json={"code": code})
    assert r.status_code == 200, r.text
    return c


# =============================================================================
# the admin surface is closed
# =============================================================================

@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_an_ordinary_invited_user_is_404_on_every_admin_route(secured, method, path, body):
    """Being logged in is not being the operator."""
    c = session(USER_CODE)
    r = getattr(c, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 404, f"{path} leaked to a non-admin: {r.status_code}"


@pytest.mark.parametrize("method,path,body", ADMIN_ROUTES)
def test_an_anonymous_caller_is_404_on_every_admin_route(secured, method, path, body):
    c = TestClient(server.app)
    r = getattr(c, method)(path, **({"json": body} if body else {}))
    assert r.status_code == 404


def test_the_admin_surface_is_disabled_when_auth_is_disabled(monkeypatch, store):
    """With no codes configured every visitor is the same 'legacy' tenant, so
    there is no operator to distinguish — the surface must fail closed rather
    than stand open to the world."""
    monkeypatch.setattr(server, "auth", Auth(codes="", secret="k", salt=b"s"))
    c = TestClient(server.app)
    assert c.get("/api/tasks").status_code == 200      # app is open...
    assert c.get("/api/admin/invites").status_code == 404   # ...admin is not


def test_admin_routes_404_rather_than_403(secured):
    """404 so a regular user cannot even learn the surface exists."""
    c = session(USER_CODE)
    r = c.get("/api/admin/invites")
    assert r.status_code == 404 and "admin" not in r.text.lower()


def test_a_user_cannot_promote_themselves_via_approve(secured, store):
    """The obvious privilege escalation: approve yourself as admin."""
    c = session(USER_CODE)
    assert c.post("/api/admin/invites/approve",
                  json={"email": "me@example.com", "is_admin": True}).status_code == 404
    assert store.by_email("me@example.com") is None


def test_the_operator_reaches_the_admin_surface(secured):
    c = session(ADMIN_CODE)
    assert c.get("/api/admin/invites").status_code == 200


def test_me_reports_admin_only_for_the_operator(secured):
    assert session(ADMIN_CODE).get("/api/me").json()["is_admin"] is True
    assert session(USER_CODE).get("/api/me").json()["is_admin"] is False
    anon = TestClient(server.app).get("/api/me").json()
    assert anon["authenticated"] is False and anon["is_admin"] is False


# =============================================================================
# request access — records, never grants
# =============================================================================

def test_request_access_records_a_request_without_granting(secured, store):
    anon = TestClient(server.app)
    r = anon.post("/api/access/request", json={"email": "Wanted@Example.com"})
    assert r.status_code == 200 and r.json()["ok"] is True

    row = store.by_email("wanted@example.com")
    assert row["status"] == REQUESTED
    assert row["user_id"] is None                 # no tenant
    assert "code" not in r.json()                 # and no code handed out


def test_a_requested_invite_cannot_be_used_to_log_in(secured, store):
    TestClient(server.app).post("/api/access/request", json={"email": "a@example.com"})
    # There is no code to try; prove the row grants nothing by attempting the
    # email itself and a guess, and by checking the app is still shut.
    for attempt in ("a@example.com", "", "requested"):
        assert TestClient(server.app).post("/api/session",
                                           json={"code": attempt}).status_code == 401
    assert TestClient(server.app).get("/api/tasks").status_code == 401


@pytest.mark.parametrize("email", [
    "", "   ", "no-at-sign", "two@@example.com", "a@nodot", "a b@example.com",
    "a@example.com\nBcc: victim@example.com", "x" * 300 + "@example.com",
])
def test_bad_emails_are_refused(secured, email):
    r = TestClient(server.app).post("/api/access/request", json={"email": email})
    assert r.status_code == 400


def test_email_validation_helper():
    assert valid_email("a.b+c@example.co.uk")
    assert not valid_email("a@example")
    assert not valid_email("a@ex ample.com")
    assert normalise_email("  Bob@Example.COM ") == "bob@example.com"


def test_request_access_is_rate_limited(secured, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "rl.db", global_cap=100, user_cap=100,
                               rate_per_hour=3))
    c = TestClient(server.app)
    codes = [c.post("/api/access/request", json={"email": f"a{i}@example.com"}).status_code
             for i in range(5)]
    assert codes.count(200) == 3 and codes[-1] == 429


def test_re_requesting_cannot_reopen_a_revoked_invite(secured, store):
    """Otherwise revocation is undone by anyone who knows the email."""
    admin = session(ADMIN_CODE)
    admin.post("/api/admin/invites/approve", json={"email": "b@example.com"})
    admin.post("/api/admin/invites/revoke", json={"email": "b@example.com"})

    TestClient(server.app).post("/api/access/request", json={"email": "b@example.com"})
    assert store.by_email("b@example.com")["status"] == REVOKED


def test_requesting_an_active_email_does_not_change_it(secured, store):
    admin = session(ADMIN_CODE)
    admin.post("/api/admin/invites/approve", json={"email": "c@example.com"})
    before = store.by_email("c@example.com")
    TestClient(server.app).post("/api/access/request", json={"email": "c@example.com"})
    assert store.by_email("c@example.com")["status"] == ACTIVE
    assert store.by_email("c@example.com")["user_id"] == before["user_id"]


# =============================================================================
# approve / revoke
# =============================================================================

def test_approve_issues_a_working_code(secured, store):
    admin = session(ADMIN_CODE)
    TestClient(server.app).post("/api/access/request", json={"email": "new@example.com"})

    r = admin.post("/api/admin/invites/approve", json={"email": "new@example.com"})
    assert r.status_code == 200
    code = r.json()["code"]
    assert code and len(code) >= 20

    invited = session(code)                     # the code really works
    assert invited.get("/api/tasks").status_code == 200
    assert invited.get("/api/me").json()["is_admin"] is False
    assert store.by_email("new@example.com")["status"] == ACTIVE


def test_each_approval_generates_a_distinct_random_code(secured):
    admin = session(ADMIN_CODE)
    codes = {admin.post("/api/admin/invites/approve",
                        json={"email": f"u{i}@example.com"}).json()["code"]
             for i in range(5)}
    assert len(codes) == 5


def test_the_code_is_never_stored_or_listed(secured, store):
    admin = session(ADMIN_CODE)
    code = admin.post("/api/admin/invites/approve",
                      json={"email": "d@example.com"}).json()["code"]
    listing = admin.get("/api/admin/invites").text
    assert code not in listing
    assert "code_hash" not in listing
    raw = "".join(str(v) for v in store.by_email("d@example.com").values())
    assert code not in raw


def test_an_approved_user_gets_their_own_tenant(secured):
    admin = session(ADMIN_CODE)
    c1 = admin.post("/api/admin/invites/approve", json={"email": "e1@example.com"}).json()["code"]
    c2 = admin.post("/api/admin/invites/approve", json={"email": "e2@example.com"}).json()["code"]
    u1, u2 = session(c1), session(c2)
    t = u1.post("/api/tickets", json={"title": "private"}).json()
    assert u2.get(f"/api/tickets/{t['id']}").status_code == 404


def test_revoke_immediately_blocks_an_existing_session(secured):
    """The load-bearing one: an outstanding cookie must stop working at once,
    not when it expires."""
    admin = session(ADMIN_CODE)
    code = admin.post("/api/admin/invites/approve", json={"email": "f@example.com"}).json()["code"]
    victim = session(code)
    assert victim.get("/api/tasks").status_code == 200

    assert admin.post("/api/admin/invites/revoke", json={"code": code}).status_code == 200
    assert victim.get("/api/tasks").status_code == 401       # same cookie, now dead
    assert victim.get("/api/tickets").status_code == 401


def test_a_revoked_code_cannot_log_in_again(secured):
    admin = session(ADMIN_CODE)
    code = admin.post("/api/admin/invites/approve", json={"email": "g@example.com"}).json()["code"]
    admin.post("/api/admin/invites/revoke", json={"code": code})
    assert TestClient(server.app).post("/api/session", json={"code": code}).status_code == 401


def test_revoke_by_email_works_too(secured, store):
    admin = session(ADMIN_CODE)
    code = admin.post("/api/admin/invites/approve", json={"email": "h@example.com"}).json()["code"]
    assert admin.post("/api/admin/invites/revoke", json={"email": "h@example.com"}).status_code == 200
    assert store.by_email("h@example.com")["status"] == REVOKED
    assert TestClient(server.app).post("/api/session", json={"code": code}).status_code == 401


def test_revoking_an_unknown_invite_is_404(secured):
    admin = session(ADMIN_CODE)
    assert admin.post("/api/admin/invites/revoke",
                      json={"code": "never-issued"}).status_code == 404


def test_a_revoked_env_code_stays_revoked_across_a_restart(secured, store):
    """Seeding must not resurrect: FC_INVITE_CODES is re-read on every boot."""
    admin = session(ADMIN_CODE)
    assert admin.post("/api/admin/invites/revoke", json={"code": USER_CODE}).status_code == 200
    assert TestClient(server.app).post("/api/session", json={"code": USER_CODE}).status_code == 401

    server.seed_env_invites(server.auth, store)          # simulate a restart
    assert store.by_hash(server.auth.code_hash(USER_CODE))["status"] == REVOKED
    assert TestClient(server.app).post("/api/session", json={"code": USER_CODE}).status_code == 401


def test_an_operator_can_revoke_their_own_admin_access(secured):
    """No special-casing: admin is read from the store like everything else."""
    admin = session(ADMIN_CODE)
    admin.post("/api/admin/invites/revoke", json={"code": ADMIN_CODE})
    assert admin.get("/api/admin/invites").status_code == 404


# =============================================================================
# backward compatibility + caps
# =============================================================================

def test_env_invite_codes_still_work(secured):
    assert session(USER_CODE).get("/api/tasks").status_code == 200


def test_an_env_code_keeps_its_pre_existing_tenant(secured):
    """user_id derivation is unchanged, so an existing user's data stays theirs."""
    assert session(USER_CODE).get("/api/me").json()["user"] == server.auth.user_id(USER_CODE)


def test_an_unseeded_env_code_is_seeded_on_first_use(monkeypatch, tmp_path):
    """A deployment that upgrades mid-flight has an empty store; the env code
    must still work and become manageable."""
    fresh = InviteStore(tmp_path / "fresh.db")
    monkeypatch.setattr(server, "invites", fresh)
    monkeypatch.setattr(server, "auth",
                        Auth(codes=USER_CODE, secret="k", salt=b"fixed-test-salt"))
    assert fresh.by_hash(server.auth.code_hash(USER_CODE)) is None
    assert session(USER_CODE).get("/api/tasks").status_code == 200
    assert fresh.by_hash(server.auth.code_hash(USER_CODE))["status"] == ACTIVE


def test_admin_list_shows_spend_against_the_per_user_cap(secured, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "l.db", global_cap=9.0, user_cap=1.5,
                               rate_per_hour=1000))
    admin = session(ADMIN_CODE)
    code = admin.post("/api/admin/invites/approve", json={"email": "i@example.com"}).json()["code"]
    uid = server.invites.by_email("i@example.com")["user_id"]
    res = server.ledger.reserve(uid, "1.2.3.4", 0.4)
    server.ledger.settle(res.id, 0.4)

    body = admin.get("/api/admin/invites").json()
    row = [i for i in body["invites"] if i["email"] == "i@example.com"][0]
    assert row["spent_today"] == pytest.approx(0.4)
    assert row["remaining_today"] == pytest.approx(1.1)
    assert body["caps"]["user_daily"] == 1.5 and body["caps"]["global_daily"] == 9.0
    assert session(code).get("/api/tasks").status_code == 200


def test_the_per_user_cap_applies_to_an_invited_user(secured, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "l2.db", global_cap=100.0, user_cap=0.5,
                               rate_per_hour=1000))
    admin = session(ADMIN_CODE)
    admin.post("/api/admin/invites/approve", json={"email": "j@example.com"})
    uid = server.invites.by_email("j@example.com")["user_id"]
    assert server.ledger.reserve(uid, "1.2.3.4", 0.4).ok
    denied = server.ledger.reserve(uid, "1.2.3.4", 0.4)
    assert not denied.ok and denied.limit == "user_daily"


def test_the_admin_listing_never_carries_a_session_or_key(secured):
    admin = session(ADMIN_CODE)
    body = admin.get("/api/admin/invites").text
    for secret in (ADMIN_CODE, USER_CODE, "test-signing-key"):
        assert secret not in body
