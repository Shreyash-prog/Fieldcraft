#!/usr/bin/env python3
"""Offline robustness suite for the MULTI-FILE repo loop.

Drives the real engine + RepoLiveAdapter against a contract-conformant fake CLI
on a genuine multi-file repo (repo_tasks/textkit): full convergence, and the
protected-path integrity guard. No key required. Run from the repo root:

    python tools/repo_robustness_check.py
"""
import os, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FAKE = ROOT / "tools" / "fake_claude_repo.py"
os.chmod(FAKE, 0o755)
os.environ["FC_CLAUDE_BIN"] = str(FAKE)
os.environ["FC_FAKE_TASK_DIR"] = str(ROOT / "repo_tasks" / "textkit")

from fieldcraft_loop.engine import Engine
from fieldcraft_loop.repo_task import RepoTask, copy_repo
from fieldcraft_loop.repo_adapters import RepoLiveAdapter

R = []
def chk(n, ok): R.append(ok); print(("PASS " if ok else "FAIL ") + n)

os.environ["FAKE_CLAUDE_MODE"] = "progressive"
e = Engine(tempfile.mkdtemp())
b = e.create({"adapter": "claude", "review": "auto"}, str(ROOT / "repo_tasks" / "textkit"))
e.advance(b)
chk("live multi-file loop converges", e.aar(e.get(b))["final_state"] == "done")

os.environ["FAKE_CLAUDE_MODE"] = "cheat"
t = RepoTask.load(ROOT / "repo_tasks" / "textkit")
wd = Path(tempfile.mkdtemp()) / "w"; copy_repo(t, wd)
orig = (wd / "tests" / "test_casing.py").read_text()
tr = RepoLiveAdapter().turn(ROOT / "repo_tasks" / "textkit", wd, "", 1)
chk("protected-path integrity guard",
    "reverted protected edits" in tr.turns[0].note and (wd / "tests" / "test_casing.py").read_text() == orig)

print(f"\n{sum(R)}/{len(R)} passed")
sys.exit(0 if all(R) else 1)
