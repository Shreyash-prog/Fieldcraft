"""Governance — a declarative policy engine for what an agent may do.

The loop already reverts edits to test files (integrity). A Policy generalizes
that to a full change-control layer: which paths are editable, which are
protected, which commands may run, what content is forbidden in added code
(secrets, eval, network, disabling assertions), and how many files may change
before a human must approve. The engine evaluates a proposed change set and
returns a decision — allow, revert specific files, block, or require approval —
each with a reason, so every governance decision is explainable and auditable.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field


# --- default forbidden content patterns (added lines) -----------------------
DEFAULT_FORBIDDEN = {
    "hardcoded_secret": r"(?i)(api[_-]?key|secret|password|token)\s*=\s*['\"][A-Za-z0-9/\+_-]{12,}",
    "aws_key": r"AKIA[0-9A-Z]{16}",
    "network_call": r"\b(requests\.(get|post)|urllib\.request\.urlopen|socket\.socket)\b",
    "dynamic_exec": r"\b(eval|exec)\s*\(",
    "disabled_test": r"@pytest\.mark\.skip|assert\s+True\s*(#|$)",
}


@dataclass
class Policy:
    editable_paths: list[str] = field(default_factory=lambda: ["**"])   # allowlist globs
    protected_paths: list[str] = field(default_factory=list)            # deny globs (win)
    allowed_commands: list[list[str]] = field(default_factory=list)     # exact allowlist ([] = any)
    forbidden_patterns: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_FORBIDDEN))
    max_files_changed: int = 25
    max_budget_usd: float = 2.0
    max_iterations: int = 6

    @classmethod
    def from_dict(cls, d: dict) -> "Policy":
        d = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**d)


@dataclass
class Violation:
    kind: str            # protected_path | not_editable | forbidden_command | forbidden_content
    ref: str             # path or pattern name
    action: str          # revert | block | approve
    reason: str


@dataclass
class PolicyDecision:
    allowed: bool
    violations: list[Violation] = field(default_factory=list)
    revert_paths: list[str] = field(default_factory=list)
    requires_approval: bool = False
    blocked: bool = False

    def summary(self) -> str:
        if self.blocked:
            return "blocked"
        if self.revert_paths:
            return f"reverted {len(self.revert_paths)} file(s)"
        if self.requires_approval:
            return "requires approval"
        return "clean"


def _match_any(path: str, globs: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, g) or fnmatch.fnmatch(path, g.rstrip("/") + "/*")
               for g in globs)


class PolicyEngine:
    def __init__(self, policy: Policy):
        self.policy = policy

    def evaluate(self, changed_files: list[str], added_lines: dict[str, list[str]],
                 command: list[str] | None = None) -> PolicyDecision:
        p = self.policy
        d = PolicyDecision(allowed=True)

        for path in changed_files:
            if _match_any(path, p.protected_paths):
                d.violations.append(Violation("protected_path", path, "revert",
                                              f"{path} is protected"))
                d.revert_paths.append(path)
            elif not _match_any(path, p.editable_paths):
                d.violations.append(Violation("not_editable", path, "revert",
                                              f"{path} is outside the editable allowlist"))
                d.revert_paths.append(path)

        for path, lines in added_lines.items():
            if path in d.revert_paths:
                continue
            for name, pat in p.forbidden_patterns.items():
                if any(re.search(pat, ln) for ln in lines):
                    d.violations.append(Violation("forbidden_content", f"{name}:{path}", "revert",
                                                  f"added code matches forbidden pattern '{name}'"))
                    d.revert_paths.append(path)
                    break

        if command is not None and p.allowed_commands and command not in p.allowed_commands:
            d.violations.append(Violation("forbidden_command", " ".join(command), "block",
                                          "command not in the allowlist"))
            d.blocked = True

        net_changed = [f for f in changed_files if f not in d.revert_paths]
        if len(net_changed) > p.max_files_changed:
            d.requires_approval = True
            d.violations.append(Violation("scope", f"{len(net_changed)} files", "approve",
                                          f"more than {p.max_files_changed} files changed"))

        d.revert_paths = sorted(set(d.revert_paths))
        d.allowed = not d.blocked and not d.revert_paths and not d.requires_approval
        return d
