"""The reviewer — the human-in-the-loop seam.

After verification, a Reviewer decides what happens: approve (done), request
changes (with directives that steer the next turn), or reject. `AutoReviewer`
approves on a clean verdict and otherwise loops on verifier-generated feedback.
`HumanReviewer` pauses the loop, shows the diff and the per-criterion verdict,
and takes the reviewer's decision — free-text comments are classified by the
Turn Assembler into next-turn directives, exactly like the automated path.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import feedback as fb


@dataclass
class ReviewDecision:
    kind: str                       # approve | changes | reject
    directives: list = field(default_factory=list)
    by: str = "auto"
    comment: str = ""


class AutoReviewer:
    def review(self, turn: int, diff: str, eff) -> ReviewDecision:
        if eff.all_tests_pass and eff.criteria_met == len(eff.criteria):
            return ReviewDecision("approve", by="auto")
        return ReviewDecision("changes", directives=fb.assemble_feedback(eff), by="auto")


class HumanReviewer:
    def review(self, turn: int, diff: str, eff) -> ReviewDecision:
        self._render(turn, diff, eff)
        choice = self._ask(
            "Review — [a]pprove / [c]omment / [s]kip (use auto-feedback) / [r]eject: ")
        if choice.startswith("a"):
            return ReviewDecision("approve", by="human")
        if choice.startswith("r"):
            return ReviewDecision("reject", by="human")
        if choice.startswith("c"):
            comment = self._ask("  your comment: ")
            if comment:
                return ReviewDecision(
                    "changes", directives=fb.classify_comment(comment, eff.criteria),
                    by="human", comment=comment)
        # skip / empty comment -> fall back to automated feedback
        return ReviewDecision("changes", directives=fb.assemble_feedback(eff), by="auto")

    @staticmethod
    def _ask(prompt: str) -> str:
        try:
            return input(prompt).strip().lower() if "[" in prompt else input(prompt).strip()
        except EOFError:
            return ""

    @staticmethod
    def _render(turn: int, diff: str, eff) -> None:
        print(f"\n----- REVIEW · iteration {turn} -----")
        print("diff:")
        print("\n".join("    " + ln for ln in (diff or "(no diff)").splitlines()))
        print(f"verdict: score={eff.score}  tests={eff.tests_passed}/{eff.tests_total}  "
              f"criteria={eff.criteria_met}/{len(eff.criteria)}")
        for c in eff.criteria:
            mark = "PASS" if c.verdict == "met" else "FAIL"
            print(f"    {c.id} {mark} — {c.rationale}")
