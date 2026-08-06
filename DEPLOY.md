# Deploying the Fieldcraft POC

The service is hardened for a public deployment and containerized. It runs
**offline by default** (mock agent + behavioral judge, `FC_ALLOW_LIVE=0`), so you
can expose it with zero API spend; flip live mode on when you want the real agent.

## Set these before you expose the app

```bash
fly secrets set FC_INVITE_CODES="a-long-random-code,another-for-a-second-user"
fly secrets set FC_SECRET_KEY="$(openssl rand -hex 32)"
```

- `FC_INVITE_CODES` — comma-separated access codes. **Unset = the app is open to
  anyone with the URL**, every visitor shares one `legacy` tenant, and `/healthz`
  reports `auth_enabled: false` (the fallback is deliberate, but it is not a
  deployment posture). Each distinct code is a distinct tenant: users only ever see
  their own briefs, events, and connected repos.
- `FC_SECRET_KEY` — signs the session cookie. Unset means a random key per boot, so
  everyone is logged out on restart. Rotating it logs everyone out; rotating a code
  revokes that one holder (there is no per-session revocation).
- Treat codes as bearer secrets: anyone a code is forwarded to becomes that tenant.
  Neither the codes nor the key are ever logged or returned by an endpoint.

This is invite-code gating with per-user data isolation — **not** SSO, accounts, or
roles. See HARDENING.md P0-2 for the precise claim.

## What's hardened

- **Auth + tenant isolation** — every state-reading/-changing API route requires a signed
  session cookie (`itsdangerous`, expiring, `HttpOnly`/`SameSite=Lax`/`Secure` behind https);
  only the SPA shell, `/healthz`, and `POST /api/session` are public. Runs carry a `user_id`,
  and another tenant's brief returns **404** rather than 403 so existence never leaks.
- **Per-IP rate limiting** — `FC_BRIEFS_PER_HOUR` briefs per IP per rolling hour (429 over limit).
- **Spend caps** — per-run budget clamp (`FC_MAX_BUDGET_PER_RUN_USD`) and a global
  `FC_DAILY_COST_CAP_USD` that pauses live runs once hit.
- **Concurrency limit** — `FC_MAX_CONCURRENT` simultaneous runs (503 over limit).
- **Request clamps** — iterations/budget are clamped to safe bounds server-side.
- **Hardened code execution** — every test/build command runs through the single
  chokepoint `fieldcraft_loop/sandbox.py:run_sandboxed`: an environment **built from an
  allowlist** (no `ANTHROPIC_API_KEY`, no `FC_*`/`AWS_*`/`*_TOKEN`, no proxy vars),
  POSIX resource limits (`FC_SANDBOX_CPU_S`, `FC_SANDBOX_MEM_MB`, `FC_SANDBOX_NPROC`,
  `FC_SANDBOX_FSIZE_MB`, no core dumps), a wall-clock timeout that kills the whole
  **process group**, and argv-only invocation (never `shell=True`). The container also
  runs as a **non-root** user. `GET /healthz` reports `sandbox_limits` — the limits that
  machine actually applied, so the claim is verifiable rather than assumed.
  **Not** provided: filesystem isolation (same OS user), and **not** network isolation —
  executed code *can* open sockets. See below.
- **Durable history** — completed runs + AARs persist in SQLite and survive restart;
  runs interrupted by a restart are reconciled to `interrupted`.
- **Health check** — `GET /healthz` (used by the container + Fly checks).
- **Connected repos are read-only and bounded** — `POST /api/repos/connect` shallow-clones
  a **public** `https://github.com/<owner>/<repo>` URL (no credentials, nothing pushed back),
  rebuilds the clone URL from the validated owner/repo (so nothing user-typed reaches git),
  times out at `FC_CLONE_TIMEOUT_S`, and deletes any clone over `FC_MAX_REPO_MB`. Connected
  repos run with the **mock agent only**, so this path never spends. Caveat: the size cap is
  measured *after* the clone (git has no size limit flag) — the timeout is what bounds the
  download itself. Dependencies are not installed, so a repo needing them reports `0/0`
  tests rather than a score. A connected repo's tests run through `run_sandboxed`
  (credential-free, resource-limited) but **not** in an isolated machine — see below.

## Network egress: what is and is not restricted

Executed test code **can open network sockets**. Nothing in this deployment blocks
that, and nothing in the code claims to. What we do control inside the container:

- the child inherits **no proxy configuration** (`HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`
  are never copied) and **no credentials**, so a request it makes carries nothing of ours;
- CPU/memory/file-size limits and the process-group timeout bound how long it can keep
  trying.

True egress control is not available to a process inside a single Fly Machine without
extra infrastructure. **TODO (future work, HARDENING P0-1):** run each execution on a
disposable **isolated Fly Machine** with an egress-restricted network (or gVisor/
Firecracker), and drop the in-container path to a dev-only fallback. Until that exists,
deploy with `FC_ALLOW_LIVE=0`, keep `FC_MAX_CONCURRENT` low, and treat a connected repo's
test suite as untrusted code with internet access running as the app user.

## Deploy to Fly.io

```bash
fly launch --no-deploy        # or: fly apps create fieldcraft-poc  (fly.toml is included)
fly volumes create fieldcraft_data --size 1        # durable SQLite
fly deploy
```

To enable the **live agent/judge** (real Claude, real spend):

```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set FC_ALLOW_LIVE=1
```

Keep the caps conservative when live: `FC_DAILY_COST_CAP_USD` and
`FC_MAX_BUDGET_PER_RUN_USD` are your blast-radius limits.

## Portable to any container host

The Dockerfile is standard — Render, Railway, or Cloud Run work the same way:
build the image, mount a volume at `FC_DATA_DIR` (`/data`), expose port 8000,
set the `FC_*` env vars.

## Honest limits of this POC

- **Single-instance guards.** The rate limiter, cost tracker, and concurrency
  guard are in-memory — correct for one machine. Multi-instance needs a shared
  store (Redis).
- **Process-level sandbox.** Non-root + timeouts bound the test subprocess, which
  is fine for this trusted sample task. For *untrusted* agent code at scale, add
  stronger isolation (gVisor/Firecracker, per-run containers, or Judge0).
- **Durable, resumable runs.** Run state lives entirely in SQLite (+ the workdir),
  so a run paused for human review **survives a restart** and is resumed by whichever
  process is up. Background threads only *drive* the engine; killing one loses at most
  the in-flight turn, which is safely re-advanced on restart.

## Env reference

| Var | Default | Meaning |
|---|---|---|
| `FC_INVITE_CODES` | *(unset)* | comma-separated access codes; unset = **open deployment** |
| `FC_SECRET_KEY` | *(random per boot)* | session-cookie signing key |
| `FC_SESSION_TTL_S` | `604800` | session lifetime (7 days) |
| `FC_ALLOW_LIVE` | `0` | enable claude/tool-use (needs `ANTHROPIC_API_KEY`) |
| `FC_BRIEFS_PER_HOUR` | `10` | per-IP brief rate limit |
| `FC_MAX_CONCURRENT` | `4` | simultaneous runs |
| `FC_DAILY_COST_CAP_USD` | `5` | global daily live-spend ceiling |
| `FC_MAX_BUDGET_PER_RUN_USD` | `1` | per-run budget clamp |
| `FC_MAX_ITERATIONS` | `6` | per-run iteration clamp |
| `FC_PYTEST_TIMEOUT_S` | `30` | test subprocess timeout |
| `FC_SANDBOX_CPU_S` | `60` | CPU-second limit per executed command |
| `FC_SANDBOX_MEM_MB` | `512` | address-space limit per executed command |
| `FC_SANDBOX_NPROC` | `256` | process limit (Linux only; per-UID) |
| `FC_SANDBOX_FSIZE_MB` | `64` | max file size an executed command may write |
| `FC_MAX_REPO_MB` | `50` | size cap on a connected GitHub repo |
| `FC_CLONE_TIMEOUT_S` | `60` | `git clone` timeout for a connected repo |
| `FC_DATA_DIR` | `out/web` (`/data` in container) | SQLite location |
| `FC_CORS_ORIGINS` | `*` | allowed origins |
