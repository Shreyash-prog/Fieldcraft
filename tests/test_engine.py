"""Resumable engine — lifecycle, human review, restart survival, circuit breakers."""
from fieldcraft_loop.engine import Engine
from tests.conftest import TASK


def test_auto_run_converges(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "mock", "review": "auto"}, TASK)
    e.advance(b)
    a = e.aar(e.get(b))
    assert a["final_state"] == "done" and a["iterations"] == 2 and a["approved_by"] == "auto"

def test_human_review_flow(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "mock", "review": "human"}, TASK)
    e.advance(b)
    assert e.get(b)["status"] == "awaiting_review"
    p = e.pending(b)
    assert p["turn"] == 1 and any(c["verdict"] == "unmet" for c in p["criteria"])
    e.submit_review(b, "changes", "phones still unmasked"); e.advance(b)
    e.submit_review(b, "approve")
    a = e.aar(e.get(b))
    assert a["final_state"] == "done" and a["approved_by"] == "human"

def test_survives_restart(datadir):
    b = None
    e1 = Engine(datadir)
    b = e1.create({"adapter": "mock", "review": "human"}, TASK)
    e1.advance(b)
    assert e1.get(b)["status"] == "awaiting_review"
    del e1
    e2 = Engine(datadir)                          # fresh process, same data dir
    assert e2.get(b)["status"] == "awaiting_review"
    e2.submit_review(b, "changes", "phones"); e2.advance(b)
    del e2
    e3 = Engine(datadir)
    e3.submit_review(b, "approve")
    a = e3.aar(e3.get(b))
    assert a["final_state"] == "done" and a["approved_by"] == "human" and a["iterations"] == 2

def test_budget_circuit_breaker(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "mock", "review": "auto", "budget": 0.05}, TASK)
    e.advance(b)
    assert e.get(b)["status"] == "needs_human"    # first turn's cost exceeds budget

def test_iteration_circuit_breaker(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "mock", "review": "auto", "max_iterations": 1}, TASK)
    e.advance(b)
    assert e.get(b)["status"] == "needs_human"    # can't converge within 1 iteration

def test_guided_converges_faster(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "guided", "review": "auto"}, TASK)
    e.advance(b)
    assert e.aar(e.get(b))["iterations"] == 1     # Field Guide flags the trap
