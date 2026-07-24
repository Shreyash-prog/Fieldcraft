"""Measure the Field Guide's impact — the product thesis in one number.

Runs the same Brief with the same agent, once with the compiled Field Guide and
once blind, and reports the efficiency delta. This is what Fieldcraft exists to
surface: better context -> measurably more efficient delivery.

    python -m fieldcraft_guide.impact
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from fieldcraft_loop.controller import Controller
from fieldcraft_loop.guided_adapter import GuidedMockAdapter
from fieldcraft_loop.models import Brief
from fieldcraft_loop.store import EventStore

from .bootstrap import bootstrap
from .compile import compile_context

ROOT = Path(__file__).resolve().parent.parent
TASK = ROOT / "sample_task"


def _run(guide_context: str, tag: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        store = EventStore(Path(td) / "e.db")
        brief = Brief(brief_id=f"B-{tag}",
                      goal="Implement redact_pii so all tests and criteria pass",
                      task_dir=str(TASK))
        return Controller(store, adapter=GuidedMockAdapter(guide_context)).run(brief, Path(td) / "work")


def main() -> int:
    guide = bootstrap(TASK)
    ctx = compile_context(guide)
    with_guide = _run(ctx, "guided")
    blind = _run("", "blind")

    print("=== Field Guide impact (same task, same agent) ===")
    print(f"  guide traps surfaced: {len(guide.traps)}")
    for tag, a in (("with guide", with_guide), ("without guide", blind)):
        print(f"  {tag:14} iterations={a['iterations']}  cost=${a['total_cost_usd']}  "
              f"converged@{a['turns_to_converge']}  rework={a['rework_turns']}")
    di = blind["iterations"] - with_guide["iterations"]
    ratio = round(blind["total_cost_usd"] / with_guide["total_cost_usd"], 2) if with_guide["total_cost_usd"] else None
    print(f"  -> Field Guide saved {di} iteration(s); {ratio}x cheaper to converge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
