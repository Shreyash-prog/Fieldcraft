#!/usr/bin/env python3
import json, os, sys, shutil
from pathlib import Path
args = sys.argv[1:]
prompt = args[args.index("-p")+1] if "-p" in args else ""
mode = os.environ.get("FAKE_CLAUDE_MODE", "progressive")
task = Path(os.environ["FC_FAKE_TASK_DIR"])
def overlay(patch):
    for f in (task/patch).rglob("*"):
        if f.is_file():
            tgt = Path.cwd()/f.relative_to(task/patch)
            tgt.parent.mkdir(parents=True, exist_ok=True); tgt.write_text(f.read_text())
def emit(**kw):
    b={"type":"result","subtype":"success","is_error":False,"total_cost_usd":0.09,"num_turns":3}
    b.update(kw); print(json.dumps(b)); sys.exit(0)
if mode == "cheat":
    # try to make tests pass by editing a protected test, plus apply solution
    (Path.cwd()/"tests"/"test_casing.py").write_text("def test_ok():\n    assert True\n")
    overlay(".solution"); emit(total_cost_usd=0.05, num_turns=2)
# progressive: stage1 first, full solution once told tests fail
overlay(".solution" if ("still fail" in prompt or "did not" in prompt) else ".stages/stage1")
emit()
