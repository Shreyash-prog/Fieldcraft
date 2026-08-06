# Deploying the Fieldcraft POC

The service is hardened for a public deployment and containerized. It runs
**offline by default** (mock agent + behavioral judge, `FC_ALLOW_LIVE=0`), so you
can expose it with zero API spend; flip live mode on when you want the real agent.

## What's hardened

- **Per-IP rate limiting** — `FC_BRIEFS_PER_HOUR` briefs per IP per rolling hour (429 over limit).
- **Spend caps** — per-run budget clamp (`FC_MAX_BUDGET_PER_RUN_USD`) and a global
  `FC_DAILY_COST_CAP_USD` that pauses live runs once hit.
- **Concurrency limit** — `FC_MAX_CONCURRENT` simultaneous runs (503 over limit).
- **Request clamps** — iterations/budget are clamped to safe bounds server-side.
- **Sandbox hygiene** — the container runs as a **non-root** user and every test
  subprocess is bounded by `FC_PYTEST_TIMEOUT_S` (a timeout is a failed verdict, not a hang).
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
  tests rather than a score. Running a connected repo's tests is still unsandboxed
  execution (HARDENING P0-1).

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
| `FC_ALLOW_LIVE` | `0` | enable claude/tool-use (needs `ANTHROPIC_API_KEY`) |
| `FC_BRIEFS_PER_HOUR` | `10` | per-IP brief rate limit |
| `FC_MAX_CONCURRENT` | `4` | simultaneous runs |
| `FC_DAILY_COST_CAP_USD` | `5` | global daily live-spend ceiling |
| `FC_MAX_BUDGET_PER_RUN_USD` | `1` | per-run budget clamp |
| `FC_MAX_ITERATIONS` | `6` | per-run iteration clamp |
| `FC_PYTEST_TIMEOUT_S` | `30` | test subprocess timeout |
| `FC_MAX_REPO_MB` | `50` | size cap on a connected GitHub repo |
| `FC_CLONE_TIMEOUT_S` | `60` | `git clone` timeout for a connected repo |
| `FC_DATA_DIR` | `out/web` (`/data` in container) | SQLite location |
| `FC_CORS_ORIGINS` | `*` | allowed origins |
