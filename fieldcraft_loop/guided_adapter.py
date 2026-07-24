"""A Field-Guide-aware mock agent, task-generic.

If the compiled Field Guide already flags this task's trap (its trap_keywords),
the agent gets it right on the first turn (1 iteration). Without the guide it
makes the naive partial attempt and needs the review loop to discover the trap
(2 iterations). Same agent, same task — context is the only difference.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from fieldcraft_aar.models import RunTrace, Turn
from .task import Task


class GuidedMockAdapter:
    COST = 0.08

    def __init__(self, guide_context: str = ""):
        self.guide = (guide_context or "").lower()

    def turn(self, task_dir: Path, workdir: Path, feedback: str, turn_index: int) -> RunTrace:
        task = Task.load(task_dir)
        knows_trap = any(kw.lower() in self.guide for kw in task.trap_keywords)
        target = workdir / task.target_file
        before = target.read_text()
        if knows_trap or feedback.strip():
            sol = task.solution_path()
            note = ("full solution — Field Guide flagged the trap up front"
                    if knows_trap and turn_index == 1 else "revised per feedback")
            tc = 3
        else:
            sol = task.stage_path(0); note = "first pass (partial attempt)"; tc = 2
        after = sol.read_text()
        target.write_text(after)
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{task.target_file}", tofile=f"b/{task.target_file}"))
        return RunTrace(condition=f"turn{turn_index}", adapter="guided-mock",
                        spec_completeness=0.9 if knows_trap else 0.5,
                        turns=[Turn(cost_usd=self.COST, tool_calls=tc, event="progress", note=note)],
                        wall_clock_s=18.0, diff=diff)
