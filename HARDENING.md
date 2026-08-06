# Fieldcraft — Hardening Backlog

Prioritized from a senior-architecture review of the current codebase, scoped against the platform in `VISION.md`. Severity is stated as **current exposure** (the app today: local/offline, mock agents) vs **vision-blocking** (the risk once agents can act across a customer's trust boundary — real repos, cloud, databases, live models). Most items are low-risk today and existential for the vision; the vision defines the priority, not the current demo.

Legend: **P0** = must exist before any real/untrusted connection is wired. **P1** = correctness/trust foundations. **P2** = scale/ops.

---

## P0 — prerequisites for the vision

### P0-1 · Sandboxed, credential-free code execution
- **Where:** `fieldcraft_loop/repo_task.py:run_tests`, `fieldcraft_aar/effectiveness.py:run_pytest` — both `subprocess.run(cmd, cwd=workdir)` with only a timeout.
- **Problem:** agent-authored code is executed with no isolation (no container/microVM, no filesystem/network/user isolation), in a process that holds `ANTHROPIC_API_KEY` in its environment. Executed code can read env, open sockets, and exfiltrate.
- **Current exposure:** low (mock, local, trusted tasks). **Vision:** existential — running untrusted repos or credentialed tasks unsandboxed = customer breach.
- **Remediation:** move execution into a disposable, network-egress-controlled sandbox (gVisor/Firecracker or a locked-down container) with **no ambient credentials**; inject secrets only via short-lived brokered tokens, never process env.

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
