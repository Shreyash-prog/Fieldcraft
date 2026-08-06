"""The three-mode comparison — the same task, run three ways, measured.

What this is, exactly
---------------------
Three real engine runs over one **bundled, scripted** task. Every run goes
through the same governed loop, writes the same event log, and has its
effectiveness measured by actually executing the task's test suite each turn.
The measurement is real. The *agent* is a scripted mock and the *human* is
simulated deterministically — this demonstrates a mechanism, it is not a
benchmark of a live model. Nothing here touches a connected repo or a live
provider (that is Phase B).

The three modes
---------------
1. ``hitl_no_comments`` — review=human, blind adapter. The simulated reviewer
   approves when the verdict is clean and otherwise asks for changes **without
   contributing any task knowledge**. A rubber stamp.
2. ``hitl_comments`` — review=human, guided adapter. The reviewer knows the
   task's trap and says so, so the agent has it *before the first attempt*.
   This is the existing Field-Guide-guided mechanism, surfaced as comment
   quality.
3. ``autonomous`` — review=auto, blind adapter. No human turn at all; the loop
   feeds back its own verdict.

The honest result this is built to show
---------------------------------------
Modes 1 and 3 are both **unsteered** and land in the same place: a reviewer who
adds no information adds no value. Only mode 2 improves, and it improves
*efficiency*, not the outcome — all three converge to the same effectiveness,
mode 2 just gets there in fewer turns for less money.

Do not "fix" modes 1 and 3 into looking different. Their equality is the finding.

Where mode 2's advantage actually comes from
--------------------------------------------
The steering knowledge reaches the agent as **context available before turn 1**
(the compiled Field Guide for the task), which is what a reviewer who already
knows the trap contributes. It is recorded on the run's timeline as the
reviewer's steering brief so a viewer can read exactly what was supplied. A
review comment submitted *after* turn 1 cannot save turn 1 — which is precisely
why mode 1 cannot beat mode 3.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from fieldcraft_measure.metrics import efficiency_captured, operator_quality

from .models import State
from .progressive_adapter import ProgressiveMockAdapter

# Best-known path for these tasks: one turn, if you already know the trap. Used
# as the efficiency reference so "efficiency captured" means something.
REFERENCE_COST = round(ProgressiveMockAdapter.COST_PER_TURN, 4)

# What a reviewer with nothing to add says. Deliberately carries no task
# knowledge — it must not name a criterion, or it would steer by accident.
NO_STEER_COMMENT = "Not there yet — please keep working."

MAX_REVIEW_TURNS = 12          # a guard on the simulated-review loop, never hit


@dataclass(frozen=True)
class Mode:
    key: str
    label: str
    adapter: str
    review: str
    steered: bool
    blurb: str


MODES: tuple[Mode, ...] = (
    Mode(key="hitl_no_comments",
         label="Human in the loop · reviews only",
         adapter="mock", review="human", steered=False,
         blurb="A reviewer approves the work but gives no steering comment."),
    Mode(key="hitl_comments",
         label="Human in the loop · reviews + comments",
         adapter="guided", review="human", steered=True,
         blurb="A reviewer who knows the trap says so before the first attempt."),
    Mode(key="autonomous",
         label="Autonomous · no human turn",
         adapter="mock", review="auto", steered=False,
         blurb="No human at all — the loop feeds back its own verdict."),
)
MODE_KEYS = tuple(m.key for m in MODES)


def steering_brief(task_dir: str | Path) -> str:
    """The trap knowledge a well-informed reviewer would hand over, taken from
    the task's compiled Field Guide. Empty string if the guide cannot be built —
    in which case mode 2 simply behaves like mode 1, which is honest."""
    try:
        from fieldcraft_guide.bootstrap import bootstrap
        from fieldcraft_guide.compile import compile_context
        return compile_context(bootstrap(str(task_dir))).strip()
    except Exception:
        return ""


def _simulate_reviews(engine, bid: str, mode: Mode, comment: str) -> dict:
    """Drive a human-review run to completion with a deterministic reviewer.

    Clean verdict -> approve. Otherwise -> request changes, carrying `comment`.
    This is the simulated human; it is labelled as such everywhere it surfaces.
    """
    from .engine import TERMINAL
    r = engine.advance(bid)
    for _ in range(MAX_REVIEW_TURNS):
        if not r or r["status"] != "awaiting_review":
            break
        verdict = r.get("last_verdict") or {}
        if float(verdict.get("score", 0.0)) >= 0.999:
            r = engine.submit_review(bid, "approve", "")
            break
        r = engine.submit_review(bid, "changes", comment)
        if r and r["status"] not in TERMINAL:
            r = engine.advance(bid)
    return engine.get(bid)


def run_mode(engine, mode: Mode, task_dir: str | Path, task_name: str,
             user_id: str, *, max_iterations: int = 5, budget: float = 2.0,
             extra_config: dict | None = None) -> dict:
    """Run one mode end to end and return its measured result."""
    cfg = {"task": task_name, "adapter": mode.adapter, "grader": "behavioral",
           "review": mode.review, "max_iterations": max_iterations, "budget": budget,
           "goal": f"[{mode.key}] {task_name} — scripted three-mode comparison",
           "comparison_mode": mode.key, **(extra_config or {})}
    bid = engine.create(cfg, str(task_dir), user_id)

    comment = ""
    if mode.steered:
        # Record what the reviewer contributed, on the run's own timeline, so the
        # drill-in shows the steering rather than asking anyone to take it on faith.
        comment = steering_brief(task_dir)
        if comment:
            engine.events.append(bid, 0, State.READY, "human_comment", {
                "by": "simulated reviewer",
                "comment": comment,
                "note": ("steering brief — supplied as context before turn 1 "
                         "(simulated human, scripted comparison)")})

    if mode.review == "auto":
        engine.advance(bid)
    else:
        _simulate_reviews(engine, bid, mode, comment or NO_STEER_COMMENT)

    r = engine.get(bid)
    return measure(engine, r, mode)


def measure(engine, r: dict, mode: Mode) -> dict:
    """AAR + the measurement-layer efficiency metrics for one finished run."""
    aar = engine.aar(r)
    iters = int(aar["iterations"] or 0)
    cost = float(aar["total_cost_usd"] or 0.0)
    rework = int(aar["rework_turns"] or 0)
    ec = efficiency_captured(cost, REFERENCE_COST)
    return {
        "mode": mode.key, "label": mode.label, "blurb": mode.blurb,
        "steered": mode.steered, "brief_id": r["brief_id"],
        "provider": "scripted",            # never a live model in this phase
        "simulated_human": mode.review == "human",
        "iterations": iters,
        "cost_usd": round(cost, 4),
        "effectiveness": aar["final_effectiveness"],
        "turns_to_converge": aar["turns_to_converge"],
        "rework_turns": rework,
        "efficiency_captured": ec,
        "operator_quality": operator_quality(ec, rework, iters),
        "final_state": aar["final_state"],
        "trajectory": aar["effectiveness_trajectory"],
        "at": time.time(),
    }


def run_comparison(engine, task_dir: str | Path, task_name: str, user_id: str,
                   on_progress=None, **kw) -> list[dict]:
    """Run all three modes **sequentially** and return their results in order.

    `on_progress(mode_key, status, result)` is called as each mode starts and
    finishes so a caller can stream it. Sequential on purpose: the modes share
    the machine, and a comparison whose timings depend on scheduling is not a
    comparison.
    """
    results: list[dict] = []
    for mode in MODES:
        if on_progress:
            on_progress(mode.key, "running", None)
        res = run_mode(engine, mode, task_dir, task_name, user_id, **kw)
        results.append(res)
        if on_progress:
            on_progress(mode.key, "done", res)
    return results


def deltas(results: list[dict]) -> dict:
    """The comparison's actual claims, computed rather than asserted."""
    by = {r["mode"]: r for r in results}
    hitl, comm, auto = (by.get("hitl_no_comments"), by.get("hitl_comments"),
                        by.get("autonomous"))
    if not (hitl and comm and auto):
        return {}
    unsteered_equal = (hitl["iterations"] == auto["iterations"]
                       and hitl["cost_usd"] == auto["cost_usd"])
    return {
        "unsteered_modes_equivalent": unsteered_equal,
        "steering_saved_iterations": hitl["iterations"] - comm["iterations"],
        "steering_saved_cost": round(hitl["cost_usd"] - comm["cost_usd"], 4),
        "effectiveness_equal": len({r["effectiveness"] for r in results}) == 1,
        "best_mode": min(results, key=lambda r: (r["iterations"], r["cost_usd"]))["mode"],
    }
