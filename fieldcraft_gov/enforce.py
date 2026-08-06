"""Parse a unified diff into a change set and apply policy reverts."""
from __future__ import annotations

import re
from pathlib import Path

from .policy import Policy, PolicyEngine, PolicyDecision


def parse_diff(diff: str) -> tuple[list[str], dict[str, list[str]]]:
    """(changed_files, added_lines_by_file) from a unified diff."""
    files: list[str] = []
    added: dict[str, list[str]] = {}
    cur = None
    for line in (diff or "").splitlines():
        m = re.match(r"^\+\+\+ b/(.+)$", line)
        if m:
            cur = m.group(1)
            if cur not in files:
                files.append(cur)
            added.setdefault(cur, [])
            continue
        if cur and line.startswith("+") and not line.startswith("+++"):
            added[cur].append(line[1:])
    return files, added


def apply_reverts(before: dict[str, str], workdir: Path, revert_paths: list[str]) -> list[str]:
    reverted = []
    for path in revert_paths:
        tgt = workdir / path
        if path in before:
            tgt.parent.mkdir(parents=True, exist_ok=True)
            tgt.write_text(before[path])
            reverted.append(path)
        elif tgt.exists():
            tgt.unlink()
            reverted.append(path)
    return reverted


def enforce(policy: Policy, diff: str, before: dict[str, str], workdir: Path,
            command: list[str] | None = None) -> tuple[PolicyDecision, list[str]]:
    files, added = parse_diff(diff)
    decision = PolicyEngine(policy).evaluate(files, added, command)
    reverted = apply_reverts(before, workdir, decision.revert_paths) if decision.revert_paths else []
    return decision, reverted
