# Fieldcraft — Hardening Backlog

Prioritized from a senior-architecture review of the current codebase, scoped against the platform in `VISION.md`. Severity is stated as **current exposure** (the app today: local/offline, mock agents) vs **vision-blocking** (the risk once agents can act across a customer's trust boundary — real repos, cloud, databases, live models). Most items are low-risk today and existential for the vision; the vision defines the priority, not the current demo.

Legend: **P0** = must exist before any real/untrusted connection is wired. **P1** = correctness/trust foundations. **P2** = scale/ops.

---

## P0 — prerequisites for the vision

### P0-1 · Sandboxed, credential-free code execution — **PARTIALLY ADDRESSED**
*In-container hardening is done; true isolation (microVM / isolated Machine per run) is still pending.*

- **Where:** all test/build execution now goes through one chokepoint, `fieldcraft_loop/sandbox.py:run_sandboxed`. `repo_task.py:run_tests` and `effectiveness.py:run_pytest` call it and nothing else calls `subprocess` for task code.
- **Original problem:** agent-authored code ran with no isolation in a process holding `ANTHROPIC_API_KEY`. Since the "connect a public GitHub repo" feature, the code being run can also be a stranger's.

**What `run_sandboxed` now guarantees** (single container, one Fly Machine):
- **Credential-free child.** The environment is *built from an allowlist* (PATH, locale, TZ/TERM) plus a private HOME/TMPDIR — `os.environ` is never inherited. `ANTHROPIC_API_KEY`, every `FC_*`/`AWS_*`/`*_KEY`/`*_TOKEN`/`*_SECRET`, and all proxy variables are absent by construction; a caller-supplied `env_extra` is filtered by the same check. Proven by test: planted secrets in the parent do not appear in the child.
- **Resource limits** (POSIX) via `preexec_fn`: `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE`, `RLIMIT_CORE` (=0), and `RLIMIT_NPROC` **on Linux only** (it is per-UID, so on a dev machine it would count the developer's own processes). Configurable: `FC_SANDBOX_CPU_S`, `FC_SANDBOX_MEM_MB`, `FC_SANDBOX_NPROC`, `FC_SANDBOX_FSIZE_MB`.
- **Honest reporting of limits.** The child reports which limits it actually set back over a pipe; `SandboxResult.limits` and `GET /healthz` (`sandbox_limits`) publish that per machine, because platforms differ — macOS refuses `RLIMIT_AS`, so on a Mac the memory cap is *not* in force and says so rather than being assumed.
- **Wall-clock timeout that kills the process group** (`start_new_session=True` + `killpg`), so children outliving their parent are killed too. Proven by test.
- **argv only.** A shell string is rejected; `shell=True` is never used, so metacharacters in commands or filenames are inert. Proven by test.
- **Graceful non-POSIX fallback:** on Windows the environment stripping and timeout still apply and a warning is logged that resource limits were skipped.

**What it explicitly does NOT guarantee** — do not rely on these:
- **No filesystem isolation.** `cwd` is the workdir and HOME/TMPDIR are a private scratch dir, but the child runs as the *same OS user* and can read/write anything that user can (including the app's SQLite files). Real confinement needs a mount namespace or a separate machine.
- **No network isolation.** The child can open sockets and reach the internet. Nothing in-container blocks egress; we only guarantee it carries none of our credentials or proxy config. **Do not describe the sandbox as network-isolated.**
- **No protection against a determined escape.** rlimits and a stripped environment raise the cost of accidents and casual misbehaviour. They are not a security boundary against an attacker who is trying.
- **Limits are per-process.** N concurrent runs can each consume the full memory limit; only `FC_MAX_CONCURRENT` bounds the total.
- **Out of scope, still unsandboxed:** the `claude` CLI invocations (`fieldcraft_loop/live_adapter.py`, `repo_adapters.py:RepoLiveAdapter`, `fieldcraft_aar/adapters.py`) run *with* ambient credentials by design — that is the agent, not the agent's output. Our own `git clone` (`github_source.py`) and `git rev-parse` (`fieldcraft_guide/bootstrap.py`) are also outside this path.

- **Remaining work (still P0):** run each execution on a disposable, network-egress-controlled **isolated Fly Machine** (or gVisor/Firecracker), with filesystem confinement and secrets injected only via short-lived brokered tokens. Until then, treat a connected repo's test suite as untrusted code with internet access running as the app user.

### P0-2 · Authentication + tenant isolation
- **Where:** `fieldcraft_web/server.py` — zero auth (`grep Depends/Authorization` = 0); `FC_CORS_ORIGINS` defaults to `*`. No `org_id`/`user_id` in the data model; one global `events`/`runs` table and one global report cache.
- **Problem:** anyone reaching the URL can start runs, spend, and read every brief/event. No isolation between customers.
- **Current exposure:** low if deployed with `FC_ALLOW_LIVE=0` + locked CORS. **Vision:** existential — the platform is inherently multi-customer.
- **Remediation:** add identity (auth) and a tenant column threaded through every query and cache key. Make this a **data-model decision before** platform work; retrofitting tenancy is painful.

### P0-3 · Real scoped-credential backend
- **Where:** `fieldcraft_gov/credentials.py` — `CredentialBroker` is an in-memory dict of capability strings; audit is an in-memory list lost on restart.
- **Problem:** fine as a *model*, nowhere near "agents get scoped CRUD on a customer's AWS/DB." No real secret storage, IAM/STS integration, or durable audit.
- **Remediation:** keep the interface; back it with real short-lived scoped tokens (STS/KMS-style), durable audit, and **destructive-op approval enforced at grant time** (broker denies `delete` without an approval token) — not in loop code.

### P0-4 · Durable, transactional spend/rate enforcement
- **Where:** `fieldcraft_web/limits.py` — `RateLimiter`/`CostTracker`/`Concurrency` hold state in process memory.
- **Problem:** a restart/crash-loop resets the daily spend cap; the cost ceiling is not durable.
- **Remediation:** persist counters (DB/Redis) and enforce transactionally before any spend, especially before enabling live models or real cloud calls.

### P0-5 · Provenance + injection defense on ingested content
- **Where:** live prompt assembly (`fieldcraft_loop/live_adapter.py:_prompt`) pulls task files, `NOTES.md`, acceptance criteria, and Field-Guide-bootstrapped repo content; the flywheel (`fieldcraft_guide/flywheel.py`) writes learned traps **back** into the guide.
- **Problem:** untrusted content (customer repos, Confluence, PDFs in the vision) can carry prompt-injection; the flywheel makes injection **persistent** across future runs. No provenance or trust boundary, no review gate on flywheel promotions.
- **Remediation:** tag content provenance; treat external content as untrusted (delimit, strip instructions); require human approval before the flywheel promotes anything into prompts.

---

## P1 — correctness & trust foundations

### P1-1 · Atomic event/state consistency (or true replay)
- **Where:** `fieldcraft_loop/engine.py` resume reads a `run_store` snapshot (iteration, cost, trajectory, last_verdict, last_diff, last_feedback) rather than replaying the event log; event `append` and `run_store.update` are separate commits with no shared transaction.
- **Problem:** a crash between the two writes leaves audit log and state cursor inconsistent; "event-sourced" is aspirational for resume. 
- **Remediation:** either fold state from the event log (true event sourcing) or make event-append + state-update atomic; add a consistency check on resume.

### P1-2 · Tamper-evident audit
- **Where:** `fieldcraft_loop/store.py` — plain mutable SQLite table.
- **Problem:** anyone with DB/disk access (incl. a sandbox-escaped agent) can rewrite history; a customer security team won't accept a mutable audit.
- **Remediation:** enforce append-only + hash-chain or sign events so tampering is detectable.

### P1-3 · Judge trust: variance + held-out calibration
- **Where:** `fieldcraft_aar/` calibration — single run, 0.83 kappa, unmeasured variance; behavioral probes are fixed/known (gameable, Goodhart).
- **Remediation:** measure kappa variance across runs; maintain a refreshed held-out calibration set; consider an ensemble / disagreement-flagging so one judge miss doesn't silently corrupt a score.

### P1-4 · Reproducible live runs
- **Problem:** no run manifest (model version, prompt hash, temperature, seeds) — a live score can't be reproduced.
- **Remediation:** capture a full manifest per live run; a measurement product must be able to reproduce its measurements.

### P1-5 · Preventive (not post-hoc) guardrails + fail-closed defaults
- **Where:** `fieldcraft_gov/enforce.py` reverts *after* the turn; forbidden-content is regex on the diff (bypassable via base64/concat/unicode); `editable_paths` defaults to `["**"]`; path matching is `fnmatch` with no `../`/symlink defense.
- **Remediation:** enforce at the sandbox boundary (egress rules, capability tokens); default-deny allowlists; treat diff regex as lint, not a security control.

### P1-6 · Concurrency isolation for parallel agents
- **Where:** `fieldcraft_graph/executor.py` fan-out runs N coder nodes writing to one shared workdir.
- **Problem:** safe today only because demo sub-tasks touch disjoint files; two branches on one file = lost-write race.
- **Remediation:** per-branch worktrees/copies, merged deliberately with real conflict detection.

---

## P2 — scale & operations

- **P2-1 · Horizontal scale:** move off single-process SQLite + in-memory caches (Postgres + Redis) so more than one instance can run without double-spend/divergent caches.
- **P2-2 · Observability:** structured logging, tracing with correlation IDs across graph nodes, metrics export, alerting. Today the app is blind in production.
- **P2-3 · Robust error handling:** replace broad `except Exception` swallows (report compute, live parse) with typed handling that surfaces failures; validate the API `policy` dict before it reaches the engine.
- **P2-4 · Adversarial test suite:** current 96 tests exercise the machinery but are largely mocks-testing-mocks; add tests for an agent trying to escape the sandbox, defeat policy, or game the judge.

---

## Sequencing note

Deploy the current system first (with `FC_ALLOW_LIVE=0` and locked CORS) so every change below is verified against a running baseline. Then work top-down: the P0 set is the foundation the vision's connection fabric stands on. Multi-model support (per-provider keys/budgets) should land **after** P0-1/P0-2/P0-4, since more keys multiply the spend-safety and secret-handling surface.
