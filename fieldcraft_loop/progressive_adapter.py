"""Feedback-driven mock agent, task-generic.

Turn 1 makes a partial first attempt (the task's staged solution); once any
feedback comes back, it completes the job (the task's full solution). This
exercises the loop — feedback -> iteration -> convergence — with effectiveness
measured for real each turn. Works for any task via its manifest.
"""
from __future__ import annotations

import difflib
from pathlib import Path

from fieldcraft_aar.models import RunTrace, Turn
from .task import Task


class ProgressiveMockAdapter:
    COST_PER_TURN = 0.08

    def turn(self, task_dir: Path, workdir: Path, feedback: str, turn_index: int) -> RunTrace:
        task = Task.load(task_dir)
        target = workdir / task.target_file
        before = target.read_text()
        if feedback.strip():
            sol = task.solution_path(); note = "revised to full solution per feedback"; tc = 3
        else:
            sol = task.stage_path(0); note = "first pass (partial attempt)"; tc = 2
        after = sol.read_text()
        target.write_text(after)
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{task.target_file}", tofile=f"b/{task.target_file}"))
        return RunTrace(condition=f"turn{turn_index}", adapter="progressive-mock",
                        spec_completeness=0.6,
                        turns=[Turn(cost_usd=self.COST_PER_TURN, tool_calls=tc,
                                    event="progress", note=note)],
                        wall_clock_s=20.0, diff=diff)
