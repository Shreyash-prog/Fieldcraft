"""Resumable engine — a step-based reformulation of the loop.

Instead of one blocking run() that holds state in a thread, the engine persists
all state after each step. `advance()` runs turns until the run completes or
needs human review, then returns; `submit_review()` records the decision and
sets the run runnable again. Because state lives entirely in SQLite (+ the
workdir on disk), a run paused for review survives a process restart: a fresh
Engine on the same data dir resumes it. Adapters/graders are rebuilt from the
stored config each step, so nothing run-specific is held in memory between steps.
"""
from __future__ import annotations

import json
import shutil
import types
import uuid
from pathlib import Path

from fieldcraft_aar.effectiveness import BehavioralGrader, compute_effectiveness

from . import feedback as fb
from .models import State
from .run_store import RunStore
from .store import EventStore

TERMINAL = {"done", "needs_human", "error"}


class Engine:
    def __init__(self, data_dir: str | Path):
        self.dir = Path(data_dir)
        (self.dir / "work").mkdir(parents=True, exist_ok=True)
        self.events = EventStore(self.dir / "events.db")
        self.runs = RunStore(self.dir / "runs.db")

    # -- lifecycle ---------------------------------------------------------
    def create(self, config: dict, task_dir: str) -> str:
        from .task import Task
        bid = "BRIEF-" + uuid.uuid4().hex[:6]
        wd = self.dir / "work" / bid
        kind = "single"
        try:
            kind = json.loads((Path(task_dir) / "task.json").read_text()).get("kind", "single")
        except Exception:
            pass
        if kind == "repo":
            from .repo_task import RepoTask, copy_repo
            rt = RepoTask.load(task_dir)
            copy_repo(rt, wd)
            config = {**config, "task_dir": str(task_dir), "kind": "repo",
                      "test_command": rt.test_command}
        else:
            task = Task.load(task_dir)
            if wd.exists():
                shutil.rmtree(wd)
            wd.mkdir(parents=True)
            for f in (task.target_file, task.test_file):
                shutil.copy2(Path(task_dir) / f, wd / f)
            config = {**config, "task_dir": str(task_dir), "kind": "single",
                      "module": task.module, "criteria_file": task.criteria_file}
        self.runs.create(bid, config, str(wd))
        self.events.append(bid, 0, State.DRAFT, "created", {"goal": config.get("goal", "")})
        self.events.append(bid, 0, State.READY, "ready", {})
        return bid

    def advance(self, bid: str) -> dict | None:
        """Run turns until the run finishes or needs a human. Idempotent-safe to
        call on a running/ready run; a no-op on terminal or awaiting-review runs."""
        r = self.runs.get(bid)
        if not r or r["status"] in TERMINAL or r["status"] == "awaiting_review":
            return r
        cfg = r["config"]
        task_dir = Path(cfg["task_dir"])
        wd = Path(r["workdir"])
        is_repo = cfg.get("kind") == "repo"
        module = cfg.get("module", "redact")
        criteria = ([] if is_repo else
                    json.loads((task_dir / cfg.get("criteria_file", "criteria.json")).read_text()))
        adapter, grader = self._adapter(cfg), self._grader(cfg)
        it, total, traj = r["iteration"], r["total_cost"], list(r["trajectory"])
        last_fb = r["last_feedback"]
        maxit, budget = int(cfg.get("max_iterations", 5)), float(cfg.get("budget", 2.0))
        self.runs.update(bid, status="running")

        while True:
            it += 1
            self.events.append(bid, it, State.WORKING, "turn_start", {"feedback": last_fb})
            pre = None
            if cfg.get("policy"):
                from .repo_task import snapshot as _snap
                pre = _snap(wd)
            trace = adapter.turn(task_dir, wd, last_fb, it)

            if cfg.get("policy"):
                from fieldcraft_gov.policy import Policy
                from fieldcraft_gov.enforce import enforce as _enforce
                from .repo_task import snapshot as _snap, multi_file_diff as _mfd
                pol = Policy.from_dict(cfg["policy"])
                decision, reverted = _enforce(pol, trace.diff, pre or {}, wd,
                                              command=cfg.get("test_command"))
                if reverted:
                    trace.diff = _mfd(pre or {}, _snap(wd))
                self.events.append(bid, it, State.VERIFYING, "policy", {
                    "decision": decision.summary(), "reverted": reverted,
                    "violations": [{"kind": v.kind, "ref": v.ref, "action": v.action,
                                    "reason": v.reason} for v in decision.violations]})
                if decision.blocked or (decision.requires_approval and cfg.get("review") == "auto"):
                    self.events.append(bid, it, State.NEEDS_HUMAN, "policy_stop",
                                       {"reason": decision.summary()})
                    return self._terminal(bid, "needs_human", it, total, traj, None)
            tc = round(sum(t.cost_usd for t in trace.turns), 4)
            total = round(total + tc, 4)
            self.events.append(bid, it, State.WORKING, "turn_done",
                               {"cost_usd": tc, "note": trace.turns[-1].note}, cost=tc)
            self.runs.update(bid, iteration=it, total_cost=total, last_diff=trace.diff)

            if total > budget:
                self.events.append(bid, it, State.NEEDS_HUMAN, "budget_exceeded", {"total_cost_usd": total})
                return self._terminal(bid, "needs_human", it, total, traj, None)

            if is_repo:
                from .repo_task import compute_repo_effectiveness
                eff = compute_repo_effectiveness(wd, cfg["test_command"])
            else:
                eff = compute_effectiveness(wd, criteria, trace.diff, grader, module)
            traj = traj + [eff.score]
            verdict = {"score": eff.score, "tests": f"{eff.tests_passed}/{eff.tests_total}",
                       "criteria_met": eff.criteria_met, "criteria_total": len(eff.criteria),
                       "failing_tests": list(getattr(eff, "failing_tests", [])),
                       "criteria": [{"id": c.id, "verdict": c.verdict, "evidence": c.rationale}
                                    for c in eff.criteria]}
            self.events.append(bid, it, State.VERIFYING, "verdict", verdict)
            self.runs.update(bid, trajectory=traj, last_verdict=verdict)

            clean = eff.all_tests_pass and eff.criteria_met == len(eff.criteria)
            if cfg.get("review", "human") == "auto":
                if clean:
                    self.events.append(bid, it, State.DONE, "approved", {"by": "auto", "score": eff.score})
                    return self._terminal(bid, "done", it, total, traj, "auto")
                directives = fb.assemble_feedback(eff)
                last_fb = fb.render(directives)
                self.events.append(bid, it, State.CHANGES_REQUESTED, "changes_requested",
                                   {"by": "auto", "directives": [d.__dict__ for d in directives]})
                self.runs.update(bid, last_feedback=last_fb)
                if it >= maxit:
                    self.events.append(bid, it, State.NEEDS_HUMAN, "max_iterations", {})
                    return self._terminal(bid, "needs_human", it, total, traj, None)
                continue
            # human review: pause here; state is fully persisted
            self.runs.update(bid, status="awaiting_review")
            return self.runs.get(bid)

    def submit_review(self, bid: str, kind: str, comment: str = "") -> dict | None:
        """Record a human decision. Returns the run; if it became runnable
        ('changes'), the caller drives advance() (possibly in the background)."""
        r = self.runs.get(bid)
        if not r or r["status"] != "awaiting_review":
            return r
        it, cfg = r["iteration"], r["config"]
        if comment:
            self.events.append(bid, it, State.AWAITING_REVIEW, "human_comment",
                               {"by": "human", "comment": comment})
        if kind == "approve":
            self.events.append(bid, it, State.DONE, "approved",
                               {"by": "human", "score": r["last_verdict"]["score"]})
            return self._terminal(bid, "done", it, r["total_cost"], r["trajectory"], "human")
        if kind == "reject":
            self.events.append(bid, it, State.NEEDS_HUMAN, "rejected", {"by": "human"})
            return self._terminal(bid, "needs_human", it, r["total_cost"], r["trajectory"], "human")

        # changes: classify the comment into next-turn directives
        if cfg.get("kind") == "repo":
            crits = []          # repo tasks have no per-criterion probes
        else:
            crit_texts = {c["id"]: c["text"] for c in json.loads(
                (Path(cfg["task_dir"]) / cfg.get("criteria_file", "criteria.json")).read_text())}
            crits = [types.SimpleNamespace(id=c["id"], text=crit_texts.get(c["id"], c["id"]),
                                           verdict=c["verdict"]) for c in r["last_verdict"]["criteria"]]
        directives = fb.classify_comment(comment, crits) if comment else []
        last_fb = fb.render(directives) if directives else r["last_feedback"]
        self.events.append(bid, it, State.CHANGES_REQUESTED, "changes_requested",
                           {"by": "human", "directives": [d.__dict__ for d in directives]})
        if it >= int(cfg.get("max_iterations", 5)):
            self.events.append(bid, it, State.NEEDS_HUMAN, "max_iterations", {})
            return self._terminal(bid, "needs_human", it, r["total_cost"], r["trajectory"], None)
        self.runs.update(bid, status="running", last_feedback=last_fb)
        return self.runs.get(bid)

    # -- views -------------------------------------------------------------
    def get(self, bid): return self.runs.get(bid)

    def get_events(self, bid): return self.events.events(bid)

    def pending(self, bid) -> dict | None:
        r = self.runs.get(bid)
        if not r or r["status"] != "awaiting_review" or not r["last_verdict"]:
            return None
        v = r["last_verdict"]
        return {"turn": r["iteration"], "diff": r["last_diff"], "score": v["score"],
                "tests": v["tests"], "criteria": v["criteria"]}

    def aar(self, r: dict) -> dict:
        traj = r["trajectory"]
        conv = next((i + 1 for i, s in enumerate(traj) if s >= 0.999), None)
        rework = sum(1 for i in range(1, len(traj)) if traj[i] < traj[i - 1])
        return {"brief": r["brief_id"], "final_state": r["status"], "approved_by": r["approved_by"],
                "iterations": r["iteration"], "total_cost_usd": r["total_cost"],
                "turns_to_converge": conv, "rework_turns": rework,
                "effectiveness_trajectory": traj, "final_effectiveness": traj[-1] if traj else 0.0}

    def runnable_after_restart(self) -> list[str]:
        """Runs left mid-turn by a restart can be safely re-advanced (idempotent)."""
        return self.runs.list_status("running") + self.runs.list_status("ready")

    # -- internals ---------------------------------------------------------
    def _terminal(self, bid, status, it, total, traj, approved_by):
        self.runs.update(bid, status=status, approved_by=approved_by,
                         iteration=it, total_cost=total, trajectory=traj)
        return self.runs.get(bid)

    def _grader(self, cfg):
        if cfg.get("grader") == "tooluse":
            from fieldcraft_aar.grader_tooluse import ClaudeToolUseGrader
            return ClaudeToolUseGrader()
        return BehavioralGrader()

    def _adapter(self, cfg):
        name = cfg.get("adapter", "mock")
        if cfg.get("kind") == "repo":
            from .repo_adapters import RepoMockAdapter, RepoGuidedAdapter, RepoLiveAdapter
            if name == "claude":
                return RepoLiveAdapter(guide_context=self._guide(cfg))
            if name == "guided":
                return RepoGuidedAdapter(self._guide(cfg))
            return RepoMockAdapter()
        if name == "claude":
            from .live_adapter import ClaudeCodeLoopAdapter
            return ClaudeCodeLoopAdapter(guide_context=self._guide(cfg))
        if name == "guided":
            from .guided_adapter import GuidedMockAdapter
            return GuidedMockAdapter(self._guide(cfg))
        from .progressive_adapter import ProgressiveMockAdapter
        return ProgressiveMockAdapter()

    @staticmethod
    def _guide(cfg) -> str:
        try:
            from fieldcraft_guide.bootstrap import bootstrap
            from fieldcraft_guide.compile import compile_context
            return compile_context(bootstrap(cfg["task_dir"]))
        except Exception:
            return ""
