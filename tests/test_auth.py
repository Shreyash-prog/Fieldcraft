"""Invite-code sessions and the tenant boundary.

The server module is imported once with no FC_INVITE_CODES (the fallback the
rest of the suite relies on), so tests that need auth *on* swap in a configured
Auth via monkeypatch — the dependency reads the module global at call time.
"""
import pytest
from fastapi.testclient import TestClient

from fieldcraft_web import auth as auth_mod
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, LEGACY_USER, Auth
from fieldcraft_loop.run_store import RunStore

CODES = "alpha-code,beta-code"
PROTECTED = [("get", "/api/tasks"), ("get", "/api/briefs"), ("get", "/api/reports/benchmark"),
             ("get", "/api/briefs/BRIEF-nope"), ("get", "/api/briefs/BRIEF-nope/events"),
             ("get", "/api/briefs/BRIEF-nope/pending")]


@pytest.fixture(autouse=True)
def relaxed_limits(monkeypatch):
    """This module starts more briefs than the deployed per-IP/concurrency budget."""
    monkeypatch.setattr(server, "rate", server.RateLimiter(per_hour=500))
    monkeypatch.setattr(server, "conc", server.Concurrency(64))


@pytest.fixture
def secured(monkeypatch):
    """Turn auth on for this test with a fixed salt + signing key."""
    monkeypatch.setattr(server, "auth",
                        Auth(codes=CODES, secret="test-signing-key", salt=b"fixed-test-salt"))
    return server.auth


def session(code: str) -> TestClient:
    """A client holding the session cookie for `code` (its own cookie jar)."""
    c = TestClient(server.app)
    r = c.post("/api/session", json={"code": code})
    assert r.status_code == 200, r.text
    assert c.cookies.get(COOKIE)
    return c


def start_brief(client: TestClient, **body) -> str:
    r = client.post("/api/briefs", json={"adapter": "mock", "review": "auto", **body})
    assert r.status_code == 200, r.text
    return r.json()["brief_id"]


# --- gate --------------------------------------------------------------------

@pytest.mark.parametrize("method,path", PROTECTED)
def test_no_session_is_401(secured, method, path):
    assert getattr(TestClient(server.app), method)(path).status_code == 401

def test_state_changing_endpoints_are_401_without_a_session(secured):
    anon = TestClient(server.app)
    assert anon.post("/api/briefs", json={"adapter": "mock"}).status_code == 401
    assert anon.post("/api/repos/connect", json={"url": "https://github.com/o/r"}).status_code == 401
    assert anon.post("/api/briefs/BRIEF-x/review", json={"kind": "approve"}).status_code == 401

def test_valid_code_opens_a_session(secured):
    c = session("alpha-code")
    assert c.get("/api/tasks").status_code == 200

def test_invalid_code_is_401_and_sets_no_cookie(secured):
    c = TestClient(server.app)
    r = c.post("/api/session", json={"code": "not-a-code"})
    assert r.status_code == 401 and not c.cookies.get(COOKIE)

def test_a_forged_cookie_is_rejected(secured):
    c = TestClient(server.app)
    c.cookies.set(COOKIE, "u-deadbeefcafe")            # unsigned
    assert c.get("/api/tasks").status_code == 401

def test_expired_session_is_rejected(monkeypatch):
    a = Auth(codes=CODES, secret="k", ttl_s=-1, salt=b"s")   # any token is already too old
    assert a.verify(a.issue("u-x")) is None
    monkeypatch.setattr(server, "auth", a)
    token = a.issue(a.user_id("alpha-code"))
    c = TestClient(server.app)
    c.cookies.set(COOKIE, token)
    assert c.get("/api/tasks").status_code == 401

def test_public_routes_stay_public(secured):
    anon = TestClient(server.app)
    assert anon.get("/healthz").status_code == 200
    assert anon.get("/").status_code == 200

def test_different_codes_are_different_tenants(secured):
    assert secured.user_for_code("alpha-code") != secured.user_for_code("beta-code")
    assert secured.user_for_code("alpha-code").startswith("u-")

def test_user_ids_are_salted_not_derived_from_the_code_alone():
    a, b = Auth(codes="x", salt=b"salt-a"), Auth(codes="x", salt=b"salt-b")
    assert a.user_id("x") != b.user_id("x")


# --- tenant isolation --------------------------------------------------------

def test_user_a_cannot_see_user_b_brief(secured):
    a, b = session("alpha-code"), session("beta-code")
    bid = start_brief(a)
    assert a.get(f"/api/briefs/{bid}").status_code == 200
    for path in (f"/api/briefs/{bid}", f"/api/briefs/{bid}/events",
                 f"/api/briefs/{bid}/pending", f"/api/briefs/{bid}/stream"):
        assert b.get(path).status_code == 404, path      # 404, not 403: no existence leak

def test_user_b_cannot_review_user_a_brief(secured):
    a, b = session("alpha-code"), session("beta-code")
    bid = start_brief(a, review="human")
    assert b.post(f"/api/briefs/{bid}/review", json={"kind": "approve"}).status_code == 404

def test_brief_list_only_shows_your_own(secured):
    a, b = session("alpha-code"), session("beta-code")
    bid = start_brief(a)
    assert bid in [x["brief_id"] for x in a.get("/api/briefs").json()["briefs"]]
    assert bid not in [x["brief_id"] for x in b.get("/api/briefs").json()["briefs"]]

def test_connected_repo_is_invisible_to_another_user(secured, monkeypatch):
    from pathlib import Path
    from tests.test_github_source import _fake_clone            # fake git: no network
    from fieldcraft_loop import github_source as gs

    def fake_git(args, timeout_s, cwd=None):
        if args[0] == "clone":
            _fake_clone(Path(args[-1]), {"README.md": "hi\n"})
        return 0, ""
    monkeypatch.setattr(gs.shutil, "which", lambda name: "/usr/bin/git")
    monkeypatch.setattr(gs, "_git", fake_git)

    a, b = session("alpha-code"), session("beta-code")
    handle = a.post("/api/repos/connect",
                    json={"url": "https://github.com/owner/tenant-test"}).json()["task"]

    assert handle in [t["name"] for t in a.get("/api/tasks").json()["tasks"]]
    assert handle not in [t["name"] for t in b.get("/api/tasks").json()["tasks"]]
    # B naming A's handle does not reach A's repo: it falls back to the sample task
    bid = start_brief(b, task=handle)
    assert "sample_task" in server.engine.get(bid)["config"]["task_dir"]


# --- store-level tenancy + migration ----------------------------------------

def test_run_store_scopes_by_user(tmp_path):
    s = RunStore(tmp_path / "runs.db")
    s.create("B1", {}, "/w", "u-a")
    s.create("B2", {}, "/w", "u-b")
    assert s.get("B1", "u-a") and s.get("B1", "u-b") is None
    assert s.get("B1") is not None                      # unscoped read still works
    assert [r["brief_id"] for r in s.list_all(user_id="u-a")] == ["B1"]
    assert s.list_status("ready", user_id="u-b") == ["B2"]

def test_pre_tenancy_rows_migrate_to_the_legacy_user(tmp_path):
    import json, sqlite3, time
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)                             # the pre-tenancy schema
    db.execute("""CREATE TABLE runs(brief_id TEXT PRIMARY KEY, config TEXT, workdir TEXT,
                  status TEXT, iteration INTEGER, total_cost REAL, trajectory TEXT,
                  last_feedback TEXT, last_verdict TEXT, last_diff TEXT, approved_by TEXT,
                  created REAL, updated REAL)""")
    db.execute("INSERT INTO runs VALUES('OLD',?,'/w','done',1,0.0,'[]','',NULL,NULL,NULL,?,?)",
               (json.dumps({}), time.time(), time.time()))
    db.commit(); db.close()

    s = RunStore(p)                                     # migrates in place
    assert s.get("OLD", LEGACY_USER) is not None        # readable in fallback mode
    assert s.get("OLD", "u-somebody") is None           # invisible to a real tenant
    assert [r["brief_id"] for r in s.list_all(user_id=LEGACY_USER)] == ["OLD"]


# --- fallback (no codes configured) -----------------------------------------

def test_fallback_is_open_when_no_codes_are_configured():
    assert server.auth.enabled is False                 # the suite's default import
    c = TestClient(server.app)
    assert c.get("/api/tasks").status_code == 200
    assert c.get("/healthz").json()["auth_enabled"] is False

def test_fallback_puts_everyone_in_the_legacy_tenant():
    c = TestClient(server.app)
    bid = start_brief(c)
    assert server.engine.runs.get(bid, LEGACY_USER) is not None

def test_healthz_reports_auth_enabled_when_codes_are_set(secured):
    assert TestClient(server.app).get("/healthz").json()["auth_enabled"] is True

def test_from_env_reads_codes(monkeypatch, tmp_path):
    monkeypatch.setenv("FC_INVITE_CODES", "a,b")
    monkeypatch.setenv("FC_SECRET_KEY", "k")
    a = auth_mod.from_env(tmp_path)
    assert a.enabled and a.user_for_code("b") and not a.user_for_code("c")

def test_salt_persists_across_restarts(tmp_path):
    first = auth_mod.load_or_create_salt(tmp_path)
    assert auth_mod.load_or_create_salt(tmp_path) == first   # same user_ids after a restart
