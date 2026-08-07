"""Per-ticket governance (B3).

A stored policy is a promise: "this ticket's runs are checked". These tests hold
that promise to the code — a policy that saves but does not reach the engine
would be worse than no policy at all, because the operator would believe their
runs were governed.

Enforcement itself is unchanged and untested here beyond confirming it fires:
`engine.advance` -> `fieldcraft_gov.enforce` is the single site, as before.
"""
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop.engine import TERMINAL
from fieldcraft_loop.ticket_store import TicketStore
from fieldcraft_web import governance, server
from fieldcraft_web.auth import COOKIE, Auth

CODES = "alpha-code,beta-code"
FULL = {"protected_paths": ["tests/", "*.env"],
        "forbid": {"secrets": True, "eval": True, "network": False}}


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "CONNECTED", {})
    return tmp_path


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


def session(code):
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c


def make(client):
    return client.post("/api/tickets", json={"title": "Govern this"}).json()


def wait(bid, timeout_s=90):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = server.engine.get(bid)
        if r and (r["status"] in TERMINAL or r["status"] == "awaiting_review"):
            return r
        time.sleep(0.15)
    raise AssertionError("run never settled")


# =============================================================================
# store + shape
# =============================================================================

def test_a_new_ticket_is_ungoverned():
    c = TestClient(server.app)
    t = make(c)
    assert t["governance_policy"] is None
    assert c.get(f"/api/tickets/{t['id']}").json()["governance_policy"] is None


def test_set_get_and_clear():
    c = TestClient(server.app)
    t = make(c)
    r = c.put(f"/api/tickets/{t['id']}/governance", json={"policy": FULL})
    assert r.status_code == 200
    assert r.json()["governance_policy"] == FULL

    got = c.get(f"/api/tickets/{t['id']}/governance").json()
    assert got["governance_policy"] == FULL
    assert "protected path" in got["summary"]
    assert c.get(f"/api/tickets/{t['id']}").json()["governance_policy"] == FULL

    assert c.put(f"/api/tickets/{t['id']}/governance",
                 json={"policy": None}).json()["governance_policy"] is None
    assert c.get(f"/api/tickets/{t['id']}").json()["governance_policy"] is None


def test_an_empty_policy_is_stored_as_ungoverned():
    """Asking for nothing is not a policy — it must not read as 'governed'."""
    c = TestClient(server.app)
    t = make(c)
    r = c.put(f"/api/tickets/{t['id']}/governance",
              json={"policy": {"protected_paths": [],
                               "forbid": {"secrets": False, "eval": False, "network": False}}})
    assert r.json()["governance_policy"] is None


@pytest.mark.parametrize("bad", [
    {"protected_paths": "tests/"},                       # not a list
    {"protected_paths": [123]},                          # not strings
    {"protected_paths": ["x" * 500]},                    # too long
    {"protected_paths": ["a"] * 200},                    # too many
    {"forbid": {"secrets": "yes"}},                      # not a bool
    {"forbid": {"nonsense": True}},                      # unknown flag
    {"forbid": []},                                      # not an object
    "not-an-object",
])
def test_bad_shapes_are_rejected(bad):
    c = TestClient(server.app)
    t = make(c)
    r = c.put(f"/api/tickets/{t['id']}/governance", json={"policy": bad})
    assert r.status_code == 400, f"{bad!r} should have been refused"
    assert c.get(f"/api/tickets/{t['id']}").json()["governance_policy"] is None


def test_paths_are_trimmed_and_blanks_dropped():
    c = TestClient(server.app)
    t = make(c)
    r = c.put(f"/api/tickets/{t['id']}/governance",
              json={"policy": {"protected_paths": ["  tests/ ", "", "  "],
                               "forbid": {"secrets": False, "eval": False, "network": False}}})
    assert r.json()["governance_policy"]["protected_paths"] == ["tests/"]


def test_migration_adds_the_column_to_an_older_ticket_row(tmp_path):
    """A database written before B3 must open, keep its rows, and read as
    ungoverned rather than crashing."""
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)
    db.execute("""CREATE TABLE tickets(
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'backlog',
                    created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    db.execute("INSERT INTO tickets VALUES('TCK-old','legacy','ancient','',"
               "'backlog',1.0,1.0)")
    db.commit(); db.close()

    store = TicketStore(p)                      # migrate in place
    t = store.get("TCK-old", "legacy")
    assert t["title"] == "ancient" and t["governance_policy"] is None
    store.update("TCK-old", "legacy", governance_policy=FULL)
    assert store.get("TCK-old", "legacy")["governance_policy"] == FULL


# =============================================================================
# compilation — intent in, enforceable policy out
# =============================================================================

def test_compilation_produces_the_shape_the_engine_enforces():
    out = governance.compile_policy(FULL)
    assert set(out) == {"protected_paths", "editable_paths", "forbidden_patterns"}
    assert out["protected_paths"] == ["tests/", "*.env"]
    assert out["editable_paths"] == ["**"]
    assert "aws_key" in out["forbidden_patterns"]          # secrets on
    assert "dynamic_exec" in out["forbidden_patterns"]     # eval on
    assert "network_call" not in out["forbidden_patterns"]  # network off


def test_compilation_matches_the_patterns_the_old_form_produced():
    """The Run-a-task page's buildPolicy() has always emitted these exact
    expressions; moving them server-side must not change them."""
    pats = governance.compile_policy(
        {"protected_paths": [], "forbid": {"secrets": True, "eval": True, "network": True}}
    )["forbidden_patterns"]
    assert pats["aws_key"] == r"AKIA[0-9A-Z]{16}"
    assert pats["dynamic_exec"] == r"\b(eval|exec)\s*\("
    assert pats["network_call"] == \
        r"\b(requests\.(get|post)|urllib\.request\.urlopen|socket\.socket)\b"
    assert pats["hardcoded_secret"].startswith("(?i)(api[_-]?key|secret|password|token)")


def test_compiling_nothing_is_none():
    assert governance.compile_policy(None) is None
    assert governance.compile_policy({"protected_paths": [], "forbid": {}}) is None


# =============================================================================
# it actually reaches the run
# =============================================================================

def test_a_run_picks_up_the_stored_policy_automatically():
    """The load-bearing one: the operator sets it once on the ticket and every
    run is governed without re-specifying anything."""
    c = TestClient(server.app)
    t = make(c)
    c.put(f"/api/tickets/{t['id']}/governance", json={"policy": FULL})

    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    cfg = server.engine.get(bid)["config"]
    assert cfg["policy"] is not None, "the stored policy never reached the run"
    assert cfg["policy"]["protected_paths"] == ["tests/", "*.env"]
    assert "aws_key" in cfg["policy"]["forbidden_patterns"]
    assert c.get("/api/briefs").json()["briefs"][0]["policy"] is True


def test_an_ungoverned_ticket_still_runs_with_no_policy():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    assert server.engine.get(bid)["config"]["policy"] is None


def test_an_explicit_per_run_policy_overrides_the_stored_one():
    c = TestClient(server.app)
    t = make(c)
    c.put(f"/api/tickets/{t['id']}/governance", json={"policy": FULL})
    override = {"protected_paths": ["only-this/"],
                "forbid": {"secrets": False, "eval": False, "network": True}}
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "auto", "policy": override}).json()["brief_id"]
    pol = server.engine.get(bid)["config"]["policy"]
    assert pol["protected_paths"] == ["only-this/"]
    assert "network_call" in pol["forbidden_patterns"]
    assert "aws_key" not in pol["forbidden_patterns"], "the stored policy leaked through"


def test_an_explicit_null_policy_runs_this_one_ungoverned():
    """Explicitly asking for no policy must be honoured, and is different from
    omitting the field."""
    c = TestClient(server.app)
    t = make(c)
    c.put(f"/api/tickets/{t['id']}/governance", json={"policy": FULL})
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "auto", "policy": None}).json()["brief_id"]
    assert server.engine.get(bid)["config"]["policy"] is None


def test_a_precompiled_policy_from_b1_still_works():
    """B1 callers hand in a ready-made enforcement dict; that must pass through
    untouched rather than being mistaken for intent."""
    c = TestClient(server.app)
    t = make(c)
    raw = {"protected_paths": ["tests/"], "editable_paths": ["**"],
           "forbidden_patterns": {"aws_key": "AKIA[0-9A-Z]{16}"}}
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "auto", "policy": raw}).json()["brief_id"]
    assert server.engine.get(bid)["config"]["policy"] == raw


def test_the_stored_policy_is_enforced_on_a_violating_run(monkeypatch):
    """End to end: set the policy on the ticket, run an agent that plants a
    secret, and the engine's existing enforcement catches it."""
    from fieldcraft_aar.models import RunTrace, Turn
    from fieldcraft_loop.repo_task import snapshot, multi_file_diff

    class _Violator:
        def turn(self, task_dir, workdir, feedback, turn_index):
            before = snapshot(workdir)
            (workdir / "redact.py").write_text(
                'API_KEY = "AKIA1234567890ABCDEF"\n\ndef redact_pii(t):\n    return t\n')
            return RunTrace(condition="t1", adapter="violator", spec_completeness=0.5,
                            turns=[Turn(cost_usd=0.05, tool_calls=1, event="progress", note="")],
                            wall_clock_s=1.0, diff=multi_file_diff(before, snapshot(workdir)))

    monkeypatch.setattr(server.engine, "_adapter", lambda cfg: _Violator())
    c = TestClient(server.app)
    t = make(c)
    c.put(f"/api/tickets/{t['id']}/governance",
          json={"policy": {"protected_paths": [],
                           "forbid": {"secrets": True, "eval": False, "network": False}}})

    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    wait(bid)
    pol = [e for e in server.engine.get_events(bid) if e["type"] == "policy"]
    assert pol, "the policy check should have run"
    assert pol[0]["payload"]["violations"], "the planted secret should have been caught"


def test_no_second_enforcement_path_was_added():
    """Governance stays engine-level: one call site, and this module compiles
    into it rather than enforcing anything itself."""
    src = (server.Path(__file__).resolve().parent.parent /
           "fieldcraft_web" / "governance.py").read_text()
    code = [ln for ln in src.splitlines()
            if ln.strip() and not ln.lstrip().startswith(("#", "*"))]
    body = "\n".join(code)
    # It may *describe* the enforcement site in prose; it must not import it or
    # call it. Enforcement stays exactly where it was.
    for forbidden in ("import fieldcraft_gov", "from fieldcraft_gov",
                      "enforce(", "Policy.from_dict"):
        assert forbidden not in body, f"governance.py should not contain {forbidden!r}"


# =============================================================================
# tenancy
# =============================================================================

def test_another_tenant_cannot_read_or_set_the_policy(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    a.put(f"/api/tickets/{t['id']}/governance", json={"policy": FULL})

    assert b.get(f"/api/tickets/{t['id']}/governance").status_code == 404
    assert b.put(f"/api/tickets/{t['id']}/governance",
                 json={"policy": None}).status_code == 404
    assert a.get(f"/api/tickets/{t['id']}/governance").json()["governance_policy"] == FULL


def test_governance_requires_a_session(secured):
    anon = TestClient(server.app)
    assert anon.get("/api/tickets/TCK-x/governance").status_code == 401
    assert anon.put("/api/tickets/TCK-x/governance", json={"policy": None}).status_code == 401


def test_an_unknown_ticket_is_404():
    c = TestClient(server.app)
    assert c.get("/api/tickets/TCK-nope/governance").status_code == 404
    assert c.put("/api/tickets/TCK-nope/governance", json={"policy": None}).status_code == 404
