"""Fieldcraft POC — production server on the resumable engine.

Uses the step-based Engine so runs are durable: a run paused for human review
survives a restart and is resumed by whichever process is up. Background threads
merely *drive* advance() (they hold no run state), so killing them loses at most
the in-flight turn. Keeps the Phase-D hardening: rate limits, spend caps,
concurrency guard, request clamps, health check, CORS.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from fieldcraft_loop import github_source
from fieldcraft_loop.engine import Engine, TERMINAL
from .config import settings
from .limits import RateLimiter, CostTracker, Concurrency

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FC_DATA_DIR", ROOT / "out" / "web"))
STATIC = Path(__file__).resolve().parent / "static"
TASK_DIR = str(ROOT / "sample_task")

TASKS = {
    "redact_pii": (ROOT / "sample_task", "single"),
    "slugify": (ROOT / "tasks" / "slugify", "single"),
    "parse_bool": (ROOT / "tasks" / "parse_bool", "single"),
    "chunk": (ROOT / "tasks" / "chunk", "single"),
    "textkit (multi-file repo)": (ROOT / "repo_tasks" / "textkit", "repo"),
}

# repo tasks built at runtime from a connected public GitHub repo: handle -> task dir
CONNECTED: dict[str, Path] = {}

engine = Engine(DATA)
rate = RateLimiter(settings.briefs_per_hour)
cost = CostTracker()
conc = Concurrency(settings.max_concurrent)

app = FastAPI(title="Fieldcraft POC")
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


def _drive(bid: str, gated: bool):
    """Run advance() in the background; account cost + release the slot at the end."""
    def run():
        try:
            r = engine.advance(bid)
        finally:
            if gated:
                conc.release()
        if r and r["status"] in TERMINAL:
            cost.add(r["total_cost"])
    threading.Thread(target=run, daemon=True).start()


@app.on_event("startup")
def _resume():
    stuck = engine.runnable_after_restart()
    for bid in stuck:
        _drive(bid, gated=False)     # resume interrupted runs
    if stuck:
        print(f"[startup] resuming {len(stuck)} interrupted run(s)")


class CreateBrief(BaseModel):
    task: str = "redact_pii"
    adapter: str = "mock"
    grader: str = "behavioral"
    review: str = "human"
    max_iterations: int = 5
    budget: float = 2.0
    policy: dict | None = None


class ReviewReq(BaseModel):
    kind: str
    comment: str = ""


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")


@app.get("/healthz")
def healthz():
    return {"ok": True, "active_runs": conc.active,
            "daily_cost_remaining": cost.remaining(settings.daily_cost_cap_usd)}


@app.post("/api/briefs")
def create_brief(req: CreateBrief, request: Request):
    if not rate.allow(client_ip(request)):
        raise HTTPException(429, "rate limit: too many briefs from your IP, try later")
    connected = req.task in CONNECTED
    if connected and (req.adapter != "mock" or req.grader == "tooluse"):
        raise HTTPException(403, "connected repos run with the offline mock agent only "
                                 "(adapter='mock', grader='behavioral')")
    live = req.adapter == "claude" or req.grader == "tooluse"
    if live and not settings.allow_live:
        raise HTTPException(403, "live mode is disabled on this deployment")
    if live and cost.remaining(settings.daily_cost_cap_usd) <= 0:
        raise HTTPException(429, "daily spend cap reached; live runs paused until tomorrow")
    if not conc.acquire():
        raise HTTPException(503, "too many concurrent runs; try again shortly")

    req.max_iterations = max(1, min(req.max_iterations, settings.max_iterations_cap))
    req.budget = max(0.1, min(req.budget, settings.max_budget_per_run_usd))
    goal = ("Make the connected repository's test suite pass" if connected else
            "Implement redact_pii so all tests and acceptance criteria pass")
    cfg = {**req.model_dump(), "goal": goal}
    task_dir = str(CONNECTED[req.task] if connected
                   else TASKS.get(req.task, (Path(TASK_DIR), "single"))[0])
    bid = engine.create(cfg, task_dir)
    _drive(bid, gated=True)
    return {"brief_id": bid, "config": req.model_dump()}


@app.get("/api/briefs/{brief_id}")
def get_brief(brief_id: str):
    r = engine.get(brief_id)
    if not r:
        raise HTTPException(404, "unknown brief")
    return {"brief_id": brief_id, "status": r["status"],
            "awaiting_review": r["status"] == "awaiting_review",
            "aar": engine.aar(r) if r["status"] in TERMINAL else None}


@app.get("/api/briefs/{brief_id}/events")
def get_events(brief_id: str):
    return {"events": engine.get_events(brief_id)}


@app.get("/api/briefs/{brief_id}/pending")
def get_pending(brief_id: str):
    return {"pending": engine.pending(brief_id)}


@app.post("/api/briefs/{brief_id}/review")
def submit_review(brief_id: str, req: ReviewReq):
    r = engine.get(brief_id)
    if not r:
        raise HTTPException(404, "unknown brief")
    if r["status"] != "awaiting_review":
        raise HTTPException(409, "not awaiting review")
    if req.kind not in ("approve", "changes", "reject"):
        raise HTTPException(400, "kind must be approve | changes | reject")
    after = engine.submit_review(brief_id, req.kind, req.comment[:2000])
    if after and after["status"] == "running":
        _drive(brief_id, gated=False)     # resume without gating (bounded by max_iterations)
    return {"ok": True}


@app.get("/api/tasks")
def list_tasks():
    out = [{"name": n, "kind": k} for n, (_, k) in TASKS.items()]
    out += [{"name": n, "kind": "repo"} for n in CONNECTED]
    return {"tasks": out}


class ConnectRepo(BaseModel):
    url: str


@app.post("/api/repos/connect")
def connect_repo(req: ConnectRepo, request: Request):
    """Shallow-clone a public GitHub repo and turn it into a runnable repo task.

    Read-only and offline: nothing is pushed back, and no agent runs here — the
    caller starts a normal brief against the returned handle (mock adapter only,
    so FC_ALLOW_LIVE is untouched by this path).
    """
    if not rate.allow(client_ip(request)):
        raise HTTPException(429, "rate limit: too many requests from your IP, try later")
    if not conc.acquire():                       # a clone is real work; bound it
        raise HTTPException(503, "too many concurrent runs; try again shortly")
    try:
        owner, name = github_source.parse_repo_url(req.url)
        handle = f"{owner}/{name} (connected)"
        tdir = DATA / "connected" / f"{owner}-{name}-{uuid.uuid4().hex[:6]}"
        info = github_source.clone_public_repo(req.url, tdir / "repo")
        cmd = github_source.detect_test_command(info.path)
        (tdir / "task.json").write_text(json.dumps(
            {"name": handle, "kind": "repo", "repo_dir": "repo", "test_command": cmd,
             "protected_paths": github_source.DEFAULT_PROTECTED}))
    except github_source.GitHubSourceError as e:
        raise HTTPException(400, str(e))
    finally:
        conc.release()

    CONNECTED[handle] = tdir
    return {"task": handle, "adapter": "mock", "kind": "repo", "test_command": cmd,
            "protected_paths": github_source.DEFAULT_PROTECTED,
            "tests_detected": github_source.has_tests(info.path),
            "repo": {"owner": info.owner, "name": info.name, "url": info.url,
                     "default_branch": info.default_branch,
                     "file_count": info.file_count, "size_mb": info.size_mb}}


# --- differentiator reports (computed lazily on first request, then cached) ---
import dataclasses  # noqa: E402

_REPORTS: dict = {}


def _rep_benchmark():
    from fieldcraft_bench.run import benchmark
    return benchmark()


def _rep_measurement():
    from fieldcraft_measure.run import measure
    r = measure()
    return {"scorecards": [dataclasses.asdict(c) for c in r["cards"]],
            "diffs": r["diffs"], "effect": r["effect"]}


def _rep_flywheel():
    from fieldcraft_guide.flywheel import demo
    return demo(str(ROOT / "sample_task"))


def _rep_governance():
    from fieldcraft_loop.repo_task import apply_patch, snapshot, multi_file_diff
    from fieldcraft_aar.models import RunTrace, Turn
    from fieldcraft_gov.report import governance_summary
    from fieldcraft_gov.credentials import CredentialBroker

    class _V:
        def turn(self, task_dir, workdir, feedback, turn_index):
            before = snapshot(workdir)
            apply_patch(Path(task_dir) / ".solution", workdir)
            (workdir / "config.py").write_text('API_KEY = "AKIA1234567890ABCDEF"\n')
            return RunTrace(condition="t1", adapter="violator", spec_completeness=0.9,
                            turns=[Turn(cost_usd=0.09, tool_calls=3, event="progress", note="")],
                            wall_clock_s=1.0, diff=multi_file_diff(before, snapshot(workdir)))
    import tempfile
    e = Engine(tempfile.mkdtemp())
    e._adapter = lambda cfg: _V()
    b = e.create({"adapter": "mock", "review": "auto",
                  "policy": {"editable_paths": ["textkit/**", "config.py"], "protected_paths": ["tests/"]}},
                 str(ROOT / "repo_tasks" / "textkit"))
    e.advance(b)
    gov = governance_summary(e.get_events(b))
    br = CredentialBroker()
    g = br.issue("BRIEF-demo", ["repo:read", "tests:run"], ttl_s=300)
    creds = [{"cap": "tests:run", "allowed": br.check(g.grant_id, "tests:run")},
             {"cap": "repo:write", "allowed": br.check(g.grant_id, "repo:write")}]
    br.revoke(g.grant_id)
    creds.append({"cap": "tests:run (after revoke)", "allowed": br.check(g.grant_id, "tests:run")})
    return {"final_state": e.aar(e.get(b))["final_state"], "governance": gov,
            "grant_scope": sorted(g.capabilities), "credential_checks": creds,
            "audit_entries": len(br.audit)}


_REPORT_FNS = {"benchmark": _rep_benchmark, "measurement": _rep_measurement,
               "flywheel": _rep_flywheel, "governance": _rep_governance}


def _compute_report(kind: str):
    try:
        _REPORTS[kind] = {"status": "ready", "data": _REPORT_FNS[kind]()}
    except Exception as e:  # surface, don't hang
        _REPORTS[kind] = {"status": "error", "error": repr(e)}


@app.get("/api/reports/{kind}")
def get_report(kind: str):
    if kind not in _REPORT_FNS:
        raise HTTPException(404, "unknown report")
    r = _REPORTS.get(kind)
    if r is None:
        _REPORTS[kind] = {"status": "computing"}
        threading.Thread(target=_compute_report, args=(kind,), daemon=True).start()
        return {"status": "computing"}
    return r


@app.get("/api/briefs")
def list_briefs():
    out = []
    for r in engine.runs.list_all():
        cfg = r["config"]; td = cfg.get("task_dir", "")
        out.append({"brief_id": r["brief_id"], "status": r["status"],
                    "iteration": r["iteration"], "cost": round(r["total_cost"], 4),
                    "adapter": cfg.get("adapter", ""), "policy": bool(cfg.get("policy")),
                    "task": Path(td).name if td else "", "created": r["created"]})
    return {"briefs": out}


def _sse(event: str, data) -> str:
    import json as _j
    return f"event: {event}\ndata: {_j.dumps(data)}\n\n"


@app.get("/api/briefs/{bid}/stream")
async def stream(bid: str):
    import asyncio

    async def gen():
        seen = 0
        for _ in range(2400):                       # ~12 min ceiling
            r = engine.get(bid)
            if not r:
                yield _sse("state", {"status": "error"}); return
            ev = engine.get_events(bid)
            for e in ev[seen:]:
                yield _sse("event", e)
            seen = len(ev)
            st = r["status"]
            if st in ("done", "needs_human", "error"):
                yield _sse("state", {"status": st, "aar": engine.aar(r)}); return
            if st == "awaiting_review":
                yield _sse("state", {"status": "awaiting_review", "pending": engine.pending(bid)}); return
            await asyncio.sleep(0.3)
        yield _sse("state", {"status": "timeout"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
