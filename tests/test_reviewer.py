"""Reviewer seam — AutoReviewer decisions and HumanReviewer prompt handling."""
from fieldcraft_loop.review import AutoReviewer, HumanReviewer, ReviewDecision
from fieldcraft_aar.models import Effectiveness, CriterionVerdict


def _eff(all_pass, criteria):
    return Effectiveness(tests_total=4, tests_passed=4 if all_pass else 2,
                         all_tests_pass=all_pass, criteria=criteria, score=1.0 if all_pass else 0.5)

def test_auto_approves_clean():
    c = [CriterionVerdict(id="AC1", text="x", verdict="met", rationale="")]
    d = AutoReviewer().review(1, "diff", _eff(True, c))
    assert d.kind == "approve" and d.by == "auto"

def test_auto_requests_changes():
    c = [CriterionVerdict(id="AC1", text="x", verdict="unmet", rationale="")]
    d = AutoReviewer().review(1, "diff", _eff(False, c))
    assert d.kind == "changes" and d.directives

def test_human_approve(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "a")
    c = [CriterionVerdict(id="AC1", text="x", verdict="met", rationale="")]
    d = HumanReviewer().review(1, "diff", _eff(True, c))
    assert d.kind == "approve" and d.by == "human"

def test_human_comment(monkeypatch):
    answers = iter(["c", "fix the phones"])
    monkeypatch.setattr("builtins.input", lambda *_: next(answers))
    c = [CriterionVerdict(id="AC2", text="Phones masked", verdict="unmet", rationale="")]
    d = HumanReviewer().review(1, "diff", _eff(False, c))
    assert d.kind == "changes" and d.by == "human" and d.comment == "fix the phones"
