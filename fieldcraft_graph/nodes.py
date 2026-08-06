"""The role-players. Each node reads/writes shared state and returns a NodeResult.

Nodes are deliberately small — the intelligence is in composition (the graph) and
in the agents/judges they wrap, which stay swappable (mock here; live later).
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from .models import NodeResult
from fieldcraft_loop.repo_task import (RepoTask, apply_patch, snapshot,
                                       multi_file_diff, run_tests)


class PlanNode:
    kind = "plan"

    def __init__(self, id="plan"):
        self.id = id

    def run(self, s) -> NodeResult:
        task = RepoTask.load(s["task_dir"])
        sol = task.solution_patch()
        files = sorted(str(f.relative_to(sol)) for f in sol.rglob("*.py")
                       if f.is_file() and f.name != "__init__.py")
        subs = [{"id": Path(f).stem, "file": f} for f in files]
        return NodeResult(outputs={"sub_tasks": subs},
                          note=f"decomposed into {len(subs)} sub-task(s): " + ", ".join(x["id"] for x in subs),
                          events=[("plan", {"sub_tasks": [x["id"] for x in subs]})])


class CodeNode:
    """Wraps the coding agent. Scoped (one sub-task, for fan-out) or progressive
    (stage then full solution, for the linear loop)."""
    kind = "code"

    def __init__(self, id="code", scope=None):
        self.id = id
        self.scope = scope

    def run(self, s) -> NodeResult:
        task = RepoTask.load(s["task_dir"])
        wd = Path(s["workdir"])
        before = snapshot(wd)
        scope = self.scope or s.get("_item")
        t0 = time.time()
        if scope:                                   # parallel: implement just this file
            src = task.solution_patch() / scope["file"]
            tgt = wd / scope["file"]
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(src.read_text())
            note = f"[{scope['id']}] implemented {scope['file']}"
        else:                                        # progressive: stage1, then full solution
            patch = task.solution_patch() if s.get("feedback") else task.stage_patch(0)
            apply_patch(patch, wd)
            note = "applied full solution per feedback" if s.get("feedback") else "first pass (one module)"
        diff = multi_file_diff(before, snapshot(wd))
        return NodeResult(outputs={"diff": diff}, cost_usd=0.09, wall_s=time.time() - t0,
                          note=note, events=[("turn_done", {"note": note, "cost_usd": 0.09})])


class IntegrateNode:
    """Fan-in: recompute the merged diff from the pre-fan-out snapshot; flag
    conflicts (the same file claimed by two sub-tasks)."""
    kind = "integrate"

    def __init__(self, id="integrate"):
        self.id = id

    def run(self, s) -> NodeResult:
        wd = Path(s["workdir"])
        diff = multi_file_diff(s.get("_prefanout", {}), snapshot(wd))
        files = [st["file"] for st in s.get("sub_tasks", [])]
        conflict = len(files) != len(set(files))
        note = f"merged {len(files)} branch(es)" + (" — CONFLICT" if conflict else "")
        return NodeResult(outputs={"diff": diff, "conflict": conflict}, note=note,
                          events=[("integrate", {"files": files, "conflict": conflict})])


class VerifyNode:
    kind = "verify"

    def __init__(self, id="verify"):
        self.id = id

    def run(self, s) -> NodeResult:
        task = RepoTask.load(s["task_dir"])
        t0 = time.time()
        p, tot, fail = run_tests(Path(s["workdir"]), task.test_command)
        conv = tot > 0 and p == tot
        return NodeResult(
            outputs={"verdict": {"tests": f"{p}/{tot}", "passed": p, "total": tot, "failing": fail},
                     "converged": conv,
                     "feedback": "" if conv else "tests failing: " + ", ".join(fail[:4])},
            wall_s=time.time() - t0, note=f"tests {p}/{tot}",
            events=[("verdict", {"tests": f"{p}/{tot}", "failing": fail})])


class CriticNode:
    """Adversarial pre-review of the diff — catches what tests don't (leftover
    TODOs, bare excepts, secrets). Flags route back to the coder."""
    kind = "critic"
    FORBID = {"leftover_todo": r"TODO|FIXME", "bare_except": r"except\s*:",
              "hardcoded_secret": r"AKIA[0-9A-Z]{16}", "dynamic_exec": r"\b(eval|exec)\s*\("}

    def __init__(self, id="critic"):
        self.id = id

    def run(self, s) -> NodeResult:
        added = [l[1:] for l in (s.get("diff", "") or "").splitlines()
                 if l.startswith("+") and not l.startswith("+++")]
        flags = [name for name, pat in self.FORBID.items() if any(re.search(pat, l) for l in added)]
        flag = flags[0] if flags else ""
        return NodeResult(outputs={"critic_flag": flag},
                          note=("flagged: " + flag if flag else "no issues"),
                          events=[("critic", {"flag": flag})])


class ReviewNode:
    kind = "review"

    def __init__(self, id="review", mode="auto"):
        self.id = id
        self.mode = mode

    def run(self, s) -> NodeResult:
        approve = bool(s.get("converged")) and not s.get("critic_flag")
        return NodeResult(outputs={"approved": approve, "approved_by": self.mode},
                          note="approved" if approve else "changes requested",
                          events=[("review", {"approved": approve, "by": self.mode})])
