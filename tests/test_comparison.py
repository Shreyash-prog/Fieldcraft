"""The three-mode comparison (A3).

Scripted and offline: bundled tasks, mock adapters, simulated human decisions,
no network and no live provider. The load-bearing assertions are the honesty
properties — modes 1 and 3 must come out equal, and only mode 2 may improve.
"""
import time

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop import comparison as cmp_mod
from fieldcraft_loop.ticket_store import RUN_MODES, TicketStore
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth

CODES = "alpha-code,beta-code"


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "COMPARISONS", {})
    return tmp_path


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c


def make(client) -> dict:
    r = client.post("/api/tickets", json={"title": "Compare the three modes"})
    assert r.status_code == 200, r.text
    return r.json()


def run_comparison(client, tid, task="redact_pii", timeout_s=180) -> dict:
    """Kick it off and wait for the background worker to finish."""
    r = client.post(f"/api/tickets/{tid}/comparison", json={"task": task})
    assert r.status_code == 200, r.text
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/tickets/{tid}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            assert body["status"] == "done", body.get("error")
            return body
        time.sleep(0.25)
    raise AssertionError("comparison did not finish in time")


def by_mode(comp) -> dict:
    return {m["mode"]: m["result"] for m in comp["modes"]}


# --- shape -------------------------------------------------------------------

def test_the_three_modes_are_the_ticket_store_run_modes():
    """The comparison's modes and the ticket model's RUN_MODES must not drift."""
    assert set(cmp_mod.MODE_KEYS) == set(RUN_MODES)


def test_start_returns_three_queued_modes():
    c = TestClient(server.app)
    t = make(c)
    body = c.post(f"/api/tickets/{t['id']}/comparison", json={}).json()
    assert [m["mode"] for m in body["modes"]] == list(cmp_mod.MODE_KEYS)
    assert body["scripted"] is True
    run_comparison_wait(c, t["id"])


def run_comparison_wait(client, tid, timeout_s=180):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = client.get(f"/api/tickets/{tid}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            return body
        time.sleep(0.25)
    raise AssertionError("comparison did not finish")


def test_runs_three_modes_and_returns_three_results():
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    res = by_mode(comp)
    assert set(res) == set(cmp_mod.MODE_KEYS)
    for r in res.values():
        assert r["brief_id"].startswith("BRIEF-")
        assert r["final_state"] == "done"
        assert r["provider"] == "scripted"


# --- the honesty properties --------------------------------------------------

def test_steering_converges_faster_and_cheaper():
    c = TestClient(server.app)
    t = make(c)
    res = by_mode(run_comparison(c, t["id"]))
    steered = res["hitl_comments"]
    for other in ("hitl_no_comments", "autonomous"):
        assert steered["iterations"] < res[other]["iterations"], (
            f"steering should converge faster than {other}")
        assert steered["cost_usd"] < res[other]["cost_usd"]


def test_a_rubber_stamp_reviewer_is_equivalent_to_no_reviewer():
    """The load-bearing honesty property. Modes 1 and 3 are both unsteered, so
    they must land in the same place — a reviewer who adds no information adds
    no value. If this ever fails, the comparison is fabricating a difference."""
    c = TestClient(server.app)
    t = make(c)
    res = by_mode(run_comparison(c, t["id"]))
    hitl, auto = res["hitl_no_comments"], res["autonomous"]
    assert hitl["iterations"] == auto["iterations"]
    assert hitl["cost_usd"] == auto["cost_usd"]
    assert hitl["effectiveness"] == auto["effectiveness"]
    assert hitl["operator_quality"] == auto["operator_quality"]


def test_all_three_reach_the_same_effectiveness():
    """Steering changes the cost of getting there, not the outcome. Claiming it
    improves quality too would be the easy lie."""
    c = TestClient(server.app)
    t = make(c)
    res = by_mode(run_comparison(c, t["id"]))
    assert len({r["effectiveness"] for r in res.values()}) == 1


def test_deltas_state_the_claims_explicitly():
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    d = comp["deltas"]
    assert d["unsteered_modes_equivalent"] is True
    assert d["effectiveness_equal"] is True
    assert d["steering_saved_iterations"] >= 1
    assert d["steering_saved_cost"] > 0
    assert d["best_mode"] == "hitl_comments"


def test_operator_quality_rewards_the_steered_run():
    c = TestClient(server.app)
    t = make(c)
    res = by_mode(run_comparison(c, t["id"]))
    assert res["hitl_comments"]["operator_quality"] > res["hitl_no_comments"]["operator_quality"]


# --- persistence -------------------------------------------------------------

def test_results_persist_on_the_ticket():
    c = TestClient(server.app)
    t = make(c)
    run_comparison(c, t["id"])
    runs = c.get(f"/api/tickets/{t['id']}").json()["runs"]
    assert {r["mode"] for r in runs} == set(cmp_mod.MODE_KEYS)
    for r in runs:
        assert r["brief_id"].startswith("BRIEF-")
        assert r["provider"] == "scripted"
        assert r["result"]["iterations"] >= 1


def test_a_finished_comparison_is_restored_from_the_ticket():
    """A reload must still show the last result, so it is rebuilt from the
    ticket rather than the in-memory progress record."""
    c = TestClient(server.app)
    t = make(c)
    run_comparison(c, t["id"])
    server.COMPARISONS.clear()                      # simulate a restart
    comp = c.get(f"/api/tickets/{t['id']}/comparison").json()["comparison"]
    assert comp["status"] == "done" and comp["restored"] is True
    assert len(comp["modes"]) == 3
    assert comp["deltas"]["unsteered_modes_equivalent"] is True


def test_rerunning_replaces_rather_than_appends():
    c = TestClient(server.app)
    t = make(c)
    run_comparison(c, t["id"])
    server.COMPARISONS.clear()
    run_comparison(c, t["id"])
    runs = c.get(f"/api/tickets/{t['id']}").json()["runs"]
    assert len(runs) == 3, "a second comparison should replace, not pile up"


def test_each_mode_is_drillable_into_its_timeline():
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    for m in comp["modes"]:
        ev = c.get(f"/api/briefs/{m['result']['brief_id']}/events").json()["events"]
        assert [e for e in ev if e["type"] == "verdict"], m["mode"]


def test_the_steered_run_records_its_steering_brief_on_the_timeline():
    """Mode 2's advantage must be visible in the log, not just asserted."""
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    steered = by_mode(comp)["hitl_comments"]
    ev = c.get(f"/api/briefs/{steered['brief_id']}/events").json()["events"]
    briefs = [e for e in ev if e["type"] == "human_comment"]
    assert briefs, "the steering brief should be on the timeline"
    assert briefs[0]["payload"]["by"] == "simulated reviewer"
    assert "before turn 1" in briefs[0]["payload"]["note"]


def test_the_unsteered_reviewer_comment_carries_no_task_knowledge():
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    plain = by_mode(comp)["hitl_no_comments"]
    ev = c.get(f"/api/briefs/{plain['brief_id']}/events").json()["events"]
    comments = [e["payload"]["comment"] for e in ev if e["type"] == "human_comment"]
    assert comments and all(c == cmp_mod.NO_STEER_COMMENT for c in comments)
    trap = cmp_mod.steering_brief(server.COMPARISON_TASKS["redact_pii"]).lower()
    assert trap, "the guide should exist for redact_pii"
    for word in ("phone", "dashed", "bare"):
        assert word not in " ".join(comments).lower(), "the rubber stamp must not steer"


# --- guards ------------------------------------------------------------------

def test_a_second_comparison_while_one_runs_is_409():
    c = TestClient(server.app)
    t = make(c)
    assert c.post(f"/api/tickets/{t['id']}/comparison", json={}).status_code == 200
    r = c.post(f"/api/tickets/{t['id']}/comparison", json={})
    assert r.status_code in (409, 200)     # 200 only if the first already finished
    if r.status_code == 409:
        assert "already running" in r.json()["detail"]
    run_comparison_wait(c, t["id"])


def test_only_bundled_scripted_tasks_are_accepted():
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/comparison", json={"task": "nope"})
    assert r.status_code == 400 and "bundled scripted task" in r.json()["detail"]


def test_a_connected_repo_task_is_not_a_comparison_target():
    """A3 is scripted-only: the connected repo is Phase B, so its handle must
    not be runnable here even though it is a valid task elsewhere."""
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/comparison",
               json={"task": "owner/repo (connected)"})
    assert r.status_code == 400


def test_the_repo_kind_bundled_task_is_excluded():
    """textkit is bundled but is a repo task with no Field Guide trap path."""
    assert "textkit (multi-file repo)" not in server.COMPARISON_TASKS
    assert "redact_pii" in server.COMPARISON_TASKS


# --- tenancy -----------------------------------------------------------------

def test_comparison_on_someone_elses_ticket_is_404(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    assert b.post(f"/api/tickets/{t['id']}/comparison", json={}).status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/comparison").status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/comparison/stream").status_code == 404


def test_another_tenant_cannot_read_the_comparison_runs(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    comp = run_comparison(a, t["id"])
    for m in comp["modes"]:
        bid = m["result"]["brief_id"]
        assert b.get(f"/api/briefs/{bid}/events").status_code == 404
        assert b.get(f"/api/briefs/{bid}").status_code == 404


# --- the module's own contract ----------------------------------------------

def test_modes_are_exactly_one_steered_and_two_unsteered():
    steered = [m for m in cmp_mod.MODES if m.steered]
    assert len(steered) == 1 and steered[0].key == "hitl_comments"
    unsteered = [m for m in cmp_mod.MODES if not m.steered]
    assert {m.adapter for m in unsteered} == {"mock"}, (
        "both unsteered modes must use the same blind adapter, or they are not "
        "comparable and the equality property is meaningless")


def test_no_mode_uses_a_live_provider():
    assert {m.adapter for m in cmp_mod.MODES} <= {"mock", "guided"}


# =============================================================================
# spend caps (B1.5) — the comparison goes through the same enforcement as
# POST /api/briefs and POST /api/tickets/{id}/runs
# =============================================================================
# Before B1.5 this path called ledger.reserve(..., enforce_cost=False) directly
# and clamped nothing, so it was the one user-triggerable run that could not be
# blocked by a cap. It now creates every mode through server.start_governed_run.
#
# MUTATION CHECK: flipping the shared helper back to enforce_cost=False, or
# re-inlining a reserve into the comparison worker, must fail
# test_a_live_comparison_mode_is_blocked_when_the_cap_is_exhausted and
# test_the_comparison_adds_no_second_reserve_site below. Both are written to
# depend on the real enforcement, not on a message string alone.

from fieldcraft_web.ledger import Ledger          # noqa: E402
from fieldcraft_loop import comparison as _cmp    # noqa: E402


def test_every_comparison_mode_is_created_through_the_shared_helper():
    """Structural: the comparison must not create runs of its own."""
    import inspect
    src = inspect.getsource(_cmp)
    assert "engine.create(" not in src, (
        "comparison.py must not create runs directly — that is how it bypassed "
        "the ledger before B1.5")
    worker = inspect.getsource(server.start_comparison)
    assert "start_governed_run" in worker
    assert "ledger.reserve" not in worker


def test_the_comparison_adds_no_second_reserve_site():
    import inspect
    src = inspect.getsource(server)
    assert src.count("ledger.reserve(user, ip, budget, enforce_cost=live)") == 1
    assert src.count("ledger.reserve(") == 1, "there must be exactly one reservation site"


def test_comparison_runs_are_clamped_to_the_configured_caps(monkeypatch):
    monkeypatch.setattr(server.settings, "max_iterations_cap", 2)
    monkeypatch.setattr(server.settings, "max_budget_per_run_usd", 0.30)
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    for m in comp["modes"]:
        cfg = server.engine.get(m["result"]["brief_id"])["config"]
        assert cfg["max_iterations"] == 2, "an unclamped comparison mode slipped through"
        assert cfg["budget"] == 0.30


def test_a_scripted_comparison_still_reserves_and_settles(tmp_path, monkeypatch):
    """Accounted-but-not-blocked: the money path is always exercised."""
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "l.db", global_cap=50.0, user_cap=50.0,
                               rate_per_hour=1000))
    c = TestClient(server.app)
    t = make(c)
    comp = run_comparison(c, t["id"])
    for m in comp["modes"]:
        cfg = server.engine.get(m["result"]["brief_id"])["config"]
        assert cfg["reservation_id"].startswith("RSV-")
    time.sleep(0.5)
    spent = server.ledger.spent_user("legacy")
    assert spent > 0, "the scripted comparison should have settled a nominal cost"
    assert spent < 1.0, f"three mock modes should cost pennies, got {spent}"


def test_a_live_comparison_mode_is_blocked_when_the_cap_is_exhausted(tmp_path, monkeypatch):
    """The hole B1.5 closes.

    A mode that can really spend must be refused at reservation once the tenant's
    daily cap is gone — and no engine run may be created. The live mode never
    reaches a provider: the refusal happens before engine.create.
    """
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "cap.db", global_cap=100.0, user_cap=1.0,
                               rate_per_hour=1000))
    monkeypatch.setattr(server.settings, "allow_live", True)
    # A comparison whose first mode can spend real money.
    live_mode = _cmp.Mode(key="hitl_no_comments", label="live probe", adapter="claude",
                          review="auto", steered=False, blurb="")
    monkeypatch.setattr(_cmp, "MODES", (live_mode,))

    c = TestClient(server.app)
    t = make(c)
    before = len(c.get("/api/briefs").json()["briefs"])
    burn = server.ledger.reserve("legacy", "1.2.3.4", 1.0, enforce_cost=True)
    assert burn.ok
    server.ledger.settle(burn.id, 1.0)

    assert c.post(f"/api/tickets/{t['id']}/comparison", json={}).status_code == 200
    body = run_comparison_wait(c, t["id"])

    assert body["status"] == "error", "an over-cap comparison must not proceed"
    assert "cap" in (body.get("error") or "").lower(), body.get("error")
    assert len(c.get("/api/briefs").json()["briefs"]) == before, \
        "no engine run may be created once the cap refuses the reservation"


def test_the_live_gate_applies_to_comparison_modes(monkeypatch):
    """allow_live=False must refuse a live mode even with budget to spare."""
    monkeypatch.setattr(server.settings, "allow_live", False)
    live_mode = _cmp.Mode(key="hitl_no_comments", label="live probe", adapter="claude",
                          review="auto", steered=False, blurb="")
    monkeypatch.setattr(_cmp, "MODES", (live_mode,))
    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/comparison", json={})
    body = run_comparison_wait(c, t["id"])
    assert body["status"] == "error"
    assert "live mode is disabled" in (body.get("error") or "")


def test_a_failed_comparison_does_not_strand_budget(tmp_path, monkeypatch):
    """drive=False made the worker responsible for settlement; a mid-run failure
    must release rather than leave the reservation counting against the cap."""
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "l2.db", global_cap=50.0, user_cap=50.0,
                               rate_per_hour=1000))
    boom = _cmp.Mode(key="hitl_no_comments", label="boom", adapter="mock",
                     review="auto", steered=False, blurb="")
    monkeypatch.setattr(_cmp, "MODES", (boom,))

    def _explode(*a, **k):
        raise RuntimeError("simulated engine failure")
    monkeypatch.setattr(server.engine, "advance", _explode)

    c = TestClient(server.app)
    t = make(c)
    c.post(f"/api/tickets/{t['id']}/comparison", json={})
    body = run_comparison_wait(c, t["id"])
    assert body["status"] == "error"
    time.sleep(0.4)
    assert server.ledger.spent_user("legacy") == 0.0, "a failed run stranded budget"
