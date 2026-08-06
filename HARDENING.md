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

### P0-2 · Authentication + tenant isolation — **ADDRESSED for single-operator multi-user**
*Enterprise identity (SSO/OIDC), RBAC, and org-level tenancy are still future work.*

- **Where:** `fieldcraft_web/auth.py` (sessions + tenant key), `fieldcraft_web/server.py` (the `require_session` dependency and per-tenant scoping), `fieldcraft_loop/run_store.py` (`user_id` column).

**What exists now:**
- **Invite-code sessions.** An operator sets `FC_INVITE_CODES` (comma-separated); `POST /api/session` exchanges a code for a signed, expiring cookie. Signing is `itsdangerous.URLSafeTimedSerializer` with `FC_SECRET_KEY`; code comparison is `hmac.compare_digest` over every configured code with no early exit. No hand-rolled crypto, and codes/keys are never logged or echoed.
- **Every API route that reads or changes state requires a session** (`require_session`): `/api/briefs` (create/list/get/events/pending/stream/review), `/api/repos/connect`, `/api/tasks`, `/api/reports/*`. Only `GET /` (the SPA shell), `/healthz`, and `POST /api/session` are public.
- **A tenant column, threaded through.** `runs.user_id` (indexed) with `user_id` on `RunStore.create/get/list_all/list_status` and on `Engine.create/get/get_events/pending/submit_review`. A user_id is `hmac(server_salt, code)`, so the same code keeps its data across restarts and two codes are two tenants; the salt is generated per deployment and persisted next to the databases.
- **Cross-tenant access 404s, never 403** — the reads are filtered in SQL, so another user's brief is simply not there and its existence never leaks. Events are gated by the run's ownership rather than duplicating the tenant onto every event row.
- **Connected repos are per-tenant** (`CONNECTED[user_id][handle]`); the report cache stays shared *because* every report is computed from repo-bundled fixture tasks in a throwaway directory and contains no user data — reading one still needs a session.
- **Migration.** `RunStore._migrate()` adds the column in place; pre-tenancy rows keep `user_id IS NULL`, are read as the reserved `legacy` tenant, and are therefore visible only in unauthenticated fallback mode.
- **Fallback is loud, not silent.** With no codes configured the app stays open exactly as before (everyone is `legacy`), but logs a startup warning and reports `auth_enabled: false` on `/healthz`.

**What this is not — do not oversell it:**
- No email/OAuth/SSO/OIDC, no user directory, no account recovery. A code *is* the identity.
- **No roles or permissions.** Every session has identical rights over its own data; there is no admin/read-only distinction.
- **No per-session revocation.** Cutting off one holder means rotating that code (or `FC_SECRET_KEY`, which logs everyone out). Codes are bearer secrets — anyone they are forwarded to becomes that tenant.
- **No org/team concept**, no per-tenant rate or spend accounting (limits are still global/per-IP), and no CSRF token (the cookie is `SameSite=Lax`, `HttpOnly`, and `Secure` behind https, which is the mitigation being relied on).
- Tenancy covers runs, events, and connected repos. **Workdirs on disk are not separated by user**, and the sandbox does not isolate them (see P0-1) — a test suite executing as the app user can still reach another tenant's workdir on disk.
- **Remaining work:** real identity (OIDC/SSO), roles, org-level tenancy with a durable per-tenant quota, and filesystem separation of workdirs.

### P0-3 · Real scoped-credential backend
- **Where:** `fieldcraft_gov/credentials.py` — `CredentialBroker` is an in-memory dict of capability strings; audit is an in-memory list lost on restart.
- **Problem:** fine as a *model*, nowhere near "agents get scoped CRUD on a customer's AWS/DB." No real secret storage, IAM/STS integration, or durable audit.
- **Remediation:** keep the interface; back it with real short-lived scoped tokens (STS/KMS-style), durable audit, and **destructive-op approval enforced at grant time** (broker denies `delete` without an approval token) — not in loop code.

### P0-4 · Durable, transactional spend/rate enforcement — **ADDRESSED for single-node**
*Multi-instance correctness still requires a shared store.*

- **Where:** `fieldcraft_web/ledger.py` (SQLite in `FC_DATA_DIR`, alongside the run/event stores), wired into `create_brief`, `_drive`/`submit_review`, and `/healthz`.
- **Original problem:** `RateLimiter`/`CostTracker` held counters in process memory, so a restart or crash-loop reset the daily spend cap.

**What exists now:**
- **Reserve → settle/release.** A brief reserves its clamped per-run budget *before* it is created; the run's terminal state settles the reservation to the cost the loop actually reported (up or down); a failure to start releases it. `settle` is idempotent, so a retried or double-driven run cannot double-charge.
- **One transaction per decision.** `reserve()` checks the per-IP rolling-hour rate, the global daily cap, and the **new per-user daily cap** (`FC_USER_DAILY_COST_CAP_USD`, default 1) and inserts the reservation inside a single `BEGIN IMMEDIATE`, under the store lock. Denials name the limit (`rate` | `global_daily` | `user_daily`) and record nothing. Tested: 20 threads racing for a cap that fits 4 → exactly 4 win, total never exceeds the cap.
- **Durable.** Spend and rate rows persist in SQLite: reopening the ledger from the same directory preserves the day's spend, and an *unsettled* reservation survives a restart and can still be settled. Tested as the headline P0-4 property.
- **Windows.** UTC calendar day for cost, rolling hour for rate; rows older than two days are pruned on write. `/healthz.daily_cost_remaining` is read from the ledger, not memory.
- **Concurrency stays in memory on purpose** (`limits.py:Concurrency`): it bounds live threads in this process, not money, so there is nothing to carry across a restart. `RateLimiter`/`CostTracker` are superseded and no longer wired in.

**What this does not claim:**
- **Single-node only.** Correctness rests on `BEGIN IMMEDIATE` over one SQLite file. Two instances on separate volumes would each enforce their own cap and could double-spend. Multi-instance needs the ledger in Postgres/Redis (P2-1).
- **Best-effort against provider-side truth.** We settle what the loop reports the agent spent; the provider's accounting is authoritative. Under-reported cost is under-recorded here.
- **Enforced per brief, not per API call.** A single run can overshoot its reservation before it settles; the engine's per-run budget clamp is what bounds that overshoot, and the cap is what bounds how many runs may start.
- **Offline runs reserve and settle but do not *block* on the money caps** (`enforce_cost=False`), matching prior behaviour: their costs are simulated, so blocking a $0 mock run on a dollar ceiling would be a false guard. Their simulated cost is still recorded and still shows in `daily_cost_remaining`, so — as before — heavy mock use can draw the displayed global budget down and gate live runs.

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

### P1-3 · Judge trust: variance + held-out calibration — **PARTIALLY ADDRESSED**
*Variance is now measured across 5 live runs; a held-out set and an ensemble are still future work.*

- **Where:** `fieldcraft_aar/calibration.py`; results recorded in [`docs/CALIBRATION.md`](docs/CALIBRATION.md).
- **Measured (5 live runs against the Anthropic API, forced tool-use judge, 38 labeled fixtures = 152 judgments per run):** mean Cohen's kappa **0.886**, range 0.856–0.916, **SD 0.022**; mean agreement 94.5%. Per-criterion agreement is 1.000 on AC1/AC2/AC3 and 0.779 on AC4.
- **Failure mode is characterized, not just quantified:** all 42 disagreements across 760 judgments were the judge predicting `unmet` where the label was `met`, on AC4 (idempotence), concentrated on edge-case fixtures (`empty_out.py` and part of the `gen_0NN` set). There were **no false `met` verdicts** — the bias is conservative, so a score from this judge is a floor, not an inflated ceiling. Because the same fixture family fails each run, most of the kappa spread is a handful of borderline cases flipping rather than broad instability.
- **Still open:** the fixture set is **fixed and committed, so it can be tuned against** (Goodhart) — a refreshed held-out set is outstanding; there is no ensemble or disagreement-flagging, so one judge miss still passes through silently; and this is one task, one fixture set, one model, five runs — not a broad study, and it does not transfer to other criteria or a changed prompt/model.
- **Remediation (remaining):** maintain a refreshed held-out calibration set; add an ensemble / disagreement-flagging path; re-run calibration on any model, prompt, or criteria change and commit the result alongside the existing table.

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
