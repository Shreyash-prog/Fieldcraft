"""Turn Assembler (Phase 2, lite). Converts a verification verdict into
classified, slotted next-turn instructions rather than free text. In Phase 4
this is where *human* comments get classified the same way.
"""
from __future__ import annotations

from .models import Directive


def assemble_feedback(effectiveness) -> list[Directive]:
    directives: list[Directive] = []
    for c in effectiveness.criteria:
        if c.verdict != "met":
            directives.append(Directive(
                type="criterion_fix", ref=c.id,
                instruction=f"{c.text}: currently '{c.verdict}'. Make it pass. ({c.rationale})",
            ))
    if not effectiveness.all_tests_pass:
        failing = getattr(effectiveness, "failing_tests", None)
        if failing:
            directives.append(Directive(
                type="global_constraint", ref="tests",
                instruction=("These tests still fail: " + ", ".join(failing[:6])
                             + ". Fix the implementation (do not edit the tests)."),
            ))
        else:
            directives.append(Directive(
                type="global_constraint", ref="tests",
                instruction=(f"{effectiveness.tests_passed}/{effectiveness.tests_total} "
                             f"tests pass; all must pass."),
            ))
    return directives


def render(directives: list[Directive]) -> str:
    return "\n".join(f"- [{d.type}:{d.ref}] {d.instruction}" for d in directives)


def classify_comment(text: str, verdicts) -> list[Directive]:
    """Turn Assembler for *human* input: classify a free-text review comment into
    next-turn directives. A comment naming a criterion (by id or its key noun)
    becomes a criterion_override; anything else becomes a global_constraint."""
    low = text.lower()
    directives: list[Directive] = []
    for v in verdicts:
        key = v.text.split()[0].lower().rstrip("s") if v.text else ""
        if v.id.lower() in low or (key and key in low):
            directives.append(Directive(
                type="criterion_override", ref=v.id,
                instruction=f"Reviewer ({v.text}): {text.strip()}"))
    if not directives:
        directives.append(Directive(
            type="global_constraint", ref="reviewer",
            instruction=f"Reviewer: {text.strip()}"))
    return directives
