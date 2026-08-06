"""Live adapters driven by contract-conformant fake CLIs (no key)."""
import os, tempfile, shutil
from pathlib import Path
import pytest
from tests.conftest import ROOT, TASK, REPO_TASK
from fieldcraft_loop.engine import Engine
from fieldcraft_loop.live_adapter import ClaudeCodeLoopAdapter
from fieldcraft_loop.repo_adapters import RepoLiveAdapter
from fieldcraft_loop.repo_task import RepoTask, copy_repo

FAKE = ROOT / "tools" / "fake_claude.py"
FAKE_REPO = ROOT / "tools" / "fake_claude_repo.py"


@pytest.fixture(autouse=True)
def _fake_env(monkeypatch):
    os.chmod(FAKE, 0o755); os.chmod(FAKE_REPO, 0o755)
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "progressive")


def test_single_file_live_loop(monkeypatch, datadir):
    monkeypatch.setenv("FC_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FC_FAKE_TASK_DIR", TASK)
    e = Engine(datadir)
    b = e.create({"adapter": "claude", "review": "auto"}, TASK)
    e.advance(b)
    assert e.aar(e.get(b))["final_state"] == "done"

def test_single_file_integrity_and_errors(monkeypatch):
    monkeypatch.setenv("FC_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FC_FAKE_TASK_DIR", TASK)
    def turn(mode):
        monkeypatch.setenv("FAKE_CLAUDE_MODE", mode)
        wd = Path(tempfile.mkdtemp())
        for f in ("redact.py", "test_redact.py"):
            shutil.copy2(Path(TASK) / f, wd / f)
        return ClaudeCodeLoopAdapter().turn(Path(TASK), wd, "", 1), wd
    tr, wd = turn("cheat")
    assert "reverted unauthorized test-file edit" in tr.turns[0].note
    assert (wd / "test_redact.py").read_text() == (Path(TASK) / "test_redact.py").read_text()
    assert "agent error" in turn("error")[0].turns[0].note
    assert "agent error" in turn("badjson")[0].turns[0].note
    assert "no changes made" in turn("noop")[0].turns[0].note

def test_repo_live_loop_and_integrity(monkeypatch, datadir):
    monkeypatch.setenv("FC_CLAUDE_BIN", str(FAKE_REPO))
    monkeypatch.setenv("FC_FAKE_TASK_DIR", REPO_TASK)
    e = Engine(datadir)
    b = e.create({"adapter": "claude", "review": "auto"}, REPO_TASK)
    e.advance(b)
    assert e.aar(e.get(b))["final_state"] == "done"
    # integrity on a protected test
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "cheat")
    t = RepoTask.load(REPO_TASK)
    wd = Path(tempfile.mkdtemp()) / "w"; copy_repo(t, wd)
    orig = (wd / "tests" / "test_casing.py").read_text()
    tr = RepoLiveAdapter().turn(Path(REPO_TASK), wd, "", 1)
    assert "reverted protected edits" in tr.turns[0].note
    assert (wd / "tests" / "test_casing.py").read_text() == orig
