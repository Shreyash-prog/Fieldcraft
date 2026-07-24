"""Web reviewer: the human-in-the-loop seam for a browser.

Instead of blocking on stdin like HumanReviewer, it publishes the pending review
(diff + verdict) to the run's shared state and blocks on a queue until the API
delivers the browser's decision. Same ReviewDecision contract as the terminal
reviewer, so the controller is unchanged.
"""
from __future__ import annotations

from fieldcraft_loop import feedback as fb
from fieldcraft_loop.review import ReviewDecision


class WebReviewer:
    def __init__(self, run):
        self.run = run

    def review(self, turn: int, diff: str, eff) -> ReviewDecision:
        self.run.pending = {
            "turn": turn,
            "diff": diff,
            "score": eff.score,
            "tests": f"{eff.tests_passed}/{eff.tests_total}",
            "criteria": [{"id": c.id, "verdict": c.verdict, "evidence": c.rationale}
                         for c in eff.criteria],
        }
        self.run.status = "awaiting_review"
        decision = self.run.queue.get()            # blocks until API delivers it
        self.run.pending = None
        self.run.status = "running"

        kind = decision.get("kind")
        if kind == "approve":
            return ReviewDecision("approve", by="human")
        if kind == "reject":
            return ReviewDecision("reject", by="human")
        comment = (decision.get("comment") or "").strip()
        if comment:
            return ReviewDecision("changes",
                                  directives=fb.classify_comment(comment, eff.criteria),
                                  by="human", comment=comment)
        return ReviewDecision("changes", directives=fb.assemble_feedback(eff), by="auto")
