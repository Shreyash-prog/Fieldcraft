"""Live agent adapter — runs real Claude Code each turn, hardened for real use.

The LLM itself can only be validated with the real `claude` CLI + a key, but the
integration boundary (invocation, output parsing, file integrity, error/timeout/
no-op handling) is the part that breaks in practice, and it's fully covered here
and tested against a contract-conformant fake CLI.

Robustness features:
  - preflight: clear error if the CLI is missing (set FC_CLAUDE_BIN to override)
  - per-turn timeout (FC_AGENT_TIMEOUT_S), with one retry on transient failure
  - robust JSON parsing of the result object (is_error / non-JSON / missing fields)
  - **test-file integrity**: if the agent edits the test file, the edit is reverted
    (an agent must not make tests pass by changing the tests)
  - no-op detection: an empty diff is surfaced, not silently looped on
  - task-generic via the Task manifest; carries Field Guide context into the prompt
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from fieldcraft_aar.models import RunTrace, Turn
from .task import Task


class LiveAgentError(Exception):
    pass


class ClaudeCodeLoopAdapter:
    def __init__(self, permission_mode: str = "acceptEdits", guide_context: str = "",
                 timeout_s: int | None = None, retries: int = 1):
        self.permission_mode = permission_mode
        self.guide_context = guide_context
        self.timeout_s = timeout_s or int(os.environ.get("FC_AGENT_TIMEOUT_S", "300"))
        self.retries = retries
        self.cli = os.environ.get("FC_CLAUDE_BIN", "claude")

    def preflight(self) -> None:
        if shutil.which(self.cli) is None and not Path(self.cli).exists():
            raise LiveAgentError(
                f"'{self.cli}' not found on PATH. Install Claude Code, or set FC_CLAUDE_BIN.")

    def turn(self, task_dir: Path, workdir: Path, feedback: str, turn_index: int) -> RunTrace:
        self.preflight()
        task = Task.load(task_dir)
        target = workdir / task.target_file
        test = workdir / task.test_file
        before = target.read_text()
        test_before = test.read_text() if test.exists() else None

        result = self._invoke(self._prompt(task, Path(task_dir), feedback, turn_index), workdir)

        # integrity: an agent must not edit the tests to make them pass
        reverted = False
        if test_before is not None and test.exists() and test.read_text() != test_before:
            test.write_text(test_before)
            reverted = True

        after = target.read_text()
        diff = "".join(difflib.unified_diff(
            before.splitlines(keepends=True), after.splitlines(keepends=True),
            fromfile=f"a/{task.target_file}", tofile=f"b/{task.target_file}"))

        notes = []
        if result.get("error"):
            notes.append(f"agent error: {result['error']}")
        if not diff.strip():
            notes.append("no changes made")
        if reverted:
            notes.append("reverted unauthorized test-file edit")
        note = ("first pass" if turn_index == 1 else "revised per feedback")
        if notes:
            note += " · " + "; ".join(notes)
        note += f" · {result.get('num_turns', 1)} agent turns"

        return RunTrace(condition=f"turn{turn_index}", adapter="claude-code",
                        spec_completeness=0.6,
                        turns=[Turn(cost_usd=round(result.get("cost", 0.0), 4),
                                    tool_calls=result.get("num_turns", 1),
                                    event="progress", note=note)],
                        wall_clock_s=result.get("wall", 0.0), diff=diff)

    # ------------------------------------------------------------------
    def _invoke(self, prompt: str, workdir: Path) -> dict:
        self.preflight()
        last_err = None
        for attempt in range(self.retries + 1):
            t0 = time.time()
            try:
                proc = subprocess.run(
                    [self.cli, "-p", prompt, "--output-format", "json",
                     "--permission-mode", self.permission_mode],
                    cwd=str(workdir), capture_output=True, text=True, timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                last_err = f"timeout after {self.timeout_s}s"
                continue
            except FileNotFoundError as e:
                raise LiveAgentError(str(e))
            parsed = self._parse(proc.stdout, proc.stderr, proc.returncode)
            parsed["wall"] = round(time.time() - t0, 1)
            if parsed.get("error") and parsed.get("retryable") and attempt < self.retries:
                last_err = parsed["error"]
                continue
            return parsed
        return {"error": last_err or "unknown", "retryable": False,
                "cost": 0.0, "num_turns": 1, "wall": 0.0}

    @staticmethod
    def _parse(stdout: str, stderr: str, rc: int) -> dict:
        try:
            data = json.loads(stdout.strip())
        except (json.JSONDecodeError, ValueError):
            msg = (stderr or stdout or f"exit {rc}").strip()[:300] or f"exit {rc}"
            return {"error": msg, "retryable": rc != 0, "cost": 0.0, "num_turns": 1}
        if isinstance(data, dict):
            is_err = bool(data.get("is_error") or data.get("subtype") == "error"
                          or data.get("type") == "error")
            return {"error": (data.get("error") or "agent reported error") if is_err else None,
                    "retryable": is_err,
                    "cost": float(data.get("total_cost_usd", 0.0) or 0.0),
                    "num_turns": int(data.get("num_turns", 1) or 1)}
        return {"error": "unexpected agent output shape", "retryable": False,
                "cost": 0.0, "num_turns": 1}

    def _prompt(self, task: Task, task_dir: Path, feedback: str, turn_index: int) -> str:
        if turn_index == 1 or not feedback:
            ac = task_dir / "acceptance_criteria.md"
            goal = ac.read_text() if ac.exists() else f"Implement {task.module} correctly."
            guide = (f"Field Guide for this codebase:\n{self.guide_context}\n\n"
                     if self.guide_context else "")
            return (guide + f"Edit {task.target_file} so every test in {task.test_file} passes. "
                    f"Do not modify {task.test_file}.\n\n" + goal)
        return (f"Your previous change to {task.target_file} did not fully pass review. "
                f"Address this feedback, editing only {task.target_file} "
                f"(do not modify {task.test_file}):\n\n" + feedback)
