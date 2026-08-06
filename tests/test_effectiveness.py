"""Behavioral grader probes + module parameter."""
import json
from pathlib import Path
from fieldcraft_aar.effectiveness import BehavioralGrader, compute_effectiveness, run_pytest


def _crit():
    return [{"id": "AC1", "text": "Emails masked",
             "probe": {"func": "redact_pii", "args": ["ada@example.com"], "contains": "[EMAIL]"}}]

def test_probe_contains(tmp_path):
    (tmp_path / "redact.py").write_text(
        "import re\ndef redact_pii(t):\n return re.sub(r'\\S+@\\S+','[EMAIL]',t)\n")
    v = BehavioralGrader().grade(tmp_path, _crit(), "", "redact")
    assert v[0].verdict == "met"

def test_probe_raises(tmp_path):
    (tmp_path / "m.py").write_text("def f(x):\n if x<1: raise ValueError('n')\n return x\n")
    crit = [{"id": "R1", "text": "raises", "probe": {"func": "f", "args": [0], "raises": "ValueError"}}]
    v = BehavioralGrader().grade(tmp_path, crit, "", "m")
    assert v[0].verdict == "met"

def test_probe_idempotent(tmp_path):
    (tmp_path / "m.py").write_text("def f(t): return t.strip()\n")
    crit = [{"id": "I1", "text": "idem", "probe": {"func": "f", "args": ["  x  "], "idempotent": True}}]
    v = BehavioralGrader().grade(tmp_path, crit, "", "m")
    assert v[0].verdict == "met"
