"""Principled measurement metrics.

The three families stay separate, and each is defined against something
defensible rather than an ad-hoc blend:

- **effectiveness** — functional correctness (tests) and spec conformance
  (acceptance criteria), reported as sub-scores plus a composite, and **gated on
  integrity**: if the tests were tampered with, effectiveness is invalid.
- **efficiency** — not raw cost, but cost *relative to the best-known path* for
  that task (the oracle/reference). This normalizes for task difficulty, so
  efficiency is comparable across tasks and operators. "efficiency captured" is
  the fraction of achievable efficiency realized (1.0 = optimal).
- **operator quality** — efficiency captured, discounted by process waste
  (rework), i.e. how well the human drove the loop toward the frontier.

Efficiency is only ever compared **at constant effectiveness** (see stats), so
"used less" counts only when the outcome is held equal — the Goodhart guard.
"""
from __future__ import annotations

from dataclasses import dataclass


def composite_effectiveness(test_rate: float, criteria_rate: float,
                            integrity_ok: bool) -> tuple[float, bool]:
    """Composite score + validity. Weighted toward tests (executable truth) over
    criteria grading, and invalidated if integrity was violated."""
    score = round(0.6 * test_rate + 0.4 * criteria_rate, 3)
    return score, bool(integrity_ok)


def efficiency_captured(actual_cost: float, reference_cost: float) -> float:
    """Fraction of achievable (best-known) efficiency realized. 1.0 = optimal;
    0.5 = spent twice the reference. Difficulty cancels because both are for the
    same task's reference."""
    if actual_cost <= 0:
        return 1.0
    return round(min(1.0, reference_cost / actual_cost), 3)


def operator_quality(eff_captured: float, rework_turns: int, iterations: int) -> float:
    """Efficiency captured, discounted by rework share (process waste)."""
    rework_share = (rework_turns / iterations) if iterations else 0.0
    return round(eff_captured * max(0.0, 1.0 - 0.5 * rework_share), 3)


@dataclass
class Scorecard:
    task: str
    condition: str
    effectiveness: float
    valid: bool                 # integrity held -> measurement trustworthy
    actual_cost: float
    reference_cost: float
    efficiency_captured: float
    iterations: int
    rework: int
    operator_quality: float

    @classmethod
    def build(cls, task: str, condition: str, *, test_rate: float, criteria_rate: float,
              integrity_ok: bool, actual_cost: float, reference_cost: float,
              iterations: int, rework: int) -> "Scorecard":
        eff, valid = composite_effectiveness(test_rate, criteria_rate, integrity_ok)
        ec = efficiency_captured(actual_cost, reference_cost)
        return cls(task=task, condition=condition, effectiveness=eff, valid=valid,
                   actual_cost=actual_cost, reference_cost=reference_cost,
                   efficiency_captured=ec, iterations=iterations, rework=rework,
                   operator_quality=operator_quality(ec, rework, iterations))
