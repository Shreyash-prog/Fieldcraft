"""Fieldcraft POC — production server on the resumable engine.

Uses the step-based Engine so runs are durable: a run paused for human review
survives a restart and is resumed by whichever process is up. Background threads
merely *drive* advance() (they hold no run state), so killing them loses at most
the in-flight turn. Keeps the Phase-D hardening: rate limits, spend caps,
concurrency guard, request clamps, health check, CORS.
"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from fieldcraft_loop.engine import Engine, TERMINAL
from .config import settings
from .limits import RateLimiter, CostTracker, Concurrency

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FC_DATA_DIR", ROOT / "out" / "web"))
STATIC = Path(__file__).resolve().parent / "static"
TASK_DIR = str(ROOT / "sample_task")

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
    adapter: str = "mock"
    grader: str = "behavioral"
    review: str = "human"
    max_iterations: int = 5
    budget: float = 2.0


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
    live = req.adapter == "claude" or req.grader == "tooluse"
    if live and not settings.allow_live:
        raise HTTPException(403, "live mode is disabled on this deployment")
    if live and cost.remaining(settings.daily_cost_cap_usd) <= 0:
        raise HTTPException(429, "daily spend cap reached; live runs paused until tomorrow")
    if not conc.acquire():
        raise HTTPException(503, "too many concurrent runs; try again shortly")

    req.max_iterations = max(1, min(req.max_iterations, settings.max_iterations_cap))
    req.budget = max(0.1, min(req.budget, settings.max_budget_per_run_usd))
    cfg = {**req.model_dump(),
           "goal": "Implement redact_pii so all tests and acceptance criteria pass"}
    bid = engine.create(cfg, TASK_DIR)
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
