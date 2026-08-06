"""Repo-aware agents (multi-file). Mock/guided for offline testing; live for real
Claude Code. All produce a multi-file diff and honor protected paths."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from fieldcraft_aar.models import RunTrace, Turn
from .live_adapter import LiveAgentError
from .repo_task import (RepoTask, apply_patch, multi_file_diff, revert_protected,
                        snapshot)


class RepoMockAdapter:
    COST = 0.09

    def turn(self, task_dir, workdir, feedback, turn_index) -> RunTrace:
        task = RepoTask.load(task_dir)
        before = snapshot(workdir)
        patch = task.solution_patch() if feedback.strip() else task.stage_patch(0)
        apply_patch(patch, workdir)
        note = "applied full solution per feedback" if feedback.strip() else "first pass (one module)"
        return _trace("repo-mock", turn_index, before, workdir, note, 3, self.COST)


class RepoGuidedAdapter:
    COST = 0.09

    def __init__(self, guide_context: str = ""):
        self.guide = (guide_context or "").lower()

    def turn(self, task_dir, workdir, feedback, turn_index) -> RunTrace:
        task = RepoTask.load(task_dir)
        knows = any(kw.lower() in self.guide for kw in task.trap_keywords)
        before = snapshot(workdir)
        patch = task.solution_patch() if (knows or feedback.strip()) else task.stage_patch(0)
        note = ("full solution — Field Guide flagged the trap up front"
                if knows and turn_index == 1 else
                ("applied full solution per feedback" if feedback.strip() else "first pass (one module)"))
        apply_patch(patch, workdir)
        return _trace("repo-guided", turn_index, before, workdir, note, 3, self.COST)


class RepoLiveAdapter:
    """Runs real Claude Code in a multi-file repo workdir."""

    def __init__(self, guide_context: str = "", timeout_s: int | None = None):
        self.guide_context = guide_context
        self.timeout_s = timeout_s or int(os.environ.get("FC_AGENT_TIMEOUT_S", "600"))
        self.cli = os.environ.get("FC_CLAUDE_BIN", "claude")
        self.permission_mode = "acceptEdits"

    def turn(self, task_dir, workdir, feedback, turn_index) -> RunTrace:
        if shutil.which(self.cli) is None and not Path(self.cli).exists():
            raise LiveAgentError(f"'{self.cli}' not found; set FC_CLAUDE_BIN")
        task = RepoTask.load(task_dir)
        before = snapshot(workdir)
        prompt = self._prompt(task, Path(task_dir), feedback, turn_index)
        t0 = time.time()
        try:
            proc = subprocess.run([self.cli, "-p", prompt, "--output-format", "json",
                                   "--permission-mode", self.permission_mode],
                                  cwd=str(workdir), capture_output=True, text=True, timeout=self.timeout_s)
            wall = round(time.time() - t0, 1)
            err, cost, nt = _parse(proc.stdout, proc.stderr, proc.returncode)
        except subprocess.TimeoutExpired:
            wall, err, cost, nt = self.timeout_s, f"timeout after {self.timeout_s}s", 0.0, 1

        reverted = revert_protected(before, workdir, task.protected_paths)
        notes = []
        if err:
            notes.append(f"agent error: {err}")
        if reverted:
            notes.append(f"reverted protected edits: {', '.join(reverted[:3])}")
        tr = _trace("claude-code-repo", turn_index, before, workdir,
                    ("first pass" if turn_index == 1 else "revised per feedback"), nt, cost, wall)
        if not tr.diff.strip():
            notes.append("no changes made")
        if notes:
            tr.turns[-1].note += " · " + "; ".join(notes)
        return tr

    def _prompt(self, task, task_dir, feedback, turn_index) -> str:
        prot = ", ".join(task.protected_paths)
        if turn_index == 1 or not feedback:
            ac = task_dir / "acceptance_criteria.md"
            goal = ac.read_text() if ac.exists() else "Make the test suite pass."
            guide = f"Field Guide:\n{self.guide_context}\n\n" if self.guide_context else ""
            return (guide + f"This is a multi-file repo. Make `{' '.join(task.test_command)}` pass. "
                    f"Do not edit protected paths ({prot}).\n\n{goal}")
        return (f"Tests still fail. Address this feedback; edit only source, not protected paths ({prot}):\n\n{feedback}")


def _parse(stdout, stderr, rc):
    try:
        d = json.loads(stdout.strip())
    except Exception:
        return ((stderr or stdout or f"exit {rc}").strip()[:200] or f"exit {rc}"), 0.0, 1
    if isinstance(d, dict):
        is_err = bool(d.get("is_error") or d.get("subtype") == "error")
        return (d.get("error") or "agent error") if is_err else None, \
               float(d.get("total_cost_usd", 0.0) or 0.0), int(d.get("num_turns", 1) or 1)
    return "unexpected output", 0.0, 1


def _trace(adapter, turn_index, before, workdir, note, tool_calls, cost, wall=25.0) -> RunTrace:
    diff = multi_file_diff(before, snapshot(workdir))
    return RunTrace(condition=f"turn{turn_index}", adapter=adapter, spec_completeness=0.6,
                    turns=[Turn(cost_usd=round(cost, 4), tool_calls=tool_calls, event="progress", note=note)],
                    wall_clock_s=wall, diff=diff)
