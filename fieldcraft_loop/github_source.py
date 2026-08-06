"""Connect the loop to a real, public GitHub repository.

A `RepoTask` (see `repo_task.py`) only needs a directory of source plus a test
command, so any repo can become one. This module builds that directory from a
**public** GitHub URL: validate the URL, shallow-clone it, guard its size, and
detect a plausible test command.

Scope and honesty about the guards:

* **Public only, read-only.** No credentials are ever supplied and nothing is
  pushed back. Git is run with prompting disabled, so a private repo fails fast
  ("not found or private") instead of hanging on a credential prompt.
* **The URL is never passed through as typed.** It is parsed, every component is
  checked against a strict character class, and the clone URL is *rebuilt* from
  the owner/repo pair — so shell metacharacters and `--flag`-looking segments
  cannot reach git. (git is also invoked without a shell.)
* **The size cap is enforced after the clone, not during it.** git has no
  "stop at N MB" flag, so a huge repo is downloaded, measured, and deleted. The
  clone timeout is what bounds the download in the meantime. Both are real
  limits; neither is a substitute for the sandboxing tracked in HARDENING.md.

Running a connected repo's test suite still executes that repo's code with the
same isolation as any other task — i.e. a subprocess with a timeout (HARDENING
P0-1). That is why the web app runs connected repos with the offline mock agent
only.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .repo_task import _IGNORE

# hard cap on a cloned repo's on-disk size
MAX_REPO_MB = float(os.environ.get("FC_MAX_REPO_MB", "50"))
# kill a clone that runs too long (also bounds how much a huge repo can pull)
CLONE_TIMEOUT_S = int(os.environ.get("FC_CLONE_TIMEOUT_S", "60"))

_HOSTS = {"github.com", "www.github.com"}
_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_UNSAFE = re.compile(r"[\s;&|<>$`'\"\\(){}\[\]*?!#\x00-\x1f]")

DEFAULT_PROTECTED = ["tests/", "test/", ".github/"]
DEFAULT_TEST_COMMAND = ["python", "-m", "pytest", "-q"]


class GitHubSourceError(Exception):
    """A connect attempt that failed closed — bad URL, private repo, too big."""


@dataclass
class RepoInfo:
    owner: str
    name: str
    url: str                 # canonical https clone URL we actually used
    path: str                # local clone directory
    default_branch: str
    file_count: int
    size_mb: float


def parse_repo_url(url: str) -> tuple[str, str]:
    """Validate a public GitHub https URL; return (owner, repo).

    Rejects ssh/git/http schemes, non-github hosts, embedded credentials, and
    anything carrying shell metacharacters. Raises GitHubSourceError otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        raise GitHubSourceError("a repository URL is required")
    u = url.strip()
    if len(u) > 300:
        raise GitHubSourceError("URL is too long")
    if _UNSAFE.search(u):
        raise GitHubSourceError(
            "URL contains characters that are not allowed (spaces, shell "
            "metacharacters, query strings)")

    p = urlparse(u)
    if p.scheme != "https":
        raise GitHubSourceError(
            f"only https URLs are supported (got {p.scheme or 'no'} scheme) — "
            "ssh/git remotes are not accepted")
    if "@" in p.netloc:
        raise GitHubSourceError("URLs with embedded credentials are not accepted")
    if p.netloc.lower() not in _HOSTS:
        raise GitHubSourceError(f"only github.com is supported (got '{p.netloc}')")

    parts = [s for s in p.path.split("/") if s]
    if len(parts) != 2:
        raise GitHubSourceError("URL must look like https://github.com/<owner>/<repo>")
    owner, name = parts[0], re.sub(r"\.git$", "", parts[1])
    for seg in (owner, name):
        if not _SEGMENT.match(seg):
            raise GitHubSourceError(f"invalid path segment '{seg}' in URL")
    return owner, name


def clone_url_for(owner: str, name: str) -> str:
    return f"https://github.com/{owner}/{name}.git"


def _git(args: list[str], timeout_s: int, cwd: str | None = None) -> tuple[int, str]:
    """Run git with no shell, no prompts, no ambient credentials. (rc, output)."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true",
           "SSH_ASKPASS": "true", "GCM_INTERACTIVE": "never"}
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, env=env, timeout=timeout_s,
                              capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout_s}s"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def _dir_size_mb(d: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            fp = Path(root) / f
            if not fp.is_symlink():
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
    return round(total / (1024 * 1024), 2)


def _count_files(d: Path) -> int:
    n = 0
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in _IGNORE]
        n += len(files)
    return n


def _default_branch(d: Path) -> str:
    head = d / ".git" / "HEAD"
    try:
        ref = head.read_text().strip()
    except OSError:
        return "unknown"
    return ref.split("refs/heads/", 1)[1] if "refs/heads/" in ref else "unknown"


def _clone_error(out: str) -> str:
    low = out.lower()
    if "timed out" in low:
        return f"clone {out} — repository is too slow or too large"
    if "not found" in low or "authentication" in low or "could not read username" in low:
        return "repository not found — it must exist and be public (private repos are not supported)"
    return f"git clone failed: {out.splitlines()[-1][:200] if out else 'unknown error'}"


def clone_public_repo(url: str, dest: str | Path, timeout_s: int | None = None,
                      max_mb: float | None = None) -> RepoInfo:
    """Shallow-clone a public GitHub repo into `dest`. Fails closed on a bad URL,
    a private/missing repo, a timeout, or a repo over the size cap (the partial
    clone is deleted in every failure case)."""
    owner, name = parse_repo_url(url)
    timeout_s = timeout_s or CLONE_TIMEOUT_S
    max_mb = MAX_REPO_MB if max_mb is None else max_mb
    if shutil.which("git") is None:
        raise GitHubSourceError("git is not installed on this server")

    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    clone_url = clone_url_for(owner, name)
    rc, out = _git(["clone", "--depth", "1", "--single-branch", "--no-tags",
                    clone_url, str(dest)], timeout_s)
    if rc != 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitHubSourceError(_clone_error(out))

    size = _dir_size_mb(dest)
    if size > max_mb:
        shutil.rmtree(dest, ignore_errors=True)
        raise GitHubSourceError(
            f"repository is {size} MB, over the {max_mb} MB limit (FC_MAX_REPO_MB)")

    return RepoInfo(owner=owner, name=name, url=clone_url, path=str(dest),
                    default_branch=_default_branch(dest), file_count=_count_files(dest),
                    size_mb=size)


def detect_test_command(repo: Path | str) -> list[str]:
    """Guess how this repo runs its tests. Pytest-only for now: point it at a
    tests/ directory when there is one, otherwise let pytest discover."""
    d = Path(repo)
    for sub in ("tests", "test"):
        if (d / sub).is_dir():
            return [*DEFAULT_TEST_COMMAND, sub]
    return list(DEFAULT_TEST_COMMAND)     # fall back to plain pytest discovery


def has_tests(repo: Path | str) -> bool:
    """Whether anything pytest would collect is visible. False means the loop
    will honestly report 0 tests rather than a score."""
    d = Path(repo)
    if (d / "tests").is_dir() or (d / "test").is_dir():
        return True
    return any(d.rglob("test_*.py")) or any(d.rglob("*_test.py"))
