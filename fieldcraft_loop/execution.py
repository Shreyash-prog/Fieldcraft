"""The execution seam — one interface every untrusted command goes through.

`sandbox.py` is *how* we execute today; this is *what* execution means, stated
once so a different implementation can be swapped in without touching the loop.
Phase C part 1 is this abstraction only: it adds no isolation. The default
backend is the existing local sandbox and its behaviour is unchanged.

**Everything passed to `ExecutionBackend.run` is UNTRUSTED.** `cmd` may be a
stranger's test command from a connected repo; `cwd` holds code an agent or a
third party wrote. A backend is a *containment* decision, not a convenience
wrapper — implementations must assume the command is actively hostile and must
be honest about how much containment they actually provide.

Two backends exist:

* ``LocalSandbox`` (``isolation_level="local-sandbox"``) — the current default.
  In-container hardening: credential-free environment, resource limits,
  process-group kill, argv-only. **Not** filesystem-isolated, **not**
  network-isolated: the child runs as the same OS user with open egress. Good
  enough for code we or our own agents produced in a container we control; **not
  a security boundary against a determined attacker.**
* ``RemoteMachineBackend`` (``isolation_level="remote-machine"``) — the pending
  real-isolation backend. Interface-complete and inert: selecting it raises.

Selection is `FC_EXECUTION_BACKEND` (default ``local``). An unrecognised value
raises rather than falling back, because silently downgrading isolation after an
operator asked for more of it is the worst possible failure mode.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

LOCAL, REMOTE = "local", "remote"
ENV_VAR = "FC_EXECUTION_BACKEND"

# Said in one place so /healthz, the docs and the logs cannot drift apart.
LOCAL_SANDBOX_NOTE = (
    "in-container hardening only (credential-free env, rlimits, process-group "
    "kill, argv-only). NOT filesystem-isolated and NOT network-isolated: the "
    "command runs as the same OS user with open egress. Do not use this to run "
    "untrusted third-party code from strangers.")
REMOTE_MACHINE_NOTE = (
    "disposable per-run machine with restricted egress — NOT YET PROVISIONED. "
    "Must pass an adversarial break-test before anything untrusted runs on it.")


@dataclass(frozen=True)
class ExecutionResult:
    """What a backend reports back. Never raises on the child's behalf: a
    timeout, a crash or a limit kill are all results, so verification stays a
    verdict rather than an outage."""
    returncode: int
    stdout: str
    stderr: str
    wall_s: float
    backend_id: str
    isolation_level: str
    timed_out: bool = False
    # Which resource limits the backend actually applied. Empty is meaningful:
    # it means none took effect, not that none were requested.
    limits: tuple[str, ...] = field(default_factory=tuple)

    @property
    def output(self) -> str:
        return self.stdout + self.stderr


class ExecutionBackend(ABC):
    """Where an untrusted command runs.

    Implementations must not raise for anything the *child* did — only for a
    backend that cannot run at all (misconfiguration, unprovisioned
    infrastructure). Everything the command does comes back as an
    ExecutionResult.
    """

    #: stable identifier for logs and /healthz
    backend_id: str = "abstract"
    #: what containment was actually applied — the honest part
    isolation_level: str = "none"
    filesystem_isolated: bool = False
    network_isolated: bool = False
    note: str = ""

    @abstractmethod
    def run(self, cmd: list[str], cwd: str | Path, timeout: int = 60, *,
            env_allowlist: tuple[str, ...] | None = None,
            limits: dict[str, int] | None = None) -> ExecutionResult:
        """Execute an UNTRUSTED argv list in `cwd`.

        `cmd` must be an argv list — never a shell string. `env_allowlist` names
        the parent variables the child may inherit (None = the backend's own
        default). `limits` carries resource caps (`cpu_s`, `mem_mb`, `nproc`,
        `fsize_mb`); None = the backend's configured defaults.
        """

    def describe(self) -> dict:
        """The isolation claim, for /healthz and the audit trail."""
        return {"backend_id": self.backend_id, "isolation_level": self.isolation_level,
                "filesystem_isolated": self.filesystem_isolated,
                "network_isolated": self.network_isolated, "note": self.note}


class LocalSandbox(ExecutionBackend):
    """The current chokepoint, behind the interface.

    A thin delegation to `sandbox.run_sandboxed` on purpose: the hardening, its
    tests and its documented limits all stay in one place, and this class adds no
    behaviour of its own. Routing a call through here is byte-identical to
    calling `run_sandboxed` directly.
    """

    backend_id = "local-sandbox"
    isolation_level = "local-sandbox"
    filesystem_isolated = False       # same OS user, same filesystem
    network_isolated = False          # open egress
    note = LOCAL_SANDBOX_NOTE

    def run(self, cmd: list[str], cwd: str | Path, timeout: int = 60, *,
            env_allowlist: tuple[str, ...] | None = None,
            limits: dict[str, int] | None = None) -> ExecutionResult:
        from .sandbox import run_sandboxed
        lim = limits or {}
        res = run_sandboxed(cmd, cwd, timeout=timeout, env_allowlist=env_allowlist,
                            cpu_s=lim.get("cpu_s"), mem_mb=lim.get("mem_mb"),
                            nproc=lim.get("nproc"), fsize_mb=lim.get("fsize_mb"))
        return ExecutionResult(
            returncode=res.returncode, stdout=res.stdout, stderr=res.stderr,
            wall_s=res.duration_s, backend_id=self.backend_id,
            isolation_level=self.isolation_level, timed_out=res.timed_out,
            limits=res.limits)


class RemoteMachineBackend(ExecutionBackend):
    """Per-run isolation on a disposable machine — **NOT IMPLEMENTED**.

    This class exists so the seam is real: the interface is complete, the
    selection path works, and /healthz can report which backend a deployment
    asked for. It provisions nothing. Selecting it and calling `run` raises.

    **What it will do** (Phase C part 2):

    * Spawn a **disposable Fly Machine per run** from a minimal image, run the
      command there, collect stdout/stderr/returncode, and **destroy the machine
      afterwards** — a fresh filesystem per run, so nothing an execution writes
      can be seen by the next one or by the app.
    * Carry **no ambient credentials**: the machine gets no Fly token, no
      `ANTHROPIC_API_KEY`, no app environment. The orchestrating token lives in
      the app and is never passed into the sandboxed machine.
    * **Restrict egress** so a test suite cannot exfiltrate the workdir or reach
      the app's own network — the property `local-sandbox` cannot provide at all.
    * Enforce the same wall-clock bound, with machine destruction as the
      backstop when the in-machine timeout is defeated.

    **What must be verified before it is trusted** — the claim is isolation, so
    it does not get to be assumed:

    * An **adversarial break-test suite** that actively tries to escape: reach
      the app's internal network, reach the Fly API, read another run's workdir,
      survive machine destruction, exhaust the host, and exfiltrate over DNS.
    * Proof that machines are destroyed even when a run crashes, the app
      restarts mid-run, or the API call to destroy fails — a leaked machine is a
      billing problem *and* a live box with someone's code on it.
    * Confirmation the orchestration credential cannot be reached from inside.

    Until those pass, this backend must stay unselected. It is deliberately loud
    rather than degrading to the local sandbox: an operator who configured
    `remote` wanted isolation, and quietly giving them less would be worse than
    failing.
    """

    backend_id = "remote-machine"
    isolation_level = "remote-machine"
    # Aspirational, and reported as False until the break-test proves otherwise.
    filesystem_isolated = False
    network_isolated = False
    note = REMOTE_MACHINE_NOTE

    def run(self, cmd: list[str], cwd: str | Path, timeout: int = 60, *,
            env_allowlist: tuple[str, ...] | None = None,
            limits: dict[str, int] | None = None) -> ExecutionResult:
        raise NotImplementedError(
            "remote machine isolation not yet provisioned — see Phase C part 2")


_BACKENDS = {LOCAL: LocalSandbox, REMOTE: RemoteMachineBackend}


def get_execution_backend(name: str | None = None) -> ExecutionBackend:
    """The configured backend. `FC_EXECUTION_BACKEND` (default `local`).

    Raises ValueError on an unknown name rather than defaulting to local: a typo
    in an isolation setting must stop the deployment, not silently run untrusted
    code with less containment than the operator asked for.
    """
    key = (name if name is not None else os.environ.get(ENV_VAR, LOCAL)).strip().lower()
    if not key:
        key = LOCAL
    if key not in _BACKENDS:
        raise ValueError(
            f"unknown {ENV_VAR}={key!r}; expected one of {', '.join(sorted(_BACKENDS))}")
    return _BACKENDS[key]()
