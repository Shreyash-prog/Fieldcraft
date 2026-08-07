"""The one place task code is executed.

Every command the loop runs on behalf of an agent — a repo task's test command,
pytest for a single-file task — goes through `run_sandboxed`. Centralising it
means the hardening below is applied by construction rather than remembered at
each call site (HARDENING P0-1).

**What this guarantees** (in-container, on one machine):

* **Credential-free child.** The environment is *built*, never inherited: an
  allowlist (PATH, locale, TZ/TERM) plus a private HOME/TMPDIR. `ANTHROPIC_API_KEY`,
  every `FC_*`, `AWS_*`, `*_KEY`/`*_TOKEN`/`*_SECRET`, and every proxy variable
  are absent because nothing is copied across. A caller-supplied `env_extra` is
  filtered through the same secret check, so it cannot re-introduce them.
* **Resource limits** (POSIX): CPU seconds, address space, process count, max
  file size, and no core dumps. Each limit is applied in the child and the ones
  that actually took effect are reported back on `SandboxResult.limits` — a
  platform that refuses a limit is visible, not silently assumed.
* **Wall-clock timeout** that kills the whole **process group** (the child runs
  in a new session), so a test that spawns children cannot outlive the timeout.
* **argv only.** A string command is rejected; `shell=True` is never used, so
  shell metacharacters in a command or filename are inert.

**What this does NOT guarantee** — stated plainly so nobody relies on it:

* **No filesystem isolation.** `cwd` is the workdir and HOME/TMPDIR point at a
  private scratch directory that is deleted afterwards, but the child runs as the
  *same OS user* and can read and write anything that user can. Real confinement
  needs a mount namespace, container, or microVM.
* **No network isolation.** The child can open sockets and reach the internet.
  Nothing here blocks egress; we only ensure it inherits no proxy configuration
  and no credentials, so what leaks is not *ours*. See DEPLOY.md — real egress
  control means running executions on an isolated Fly Machine (TODO, future work).
* **Limits are per-process, not per-machine.** N concurrent runs can each use the
  full memory limit; `FC_MAX_CONCURRENT` is what bounds the total.
* **Not an escape-proof sandbox.** It raises the cost of accidents and casual
  misbehaviour inside one container. It is not a security boundary against a
  determined attacker.
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

POSIX = os.name == "posix"
try:                                  # POSIX only; absent on Windows dev machines
    import resource
except ImportError:                   # pragma: no cover - platform dependent
    resource = None                   # type: ignore[assignment]

# Environment variables copied from the parent, and nothing else.
ENV_ALLOWLIST = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM")
_DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
# Names that must never reach the child, even via env_extra (belt and braces:
# the allowlist already excludes them).
_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "SESSION")
_SECRET_PREFIXES = ("FC_", "AWS_", "ANTHROPIC_", "OPENAI_", "GITHUB_", "GH_", "FLY_")

_MB = 1024 * 1024
_LIMIT_ENV = {                        # kwarg -> (env var, default)
    "cpu_s": ("FC_SANDBOX_CPU_S", 60),
    "mem_mb": ("FC_SANDBOX_MEM_MB", 512),
    "nproc": ("FC_SANDBOX_NPROC", 256),
    "fsize_mb": ("FC_SANDBOX_FSIZE_MB", 64),
}
_warned = False


@dataclass
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    duration_s: float = 0.0
    limits: tuple[str, ...] = field(default_factory=tuple)   # rlimits actually applied

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


def is_secret_name(name: str) -> bool:
    up = name.upper()
    return (up.startswith(_SECRET_PREFIXES) or
            any(h in up for h in _SECRET_HINTS))


def _reject_secret(name: str, via: str) -> bool:
    if is_secret_name(name):
        log.warning("sandbox: refusing to pass %s to the child (via %s)", name, via)
        return True
    return False


def build_env(home: str, extra: dict[str, str] | None = None,
              allowlist: tuple[str, ...] | None = None) -> dict[str, str]:
    """Build the child's environment from scratch. Nothing is inherited except
    the allowlist, and `extra` cannot smuggle a secret back in.

    Note the proxy variables (HTTP_PROXY/HTTPS_PROXY/NO_PROXY) are absent for the
    same reason as the credentials: they are simply never copied. That is *not*
    network isolation — the child can still open sockets.
    TODO(HARDENING P0-1): real egress control requires running the command on an
    isolated Fly Machine / microVM, not in this container. See DEPLOY.md.
    """
    # A caller-supplied allowlist goes through the same secret check as `extra`,
    # so widening the allowlist can never be a way to smuggle a credential in.
    names = [k for k in (allowlist or ENV_ALLOWLIST) if not _reject_secret(k, "allowlist")]
    env = {k: os.environ[k] for k in names if k in os.environ}
    env.setdefault("PATH", _DEFAULT_PATH)
    env.setdefault("LANG", "C.UTF-8")
    env["HOME"] = home
    env["TMPDIR"] = home
    env["PYTHONHASHSEED"] = "0"       # deterministic runs (HARDENING P1-4)
    for k, v in (extra or {}).items():
        if _reject_secret(k, "env_extra"):
            continue
        env[k] = str(v)
    return env


def _limit(kwarg: str, given: int | None) -> int:
    """An explicit argument wins; otherwise the env var; otherwise the default."""
    if given is not None:
        return given
    name, default = _LIMIT_ENV[kwarg]
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _limits(cpu_s, mem_mb, nproc, fsize_mb) -> dict[str, int]:
    lim = {"RLIMIT_CPU": cpu_s, "RLIMIT_AS": mem_mb * _MB, "RLIMIT_FSIZE": fsize_mb * _MB}
    # RLIMIT_NPROC counts every process of the *real UID*, not just this tree. In
    # the container that UID is ours alone; on a dev machine it would count the
    # developer's own processes and make fork() fail, so apply it on Linux only.
    if nproc and POSIX and os.uname().sysname == "Linux":
        lim["RLIMIT_NPROC"] = nproc
    return {k: v for k, v in lim.items() if v and v > 0}


def _preexec(limits: dict[str, int], report_fd: int):
    """Runs in the child between fork and exec: apply limits, report what stuck."""
    def apply() -> None:
        applied = []
        for name, val in limits.items():
            rl = getattr(resource, name, None)
            if rl is None:
                continue
            # CPU: a soft limit one second under the hard one turns into SIGXCPU
            # first (catchable/reportable) and SIGKILL only if it is ignored.
            hard = val + 1 if name == "RLIMIT_CPU" else val
            try:
                resource.setrlimit(rl, (val, hard))
            except (ValueError, OSError):
                continue              # platform refused it; simply not applied
            applied.append(name)
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            applied.append("RLIMIT_CORE")
        except (ValueError, OSError, AttributeError):
            pass
        try:
            os.write(report_fd, ",".join(applied).encode())
        except OSError:
            pass
        try:
            os.close(report_fd)       # always: the exec'd program must not inherit it
        except OSError:
            pass
    return apply


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the child *and* anything it spawned."""
    if POSIX:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    proc.kill()


def run_sandboxed(cmd: list[str], cwd: str | Path, timeout: int = 60, *,
                  env_extra: dict[str, str] | None = None,
                  env_allowlist: tuple[str, ...] | None = None,
                  cpu_s: int | None = None, mem_mb: int | None = None,
                  nproc: int | None = None, fsize_mb: int | None = None) -> SandboxResult:
    """Execute `cmd` (an argv list) in `cwd` under the guarantees documented above.

    Never raises on the child's behalf: a timeout, a crash, or a limit kill all
    come back as a SandboxResult so verification stays a verdict, not an outage.
    """
    global _warned
    if (isinstance(cmd, str) or not isinstance(cmd, (list, tuple)) or not cmd
            or not str(cmd[0]).strip()):
        raise ValueError("run_sandboxed takes a non-empty argv list, never a shell string")
    argv = [str(a) for a in cmd]

    home = tempfile.mkdtemp(prefix="fc-sandbox-")
    env = build_env(home, env_extra, env_allowlist)
    limits = _limits(_limit("cpu_s", cpu_s), _limit("mem_mb", mem_mb),
                     _limit("nproc", nproc), _limit("fsize_mb", fsize_mb)) if resource else {}
    if not resource and not _warned:
        log.warning("sandbox: `resource` unavailable on %s — resource limits SKIPPED; "
                    "only the stripped environment and the timeout apply", os.name)
        _warned = True

    kwargs: dict = {}
    rfd = wfd = -1
    if limits:
        rfd, wfd = os.pipe()
        kwargs = {"preexec_fn": _preexec(limits, wfd), "pass_fds": (wfd,)}
    if POSIX:
        kwargs["start_new_session"] = True     # so the timeout can kill the group

    t0 = time.time()
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, errors="replace",
                                close_fds=True, **kwargs)
    except OSError as e:
        _cleanup(home, rfd, wfd)
        return SandboxResult(returncode=127, stdout="", stderr=f"failed to start: {e}",
                             duration_s=round(time.time() - t0, 3))
    if wfd >= 0:
        os.close(wfd)                          # child holds the write end

    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_group(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:      # pragma: no cover - kill -9 ignored
            proc.kill()
            out, err = "", ""

    applied: tuple[str, ...] = ()
    if rfd >= 0:
        # The child wrote this before exec and closed its end, so the bytes are
        # already buffered; read without blocking so a stray fd can never hang us.
        os.set_blocking(rfd, False)
        try:
            raw = os.read(rfd, 4096).decode()
            applied = tuple(n for n in raw.split(",") if n)
        except (OSError, BlockingIOError):     # pragma: no cover
            pass
    _cleanup(home, rfd, -1)
    return SandboxResult(returncode=proc.returncode, stdout=out or "", stderr=err or "",
                         timed_out=timed_out, duration_s=round(time.time() - t0, 3),
                         limits=applied)


@lru_cache(maxsize=1)
def effective_limits() -> tuple[str, ...]:
    """Which rlimits this machine *actually* applies, probed once with a no-op
    child and cached. Exposed on /healthz so a deployment can verify the claim
    instead of trusting this file (macOS, for instance, refuses RLIMIT_AS)."""
    if resource is None:
        return ()
    return run_sandboxed([sys.executable, "-c", "pass"], tempfile.gettempdir(),
                         timeout=60).limits


def _cleanup(home: str, *fds: int) -> None:
    for fd in fds:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
    shutil.rmtree(home, ignore_errors=True)
