"""Data models for Fieldcraft AAR.

Deliberately small. Three metric families ride a single run trace:
  - effectiveness  (was the outcome good?)
  - efficiency     (what did it cost?)
  - usage_quality  (how well did the operator drive the AI?)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Turn:
    """One agent turn in a run trace."""
    cost_usd: float = 0.0
    tool_calls: int = 0
    event: str = "progress"  # progress | rework | converged
    note: str = ""


@dataclass
class RunTrace:
    """Everything the harness captured about a single run, adapter-agnostic."""
    condition: str
    adapter: str
    spec_completeness: float          # 0..1 quality of the input spec/context
    turns: list[Turn] = field(default_factory=list)
    wall_clock_s: float = 0.0
    diff: str = ""


@dataclass
class CriterionVerdict:
    id: str
    text: str
    verdict: str          # met | unmet | unclear
    rationale: str = ""


@dataclass
class Effectiveness:
    tests_total: int
    tests_passed: int
    all_tests_pass: bool
    criteria: list[CriterionVerdict] = field(default_factory=list)
    score: float = 0.0    # 0..1 composite
    failing_tests: list[str] = field(default_factory=list)

    @property
    def criteria_met(self) -> int:
        return sum(1 for c in self.criteria if c.verdict == "met")


@dataclass
class Efficiency:
    turns: int
    tool_calls: int
    cost_usd: float
    wall_clock_s: float


@dataclass
class UsageQuality:
    turns_to_converge: int
    rework_turns: int
    directive_efficiency: float   # productive_turns / total_turns, 0..1
    spec_completeness: float


@dataclass
class RunResult:
    condition: str
    adapter: str
    effectiveness: Effectiveness
    efficiency: Efficiency
    usage_quality: UsageQuality

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AAR:
    task: str
    generated_at: str
    runs: list[RunResult] = field(default_factory=list)
    comparison: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "generated_at": self.generated_at,
            "runs": [r.to_dict() for r in self.runs],
            "comparison": self.comparison,
        }
