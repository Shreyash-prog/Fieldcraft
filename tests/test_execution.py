"""The execution seam (Phase C part 1).

This step adds an interface, not isolation. So the tests check two things: that
the seam selects and reports backends correctly, and — the load-bearing part —
that routing the local path through it changed *nothing*. A refactor of the one
place untrusted code runs is only safe if it is provably a no-op today.
"""
import shutil
import sys

import pytest
from fastapi.testclient import TestClient

from fieldcraft_aar.effectiveness import run_pytest
from fieldcraft_loop import execution
from fieldcraft_loop.execution import (ENV_VAR, ExecutionBackend, ExecutionResult,
                                       LocalSandbox, RemoteMachineBackend,
                                       get_execution_backend)
from fieldcraft_loop.sandbox import run_sandboxed
from fieldcraft_web import server
from tests.conftest import ROOT


# --- selection ---------------------------------------------------------------

def test_the_default_backend_is_the_local_sandbox(monkeypatch):
    monkeypatch.delenv(ENV_VAR, raising=False)
    b = get_execution_backend()
    assert isinstance(b, LocalSandbox)
    assert b.isolation_level == "local-sandbox"


@pytest.mark.parametrize("value", ["local", "LOCAL", " local ", ""])
def test_local_is_selected_however_it_is_spelled(monkeypatch, value):
    monkeypatch.setenv(ENV_VAR, value)
    assert isinstance(get_execution_backend(), LocalSandbox)


def test_remote_is_selected_only_when_explicitly_configured(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "remote")
    b = get_execution_backend()
    assert isinstance(b, RemoteMachineBackend)
    assert b.isolation_level == "remote-machine"


def test_an_unknown_backend_raises_rather_than_downgrading(monkeypatch):
    """A typo in an isolation setting must stop the deployment. Falling back to
    local would silently give an operator less containment than they asked for."""
    monkeypatch.setenv(ENV_VAR, "remotr")
    with pytest.raises(ValueError, match="unknown FC_EXECUTION_BACKEND"):
        get_execution_backend()


def test_the_explicit_argument_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "remote")
    assert isinstance(get_execution_backend("local"), LocalSandbox)


# --- the interface is honest about what it provides --------------------------

def test_neither_backend_claims_isolation_it_does_not_have():
    for b in (LocalSandbox(), RemoteMachineBackend()):
        assert b.filesystem_isolated is False
        assert b.network_isolated is False, (
            f"{b.backend_id} claims network isolation it has not proven")


def test_the_local_backend_says_it_is_not_safe_for_strangers_code():
    note = LocalSandbox().note.lower()
    assert "not filesystem-isolated" in note and "not network-isolated" in note
    assert "untrusted third-party code" in note


def test_describe_carries_the_isolation_claim():
    d = LocalSandbox().describe()
    assert d["backend_id"] == "local-sandbox" and d["isolation_level"] == "local-sandbox"
    assert set(d) == {"backend_id", "isolation_level", "filesystem_isolated",
                      "network_isolated", "note"}


def test_the_backend_is_abstract():
    with pytest.raises(TypeError):
        ExecutionBackend()          # run() has no implementation


# --- the remote stub is inert ------------------------------------------------

def test_remote_run_raises_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError, match="not yet provisioned"):
        RemoteMachineBackend().run([sys.executable, "-c", "pass"], tmp_path, timeout=5)


def test_the_remote_stub_provisions_nothing():
    """Guard against someone adding infrastructure calls to the stub before the
    break-test exists."""
    src = (ROOT / "fieldcraft_loop" / "execution.py").read_text()
    for forbidden in ("requests.", "httpx.", "urllib.request", "subprocess",
                      "api.machines.dev", "FLY_API_TOKEN"):
        assert forbidden not in src, f"execution.py should not reference {forbidden} yet"


def test_the_remote_backend_documents_what_must_be_verified():
    doc = (RemoteMachineBackend.__doc__ or "").lower()
    for expected in ("disposable", "egress", "destroy", "break-test", "no ambient"):
        assert expected in doc, f"the remote backend docstring should mention {expected}"


# --- the local path is unchanged (the load-bearing property) -----------------

def test_local_backend_matches_run_sandboxed_exactly(tmp_path):
    cmd = [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"]
    direct = run_sandboxed(cmd, tmp_path, timeout=30)
    viaseam = LocalSandbox().run(cmd, tmp_path, timeout=30)

    assert viaseam.returncode == direct.returncode == 3
    assert viaseam.stdout == direct.stdout
    assert viaseam.stderr == direct.stderr
    assert viaseam.timed_out == direct.timed_out is False
    assert viaseam.limits == direct.limits
    assert viaseam.output == direct.output


def test_the_seam_preserves_a_timeout_as_a_result_not_an_exception(tmp_path):
    res = LocalSandbox().run([sys.executable, "-c", "import time; time.sleep(60)"],
                             tmp_path, timeout=1)
    assert res.timed_out is True and res.wall_s < 30


def test_the_seam_still_rejects_a_shell_string(tmp_path):
    with pytest.raises(ValueError):
        LocalSandbox().run("echo hi", tmp_path, timeout=5)


def test_the_seam_still_strips_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-appear")
    monkeypatch.setenv("FC_SECRET_KEY", "signing-should-not-appear")
    res = LocalSandbox().run(
        [sys.executable, "-c", "import os,json; print(json.dumps(dict(os.environ)))"],
        tmp_path, timeout=30)
    assert "sk-should-not-appear" not in res.output
    assert "signing-should-not-appear" not in res.output


def test_a_widened_allowlist_cannot_smuggle_a_secret_in(tmp_path, monkeypatch):
    """The new env_allowlist parameter must go through the same secret filter as
    env_extra, or the seam becomes a way around the credential stripping."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-appear")
    res = LocalSandbox().run(
        [sys.executable, "-c", "import os,json; print(json.dumps(dict(os.environ)))"],
        tmp_path, timeout=30,
        env_allowlist=("PATH", "ANTHROPIC_API_KEY"))
    assert "sk-should-not-appear" not in res.output


def test_limits_are_passed_through(tmp_path):
    res = LocalSandbox().run([sys.executable, "-c", "pass"], tmp_path, timeout=30,
                             limits={"cpu_s": 5, "mem_mb": 256})
    assert res.returncode == 0
    assert isinstance(res.limits, tuple)


# --- a real verification still runs through the seam -------------------------

def test_run_pytest_through_the_seam_gives_the_same_verdict(tmp_path):
    """The end-to-end check: a real task's real test suite, run through the
    refactored path, must produce the pass/total it always did."""
    wd = tmp_path / "work"
    wd.mkdir()
    for f in ("redact.py", "test_redact.py"):
        shutil.copy2(ROOT / "sample_task" / f, wd / f)

    passed, total, all_pass = run_pytest(wd)
    assert total > 0, "the seam broke test discovery"
    assert passed >= 0 and passed <= total
    # and the same command through the backend directly agrees on the count
    res = get_execution_backend().run(
        [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider",
         "-o", "addopts=", "."], wd, timeout=60)
    assert f"{total - passed} failed" in res.output or f"{passed} passed" in res.output


def test_repo_task_run_tests_still_works(tmp_path):
    from fieldcraft_loop.repo_task import RepoTask, copy_repo, run_tests
    from tests.conftest import REPO_TASK
    wd = tmp_path / "w"
    copy_repo(RepoTask.load(REPO_TASK), wd)
    passed, total, _ = run_tests(wd, [sys.executable, "-m", "pytest", "-q"])
    assert (passed, total) == (1, 8), "the seam changed the repo-task verdict"


def test_run_pytest_uses_the_configured_backend(tmp_path, monkeypatch):
    """Proof the call site really goes through the seam: point it at the remote
    stub and the NotImplementedError must surface."""
    monkeypatch.setenv(ENV_VAR, "remote")
    wd = tmp_path / "w"
    wd.mkdir()
    (wd / "test_x.py").write_text("def test_ok():\n    assert True\n")
    with pytest.raises(NotImplementedError):
        run_pytest(wd)


# --- surfaced to the operator ------------------------------------------------

def test_healthz_reports_the_active_backend():
    body = TestClient(server.app).get("/healthz").json()
    assert body["execution_backend"] == "local-sandbox"
    iso = body["execution_isolation"]
    assert iso["filesystem_isolated"] is False and iso["network_isolated"] is False
    assert "not" in iso["note"].lower()


def test_healthz_still_reports_sandbox_limits():
    from fieldcraft_loop.sandbox import effective_limits
    body = TestClient(server.app).get("/healthz").json()
    assert body["sandbox_limits"] == list(effective_limits())


def test_hardening_doc_describes_the_seam():
    doc = (ROOT / "HARDENING.md").read_text()
    assert "local-sandbox" in doc and "remote-machine" in doc
    assert "FC_EXECUTION_BACKEND" in doc


def test_result_shape():
    r = ExecutionResult(returncode=0, stdout="a", stderr="b", wall_s=1.0,
                        backend_id="local-sandbox", isolation_level="local-sandbox")
    assert r.output == "ab" and r.timed_out is False and r.limits == ()
