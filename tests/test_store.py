"""Event store — append-only integrity and ordered replay."""
from fieldcraft_loop.store import EventStore
from fieldcraft_loop.models import State


def test_append_and_replay_ordered(tmp_path):
    s = EventStore(tmp_path / "e.db")
    s.append("B1", 1, State.WORKING, "turn_done", {"cost_usd": 0.08}, cost=0.08)
    s.append("B1", 1, State.VERIFYING, "verdict", {"score": 0.5})
    s.append("B2", 1, State.WORKING, "turn_done", {"cost_usd": 0.1})
    ev = s.events("B1")
    assert [e["type"] for e in ev] == ["turn_done", "verdict"]       # ordered, brief-scoped
    assert ev[0]["payload"]["cost_usd"] == 0.08

def test_reopen_persists(tmp_path):
    p = tmp_path / "e.db"
    EventStore(p).append("B", 0, State.READY, "ready", {})
    assert len(EventStore(p).events("B")) == 1                        # survives reopen
