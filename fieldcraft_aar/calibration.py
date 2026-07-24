"""Judge calibration harness.

Runs a grader over hand-labeled candidate fixtures and reports how well it
agrees with the ground truth: overall agreement, per-criterion agreement, and
Cohen's kappa (agreement corrected for chance). This is the gate you run before
trusting a judge — and the number that makes "we calibrated the judge" a fact
rather than a claim.

    python -m fieldcraft_aar.calibration                 # offline (behavioral grader)
    python -m fieldcraft_aar.calibration --grader tooluse # live Claude forced tool-use judge
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

from .effectiveness import BehavioralGrader

ROOT = Path(__file__).resolve().parent.parent


def cohens_kappa(pairs: list[tuple[bool, bool]]) -> float:
    n = len(pairs)
    if n == 0:
        return 0.0
    po = sum(1 for p, a in pairs if p == a) / n
    # marginals for chance agreement
    pred_true = sum(1 for p, _ in pairs if p) / n
    act_true = sum(1 for _, a in pairs if a) / n
    pe = pred_true * act_true + (1 - pred_true) * (1 - act_true)
    return round((po - pe) / (1 - pe), 3) if pe != 1 else 1.0


def calibrate(fixtures_dir: Path, criteria: list[dict], grader) -> dict:
    spec = json.loads((fixtures_dir / "labels.json").read_text())
    pairs: list[tuple[bool, bool]] = []
    per_criterion: dict[str, list[tuple[bool, bool]]] = {}
    disagreements = []

    for fx in spec["fixtures"]:
        with tempfile.TemporaryDirectory() as td:
            wd = Path(td)
            shutil.copy2(fixtures_dir / fx["file"], wd / "redact.py")
            verdicts = {v.id: v.verdict for v in grader.grade(wd, criteria, "")}
        for cid, label in fx["labels"].items():
            pred = verdicts.get(cid, "unmet") == "met"
            actual = label == "met"
            pairs.append((pred, actual))
            per_criterion.setdefault(cid, []).append((pred, actual))
            if pred != actual:
                disagreements.append({"fixture": fx["file"], "criterion": cid,
                                      "predicted": verdicts.get(cid), "labeled": label})

    n = len(pairs)
    agreement = round(sum(1 for p, a in pairs if p == a) / n, 3) if n else 0.0
    return {
        "fixtures": len(spec["fixtures"]),
        "judgments": n,
        "agreement": agreement,
        "cohens_kappa": cohens_kappa(pairs),
        "per_criterion_agreement": {
            cid: round(sum(1 for p, a in ps if p == a) / len(ps), 3)
            for cid, ps in per_criterion.items()},
        "disagreements": disagreements,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fieldcraft_aar.calibration")
    ap.add_argument("--task", default=str(ROOT / "sample_task"))
    ap.add_argument("--grader", choices=["behavioral", "tooluse"], default="behavioral")
    a = ap.parse_args(argv)

    task = Path(a.task)
    criteria = json.loads((task / "criteria.json").read_text())
    if a.grader == "tooluse":
        from .grader_tooluse import ClaudeToolUseGrader
        grader = ClaudeToolUseGrader()
    else:
        grader = BehavioralGrader()

    r = calibrate(task / "fixtures", criteria, grader)
    print(f"\n=== JUDGE CALIBRATION ({a.grader}) ===")
    print(f"  fixtures:           {r['fixtures']}")
    print(f"  binary judgments:   {r['judgments']}")
    print(f"  agreement:          {r['agreement']}")
    print(f"  Cohen's kappa:      {r['cohens_kappa']}")
    print(f"  per-criterion:      {r['per_criterion_agreement']}")
    if r["disagreements"]:
        print(f"  disagreements:      {r['disagreements']}")
    else:
        print("  disagreements:      none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
