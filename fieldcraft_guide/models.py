"""The Field Guide — Fieldcraft's per-codebase brain.

A curated, versioned understanding of a repo: its module map, house conventions,
domain glossary, known traps, and test strategy. Pinned to a commit so drift
against the live code is detectable. Compiled into agent context (see compile.py)
so the agent starts a task already oriented instead of rediscovering the repo.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Module:
    path: str
    kind: str                       # package | module | test
    symbols: list[str] = field(default_factory=list)   # top-level defs/classes
    summary: str = ""               # filled by LLM enrichment (optional)


@dataclass
class FieldGuide:
    repo: str
    commit: str
    modules: list[Module] = field(default_factory=list)
    conventions: list[str] = field(default_factory=list)
    glossary: dict[str, str] = field(default_factory=dict)
    traps: list[str] = field(default_factory=list)
    test_strategy: str = ""
    sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_markdown(self) -> str:
        L = [f"# Field Guide — {self.repo}", f"`commit: {self.commit}`", ""]
        if self.test_strategy:
            L += ["## Test strategy", self.test_strategy, ""]
        if self.conventions:
            L += ["## House conventions"] + [f"- {c}" for c in self.conventions] + [""]
        if self.traps:
            L += ["## Traps & notes"] + [f"- {t}" for t in self.traps] + [""]
        if self.glossary:
            L += ["## Glossary"] + [f"- **{k}** — {v}" for k, v in self.glossary.items()] + [""]
        L += ["## Module map"]
        for m in self.modules:
            syms = (" · " + ", ".join(m.symbols[:8])) if m.symbols else ""
            note = f" — {m.summary}" if m.summary else ""
            L.append(f"- `{m.path}` ({m.kind}){syms}{note}")
        L.append("")
        return "\n".join(L)
