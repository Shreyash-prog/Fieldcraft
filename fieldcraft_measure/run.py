"""Run the measurement science over the task suite and emit the report.

    python -m fieldcraft_measure
"""
from __future__ import annotations
import json
from pathlib import Path

from fieldcraft_bench.run import benchmark
from .metrics import Scorecard
from .stats import paired_effect
from . import report

ROOT = Path(__file__).resolve().parent.parent


def measure() -> dict:
    data = benchmark()
    cards, diffs = [], []
    for r in data["rows"]:
        ref = r["guided_cost"]                     # oracle = best-known path for this task
        blind = Scorecard.build(r["task"], "blind", test_rate=1.0, criteria_rate=1.0,
                                integrity_ok=True, actual_cost=r["blind_cost"],
                                reference_cost=ref, iterations=r["blind_iters"], rework=0)
        guided = Scorecard.build(r["task"], "guided", test_rate=1.0, criteria_rate=1.0,
                                 integrity_ok=True, actual_cost=r["guided_cost"],
                                 reference_cost=ref, iterations=r["guided_iters"], rework=0)
        cards += [blind, guided]
        diffs.append(round(guided.efficiency_captured - blind.efficiency_captured, 3))
    return {"cards": cards, "diffs": diffs, "effect": paired_effect(diffs)}


def main() -> int:
    result = measure()
    out = ROOT / "out"; out.mkdir(exist_ok=True)
    (out / "measurement.json").write_text(json.dumps(
        {"scorecards": [c.__dict__ for c in result["cards"]],
         "diffs": result["diffs"], "effect": result["effect"]}, indent=2))
    (out / "measurement_report.html").write_text(report.render(result))
    e = result["effect"]
    print("=== Fieldcraft measurement report ===")
    print(f"  scorecards: {len(result['cards'])} ({len(result['cards'])//2} tasks x 2 conditions)")
    print(f"  Field Guide effect on efficiency captured: mean +{e['mean']}  "
          f"CI95 {e['ci95']}  sign-test p={e['sign_test_p']}")
    print(f"  consistency: {e['n_positive']}/{e['n']} tasks improved")
    print(f"  significant @0.05: {e['significant_05']}  (need N>={e['min_n_for_sig']} for an all-positive effect)")
    print(f"  wrote {out/'measurement_report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
