"""Connecting a public GitHub repo — URL validation, clone guards, and the
connect endpoint. The git subprocess is faked throughout: this suite never
touches the network."""
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop import github_source as gs
from fieldcraft_loop.github_source import GitHubSourceError
from fieldcraft_web import server

client = TestClient(server.app)

VALID = ["https://github.com/owner/repo",
         "https://github.com/owner/repo.git",
         "https://github.com/Owner-1/repo_2/",
         "https://www.github.com/o/r"]

REJECTED = [
    "git@github.com:owner/repo.git",            # ssh scp-style
    "ssh://git@github.com/owner/repo",          # ssh
    "http://github.com/owner/repo",             # plaintext
    "file:///etc/passwd",                       # local file
    "https://gitlab.com/owner/repo",            # other host
    "https://github.com.evil.com/owner/repo",   # lookalike host
    "https://user:pw@github.com/o/r",           # embedded credentials
    "https://github.com/owner/repo; rm -rf /",  # command injection
    "https://github.com/owner/$(whoami)",       # substitution
    "https://github.com/owner/repo`id`",        # backticks
    "https://github.com/owner/repo|nc evil",    # pipe
    "https://github.com/owner",                 # no repo
    "https://github.com/owner/repo/tree/main",  # not a repo root
    "https://github.com/../../etc",             # traversal
    "https://github.com/-flag/repo",            # argument-looking segment
    "", "   ",
]


def _fake_clone(dest: Path, files: dict, branch: str = "main"):
    (dest / ".git").mkdir(parents=True)
    (dest / ".git" / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    for rel, text in files.items():
        f = dest / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)


@pytest.fixture
def fake_git(monkeypatch):
    """Install a fake `git`. Call it to arm a clone result; inspect .calls."""
    calls = []

    def arm(files=None, rc=0, out="", branch="main"):
        def _g(args, timeout_s, cwd=None):
            calls.append(args)
            if rc == 0 and args and args[0] == "clone":
                _fake_clone(Path(args[-1]), files or {"README.md": "hi\n"}, branch)
            return rc, out
        monkeypatch.setattr(gs, "_git", _g)
        monkeypatch.setattr(gs.shutil, "which", lambda name: "/usr/bin/git")
    arm.calls = calls
    return arm


# --- URL validation ---------------------------------------------------------

@pytest.mark.parametrize("url", VALID)
def test_accepts_valid_https_github_urls(url):
    owner, name = gs.parse_repo_url(url)
    assert owner and name and not name.endswith(".git")

@pytest.mark.parametrize("url", REJECTED)
def test_rejects_bad_urls(url):
    with pytest.raises(GitHubSourceError):
        gs.parse_repo_url(url)

def test_clone_url_is_rebuilt_not_passed_through(fake_git, tmp_path):
    fake_git()
    info = gs.clone_public_repo("https://www.github.com/Owner/Repo.git", tmp_path / "repo")
    assert info.url == "https://github.com/Owner/Repo.git"
    assert gs.clone_url_for("Owner", "Repo") in fake_git.calls[0]


# --- clone guards -----------------------------------------------------------

def test_clone_returns_repo_info(fake_git, tmp_path):
    fake_git(files={"README.md": "hi\n", "pkg/a.py": "x = 1\n"}, branch="trunk")
    info = gs.clone_public_repo("https://github.com/owner/repo", tmp_path / "repo")
    assert (info.owner, info.name) == ("owner", "repo")
    assert info.default_branch == "trunk"
    assert info.file_count == 2                       # .git is not counted
    assert info.size_mb >= 0 and Path(info.path).is_dir()

def test_repo_over_size_cap_fails_closed(fake_git, tmp_path):
    fake_git(files={"big.bin": "x" * 2_000_000})
    dest = tmp_path / "repo"
    with pytest.raises(GitHubSourceError, match="over the 1 MB limit"):
        gs.clone_public_repo("https://github.com/owner/repo", dest, max_mb=1)
    assert not dest.exists()                          # partial clone removed

def test_private_or_missing_repo_message(fake_git, tmp_path):
    fake_git(rc=128, out="remote: Repository not found.")
    with pytest.raises(GitHubSourceError, match="public"):
        gs.clone_public_repo("https://github.com/owner/secret", tmp_path / "repo")

def test_clone_timeout_fails_closed(fake_git, tmp_path):
    fake_git(rc=124, out="timed out after 60s")
    dest = tmp_path / "repo"
    with pytest.raises(GitHubSourceError, match="too slow or too large"):
        gs.clone_public_repo("https://github.com/owner/repo", dest)
    assert not dest.exists()

def test_missing_git_binary(monkeypatch, tmp_path):
    monkeypatch.setattr(gs.shutil, "which", lambda name: None)
    with pytest.raises(GitHubSourceError, match="git is not installed"):
        gs.clone_public_repo("https://github.com/owner/repo", tmp_path / "repo")


# --- test-command detection -------------------------------------------------

def test_detect_test_command_prefers_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    assert gs.detect_test_command(tmp_path) == ["python", "-m", "pytest", "-q", "tests"]

def test_detect_test_command_falls_back(tmp_path):
    assert gs.detect_test_command(tmp_path) == ["python", "-m", "pytest", "-q"]

def test_has_tests(tmp_path):
    assert not gs.has_tests(tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "test_x.py").write_text("def test_x(): pass\n")
    assert gs.has_tests(tmp_path)


# --- connect endpoint -------------------------------------------------------

def test_connect_rejects_bad_url():
    r = client.post("/api/repos/connect", json={"url": "git@github.com:owner/repo.git"})
    assert r.status_code == 400 and "https" in r.json()["detail"]

def test_connect_rejects_non_github_host():
    r = client.post("/api/repos/connect", json={"url": "https://gitlab.com/o/r"})
    assert r.status_code == 400 and "github.com" in r.json()["detail"]

def test_connect_surfaces_private_repo(fake_git):
    fake_git(rc=128, out="remote: Repository not found.")
    r = client.post("/api/repos/connect", json={"url": "https://github.com/owner/secret"})
    assert r.status_code == 400 and "public" in r.json()["detail"]

def test_connect_then_run_streams_like_a_bundled_task(fake_git):
    fake_git(files={"pkg/__init__.py": "", "tests/test_ok.py": "def test_ok():\n    assert True\n"})
    d = client.post("/api/repos/connect", json={"url": "https://github.com/owner/repo"}).json()
    assert d["adapter"] == "mock" and d["test_command"][-1] == "tests" and d["tests_detected"]
    assert "tests/" in d["protected_paths"] and d["repo"]["default_branch"] == "main"
    assert d["task"] in [t["name"] for t in client.get("/api/tasks").json()["tasks"]]

    bid = client.post("/api/briefs", json={"task": d["task"], "adapter": "mock",
                                           "review": "auto"}).json()["brief_id"]
    for _ in range(80):
        s = client.get(f"/api/briefs/{bid}").json()
        if s["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.25)
    assert s["status"] == "done"                       # the repo's own tests pass
    ev = client.get(f"/api/briefs/{bid}/events").json()["events"]
    assert any(e["type"] == "verdict" and e["payload"]["tests"] == "1/1" for e in ev)

def test_connected_repo_refuses_live_agent(fake_git):
    fake_git()
    d = client.post("/api/repos/connect", json={"url": "https://github.com/owner/repo2"}).json()
    r = client.post("/api/briefs", json={"task": d["task"], "adapter": "claude"})
    assert r.status_code == 403 and "mock" in r.json()["detail"]
