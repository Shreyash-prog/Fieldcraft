"""The single execution chokepoint — what run_sandboxed actually enforces.

Resource-limit assertions are POSIX-only, and each one skips itself if the
platform reported that it could not apply that limit (macOS refuses RLIMIT_AS),
so the suite proves the real guarantee rather than the intended one.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

from fieldcraft_loop.sandbox import (POSIX, SandboxResult, build_env, effective_limits,
                                     is_secret_name, run_sandboxed)
from fieldcraft_loop.repo_task import RepoTask, copy_repo, run_tests
from tests.conftest import REPO_TASK

posix_only = pytest.mark.skipif(not POSIX, reason="resource limits are POSIX-only")

DUMP_ENV = "import json,os,sys; sys.stdout.write(json.dumps(dict(os.environ)))"

SECRETS = {"ANTHROPIC_API_KEY": "sk-ant-planted",
           "FC_SECRET": "planted",
           "AWS_SECRET_ACCESS_KEY": "planted",
           "GITHUB_TOKEN": "planted",
           "MY_DB_PASSWORD": "planted",
           "HTTPS_PROXY": "http://evil:8080"}


def child_env(cwd, **kw) -> dict:
    res = run_sandboxed([sys.executable, "-c", DUMP_ENV], cwd, timeout=60, **kw)
    assert res.returncode == 0, res.output
    return json.loads(res.stdout)


@pytest.fixture
def planted(monkeypatch):
    """Put credentials in the parent's environment, as the real server has."""
    for k, v in SECRETS.items():
        monkeypatch.setenv(k, v)
    return SECRETS


# --- credential-free environment --------------------------------------------

def test_child_never_sees_parent_credentials(planted, tmp_path):
    env = child_env(tmp_path)
    for name in planted:
        assert name not in env, f"{name} leaked into the sandbox"
    assert "planted" not in json.dumps(env)

def test_child_gets_only_the_allowlist(planted, tmp_path):
    env = child_env(tmp_path)
    assert env["PATH"] and env["PYTHONHASHSEED"] == "0"
    assert env["HOME"] != os.environ.get("HOME")          # private scratch HOME
    assert env["HOME"] == env["TMPDIR"]
    assert not any(is_secret_name(k) for k in env)

def test_env_extra_cannot_smuggle_a_secret(tmp_path):
    env = child_env(tmp_path, env_extra={"MY_TOKEN": "nope", "CI": "1"})
    assert "MY_TOKEN" not in env and env["CI"] == "1"

def test_build_env_is_built_not_inherited(planted):
    env = build_env("/tmp/scratch")
    assert set(env) <= {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM",
                        "HOME", "TMPDIR", "PYTHONHASHSEED"}

def test_scratch_home_is_removed_after_the_run(tmp_path):
    env = child_env(tmp_path)
    assert not Path(env["HOME"]).exists()

@pytest.mark.parametrize("name", ["ANTHROPIC_API_KEY", "FC_DATA_DIR", "AWS_ACCESS_KEY_ID",
                                  "x_api_key", "SESSION_TOKEN", "DB_PASSWORD"])
def test_secret_names_recognised(name):
    assert is_secret_name(name)


# --- resource limits ---------------------------------------------------------

@posix_only
def test_cpu_bomb_is_killed_by_the_cpu_limit(tmp_path):
    t0 = time.time()
    res = run_sandboxed([sys.executable, "-c", "x=0\nwhile True: x+=1"], tmp_path,
                        timeout=60, cpu_s=1)
    if "RLIMIT_CPU" not in res.limits:
        pytest.skip("platform refused RLIMIT_CPU")
    assert res.returncode != 0 and not res.timed_out      # the limit killed it
    assert time.time() - t0 < 30                          # long before the wall clock

@posix_only
def test_memory_bomb_is_killed_by_the_address_space_limit(tmp_path):
    ok = run_sandboxed([sys.executable, "-c", "b=bytearray(4*1024*1024); print(len(b))"],
                       tmp_path, timeout=60, mem_mb=256)
    if "RLIMIT_AS" not in ok.limits:
        pytest.skip("platform refused RLIMIT_AS (macOS does)")
    assert ok.returncode == 0, ok.output                  # control: python still starts
    bomb = run_sandboxed([sys.executable, "-c", "b=bytearray(400*1024*1024); print(len(b))"],
                         tmp_path, timeout=60, mem_mb=256)
    assert bomb.returncode != 0 and "400" not in bomb.stdout

@posix_only
def test_limits_are_reported_honestly(tmp_path):
    res = run_sandboxed([sys.executable, "-c", "pass"], tmp_path, timeout=60)
    assert "RLIMIT_CORE" in res.limits and "RLIMIT_FSIZE" in res.limits
    assert isinstance(res, SandboxResult) and res.duration_s >= 0
    assert set(effective_limits()) == set(res.limits)      # what /healthz reports

def test_healthz_publishes_the_real_limits():
    from fastapi.testclient import TestClient
    from fieldcraft_web.server import app
    body = TestClient(app).get("/healthz").json()
    assert body["sandbox_limits"] == list(effective_limits())


# --- wall clock --------------------------------------------------------------

def test_timeout_kills_a_sleeping_child(tmp_path):
    t0 = time.time()
    res = run_sandboxed([sys.executable, "-c", "import time; time.sleep(60)"],
                        tmp_path, timeout=2)
    assert res.timed_out and time.time() - t0 < 20

@posix_only
def test_timeout_kills_the_whole_process_group(tmp_path):
    marker = tmp_path / "grandchild.txt"
    grand = f"import time; time.sleep(3); open({str(marker)!r}, 'w').write('x')"
    parent = (f"import subprocess, sys, time; "
              f"subprocess.Popen([sys.executable, '-c', {grand!r}]); time.sleep(60)")
    res = run_sandboxed([sys.executable, "-c", parent], tmp_path, timeout=1)
    assert res.timed_out
    time.sleep(5)                                         # outlive the grandchild's sleep
    assert not marker.exists(), "grandchild survived the timeout"


# --- argv only, and cwd ------------------------------------------------------

def test_cwd_is_the_workdir(tmp_path):
    (tmp_path / "marker.txt").write_text("here\n")
    res = run_sandboxed([sys.executable, "-c",
                         "import os; print(os.getcwd()); print(os.listdir('.'))"],
                        tmp_path, timeout=60)
    assert str(tmp_path) in res.stdout and "marker.txt" in res.stdout

def test_shell_metacharacters_are_not_interpreted(tmp_path):
    evil = "; touch pwned; echo $HOME"
    res = run_sandboxed([sys.executable, "-c", "import sys; print(sys.argv[1])", evil],
                        tmp_path, timeout=60)
    assert res.stdout.strip() == evil                     # passed through literally
    assert not (tmp_path / "pwned").exists()

@pytest.mark.parametrize("bad", ["echo hi", "", [], None, ("",)])
def test_string_commands_are_rejected(bad, tmp_path):
    with pytest.raises(ValueError, match="argv list"):
        run_sandboxed(bad, tmp_path, timeout=5)

def test_missing_binary_is_a_result_not_an_exception(tmp_path):
    res = run_sandboxed(["/nonexistent/fc-binary-xyz"], tmp_path, timeout=5)
    assert res.returncode == 127 and "failed to start" in res.stderr


# --- callers still behave ----------------------------------------------------

def test_run_tests_still_scores_a_real_repo(tmp_path, planted):
    t = RepoTask.load(REPO_TASK)
    wd = tmp_path / "w"
    copy_repo(t, wd)
    passed, total, failing = run_tests(wd, t.test_command)
    assert (passed, total) == (1, 8) and failing            # stub repo: 1/8, unchanged

def test_run_tests_reports_a_timeout_as_a_failed_verdict(tmp_path):
    (tmp_path / "test_slow.py").write_text("import time\ndef test_slow():\n    time.sleep(60)\n")
    assert run_tests(tmp_path, [sys.executable, "-m", "pytest", "-q"], timeout=3) == (0, 0, ["<timeout>"])
