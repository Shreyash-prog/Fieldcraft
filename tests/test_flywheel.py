"""Field Guide flywheel — discovery, approval, persistence, self-improvement."""
import shutil
from fieldcraft_guide.flywheel import discover, approve, demo, Proposal
from fieldcraft_guide.bootstrap import bootstrap
from tests.conftest import TASK


def _events_single():
    return [{"type": "verdict", "payload": {"tests": "4/7", "criteria": [
                {"id": "AC2", "verdict": "unmet", "evidence": "contains '[PHONE]': False"}]}},
            {"type": "verdict", "payload": {"tests": "7/7", "criteria": [
                {"id": "AC2", "verdict": "met", "evidence": "ok"}]}}]

def test_discover_single_file():
    props = discover(_events_single(), existing_traps=[])
    assert props and props[0].evidence == "AC2" and "phone" in props[0].text.lower()

def test_discover_repo():
    ev = [{"type": "verdict", "payload": {"tests": "4/8", "criteria": [],
                                          "failing_tests": ["tests/test_casing.py::test_x"]}},
          {"type": "verdict", "payload": {"tests": "8/8", "criteria": [], "failing_tests": []}}]
    props = discover(ev, existing_traps=[])
    assert props and "casing" in props[0].text.lower()

def test_discover_dedup():
    first = discover(_events_single(), existing_traps=[])
    again = discover(_events_single(), existing_traps=[first[0].text])
    assert again == []                                     # already known -> no re-proposal

def test_discover_ignores_unfixed():
    ev = [{"type": "verdict", "payload": {"tests": "4/7", "criteria": [
              {"id": "AC2", "verdict": "unmet", "evidence": "x"}]}},
          {"type": "verdict", "payload": {"tests": "5/7", "criteria": [
              {"id": "AC2", "verdict": "unmet", "evidence": "still"}]}}]
    assert discover(ev, []) == []                          # never fixed -> not a learned trap

def test_approve_persists_and_bootstrap_reads(tmp_path):
    task = tmp_path / "t"; shutil.copytree(TASK, task)
    approve(Proposal(text="phone numbers appear in bare and dashed forms", evidence="AC2"), task)
    assert (task / ".fieldguide" / "learned.md").exists()
    assert any("phone" in t.lower() for t in bootstrap(task).traps)

def test_flywheel_demo_self_improves():
    r = demo(TASK)
    assert r["run1_iterations"] == 2 and r["run2_iterations"] == 1
    assert r["proposals"]                                  # a trap was learned
