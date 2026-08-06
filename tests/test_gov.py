"""Governance — policy engine, enforcement, scoped credentials, engine integration."""
import time, tempfile
from pathlib import Path
from fieldcraft_gov.policy import Policy, PolicyEngine
from fieldcraft_gov.enforce import parse_diff, enforce
from fieldcraft_gov.credentials import CredentialBroker
from fieldcraft_gov.report import governance_summary
from fieldcraft_loop.engine import Engine
from fieldcraft_loop.repo_task import apply_patch, snapshot, multi_file_diff
from fieldcraft_aar.models import RunTrace, Turn
from tests.conftest import REPO_TASK


# --- policy engine --------------------------------------------------------
def test_protected_path_reverts():
    pol = Policy(editable_paths=["**"], protected_paths=["tests/"])
    d = PolicyEngine(pol).evaluate(["tests/test_x.py", "src/a.py"], {}, None)
    assert "tests/test_x.py" in d.revert_paths and "src/a.py" not in d.revert_paths

def test_editable_allowlist_reverts_outside():
    pol = Policy(editable_paths=["src/**"])
    d = PolicyEngine(pol).evaluate(["src/a.py", "infra/deploy.yml"], {}, None)
    assert d.revert_paths == ["infra/deploy.yml"]

def test_forbidden_content_secret():
    pol = Policy()
    added = {"a.py": ['API_KEY = "AKIA1234567890ABCDEF"']}
    d = PolicyEngine(pol).evaluate(["a.py"], added, None)
    assert "a.py" in d.revert_paths and any(v.kind == "forbidden_content" for v in d.violations)

def test_forbidden_content_eval_and_network():
    pol = Policy()
    d1 = PolicyEngine(pol).evaluate(["a.py"], {"a.py": ["x = eval(user_input)"]}, None)
    d2 = PolicyEngine(pol).evaluate(["b.py"], {"b.py": ["requests.get(url)"]}, None)
    assert d1.revert_paths and d2.revert_paths

def test_command_allowlist_blocks():
    pol = Policy(allowed_commands=[["python", "-m", "pytest", "-q"]])
    d = PolicyEngine(pol).evaluate([], {}, command=["rm", "-rf", "/"])
    assert d.blocked and not d.allowed

def test_max_files_requires_approval():
    pol = Policy(max_files_changed=2)
    d = PolicyEngine(pol).evaluate(["a.py", "b.py", "c.py"], {}, None)
    assert d.requires_approval

def test_clean_change_allowed():
    pol = Policy(editable_paths=["src/**"])
    d = PolicyEngine(pol).evaluate(["src/a.py"], {"src/a.py": ["return 1"]}, None)
    assert d.allowed and not d.violations


# --- enforce (diff parsing + revert) --------------------------------------
def test_parse_diff():
    diff = "--- a/x.py\n+++ b/x.py\n@@\n+new line\n-old\n"
    files, added = parse_diff(diff)
    assert files == ["x.py"] and added["x.py"] == ["new line"]

def test_enforce_reverts_on_disk(tmp_path):
    (tmp_path / "bad.py").write_text('secret = "AKIA1234567890ABCDEF"\n')
    before = {}                                        # file is new -> revert deletes it
    diff = '--- a/bad.py\n+++ b/bad.py\n@@\n+secret = "AKIA1234567890ABCDEF"\n'
    decision, reverted = enforce(Policy(), diff, before, tmp_path)
    assert reverted == ["bad.py"] and not (tmp_path / "bad.py").exists()


# --- scoped credentials ---------------------------------------------------
def test_grant_scope_and_expiry():
    b = CredentialBroker()
    g = b.issue("BRIEF-1", ["repo:read", "tests:run"], ttl_s=100)
    assert b.check(g.grant_id, "tests:run") is True
    assert b.check(g.grant_id, "repo:write") is False           # out of scope
    assert b.check(g.grant_id, "tests:run", now=time.time() + 200) is False  # expired

def test_grant_revoke_and_audit():
    b = CredentialBroker()
    g = b.issue("BRIEF-2", ["repo:read"])
    b.revoke(g.grant_id)
    assert b.check(g.grant_id, "repo:read") is False
    actions = [a["action"] for a in b.audit]
    assert "issue" in actions and "revoke" in actions and "check" in actions

def test_unknown_grant_denied():
    assert CredentialBroker().check("G-nope", "repo:read") is False


# --- engine integration ---------------------------------------------------
class _Violator:
    def turn(self, task_dir, workdir, feedback, turn_index):
        before = snapshot(workdir)
        apply_patch(Path(task_dir) / ".solution", workdir)
        (workdir / "config.py").write_text('API_KEY = "AKIA1234567890ABCDEF"\n')
        return RunTrace(condition="t1", adapter="violator", spec_completeness=0.9,
                        turns=[Turn(cost_usd=0.09, tool_calls=3, event="progress", note="x")],
                        wall_clock_s=1.0, diff=multi_file_diff(before, snapshot(workdir)))

def test_engine_reverts_policy_violation(datadir, monkeypatch):
    e = Engine(datadir)
    monkeypatch.setattr(e, "_adapter", lambda cfg: _Violator())
    b = e.create({"adapter": "mock", "review": "auto",
                  "policy": {"editable_paths": ["textkit/**", "config.py"], "protected_paths": ["tests/"]}},
                 REPO_TASK)
    e.advance(b)
    a = e.aar(e.get(b))
    gov = governance_summary(e.get_events(b))
    assert a["final_state"] == "done"                  # converged on the legit fix
    assert "config.py" in gov["files_reverted"]        # secret reverted
    assert not (Path(e.get(b)["workdir"]) / "config.py").exists()
