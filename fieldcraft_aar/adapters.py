"""Run adapters. The harness treats "run an agent on a task" as an interface,
so the measurement layer is agnostic to model / framework / agent.

  MockAdapter        - replays a recorded trace; runs fully offline.
  ClaudeCodeAdapter  - shells out to `claude -p` (Claude Code headless).

Both return a RunTrace. Effectiveness is measured downstream by really running
the task's tests against whatever the adapter produced in the workdir.
"""
from __future__ import annotations

import difflib
import json
import shutil
import subprocess
import time
from pathlib import Path

from .models import RunTrace, Turn


class RunAdapter:
    def run(self, task_dir: Path, workdir: Path, condition: str) -> RunTrace:
        raise NotImplementedError


# ----------------------------------------------------------------------------
class MockAdapter(RunAdapter):
    """Replays a recorded scenario. Applies the recorded solution to the workdir
    (so the real pytest run reflects it) and returns the recorded turn trace.
    Effectiveness stays REAL; only the run trace is replayed."""

    def __init__(self, scenarios_dir: Path):
        self.scenarios_dir = scenarios_dir

    def run(self, task_dir: Path, workdir: Path, condition: str) -> RunTrace:
        scenario = json.loads((self.scenarios_dir / f"{condition}.json").read_text())
        target = workdir / "redact.py"
        before = target.read_text()

        # apply the recorded solution the agent "arrived at"
        solution = task_dir / scenario["solution_file"]
        after = solution.read_text()
        target.write_text(after)

        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile="a/redact.py", tofile="b/redact.py",
        ))
        turns = [Turn(**t) for t in scenario["turns"]]
        return RunTrace(
            condition=condition, adapter="mock",
            spec_completeness=scenario["spec_completeness"],
            turns=turns, wall_clock_s=scenario.get("wall_clock_s", 0.0), diff=diff,
        )


# ----------------------------------------------------------------------------
class ClaudeCodeAdapter(RunAdapter):
    """Live path. Runs Claude Code headless in the workdir and parses its JSON
    result for cost/turns. Requires the `claude` CLI + your auth. Not exercised
    in the offline demo, but written to run for real."""

    def __init__(self, prompt_for=None, permission_mode: str = "acceptEdits"):
        self.prompt_for = prompt_for or _default_prompt
        self.permission_mode = permission_mode

    def run(self, task_dir: Path, workdir: Path, condition: str) -> RunTrace:
        prompt = self.prompt_for(task_dir, condition)
        target = workdir / "redact.py"
        before = target.read_text()

        t0 = time.time()
        proc = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json",
             "--permission-mode", self.permission_mode],
            cwd=str(workdir), capture_output=True, text=True,
        )
        wall = time.time() - t0

        cost, num_turns = 0.0, 1
        try:
            result = json.loads(proc.stdout)
            cost = float(result.get("total_cost_usd", 0.0))
            num_turns = int(result.get("num_turns", 1))
        except (json.JSONDecodeError, ValueError):
            pass

        after = target.read_text()
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile="a/redact.py", tofile="b/redact.py",
        ))
        # Headless gives an aggregate; attribute cost across turns for the trace.
        per = round(cost / max(num_turns, 1), 6)
        turns = [Turn(cost_usd=per, tool_calls=1, event="progress") for _ in range(num_turns)]
        if turns:
            turns[-1].event = "converged"
        return RunTrace(
            condition=condition, adapter="claude-code",
            spec_completeness=_spec_completeness(task_dir, condition),
            turns=turns, wall_clock_s=round(wall, 1), diff=diff,
        )


def _default_prompt(task_dir: Path, condition: str) -> str:
    goal = (task_dir / "acceptance_criteria.md").read_text()
    # In live mode you'd vary the injected context by `condition` to reproduce
    # the rich- vs thin-context comparison. Kept simple here.
    return (
        "Edit redact.py so all tests in test_redact.py pass. "
        "Do not modify the tests.\n\n" + goal
    )


def _spec_completeness(task_dir: Path, condition: str) -> float:
    # Placeholder: in live mode, score the actual spec/context you fed the agent.
    return {"rich_context": 0.9, "thin_context": 0.35}.get(condition, 0.6)
