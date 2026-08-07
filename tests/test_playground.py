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

CODES = "alpha-code,beta-code"
EXPECTED = ("normalize_csv_row", "redact_pii", "parse_bool", "truncate_words")


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

def test_all_four_curated_tasks_exist():
    assert playground.TASK_IDS == EXPECTED


def test_every_curated_task_has_a_complete_story():
    cat = playground.catalogue()
    assert len(cat) == 4
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

def test_the_api_returns_all_four_with_stories():
    c = TestClient(server.app)
    body = c.get("/api/playground/tasks").json()
    assert [t["id"] for t in body["tasks"]] == list(EXPECTED)
    assert body["featured"] == "normalize_csv_row"
    for t in body["tasks"]:
        assert t["goal"] and t["catch"] and t["steering"]


def test_every_curated_task_is_actually_runnable():
    """A story for a task the comparison endpoint would reject is a dead end."""
    body = TestClient(server.app).get("/api/playground/tasks").json()
    assert set(body["runnable"]) == set(EXPECTED)
    for tid in EXPECTED:
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
