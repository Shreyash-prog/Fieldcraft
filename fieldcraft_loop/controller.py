"""The governed loop (Phase 2).

An event-sourced state machine that drives a Brief: WORKING (agent turn) ->
VERIFYING (real tests + acceptance grading) -> auto-review. If the verdict is
clean it's DONE; otherwise the Turn Assembler produces feedback and the loop
iterates. Hard stops (max_iterations, budget) route to NEEDS_HUMAN. Reusing the
Phase-1 verification/measurement, so the loop-level AAR falls out of the log.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fieldcraft_aar.effectiveness import BehavioralGrader, compute_effectiveness

from . import feedback as fb
from .models import Brief, State
from .progressive_adapter import ProgressiveMockAdapter
from .store import EventStore


class Controller:
    def __init__(self, store: EventStore, adapter=None, grader=None, reviewer=None):
        from .review import AutoReviewer
        self.store = store
        self.adapter = adapter or ProgressiveMockAdapter()
        self.grader = grader or BehavioralGrader()
        self.reviewer = reviewer or AutoReviewer()

    def run(self, brief: Brief, work_root: Path) -> dict:
        task_dir = Path(brief.task_dir).resolve()
        criteria = json.loads((task_dir / "criteria.json").read_text())
        workdir = self._init_workdir(task_dir, work_root, brief.brief_id)

        bid = brief.brief_id
        self.store.append(bid, 0, State.DRAFT, "created", {"goal": brief.goal})
        self.store.append(bid, 0, State.READY, "ready", {})

        last_feedback = ""
        total_cost = 0.0
        trajectory: list[float] = []
        it = 0

        while it < brief.max_iterations:
            it += 1

            # --- WORKING: one agent turn
            self.store.append(bid, it, State.WORKING, "turn_start", {"feedback": last_feedback})
            trace = self.adapter.turn(task_dir, workdir, last_feedback, it)
            turn_cost = round(sum(t.cost_usd for t in trace.turns), 4)
            total_cost = round(total_cost + turn_cost, 4)
            self.store.append(bid, it, State.WORKING, "turn_done",
                              {"cost_usd": turn_cost, "note": trace.turns[-1].note}, cost=turn_cost)

            if total_cost > brief.budget_usd:
                self.store.append(bid, it, State.NEEDS_HUMAN, "budget_exceeded",
                                  {"total_cost_usd": total_cost, "budget_usd": brief.budget_usd})
                return self._finish(brief, State.NEEDS_HUMAN, trajectory, total_cost, it)

            # --- VERIFYING: real tests + acceptance grading (Phase-1 reuse)
            self.store.append(bid, it, State.VERIFYING, "verify_start", {})
            eff = compute_effectiveness(workdir, criteria, trace.diff, self.grader)
            trajectory.append(eff.score)
            self.store.append(bid, it, State.VERIFYING, "verdict", {
                "score": eff.score,
                "tests": f"{eff.tests_passed}/{eff.tests_total}",
                "criteria_met": eff.criteria_met, "criteria_total": len(eff.criteria),
                "criteria": [{"id": c.id, "verdict": c.verdict, "evidence": c.rationale}
                             for c in eff.criteria],
            })

            # --- REVIEW: the reviewer (auto or human) decides
            decision = self.reviewer.review(it, trace.diff, eff)
            if decision.comment:
                self.store.append(bid, it, State.AWAITING_REVIEW, "human_comment",
                                  {"by": decision.by, "comment": decision.comment})
            if decision.kind == "approve":
                self.store.append(bid, it, State.DONE, "approved",
                                  {"by": decision.by, "score": eff.score})
                return self._finish(brief, State.DONE, trajectory, total_cost, it, decision.by)
            if decision.kind == "reject":
                self.store.append(bid, it, State.NEEDS_HUMAN, "rejected", {"by": decision.by})
                return self._finish(brief, State.NEEDS_HUMAN, trajectory, total_cost, it, decision.by)

            last_feedback = fb.render(decision.directives)
            self.store.append(bid, it, State.CHANGES_REQUESTED, "changes_requested",
                              {"by": decision.by,
                               "directives": [d.__dict__ for d in decision.directives]})

        self.store.append(bid, it, State.NEEDS_HUMAN, "max_iterations",
                          {"max_iterations": brief.max_iterations})
        return self._finish(brief, State.NEEDS_HUMAN, trajectory, total_cost, it)

    # ------------------------------------------------------------------
    def _init_workdir(self, task_dir: Path, work_root: Path, brief_id: str) -> Path:
        wd = work_root / brief_id
        if wd.exists():
            shutil.rmtree(wd)
        wd.mkdir(parents=True)
        for f in ("redact.py", "test_redact.py"):
            shutil.copy2(task_dir / f, wd / f)
        return wd

    def _finish(self, brief: Brief, final_state: State, trajectory: list[float],
                total_cost: float, iterations: int, approved_by: str | None = None) -> dict:
        converged_at = next(
            (i + 1 for i, s in enumerate(trajectory) if s >= 0.999), None)
        rework = sum(1 for i in range(1, len(trajectory)) if trajectory[i] < trajectory[i - 1])
        return {
            "brief": brief.brief_id,
            "final_state": final_state.value,
            "approved_by": approved_by,
            "iterations": iterations,
            "total_cost_usd": total_cost,
            "turns_to_converge": converged_at,
            "rework_turns": rework,
            "effectiveness_trajectory": trajectory,
            "final_effectiveness": trajectory[-1] if trajectory else 0.0,
        }
