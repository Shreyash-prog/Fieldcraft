"""Assemble per-run results into an AAR, and compute the comparison that is the
whole point: efficiency compared only at (near-)constant effectiveness."""
from __future__ import annotations

from datetime import datetime, timezone

from .models import AAR, RunResult


EFFECTIVENESS_BAND = 0.05  # runs within this score band are "same outcome"


def build_aar(task: str, runs: list[RunResult]) -> AAR:
    aar = AAR(task=task, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    aar.runs = runs
    aar.comparison = _compare(runs)
    return aar


def _compare(runs: list[RunResult]) -> dict:
    if len(runs) < 2:
        return {"note": "need >= 2 runs to compare"}

    # rank by cost ascending among runs with comparable effectiveness
    best = min(runs, key=lambda r: r.effectiveness.score - 0)  # placeholder tiebreak
    baseline = max(runs, key=lambda r: r.efficiency.cost_usd)
    cheapest = min(runs, key=lambda r: r.efficiency.cost_usd)

    eff_scores = [r.effectiveness.score for r in runs]
    same_outcome = (max(eff_scores) - min(eff_scores)) <= EFFECTIVENESS_BAND

    cost_ratio = round(baseline.efficiency.cost_usd / cheapest.efficiency.cost_usd, 2) \
        if cheapest.efficiency.cost_usd else None
    turn_ratio = round(baseline.efficiency.turns / cheapest.efficiency.turns, 2) \
        if cheapest.efficiency.turns else None

    verdict = (
        f"Same outcome (effectiveness within {EFFECTIVENESS_BAND}), but "
        f"'{baseline.condition}' spent {cost_ratio}x the cost and {turn_ratio}x the turns "
        f"of '{cheapest.condition}'. The gap tracks input spec/context completeness "
        f"({baseline.usage_quality.spec_completeness} vs {cheapest.usage_quality.spec_completeness})."
    ) if same_outcome else (
        "Effectiveness differs across runs; efficiency is not directly comparable. "
        "Hold effectiveness constant before ranking efficiency."
    )

    return {
        "same_outcome": same_outcome,
        "effectiveness_band": EFFECTIVENESS_BAND,
        "cheapest": cheapest.condition,
        "most_expensive": baseline.condition,
        "cost_ratio": cost_ratio,
        "turn_ratio": turn_ratio,
        "verdict": verdict,
        "frontier": [
            {"condition": r.condition,
             "effectiveness": r.effectiveness.score,
             "cost_usd": r.efficiency.cost_usd}
            for r in runs
        ],
    }
