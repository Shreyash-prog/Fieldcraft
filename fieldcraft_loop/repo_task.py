"""Multi-file repository tasks — the loop operating on a real repo, not one file.

A RepoTask points at a repo directory, a configurable **test command**, and
**protected paths** (e.g. tests/) the agent must not edit. The workdir is a copy
of the whole repo; verification runs the test command; the diff spans every
changed file; and integrity reverts edits to protected paths.
"""
from __future__ import annotations

import difflib
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from fieldcraft_aar.models import Effectiveness

from .sandbox import run_sandboxed

_IGNORE = (".git", "__pycache__", ".pytest_cache")


@dataclass
class RepoTask:
    dir: str
    name: str = "repo-task"
    kind: str = "repo"
    repo_dir: str = "repo"
    test_command: list[str] = field(default_factory=lambda: ["python", "-m", "pytest", "-q"])
    protected_paths: list[str] = field(default_factory=lambda: ["tests/"])
    stages: list[str] = field(default_factory=list)     # patch dirs applied on turn 1
    solution: str = ".solution"                          # patch dir (full fix)
    trap_keywords: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, task_dir: str | Path) -> "RepoTask":
        d = Path(task_dir)
        data = json.loads((d / "task.json").read_text())
        data = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        data["dir"] = str(d)
        return cls(**data)

    def stage_patch(self, i: int) -> Path | None:
        """None when the task ships no scripted stages (e.g. a connected repo)."""
        if not self.stages:
            return None
        return Path(self.dir) / self.stages[min(i, len(self.stages) - 1)]

    def solution_patch(self) -> Path:
        return Path(self.dir) / self.solution


def copy_repo(task: RepoTask, dst: Path) -> None:
    src = Path(task.dir) / task.repo_dir
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*_IGNORE))


def apply_patch(patch_dir: Path, workdir: Path) -> None:
    """Overlay a patch directory's files onto the workdir (a scripted agent's edit)."""
    for f in patch_dir.rglob("*"):
        if f.is_file():
            tgt = workdir / f.relative_to(patch_dir)
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(f.read_text())


def snapshot(workdir: Path) -> dict[str, str]:
    snap = {}
    for f in sorted(workdir.rglob("*")):
        if f.is_file() and not any(p in f.parts for p in _IGNORE):
            snap[str(f.relative_to(workdir))] = f.read_text(errors="ignore")
    return snap


def multi_file_diff(before: dict[str, str], after: dict[str, str]) -> str:
    out = []
    for path in sorted(set(before) | set(after)):
        b = before.get(path, "").splitlines(keepends=True)
        a = after.get(path, "").splitlines(keepends=True)
        if b != a:
            out.append("".join(difflib.unified_diff(b, a, fromfile=f"a/{path}", tofile=f"b/{path}")))
    return "\n".join(out)


def is_protected(path: str, protected: list[str]) -> bool:
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in protected)


def revert_protected(before: dict[str, str], workdir: Path, protected: list[str]) -> list[str]:
    """Restore any protected file the agent changed. Returns the reverted paths."""
    reverted = []
    after = snapshot(workdir)
    for path in set(before) | set(after):
        if is_protected(path, protected) and before.get(path) != after.get(path):
            tgt = workdir / path
            if path in before:
                tgt.write_text(before[path])
            elif tgt.exists():
                tgt.unlink()
            reverted.append(path)
    return reverted


def _num(pat: str, s: str) -> int:
    m = re.search(pat, s)
    return int(m.group(1)) if m else 0


def run_tests(workdir: Path, cmd: list[str], timeout: int = 120) -> tuple[int, int, list[str]]:
    """Run the task's test command in the sandbox (see `sandbox.run_sandboxed` for
    what that does and does not guarantee). A timeout is a failed verdict."""
    res = run_sandboxed(cmd, workdir, timeout=timeout)
    if res.timed_out:
        return 0, 0, ["<timeout>"]
    out = res.output
    passed, failed = _num(r"(\d+) passed", out), _num(r"(\d+) failed", out)
    failing = re.findall(r"FAILED (\S+)", out) or re.findall(r"(\S+) FAILED", out)
    return passed, passed + failed, failing


def compute_repo_effectiveness(workdir: Path, test_command: list[str]) -> Effectiveness:
    passed, total, failing = run_tests(workdir, test_command)
    rate = (passed / total) if total else 0.0
    return Effectiveness(tests_total=total, tests_passed=passed,
                         all_tests_pass=(total > 0 and passed == total),
                         criteria=[], score=round(rate, 3), failing_tests=failing)
