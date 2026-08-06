"""CLI controller loop (the terminal path, distinct from the web Engine)."""
from fieldcraft_loop.controller import Controller
from fieldcraft_loop.store import EventStore
from fieldcraft_loop.models import Brief
from tests.conftest import TASK


def test_controller_converges(tmp_path):
    store = EventStore(tmp_path / "e.db")
    brief = Brief(brief_id="B1", goal="redact", task_dir=TASK, max_iterations=5, budget_usd=2.0)
    aar = Controller(store).run(brief, tmp_path / "work")
    assert aar["final_state"] == "done" and aar["iterations"] == 2 and aar["approved_by"] == "auto"
