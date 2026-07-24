#!/usr/bin/env python3
"""Contract-conformant fake of `claude -p --output-format json`.

Behaves like a coding agent operating in cwd, and emits the Claude Code result
JSON. Modes via FAKE_CLAUDE_MODE let us exercise every branch of the real
adapter's handling. Uses the real task's staged/solution files (FC_FAKE_TASK_DIR).
"""
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
prompt = args[args.index("-p") + 1] if "-p" in args else ""
mode = os.environ.get("FAKE_CLAUDE_MODE", "progressive")
taskdir = Path(os.environ["FC_FAKE_TASK_DIR"])
man = json.loads((taskdir / "task.json").read_text())
target = Path.cwd() / man["target_file"]

def emit(**kw):
    base = {"type": "result", "subtype": "success", "is_error": False,
            "total_cost_usd": 0.09, "num_turns": 3}
    base.update(kw); print(json.dumps(base)); sys.exit(0)

if mode == "error":
    emit(subtype="error", is_error=True, error="simulated model error", total_cost_usd=0.01, num_turns=1)
if mode == "badjson":
    print("<<not valid json>>"); sys.exit(1)
if mode == "noop":
    emit(total_cost_usd=0.02, num_turns=1)          # says success but changes nothing
if mode == "cheat":
    (Path.cwd() / man["test_file"]).write_text("def test_ok():\n    assert True\n")
    target.write_text((taskdir / man["solution"]).read_text())
    emit(total_cost_usd=0.05, num_turns=2)
# progressive: partial first, full solution once told it didn't pass
src = man["solution"] if "did not fully pass" in prompt else man["stages"][0]
target.write_text((taskdir / src).read_text())
emit()
