#!/usr/bin/env python3
"""Offline robustness suite for the live agent adapter.

Drives the REAL ClaudeCodeLoopAdapter against a contract-conformant fake CLI, so
every integration branch (loop, integrity guard, no-op, error, malformed output,
missing CLI) is exercised without a key. Run from the repo root:

    python tools/live_robustness_check.py
"""
import os, tempfile, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAKE = ROOT / "tools" / "fake_claude.py"
os.environ["FC_CLAUDE_BIN"] = str(FAKE)
os.environ["FC_FAKE_TASK_DIR"] = str(ROOT / "sample_task")
os.chmod(FAKE, 0o755)
sys.path.insert(0, str(ROOT))

from fieldcraft_loop.engine import Engine
from fieldcraft_loop.live_adapter import ClaudeCodeLoopAdapter, LiveAgentError

R = []
def check(n, ok, d=""):
    R.append(ok); print(("PASS " if ok else "FAIL ") + n + (("  — " + d) if d else ""))

def one_turn(mode, feedback="", turn=1):
    os.environ["FAKE_CLAUDE_MODE"] = mode
    wd = Path(tempfile.mkdtemp())
    for f in ("redact.py", "test_redact.py"):
        shutil.copy2(ROOT / "sample_task" / f, wd / f)
    return ClaudeCodeLoopAdapter().turn(ROOT / "sample_task", wd, feedback, turn), wd

os.environ["FAKE_CLAUDE_MODE"] = "progressive"
e = Engine(tempfile.mkdtemp())
bid = e.create({"adapter": "claude", "review": "auto"}, str(ROOT / "sample_task"))
e.advance(bid); aar = e.aar(e.get(bid))
check("full live loop converges (fake agent)", aar["final_state"] == "done" and aar["iterations"] == 2)

tr, wd = one_turn("cheat")
ok = "reverted unauthorized test-file edit" in tr.turns[0].note and \
     (wd / "test_redact.py").read_text() == (ROOT / "sample_task" / "test_redact.py").read_text()
check("test-file integrity guard", ok)
check("no-op detection", "no changes made" in one_turn("noop")[0].turns[0].note)
check("agent error surfaced", "agent error" in one_turn("error")[0].turns[0].note)
check("malformed output handled", "agent error" in one_turn("badjson")[0].turns[0].note)

try:
    os.environ["FC_CLAUDE_BIN"] = "/nonexistent/claude-xyz"
    ClaudeCodeLoopAdapter().turn(ROOT / "sample_task", Path(tempfile.mkdtemp()), "", 1)
    check("missing-CLI preflight", False)
except LiveAgentError:
    check("missing-CLI preflight", True)

print(f"\n{sum(R)}/{len(R)} passed")
sys.exit(0 if all(R) else 1)
