"""Derive efficiency and AI-usage-quality metrics from a run trace.

Neither of these depends on which model or agent produced the trace, which is
the point: the measurement layer is model- and framework-agnostic.
"""
from __future__ import annotations

from .models import RunTrace, Efficiency, UsageQuality


def compute_efficiency(trace: RunTrace) -> Efficiency:
    return Efficiency(
        turns=len(trace.turns),
        tool_calls=sum(t.tool_calls for t in trace.turns),
        cost_usd=round(sum(t.cost_usd for t in trace.turns), 4),
        wall_clock_s=trace.wall_clock_s,
    )


def compute_usage_quality(trace: RunTrace) -> UsageQuality:
    n = len(trace.turns) or 1

    # first turn that reached "converged" (1-indexed); else all turns
    turns_to_converge = n
    for i, t in enumerate(trace.turns, start=1):
        if t.event == "converged":
            turns_to_converge = i
            break

    rework = sum(1 for t in trace.turns if t.event == "rework")
    productive = n - rework
    directive_efficiency = round(productive / n, 3)

    return UsageQuality(
        turns_to_converge=turns_to_converge,
        rework_turns=rework,
        directive_efficiency=directive_efficiency,
        spec_completeness=trace.spec_completeness,
    )
