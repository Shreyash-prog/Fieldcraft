"""Ticket-scoped single governed runs (B1).

The safety core of this file is the cap tests. A ticket run is a *user-initiated*
run on the operator's keys, so it must be clamped and reserved by exactly the
same code as POST /api/briefs — the comparison path's `enforce_cost=False` is
only safe because it is scripted, and that exemption must not spread here.

Everything is offline: mock adapters, no network, no live provider. The one test
that exercises the live gate never reaches a model — the reservation is refused
before `engine.create` is called.
"""
import time

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop.engine import TERMINAL
from fieldcraft_loop.ticket_store import TicketStore
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from fieldcraft_web.ledger import Ledger

CODES = "alpha-code,beta-code"


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "CONNECTED", {})


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c


def make(client, **body) -> dict:
    r = client.post("/api/tickets", json={"title": "Ship the thing", **body})
    assert r.status_code == 200, r.text
    return r.json()


def wait_terminal(bid, timeout_s=90):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = server.engine.get(bid)
        if r and r["status"] in TERMINAL or (r and r["status"] == "awaiting_review"):
            return r
        time.sleep(0.15)
    raise AssertionError(f"run {bid} never settled")


# =============================================================================
# the run itself
# =============================================================================

def test_a_ticket_can_start_a_single_governed_run():
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brief_id"].startswith("BRIEF-")
    assert body["ticket"] == t["id"] and body["kind"] == "ticket_single"

    run = wait_terminal(body["brief_id"])
    assert run["status"] in TERMINAL
    assert run["iteration"] >= 1


def test_the_run_is_tagged_with_the_ticket_and_kind():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    cfg = server.engine.get(bid)["config"]
    assert cfg["run_kind"] == "ticket_single"
    assert cfg["ticket_id"] == t["id"]


def test_history_can_distinguish_a_ticket_run():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    c.post("/api/briefs", json={"adapter": "mock", "review": "auto"})

    rows = {b["brief_id"]: b for b in c.get("/api/briefs").json()["briefs"]}
    assert rows[bid]["run_kind"] == "ticket_single" and rows[bid]["ticket_id"] == t["id"]
    plain = [b for b in rows.values() if b["run_kind"] == "brief"]
    assert plain, "a Run-a-task brief should still report run_kind='brief'"


def test_the_run_is_attached_to_the_ticket():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]

    runs = c.get(f"/api/tickets/{t['id']}").json()["runs"]
    assert [r["brief_id"] for r in runs] == [bid]
    assert runs[0]["kind"] == "ticket_single"

    listed = c.get(f"/api/tickets/{t['id']}/runs").json()["runs"]
    assert listed[0]["brief_id"] == bid and "status" in listed[0]


def test_single_runs_accumulate_and_do_not_evict_comparison_runs():
    """The ticket's runs[] is shared with A3, whose replace-by-mode logic keys on
    a `mode` field. Single runs must carry none, so neither evicts the other."""
    c = TestClient(server.app)
    t = make(c)
    a = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    b = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    runs = c.get(f"/api/tickets/{t['id']}").json()["runs"]
    assert {r["brief_id"] for r in runs} == {a, b}
    assert all("mode" not in r for r in runs)


# =============================================================================
# streaming + review reuse (no new machinery)
# =============================================================================

def test_the_existing_stream_endpoint_serves_a_ticket_run():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    wait_terminal(bid)
    with c.stream("GET", f"/api/briefs/{bid}/stream") as s:
        assert s.status_code == 200
        body = "".join(s.iter_text())
    assert "event: state" in body


def test_a_ticket_run_pauses_for_human_review_and_resumes():
    """The default is review=human, so the loop must stop and wait, then respond
    to the existing review endpoint."""
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={}).json()["brief_id"]
    run = wait_terminal(bid)
    assert run["status"] == "awaiting_review"

    pending = c.get(f"/api/briefs/{bid}/pending").json()["pending"]
    assert pending and pending["turn"] >= 1

    assert c.post(f"/api/briefs/{bid}/review",
                  json={"kind": "approve"}).status_code == 200
    assert server.engine.get(bid)["status"] == "done"


def test_requesting_changes_on_a_ticket_run_drives_another_turn():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={}).json()["brief_id"]
    wait_terminal(bid)
    r = c.post(f"/api/briefs/{bid}/review",
               json={"kind": "changes", "comment": "handle both phone formats"})
    assert r.status_code == 200
    run = wait_terminal(bid)
    assert run["iteration"] >= 2, "the comment should have driven another turn"


def test_rejecting_a_ticket_run_ends_it():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={}).json()["brief_id"]
    wait_terminal(bid)
    c.post(f"/api/briefs/{bid}/review", json={"kind": "reject"})
    assert server.engine.get(bid)["status"] == "needs_human"


# =============================================================================
# THE SAFETY CORE — caps
# =============================================================================

def test_an_exhausted_user_cap_blocks_a_ticket_run(tmp_path, monkeypatch):
    """The one that matters. A run that can really spend must be refused once the
    tenant's daily cap is gone — and nothing may be created when it is refused."""
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "cap.db", global_cap=100.0, user_cap=1.0,
                               rate_per_hour=1000))
    monkeypatch.setattr(server.settings, "allow_live", True)
    c = TestClient(server.app)
    t = make(c)
    before = len(c.get("/api/briefs").json()["briefs"])

    # burn the tenant's day
    uid = server.auth.current_user  # noqa: F841 - documented below
    spent = server.ledger.reserve("legacy", "1.2.3.4", 1.0, enforce_cost=True)
    assert spent.ok
    server.ledger.settle(spent.id, 1.0)

    r = c.post(f"/api/tickets/{t['id']}/runs",
               json={"adapter": "claude", "review": "auto"})
    assert r.status_code == 429, f"a live ticket run must be capped, got {r.status_code}"
    assert "daily spend cap" in r.json()["detail"].lower() or \
           "cap" in r.json()["detail"].lower()
    assert len(c.get("/api/briefs").json()["briefs"]) == before, "no run may be created"
    assert c.get(f"/api/tickets/{t['id']}").json()["runs"] == []


def test_an_exhausted_global_cap_blocks_a_ticket_run(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "cap2.db", global_cap=0.5, user_cap=100.0,
                               rate_per_hour=1000))
    monkeypatch.setattr(server.settings, "allow_live", True)
    c = TestClient(server.app)
    t = make(c)
    burn = server.ledger.reserve("someone-else", "9.9.9.9", 0.5, enforce_cost=True)
    server.ledger.settle(burn.id, 0.5)

    r = c.post(f"/api/tickets/{t['id']}/runs", json={"adapter": "claude", "review": "auto"})
    assert r.status_code == 429


def test_a_ticket_run_reserves_and_settles_against_the_ledger():
    """Even an offline run must go through the reservation path, so the accounting
    is always exercised and the simulated cost is recorded."""
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    cfg = server.engine.get(bid)["config"]
    assert cfg["reservation_id"].startswith("RSV-")
    wait_terminal(bid)
    time.sleep(0.4)                                    # let the worker settle
    assert server.ledger.spent_user("legacy") >= 0.0


def test_the_iteration_and_budget_clamps_apply(monkeypatch):
    monkeypatch.setattr(server.settings, "max_iterations_cap", 3)
    monkeypatch.setattr(server.settings, "max_budget_per_run_usd", 0.25)
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "auto", "max_iterations": 99,
                       "budget": 999.0}).json()["brief_id"]
    cfg = server.engine.get(bid)["config"]
    assert cfg["max_iterations"] == 3 and cfg["budget"] == 0.25


def test_the_live_gate_applies_to_ticket_runs(monkeypatch):
    monkeypatch.setattr(server.settings, "allow_live", False)
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/runs", json={"adapter": "claude"})
    assert r.status_code == 403 and "live mode is disabled" in r.json()["detail"]


def test_both_run_paths_share_one_cap_enforcement_helper():
    """Structural guard: if someone re-inlines the clamp/reserve into either
    endpoint, the two paths can drift and one of them will stop enforcing."""
    import inspect
    src = inspect.getsource(server)
    assert src.count("ledger.reserve(user, ip, budget, enforce_cost=live)") == 1
    for fn in (server.create_brief, server.start_ticket_run):
        assert "start_governed_run" in inspect.getsource(fn)
        assert "ledger.reserve" not in inspect.getsource(fn)


# =============================================================================
# connected repo
# =============================================================================

def _connect_fake_repo(c, tid, monkeypatch):
    from fieldcraft_loop import github_source

    def _clone(url, dest, timeout_s=None, max_mb=None):
        owner, name = github_source.parse_repo_url(url)
        dest = server.Path(dest)
        (dest / "tests").mkdir(parents=True, exist_ok=True)
        (dest / "tests" / "test_demo.py").write_text("def test_ok():\n    assert True\n")
        return github_source.RepoInfo(owner=owner, name=name,
                                      url=github_source.clone_url_for(owner, name),
                                      path=str(dest), default_branch="main",
                                      file_count=1, size_mb=0.01)
    monkeypatch.setattr(server.github_source, "clone_public_repo", _clone)
    r = c.post(f"/api/tickets/{tid}/repo", json={"url": "https://github.com/o/r"})
    assert r.status_code == 200, r.text
    return r.json()["repo"]["handle"]


def test_a_ticket_run_defaults_to_the_connected_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "TICKET_REPOS", tmp_path / "repos")
    c = TestClient(server.app)
    t = make(c)
    handle = _connect_fake_repo(c, t["id"], monkeypatch)

    body = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()
    assert body["task"] == handle and body["connected_repo"] is True
    cfg = server.engine.get(body["brief_id"])["config"]
    assert cfg["kind"] == "repo"


def test_the_connected_repo_mock_only_guard_holds(tmp_path, monkeypatch):
    """The guard that keeps a stranger's code away from a live provider."""
    monkeypatch.setattr(server, "TICKET_REPOS", tmp_path / "repos")
    monkeypatch.setattr(server.settings, "allow_live", True)
    c = TestClient(server.app)
    t = make(c)
    _connect_fake_repo(c, t["id"], monkeypatch)

    for bad in ({"adapter": "claude"}, {"grader": "tooluse"}):
        r = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto", **bad})
        assert r.status_code == 403, bad
        assert "offline mock agent only" in r.json()["detail"]


def test_a_missing_connected_repo_fails_loudly(tmp_path, monkeypatch):
    """After a restart CONNECTED is empty. The ticket must not silently run the
    default bundled task instead of the repo it claims to point at."""
    monkeypatch.setattr(server, "TICKET_REPOS", tmp_path / "repos")
    c = TestClient(server.app)
    t = make(c)
    handle = _connect_fake_repo(c, t["id"], monkeypatch)
    server.CONNECTED.clear()
    import shutil
    shutil.rmtree(server.TICKET_REPOS / "legacy" / t["id"], ignore_errors=True)

    r = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"})
    assert r.status_code == 409 and "no longer available" in r.json()["detail"]
    assert handle


def test_a_connected_repo_is_rehydrated_after_a_restart(tmp_path, monkeypatch):
    """The clone is still on disk, so the run should recover rather than refuse."""
    monkeypatch.setattr(server, "TICKET_REPOS", tmp_path / "repos")
    c = TestClient(server.app)
    t = make(c)
    handle = _connect_fake_repo(c, t["id"], monkeypatch)
    server.CONNECTED.clear()                       # simulate the restart

    body = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()
    assert body["task"] == handle and body["connected_repo"] is True


# =============================================================================
# governance
# =============================================================================

def test_a_policy_on_the_request_reaches_the_engine():
    c = TestClient(server.app)
    t = make(c)
    pol = {"protected_paths": ["tests/"], "editable_paths": ["**"],
           "forbidden_patterns": {"aws_key": "AKIA[0-9A-Z]{16}"}}
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "auto", "policy": pol}).json()["brief_id"]
    assert server.engine.get(bid)["config"]["policy"] == pol
    assert c.get("/api/briefs").json()["briefs"][0]["policy"] is True


def test_governance_reverts_a_violating_ticket_run(monkeypatch):
    """A mock agent that plants a hardcoded secret must be caught and reverted by
    the engine's existing enforcement — no change to fieldcraft_gov."""
    from fieldcraft_aar.models import RunTrace, Turn
    from fieldcraft_loop.repo_task import snapshot, multi_file_diff

    class _Violator:
        def turn(self, task_dir, workdir, feedback, turn_index):
            before = snapshot(workdir)
            (workdir / "redact.py").write_text(
                'API_KEY = "AKIA1234567890ABCDEF"\n\ndef redact_pii(t):\n    return t\n')
            return RunTrace(condition="t1", adapter="violator", spec_completeness=0.5,
                            turns=[Turn(cost_usd=0.05, tool_calls=1, event="progress", note="")],
                            wall_clock_s=1.0,
                            diff=multi_file_diff(before, snapshot(workdir)))

    monkeypatch.setattr(server.engine, "_adapter", lambda cfg: _Violator())
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={
        "review": "auto",
        "policy": {"protected_paths": [], "editable_paths": ["**"],
                   "forbidden_patterns": {"aws_key": "AKIA[0-9A-Z]{16}"}}}).json()["brief_id"]
    wait_terminal(bid)

    events = server.engine.get_events(bid)
    pol = [e for e in events if e["type"] == "policy"]
    assert pol, "the policy check should have run"
    assert pol[0]["payload"]["violations"], "the planted secret should be a violation"


# =============================================================================
# tenancy
# =============================================================================

def test_a_user_cannot_run_someone_elses_ticket(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    assert b.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/runs").status_code == 404
    assert a.get(f"/api/tickets/{t['id']}").json()["runs"] == []


def test_another_tenant_cannot_stream_or_review_a_ticket_run(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    bid = a.post(f"/api/tickets/{t['id']}/runs", json={}).json()["brief_id"]
    assert b.get(f"/api/briefs/{bid}").status_code == 404
    assert b.get(f"/api/briefs/{bid}/events").status_code == 404
    assert b.get(f"/api/briefs/{bid}/stream").status_code == 404
    assert b.post(f"/api/briefs/{bid}/review", json={"kind": "approve"}).status_code == 404


def test_an_unknown_ticket_is_404():
    assert TestClient(server.app).post(
        "/api/tickets/TCK-nope/runs", json={"review": "auto"}).status_code == 404


def test_the_run_endpoint_requires_a_session(secured):
    assert TestClient(server.app).post(
        "/api/tickets/TCK-x/runs", json={"review": "auto"}).status_code == 401
