"""Fieldcraft AAR — run an AI-assisted coding loop under one or more conditions,
measure it, and emit an After-Action Review.

    python -m fieldcraft_aar --adapter mock
    python -m fieldcraft_aar --adapter claude --conditions rich_context
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from .adapters import MockAdapter, ClaudeCodeAdapter
from .effectiveness import BehavioralGrader, ClaudeGrader, compute_effectiveness
from .telemetry import compute_efficiency, compute_usage_quality
from .aar import build_aar
from .models import RunResult
from . import report

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="fieldcraft_aar")
    ap.add_argument("--adapter", choices=["mock", "claude"], default="mock")
    ap.add_argument("--grader", choices=["behavioral", "claude"], default="behavioral")
    ap.add_argument("--conditions", nargs="+", default=["rich_context", "thin_context"])
    ap.add_argument("--task", default=str(ROOT / "sample_task"))
    ap.add_argument("--out", default=str(ROOT / "out"))
    args = ap.parse_args(argv)

    task_dir = Path(args.task).resolve()
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    work_root = out_dir / "work"

    criteria = json.loads((task_dir / "criteria.json").read_text())
    adapter = MockAdapter(ROOT / "scenarios") if args.adapter == "mock" else ClaudeCodeAdapter()
    grader = BehavioralGrader() if args.grader == "behavioral" else ClaudeGrader()

    runs: list[RunResult] = []
    for cond in args.conditions:
        workdir = _fresh_workdir(task_dir, work_root, cond)
        trace = adapter.run(task_dir, workdir, cond)
        eff = compute_effectiveness(workdir, criteria, trace.diff, grader)
        runs.append(RunResult(
            condition=cond, adapter=trace.adapter,
            effectiveness=eff,
            efficiency=compute_efficiency(trace),
            usage_quality=compute_usage_quality(trace),
        ))
        print(f"[{cond:14}] effectiveness={eff.score}  "
              f"tests={eff.tests_passed}/{eff.tests_total}  "
              f"cost=${compute_efficiency(trace).cost_usd}  turns={len(trace.turns)}")

    aar = build_aar(task=task_dir.name, runs=runs)
    report.write_json(aar, out_dir / "aar.json")
    report.write_html(aar, out_dir / "aar_report.html")

    print("\n" + aar.comparison.get("verdict", ""))
    print(f"\nwrote {out_dir/'aar.json'}")
    print(f"wrote {out_dir/'aar_report.html'}")
    return 0


def _fresh_workdir(task_dir: Path, work_root: Path, cond: str) -> Path:
    wd = work_root / cond
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True)
    for f in ("redact.py", "test_redact.py"):
        shutil.copy2(task_dir / f, wd / f)
    return wd


if __name__ == "__main__":
    sys.exit(main())
