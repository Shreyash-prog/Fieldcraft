import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("FC_PYTEST_TIMEOUT_S", "60")

import pytest

@pytest.fixture
def datadir(tmp_path):
    return tmp_path / "fc"

TASK = str(ROOT / "sample_task")
REPO_TASK = str(ROOT / "repo_tasks" / "textkit")

import tempfile
os.environ.setdefault("FC_DATA_DIR", tempfile.mkdtemp(prefix="fc_web_"))


@pytest.fixture(autouse=True)
def web_guards(tmp_path, monkeypatch):
    """Give each test its own spend ledger and concurrency slots.

    The server's guards are process-global, and since P0-4 the spend/rate one is
    also *durable* — without this, every test in the session would draw down one
    hourly rate budget and one daily cap. Tests that care about the limits build
    their own Ledger with the caps they want.
    """
    from fieldcraft_web import server
    from fieldcraft_web.ledger import Ledger
    monkeypatch.setattr(server, "ledger", Ledger(tmp_path / "test-ledger.db",
                                                 global_cap=10_000, user_cap=10_000,
                                                 rate_per_hour=10_000))
    monkeypatch.setattr(server, "conc", server.Concurrency(64))
