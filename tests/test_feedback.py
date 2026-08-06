"""Turn Assembler — verdict/comment -> classified directives."""
import types
from fieldcraft_loop import feedback as fb
from fieldcraft_aar.models import Effectiveness, CriterionVerdict


def _eff(criteria, all_pass=False, failing=None):
    return Effectiveness(tests_total=4, tests_passed=2, all_tests_pass=all_pass,
                         criteria=criteria, score=0.5, failing_tests=failing or [])

def test_assemble_from_failing_criteria():
    c = [CriterionVerdict(id="AC2", text="Phones masked", verdict="unmet", rationale="left unmasked")]
    ds = fb.assemble_feedback(_eff(c))
    assert any(d.ref == "AC2" and d.type == "criterion_fix" for d in ds)

def test_assemble_from_failing_tests_repo():
    ds = fb.assemble_feedback(_eff([], failing=["tests/test_casing.py::test_snake_camel"]))
    assert any("casing" in d.instruction for d in ds)

def test_classify_comment_maps_to_criterion():
    v = [types.SimpleNamespace(id="AC2", text="Phones masked", verdict="unmet")]
    ds = fb.classify_comment("the phone numbers are still wrong", v)
    assert ds and ds[0].ref == "AC2"

def test_classify_comment_falls_back_to_global():
    v = [types.SimpleNamespace(id="AC1", text="Emails masked", verdict="met")]
    ds = fb.classify_comment("please add a docstring", v)
    assert ds[0].ref == "reviewer" and ds[0].type == "global_constraint"
