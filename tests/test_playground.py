"""The "Try it" playground — four curated tasks with stories.

The stories are a product claim: "this task has this catch, and steering names it
up front". These tests hold the claim to the code — a story whose `catch` does
not correspond to a trap the scripted task actually encodes would be marketing,
not documentation. Scripted and offline throughout.
"""
import shutil
import subprocess
import sys
import time

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop import comparison as cmp_mod
from fieldcraft_loop import playground
from fieldcraft_loop.task import Task
from fieldcraft_loop.ticket_store import TicketStore
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from tests.conftest import ROOT

CODES = "alpha-code,beta-code"
# The four "measure" tasks: their trap is a *correctness* bug, so the turn-1
# attempt fails the tests. The govern task is deliberately different — its
# naive attempt passes every test and is caught by the policy instead — so it
# is excluded from the parametrisations that assert a failing first attempt.
EXPECTED = ("normalize_csv_row", "redact_pii", "parse_bool", "truncate_words")
ALL_TASKS = EXPECTED + ("secure_api_key",)


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "COMPARISONS", {})


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c


def run_pytest_on(task: Task, source, tmp_path) -> tuple[int, int]:
    """Run the task's real tests against one candidate implementation."""
    wd = tmp_path / f"wd-{source.stem}-{time.time_ns()}"
    wd.mkdir(parents=True)
    shutil.copy2(task.dir + "/" + task.test_file, wd / task.test_file)
    shutil.copy2(source, wd / task.target_file)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "--tb=no",
                        "-p", "no:cacheprovider", "-o", "addopts=", "."],
                       cwd=wd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    import re
    passed = int((re.search(r"(\d+) passed", out) or [0, 0])[1])
    failed = int((re.search(r"(\d+) failed", out) or [0, 0])[1])
    return passed, failed


# --- the catalogue -----------------------------------------------------------

def test_the_curated_tasks_exist():
    assert playground.TASK_IDS == ALL_TASKS


def test_every_curated_task_has_a_complete_story():
    cat = playground.catalogue()
    assert len(cat) == len(ALL_TASKS)
    for s in cat:
        for f in ("id", "title", "goal", "catch", "steering"):
            assert s.get(f), f"{s.get('id')} is missing {f}"
        assert len(s["goal"]) > 20 and len(s["catch"]) > 30


def test_normalize_csv_row_is_the_featured_task():
    cat = playground.catalogue()
    featured = [s for s in cat if s["featured"]]
    assert [s["id"] for s in featured] == ["normalize_csv_row"]
    assert cat[0]["id"] == "normalize_csv_row", "the featured task should lead the menu"


def test_the_featured_story_explains_why_idempotence_matters():
    s = playground.story_for("normalize_csv_row")
    assert "idempotent" in s["catch"].lower()
    assert "re-run" in s["why_it_matters"].lower() or "retry" in s["why_it_matters"].lower()


def test_an_unknown_task_has_no_story():
    assert playground.story_for("nope") is None


# --- the stories describe traps the tasks really encode ----------------------

@pytest.mark.parametrize("task_id", EXPECTED)
def test_the_steering_line_names_a_real_trap_keyword(task_id):
    """The steering brief works because the compiled guide carries these words.
    A story whose steering does not mention the actual trap would be a fiction."""
    s = playground.story_for(task_id)
    blob = (s["steering"] + " " + s["catch"]).lower()
    assert any(k.lower() in blob for k in s["trap_keywords"]), (
        f"{task_id}: story never mentions any of {s['trap_keywords']}")


@pytest.mark.parametrize("task_id", EXPECTED)
def test_the_turn_one_attempt_fails_and_the_solution_passes(task_id, tmp_path):
    """The mechanism under every story: the unsteered first attempt fails the
    task's own tests; the solution passes them all."""
    t = Task.load(playground.task_dir(task_id))
    s_passed, s_failed = run_pytest_on(t, t.stage_path(0), tmp_path)
    f_passed, f_failed = run_pytest_on(t, t.solution_path(), tmp_path)
    assert s_failed > 0, f"{task_id}: the turn-1 attempt should fail its trap test"
    assert f_failed == 0 and f_passed > 0, f"{task_id}: the solution should pass"


def test_the_idempotence_test_is_what_catches_the_naive_csv_cleaner(tmp_path):
    """The featured task, specifically: the failing test must be the idempotence
    one, not some unrelated breakage."""
    t = Task.load(playground.task_dir("normalize_csv_row"))
    wd = tmp_path / "wd"
    wd.mkdir()
    shutil.copy2(t.dir + "/" + t.test_file, wd / t.test_file)
    shutil.copy2(t.stage_path(0), wd / t.target_file)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "-o", "addopts=", "."], cwd=wd, capture_output=True, text=True)
    out = r.stdout + r.stderr
    assert "test_is_idempotent" in out, "the idempotence test should be among the failures"
    assert "FAILED" in out or "failed" in out


def test_the_naive_cleaner_really_double_converts(tmp_path):
    """Name the corruption explicitly: 15% -> 0.15 -> 0.0015 on a second pass."""
    import importlib.util
    t = Task.load(playground.task_dir("normalize_csv_row"))
    for source, expect_stable in ((t.stage_path(0), False), (t.solution_path(), True)):
        spec = importlib.util.spec_from_file_location(f"_c{time.time_ns()}", source)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        row = {"name": "ada", "email": "A@B.co", "discount": "15%"}
        once = mod.normalize_row(row)
        twice = mod.normalize_row(once)
        assert once["discount"] == 0.15
        if expect_stable:
            assert twice == once
        else:
            assert twice["discount"] == pytest.approx(0.0015), "the trap should bite"


# --- the API -----------------------------------------------------------------

def test_the_api_returns_every_task_with_its_story():
    c = TestClient(server.app)
    body = c.get("/api/playground/tasks").json()
    assert [t["id"] for t in body["tasks"]] == list(ALL_TASKS)
    assert body["featured"] == "normalize_csv_row"
    for t in body["tasks"]:
        assert t["goal"] and t["catch"] and t["steering"]


def test_every_curated_task_is_actually_runnable():
    """A story for a task the comparison endpoint would reject is a dead end."""
    body = TestClient(server.app).get("/api/playground/tasks").json()
    assert set(body["runnable"]) == set(ALL_TASKS)
    for tid in ALL_TASKS:
        assert tid in server.COMPARISON_TASKS


def test_the_playground_api_needs_a_session(secured):
    assert TestClient(server.app).get("/api/playground/tasks").status_code == 401


# --- the honest three-mode pattern, per task ---------------------------------

@pytest.mark.parametrize("task_id", EXPECTED)
def test_each_task_produces_the_honest_comparison(task_id):
    """Every curated task must show the same shape: steering buys a turn, a
    rubber-stamp reviewer buys nothing, and the outcome is identical."""
    c = TestClient(server.app)
    t = c.post("/api/tickets", json={"title": f"try {task_id}"}).json()
    assert c.post(f"/api/tickets/{t['id']}/comparison",
                  json={"task": task_id}).status_code == 200

    deadline = time.time() + 240
    body = None
    while time.time() < deadline:
        body = c.get(f"/api/tickets/{t['id']}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert body and body["status"] == "done", body

    res = {m["mode"]: m["result"] for m in body["modes"]}
    steered = res["hitl_comments"]
    for other in ("hitl_no_comments", "autonomous"):
        assert steered["iterations"] < res[other]["iterations"], task_id
        assert steered["cost_usd"] < res[other]["cost_usd"], task_id
    assert res["hitl_no_comments"]["iterations"] == res["autonomous"]["iterations"]
    assert res["hitl_no_comments"]["cost_usd"] == res["autonomous"]["cost_usd"]
    assert {r["effectiveness"] for r in res.values()} == {1.0}, task_id
    assert steered["operator_quality"] == 1.0
    assert body["deltas"]["unsteered_modes_equivalent"] is True
    assert body["deltas"]["best_mode"] == "hitl_comments"


# --- tenancy -----------------------------------------------------------------

def test_a_playground_run_is_scoped_to_its_owner(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = a.post("/api/tickets", json={"title": "mine"}).json()
    assert b.post(f"/api/tickets/{t['id']}/comparison",
                  json={"task": "normalize_csv_row"}).status_code == 404
    assert b.get(f"/api/tickets/{t['id']}/comparison").status_code == 404


def test_the_catalogue_is_the_same_for_every_tenant(secured):
    """The stories are product content, not user data — but they still need a
    session, and they must not leak another tenant's runs."""
    a, b = session("alpha-code"), session("beta-code")
    assert a.get("/api/playground/tasks").json()["tasks"] == \
           b.get("/api/playground/tasks").json()["tasks"]


# --- no new dependencies -----------------------------------------------------

def test_the_playground_adds_no_runtime_dependency():
    src = (playground._ROOT / "fieldcraft_loop" / "playground.py").read_text()
    for forbidden in ("import requests", "import httpx", "import yaml", "import numpy"):
        assert forbidden not in src


# =============================================================================
# B4b: the govern task — the catch is a policy violation, and the gate is real
# =============================================================================

def test_the_governance_task_exists_with_its_story():
    s = playground.story_for("secure_api_key")
    assert s and s["kind"] == "govern"
    assert "secure_api_key" in playground.TASK_IDS
    for f in ("title", "goal", "catch", "steering"):
        assert s[f]
    assert "hardcoded" in s["catch"].lower() or "paste" in s["catch"].lower()


def test_it_is_the_only_govern_task_and_the_others_are_measure():
    kinds = {s["id"]: s["kind"] for s in playground.catalogue()}
    assert kinds["secure_api_key"] == "govern"
    assert all(v == "measure" for k, v in kinds.items() if k != "secure_api_key")


def test_the_govern_task_declares_the_policy_it_needs():
    s = playground.story_for("secure_api_key")
    assert s["policy"]["forbid"]["secrets"] is True, (
        "the playground applies this to the ticket, so it must be declared")
    assert playground.story_for("normalize_csv_row")["policy"] is None


def test_the_tests_do_not_catch_the_hardcoded_key(tmp_path):
    """The whole lesson. Both implementations pass the suite — a green test run
    says nothing about whether the code is safe to ship."""
    t = Task.load(playground.task_dir("secure_api_key"))
    naive_p, naive_f = run_pytest_on(t, t.stage_path(0), tmp_path)
    clean_p, clean_f = run_pytest_on(t, t.solution_path(), tmp_path)
    assert naive_f == 0 and naive_p > 0, "the naive attempt should pass every test"
    assert clean_f == 0 and clean_p == naive_p


def test_the_naive_attempt_really_contains_a_credential():
    src = Task.load(playground.task_dir("secure_api_key")).stage_path(0).read_text()
    assert "AKIA" in src, "the trap must actually be a hardcoded secret"
    assert "AKIA" not in Task.load(
        playground.task_dir("secure_api_key")).solution_path().read_text()


def test_the_real_gate_catches_it_and_the_clean_fix_passes(tmp_path):
    """Uses fieldcraft_gov directly — the same enforcement the engine calls."""
    import difflib
    from fieldcraft_gov.enforce import enforce
    from fieldcraft_gov.policy import Policy
    from fieldcraft_web import governance

    t = Task.load(playground.task_dir("secure_api_key"))
    pol = Policy.from_dict(governance.compile_policy(playground.story_for("secure_api_key")["policy"]))
    base = (playground.task_dir("secure_api_key") / t.target_file).read_text()

    for source, expect_caught in ((t.stage_path(0), True), (t.solution_path(), False)):
        wd = tmp_path / f"w{source.stem}"
        wd.mkdir()
        (wd / t.target_file).write_text(source.read_text())
        diff = "".join(difflib.unified_diff(
            base.splitlines(keepends=True), source.read_text().splitlines(keepends=True),
            fromfile=f"a/{t.target_file}", tofile=f"b/{t.target_file}"))
        decision, reverted = enforce(pol, diff, {t.target_file: base}, wd)
        assert bool(decision.violations) is expect_caught, source.stem
        assert bool(reverted) is expect_caught
        if expect_caught:
            assert decision.violations[0].kind == "forbidden_content"
            assert decision.blocked is False, "a revert must let the run continue"


def test_running_the_govern_task_triggers_a_real_revert_and_converges():
    """End to end through the product: policy on the ticket, comparison run, and
    the unsteered modes get their violation reverted before converging."""
    c = TestClient(server.app)
    t = c.post("/api/tickets", json={"title": "gov demo"}).json()
    pol = playground.story_for("secure_api_key")["policy"]
    assert c.put(f"/api/tickets/{t['id']}/governance",
                 json={"policy": pol}).status_code == 200
    assert c.post(f"/api/tickets/{t['id']}/comparison",
                  json={"task": "secure_api_key"}).status_code == 200

    deadline = time.time() + 300
    while time.time() < deadline:
        body = c.get(f"/api/tickets/{t['id']}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert body["status"] == "done", body

    caught = {}
    for m in body["modes"]:
        ev = c.get(f"/api/briefs/{m['result']['brief_id']}/events").json()["events"]
        pols = [e for e in ev if e["type"] == "policy"]
        assert pols, f"{m['mode']} never ran a policy check"
        caught[m["mode"]] = (sum(len(e["payload"]["violations"]) for e in pols),
                             [p for e in pols for p in (e["payload"].get("reverted") or [])])
        assert m["result"]["effectiveness"] == 1.0, "it must still converge on the clean fix"
        assert m["result"]["final_state"] == "done"

    assert caught["hitl_no_comments"][0] >= 1, "the unsteered run should trip the gate"
    assert "apiclient.py" in caught["hitl_no_comments"][1], "the change must be reverted"
    assert caught["autonomous"][0] >= 1
    assert caught["hitl_comments"][0] == 0, (
        "the steered run knew the rule up front and should never have tripped it")


def test_the_govern_task_keeps_the_honest_three_mode_pattern():
    c = TestClient(server.app)
    t = c.post("/api/tickets", json={"title": "gov pattern"}).json()
    c.put(f"/api/tickets/{t['id']}/governance",
          json={"policy": playground.story_for("secure_api_key")["policy"]})
    c.post(f"/api/tickets/{t['id']}/comparison", json={"task": "secure_api_key"})
    deadline = time.time() + 300
    while time.time() < deadline:
        body = c.get(f"/api/tickets/{t['id']}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            break
        time.sleep(0.25)
    assert body["status"] == "done"
    res = {m["mode"]: m["result"] for m in body["modes"]}
    assert res["hitl_comments"]["iterations"] < res["hitl_no_comments"]["iterations"]
    assert res["hitl_no_comments"]["iterations"] == res["autonomous"]["iterations"]
    assert {r["effectiveness"] for r in res.values()} == {1.0}
    assert body["deltas"]["unsteered_modes_equivalent"] is True


# =============================================================================
# Regression: a Try-it task must not depend on a Board ticket surviving
# =============================================================================
# Deleting Board tickets is ordinary user behaviour. The playground used to cache
# the ticket id it created and reuse it unchecked, so deleting that ticket left a
# dangling reference and the next run failed with "unknown ticket".

def _playground_ticket(c, task_id):
    """What the UI's find-or-create does, server-side."""
    title = f"Try it · {playground.story_for(task_id)['title']}"
    existing = [t for t in c.get("/api/tickets").json()["tickets"] if t["title"] == title]
    if existing:
        return existing[0]["id"]
    return c.post("/api/tickets", json={"title": title, "status": "done"}).json()["id"]


def _run_and_wait(c, tid, task_id, timeout_s=300):
    r = c.post(f"/api/tickets/{tid}/comparison", json={"task": task_id})
    if r.status_code != 200:
        return r.status_code, None
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        body = c.get(f"/api/tickets/{tid}/comparison").json()["comparison"]
        if body and body["status"] in ("done", "error"):
            return 200, body
        time.sleep(0.25)
    raise AssertionError("comparison did not finish")


def test_a_try_it_task_runs_with_no_prior_ticket():
    c = TestClient(server.app)
    assert c.get("/api/tickets").json()["tickets"] == []
    tid = _playground_ticket(c, "parse_bool")
    status, body = _run_and_wait(c, tid, "parse_bool")
    assert status == 200 and body["status"] == "done"


def test_a_deleted_ticket_makes_the_comparison_404():
    """The mechanism behind the bug, pinned so the fix has something to fix."""
    c = TestClient(server.app)
    tid = _playground_ticket(c, "parse_bool")
    assert c.delete(f"/api/tickets/{tid}").status_code == 200
    r = c.post(f"/api/tickets/{tid}/comparison", json={"task": "parse_bool"})
    assert r.status_code == 404 and r.json()["detail"] == "unknown ticket"


def test_a_try_it_task_runs_again_after_its_ticket_was_deleted():
    """The fix, end to end: run, delete the ticket the run created, run again —
    the second run must succeed against a freshly resolved ticket."""
    c = TestClient(server.app)
    first = _playground_ticket(c, "parse_bool")
    status, body = _run_and_wait(c, first, "parse_bool")
    assert status == 200 and body["status"] == "done"

    assert c.delete(f"/api/tickets/{first}").status_code == 200
    assert c.get(f"/api/tickets/{first}").status_code == 404

    # what the UI now does: the cached id no longer resolves, so re-resolve
    second = _playground_ticket(c, "parse_bool")
    assert second != first, "a fresh ticket should have been created"
    status, body = _run_and_wait(c, second, "parse_bool")
    assert status == 200 and body["status"] == "done"
    assert body["deltas"]["unsteered_modes_equivalent"] is True


def test_the_govern_task_is_still_governed_on_a_recreated_ticket():
    """The policy must land on whichever ticket we ended up with — a recreated
    ticket running ungoverned would silently break the demo."""
    c = TestClient(server.app)
    pol = playground.story_for("secure_api_key")["policy"]
    first = _playground_ticket(c, "secure_api_key")
    c.put(f"/api/tickets/{first}/governance", json={"policy": pol})
    c.delete(f"/api/tickets/{first}")

    second = _playground_ticket(c, "secure_api_key")
    assert second != first
    assert c.get(f"/api/tickets/{second}").json()["governance_policy"] is None, (
        "a fresh ticket starts ungoverned — the playground must re-apply the policy")
    c.put(f"/api/tickets/{second}/governance", json={"policy": pol})

    status, body = _run_and_wait(c, second, "secure_api_key")
    assert status == 200 and body["status"] == "done"
    caught = 0
    for m in body["modes"]:
        ev = c.get(f"/api/briefs/{m['result']['brief_id']}/events").json()["events"]
        caught += sum(len(e["payload"]["violations"])
                      for e in ev if e["type"] == "policy")
    assert caught >= 2, "the gate should still catch the unsteered runs"


def test_the_playground_verifies_its_cached_ticket_before_using_it():
    """Structural: the cache must be checked, not trusted."""
    idx = (ROOT / "fieldcraft_web" / "static" / "index.html").read_text()
    fn = idx[idx.index("async function tryTicketFor(id, forceNew)"):][:900]
    assert "await fetch(`/api/tickets/${TRY_TICKET[id]}`)" in fn, (
        "the cached ticket must be verified before it is reused")
    assert "delete TRY_TICKET[id]" in fn, "a dead cache entry must be dropped"


def test_the_playground_retries_once_on_a_404():
    idx = (ROOT / "fieldcraft_web" / "static" / "index.html").read_text()
    fn = idx[idx.index("async function runTry(id)"):][:1200]
    assert "for(const forceNew of [false, true])" in fn
    assert "if(r.status!==404) break;" in fn


def test_a_refused_comparison_is_shown_not_left_spinning():
    """A rate-limited or capped run used to leave Try it displaying 'Running
    three ways' indefinitely — indistinguishable from one still working."""
    idx = (ROOT / "fieldcraft_web" / "static" / "index.html").read_text()
    fn = idx[idx.index("function renderTryComparison(id, c)"):][:1400]
    assert "c.status==='error'" in fn, "the error state must be rendered"
    assert "Couldn't finish this run" in fn
    assert "Try again" in fn
