"""Fieldcraft POC — production server on the resumable engine.

Uses the step-based Engine so runs are durable: a run paused for human review
survives a restart and is resumed by whichever process is up. Background threads
merely *drive* advance() (they hold no run state), so killing them loses at most
the in-flight turn. Keeps the Phase-D hardening: rate limits, spend caps,
concurrency guard, request clamps, health check, CORS.

Every API route that reads or changes state requires a session and is scoped to
that session's tenant (`auth.py`); only the SPA shell, /healthz and /api/session
are public. With no invite codes configured the app stays open exactly as it was,
but says so on /healthz — see `auth.py` for the (narrow) claim being made.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fieldcraft_loop import comparison as cmp_mod
from fieldcraft_loop import github_source, sandbox
from fieldcraft_loop.engine import Engine, TERMINAL
from fieldcraft_loop.pdf_context import PdfContextError, PdfStore
from fieldcraft_loop.ticket_store import STATUSES, TicketStore
from . import auth as auth_mod
from . import invite_store
from .config import settings
from .invite_store import InviteStore
from .ledger import Ledger
from .limits import Concurrency

log = logging.getLogger(__name__)

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

# repo tasks built at runtime from a connected public GitHub repo, per tenant:
# user_id -> handle -> task dir. Never shared across users.
CONNECTED: dict[str, dict[str, Path]] = {}

engine = Engine(DATA)
# Spend + rate live in the durable ledger (survives restart, enforced in one
# transaction). Concurrency stays in memory on purpose: it bounds live threads in
# *this* process, not money, so there is nothing to carry across a restart.
ledger = Ledger(DATA / "ledger.db", global_cap=settings.daily_cost_cap_usd,
                user_cap=settings.user_daily_cost_cap_usd,
                rate_per_hour=settings.briefs_per_hour)
conc = Concurrency(settings.max_concurrent)
auth = auth_mod.from_env(DATA)
# Who may use this deployment, and who operates it. Codes from FC_INVITE_CODES /
# FC_ADMIN_CODES are seeded as active invites so they keep working and become
# manageable (and revocable) — seeding never resurrects a revoked row.
invites = InviteStore(DATA / "invites.db")


def seed_env_invites(a=None, store=None) -> None:
    """Register every env-configured code as an active invite. Idempotent."""
    a, store = a or auth, store or invites
    for code, is_admin in a.env_invites():
        store.seed(a.code_hash(code), a.user_id(code), None, is_admin)


seed_env_invites()
tickets = TicketStore(DATA / "tickets.db")
# Ticket context (A2). Both are namespaced by user_id on disk, so one tenant's
# clone or PDF is not merely hidden from another — it is in a different tree.
pdfs = PdfStore(DATA / "ticket_pdfs", max_mb=settings.max_pdf_mb,
                max_pages=settings.max_pdf_pages,
                max_per_ticket=settings.max_pdfs_per_ticket)
TICKET_REPOS = DATA / "ticket_repos"
# Live three-mode comparisons, keyed "<user>:<ticket>". In memory on purpose:
# this is progress for a stream that lasts seconds. The *results* are durable —
# they land on the ticket's runs[] as each mode finishes.
COMPARISONS: dict[str, dict] = {}
COMPARISON_LOCK = threading.Lock()

app = FastAPI(title="Fieldcraft POC")
app.add_middleware(CORSMiddleware,
                   allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])


def require_session(request: Request) -> str:
    """The caller's tenant. 401 when auth is on and the cookie is missing/invalid
    **or the invite behind it is no longer active**; the reserved 'legacy' tenant
    when auth is disabled.

    The invite is re-checked on every request, which is what makes revocation
    immediate: a revoked code's outstanding session cookies stop working on the
    next call rather than when they expire.
    """
    uid = auth.current_user(request)
    if uid is None:
        raise auth_mod.unauthorized()
    if auth.enabled:
        inv = invites.by_user(uid)
        if not inv or inv["status"] != invite_store.ACTIVE:
            raise auth_mod.unauthorized()
        invites.touch(uid)
    return uid


def require_admin(request: Request) -> str:
    """The operator, or 404.

    Being logged in is never enough: the session's invite row must exist, be
    active, and carry is_admin. Three deliberate choices —

    * **404, not 403.** A regular invited user should not learn that an admin
      surface exists at all.
    * **Disabled when auth is disabled.** With no codes configured every visitor
      shares the `legacy` tenant, so there is no operator to distinguish and the
      admin surface would be world-open. It fails closed instead.
    * **No env-only shortcut.** Admin-ness is read from the store, so revoking an
      admin invite removes admin access too.
    """
    if not auth.enabled:
        raise HTTPException(404, "not found")
    uid = auth.current_user(request)
    if uid is None:
        raise HTTPException(404, "not found")
    inv = invites.by_user(uid)
    if not inv or inv["status"] != invite_store.ACTIVE or not inv["is_admin"]:
        raise HTTPException(404, "not found")
    return uid


def owned_run(bid: str, user: str) -> dict:
    """A run this tenant owns, or 404 — never 403, which would confirm it exists."""
    r = engine.get(bid, user)
    if not r:
        raise HTTPException(404, "unknown brief")
    return r


def _settle(r: dict | None) -> None:
    """Reconcile a finished run's reservation to what it actually cost. Safe to
    call more than once (settle is idempotent) and on non-terminal runs."""
    if r and r["status"] in TERMINAL:
        ledger.settle(r["config"].get("reservation_id", ""), r["total_cost"])


def _drive(bid: str, gated: bool):
    """Run advance() in the background; settle cost + release the slot at the end.

    The worker owns the run's liveness: if advance() raises (a missing package, a
    bad task dir, anything), the run is marked `error` with the message on the
    timeline and its reservation is settled. A thrown exception here used to kill
    the thread silently and leave the brief stuck on "running" forever.
    """
    def run():
        r = None
        try:
            r = engine.advance(bid)
        except Exception as e:                    # never let a worker die quietly
            log.exception("run %s failed in the background worker", bid)
            r = engine.fail(bid, f"{type(e).__name__}: {e}")
        finally:
            if gated:
                conc.release()
        try:
            _settle(r)                            # don't strand the reservation
        except Exception:                         # pragma: no cover - ledger is local
            log.exception("could not settle the reservation for run %s", bid)
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


class SessionReq(BaseModel):
    code: str


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")


@app.get("/healthz")
def healthz():
    return {"ok": True, "active_runs": conc.active,
            # read from the durable ledger, so a restart does not reset it
            "daily_cost_remaining": ledger.remaining_global(),
            # which sandbox limits this machine really applies — see sandbox.py
            "sandbox_limits": list(sandbox.effective_limits()),
            # false = no invite codes configured, so the deployment is open
            "auth_enabled": auth.enabled}


@app.post("/api/session")
def create_session(req: SessionReq, request: Request, response: Response):
    """Exchange an invite code for a signed, expiring session cookie."""
    if not ledger.hit("session:" + client_ip(request)):
        raise HTTPException(429, "too many attempts from your IP, try later")
    if not auth.enabled:
        return {"ok": True, "auth_enabled": False, "user": auth_mod.LEGACY_USER}
    code = req.code[:200]
    # The invite row is the authority. An env-configured code that has not been
    # seeded yet is seeded on first use, so FC_INVITE_CODES keeps working exactly
    # as before while still becoming manageable — and revocable.
    inv = invites.by_hash(auth.code_hash(code))
    if inv is None:
        uid = auth.user_for_code(code)                      # env code, first use
        if not uid:
            raise HTTPException(401, "invalid access code")  # never echo the code
        invites.seed(auth.code_hash(code), uid, None, auth.is_admin_code(code))
        inv = invites.by_hash(auth.code_hash(code))
    if not inv or inv["status"] != invite_store.ACTIVE or not inv["user_id"]:
        raise HTTPException(401, "invalid access code")
    uid = inv["user_id"]
    response.set_cookie(auth_mod.COOKIE, auth.issue(uid), max_age=auth.ttl_s,
                        httponly=True, samesite="lax", secure=auth_mod.secure_cookie(request))
    return {"ok": True, "auth_enabled": True, "user": uid, "is_admin": inv["is_admin"]}


@app.get("/api/me")
def whoami(request: Request):
    """Who the caller is, for the UI. Public: an anonymous caller gets
    authenticated=false rather than a 401, so the shell can render the gate."""
    uid = auth.current_user(request)
    inv = invites.by_user(uid) if (uid and auth.enabled) else None
    ok = bool(uid) and (not auth.enabled or (inv and inv["status"] == invite_store.ACTIVE))
    return {"authenticated": bool(ok), "auth_enabled": auth.enabled,
            "user": uid if ok else None,
            "is_admin": bool(auth.enabled and ok and inv and inv["is_admin"])}


# --- public access requests -------------------------------------------------
# Records an ask. It never grants anything: the row has no code, and the operator
# approves by hand in the admin view. Email delivery is MANUAL and out of band —
# nothing here sends mail, on purpose (no SMTP dependency, no deliverability
# surface). The operator reads the request and passes the code on however they like.

class AccessRequest(BaseModel):
    email: str


@app.post("/api/access/request")
def request_access(req: AccessRequest, request: Request):
    """PUBLIC. Rate-limited per IP; cannot self-approve."""
    if not ledger.hit("access:" + client_ip(request)):
        raise HTTPException(429, "too many requests from your IP, try later")
    if not invite_store.valid_email(req.email):
        raise HTTPException(400, "that does not look like an email address")
    invites.record_request(req.email)
    # The same answer whatever the row's real state, so this cannot be used to
    # probe who already has access.
    return {"ok": True, "message": "Request received. Access is approved by hand — "
                                   "if you're approved you'll get a code by email."}


# --- operator-only invite administration ------------------------------------
# Every route here depends on require_admin, which 404s for anyone who is not the
# operator, including a perfectly valid invited user.

class ApproveReq(BaseModel):
    email: str
    is_admin: bool = False


class RevokeReq(BaseModel):
    code: str | None = None
    email: str | None = None


def _invite_view(inv: dict) -> dict:
    """One row for the admin table, with its spend. No code, ever."""
    uid = inv.get("user_id") or ""
    return {**inv,
            "spent_today": ledger.spent_user(uid) if uid else 0.0,
            "remaining_today": ledger.remaining_user(uid) if uid else None}


@app.get("/api/admin/invites")
def admin_list_invites(_: str = Depends(require_admin)):
    # Report the caps the ledger actually enforces, not the ones settings was
    # configured with — if those ever diverge, the enforced number is the truth.
    return {"invites": [_invite_view(i) for i in invites.list_all()],
            "caps": {"user_daily": ledger.user_cap,
                     "global_daily": ledger.global_cap,
                     "global_remaining": ledger.remaining_global()},
            "statuses": list(invite_store.STATUSES)}


@app.post("/api/admin/invites/approve")
def admin_approve(req: ApproveReq, _: str = Depends(require_admin)):
    """Generate a code and activate the invite. The plaintext code is returned
    **once** — only its HMAC is stored, so it cannot be shown again."""
    if not invite_store.valid_email(req.email):
        raise HTTPException(400, "that does not look like an email address")
    code = auth_mod.new_code()
    inv = invites.approve(req.email, auth.code_hash(code), auth.user_id(code), req.is_admin)
    return {"ok": True, "code": code, "invite": _invite_view(inv),
            "note": "Copy this code now — it is stored hashed and cannot be shown again."}


@app.post("/api/admin/invites/revoke")
def admin_revoke(req: RevokeReq, _: str = Depends(require_admin)):
    """Revoke by code or by email. Takes effect on the revoked user's next
    request — require_session re-reads the invite every time."""
    inv = invites.revoke(code_hash=auth.code_hash(req.code) if req.code else None,
                         email=req.email)
    if not inv:
        raise HTTPException(404, "unknown invite")
    return {"ok": True, "invite": _invite_view(inv)}


@app.delete("/api/session")
def end_session(response: Response):
    response.delete_cookie(auth_mod.COOKIE)
    return {"ok": True}


@app.post("/api/briefs")
def create_brief(req: CreateBrief, request: Request, user: str = Depends(require_session)):
    mine = CONNECTED.get(user, {})
    connected = req.task in mine
    if connected and (req.adapter != "mock" or req.grader == "tooluse"):
        raise HTTPException(403, "connected repos run with the offline mock agent only "
                                 "(adapter='mock', grader='behavioral')")
    live = req.adapter == "claude" or req.grader == "tooluse"
    if live and not settings.allow_live:
        raise HTTPException(403, "live mode is disabled on this deployment")

    req.max_iterations = max(1, min(req.max_iterations, settings.max_iterations_cap))
    req.budget = max(0.1, min(req.budget, settings.max_budget_per_run_usd))

    # One transaction decides the rate limit and both spend caps, and holds the
    # money until the run settles. Offline runs reserve too (so the path is always
    # exercised and their simulated cost is still accounted) but the money caps
    # only *block* a run that can really spend — which is what they did before.
    res = ledger.reserve(user, client_ip(request), req.budget, enforce_cost=live)
    if not res.ok:
        raise HTTPException(429, res.message)
    if not conc.acquire():
        ledger.release(res.id)
        raise HTTPException(503, "too many concurrent runs; try again shortly")

    goal = ("Make the connected repository's test suite pass" if connected else
            "Implement redact_pii so all tests and acceptance criteria pass")
    cfg = {**req.model_dump(), "goal": goal, "reservation_id": res.id}
    task_dir = str(mine[req.task] if connected
                   else TASKS.get(req.task, (Path(TASK_DIR), "single"))[0])
    try:
        bid = engine.create(cfg, task_dir, user)
    except Exception:                      # nothing started: give the money back
        conc.release()
        ledger.release(res.id)
        raise
    _drive(bid, gated=True)
    return {"brief_id": bid, "config": req.model_dump()}


@app.get("/api/briefs/{brief_id}")
def get_brief(brief_id: str, user: str = Depends(require_session)):
    r = owned_run(brief_id, user)
    return {"brief_id": brief_id, "status": r["status"],
            "awaiting_review": r["status"] == "awaiting_review",
            "aar": engine.aar(r) if r["status"] in TERMINAL else None}


@app.get("/api/briefs/{brief_id}/events")
def get_events(brief_id: str, user: str = Depends(require_session)):
    owned_run(brief_id, user)
    return {"events": engine.get_events(brief_id, user)}


@app.get("/api/briefs/{brief_id}/pending")
def get_pending(brief_id: str, user: str = Depends(require_session)):
    owned_run(brief_id, user)
    return {"pending": engine.pending(brief_id, user)}


@app.post("/api/briefs/{brief_id}/review")
def submit_review(brief_id: str, req: ReviewReq, user: str = Depends(require_session)):
    r = owned_run(brief_id, user)
    if r["status"] != "awaiting_review":
        raise HTTPException(409, "not awaiting review")
    if req.kind not in ("approve", "changes", "reject"):
        raise HTTPException(400, "kind must be approve | changes | reject")
    after = engine.submit_review(brief_id, req.kind, req.comment[:2000], user)
    if after and after["status"] == "running":
        _drive(brief_id, gated=False)     # resume without gating (bounded by max_iterations)
    else:
        _settle(after)                    # approve/reject ends the run here
    return {"ok": True}


# --- board tickets ----------------------------------------------------------
class CreateTicket(BaseModel):
    title: str
    description: str = ""
    status: str = "backlog"


class PatchTicket(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None


def _check_status(status: str | None) -> None:
    if status is not None and status not in STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(STATUSES)}")


def _owned_ticket(tid: str, user: str) -> dict:
    """This tenant's ticket, or 404 — never 403, which would confirm it exists."""
    t = tickets.get(tid, user)
    if not t:
        raise HTTPException(404, "unknown ticket")
    return t


@app.post("/api/tickets")
def create_ticket(req: CreateTicket, user: str = Depends(require_session)):
    if not req.title.strip():
        raise HTTPException(400, "title is required")
    _check_status(req.status)
    return tickets.create(user, req.title, req.description, req.status)


@app.get("/api/tickets")
def list_tickets(user: str = Depends(require_session)):
    return {"tickets": tickets.list_for(user), "statuses": list(STATUSES)}


@app.get("/api/tickets/{tid}")
def get_ticket(tid: str, user: str = Depends(require_session)):
    return _owned_ticket(tid, user)


@app.patch("/api/tickets/{tid}")
def patch_ticket(tid: str, req: PatchTicket, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    if req.title is not None and not req.title.strip():
        raise HTTPException(400, "title cannot be empty")
    _check_status(req.status)
    return tickets.update(tid, user, **req.model_dump(exclude_unset=True))


@app.delete("/api/tickets/{tid}")
def delete_ticket(tid: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    ok = tickets.delete(tid, user)
    if ok:                                  # don't leave the context orphaned on disk
        _drop_ticket_repo(tid, user)
        try:
            pdfs.delete_ticket(user, tid)
        except PdfContextError:
            pass
    return {"ok": ok}


# --- ticket context: a connected repo (A2) ----------------------------------
# The same validated, credential-free clone the /api/repos/connect path uses —
# only the destination and the owning record differ: the clone lands under the
# tenant's own directory and the ticket keeps the handle. No agent runs here.
_PART = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class TicketRepo(BaseModel):
    url: str


def _ticket_repo_dir(tid: str, user: str) -> Path:
    for part in (user, tid):
        if not _PART.match(part or ""):
            raise HTTPException(400, "invalid identifier")
    return TICKET_REPOS / user / tid


def _repo_facts(tid: str, user: str) -> dict | None:
    p = _ticket_repo_dir(tid, user) / "meta.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def _drop_ticket_repo(tid: str, user: str) -> None:
    """Remove the clone and forget the handle. Safe to call when nothing is set."""
    facts = _repo_facts(tid, user)
    if facts:
        CONNECTED.get(user, {}).pop(facts.get("handle", ""), None)
    shutil.rmtree(_ticket_repo_dir(tid, user), ignore_errors=True)


@app.post("/api/tickets/{tid}/repo")
def connect_ticket_repo(tid: str, req: TicketRepo, request: Request,
                        user: str = Depends(require_session)):
    """Attach a public GitHub repo to this ticket.

    Read-only and offline: credentials are never supplied, nothing is pushed
    back, and no agent runs (that is A3). Reconnecting replaces the old clone.
    """
    _owned_ticket(tid, user)
    if not ledger.hit("ticketrepo:" + client_ip(request)):
        raise HTTPException(429, "rate limit: too many requests from your IP, try later")
    if not conc.acquire():                   # a clone is real work; bound it
        raise HTTPException(503, "too many concurrent runs; try again shortly")

    # Clone into a staging directory and swap it in only once it is good. A
    # failed reconnect must leave the repo you already had exactly as it was —
    # cleaning up `tdir` directly would delete a working clone and leave the
    # ticket pointing at nothing.
    tdir = _ticket_repo_dir(tid, user)
    staging = tdir.parent / f".{tid}.incoming-{uuid.uuid4().hex[:8]}"
    try:
        owner, name = github_source.parse_repo_url(req.url)
        info = github_source.clone_public_repo(req.url, staging / "repo")
        cmd = github_source.detect_test_command(info.path)
        handle = f"{owner}/{name} (ticket {tid})"
        facts = {"handle": handle, "owner": info.owner, "name": info.name,
                 "url": info.url, "default_branch": info.default_branch,
                 "file_count": info.file_count, "size_mb": info.size_mb,
                 "test_command": cmd, "has_tests": github_source.has_tests(info.path),
                 "connected_at": time.time()}
        (staging / "task.json").write_text(json.dumps(
            {"name": handle, "kind": "repo", "repo_dir": "repo", "test_command": cmd,
             "protected_paths": github_source.DEFAULT_PROTECTED}))
        (staging / "meta.json").write_text(json.dumps(facts))
    except github_source.GitHubSourceError as e:
        shutil.rmtree(staging, ignore_errors=True)   # only ever the new attempt
        raise HTTPException(400, str(e))
    finally:
        conc.release()

    _drop_ticket_repo(tid, user)             # now replace the old one
    staging.rename(tdir)
    CONNECTED.setdefault(user, {})[handle] = tdir
    tickets.update(tid, user, repo_url=info.url, repo_task_handle=handle)
    return {"repo": facts}


@app.get("/api/tickets/{tid}/repo")
def get_ticket_repo(tid: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    return {"repo": _repo_facts(tid, user)}


@app.delete("/api/tickets/{tid}/repo")
def disconnect_ticket_repo(tid: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    _drop_ticket_repo(tid, user)
    tickets.update(tid, user, repo_url=None, repo_task_handle=None)
    return {"ok": True}


# --- ticket context: PDF documents (A2) -------------------------------------
# Uploads are validated by magic bytes and parsed at upload time, so a file that
# is not a readable PDF is rejected while a human is watching. The extracted text
# is stored and listed back; NOTHING reads it into a prompt in this phase — see
# the P0-5 warning in fieldcraft_loop/pdf_context.py before wiring A3.


async def _read_capped(f: UploadFile, limit: int) -> bytes:
    """Read at most limit+1 bytes so an oversize upload is refused without ever
    being held in memory in full."""
    buf = bytearray()
    while True:
        chunk = await f.read(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > limit:
            raise PdfContextError(
                f"file is over the {settings.max_pdf_mb} MB limit (FC_MAX_PDF_MB)")
    return bytes(buf)


def _sync_pdf_ids(tid: str, user: str) -> list[dict]:
    """Keep the ticket's pdf_context_ids in step with what is on disk."""
    listing = pdfs.list_for(user, tid)
    tickets.update(tid, user, pdf_context_ids=[m["id"] for m in listing])
    return listing


@app.post("/api/tickets/{tid}/pdfs")
async def upload_ticket_pdfs(tid: str, files: list[UploadFile] = File(...),
                             user: str = Depends(require_session)):
    """Attach one or more PDFs as context. All-or-nothing: if any file in the
    request is rejected, the ones already stored by *this* request are removed,
    so a partial batch never lands."""
    _owned_ticket(tid, user)
    if len(files) > settings.max_pdfs_per_ticket:
        raise HTTPException(400, f"at most {settings.max_pdfs_per_ticket} files per upload")

    added: list[dict] = []
    try:
        for f in files:
            data = await _read_capped(f, int(settings.max_pdf_mb * 1024 * 1024))
            added.append(pdfs.add(user, tid, f.filename, data))
    except PdfContextError as e:
        for m in added:                      # roll back this request's writes
            pdfs.delete(user, tid, m["id"])
        name = getattr(files[len(added)], "filename", "") if len(added) < len(files) else ""
        raise HTTPException(400, f"{name}: {e}" if name else str(e))

    return {"pdfs": _sync_pdf_ids(tid, user), "added": [m["id"] for m in added]}


@app.get("/api/tickets/{tid}/pdfs")
def list_ticket_pdfs(tid: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    return {"pdfs": pdfs.list_for(user, tid)}


@app.delete("/api/tickets/{tid}/pdfs/{pdf_id}")
def delete_ticket_pdf(tid: str, pdf_id: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    if not pdfs.delete(user, tid, pdf_id):
        raise HTTPException(404, "unknown document")
    return {"ok": True, "pdfs": _sync_pdf_ids(tid, user)}


# --- ticket context: the three-mode comparison (A3) -------------------------
# Three real engine runs over one BUNDLED, SCRIPTED task, run sequentially. The
# agent is a mock and the human decisions are simulated deterministically; the
# effectiveness measurement is real (the task's tests actually execute). This is
# never pointed at a connected repo or a live provider — that is Phase B.

# Only bundled single-file tasks: they carry the Field Guide trap the steered
# mode depends on, and none of them is user-supplied code.
COMPARISON_TASKS = {n: p for n, (p, kind) in TASKS.items() if kind == "single"}
DEFAULT_COMPARISON_TASK = "redact_pii"


class RunComparison(BaseModel):
    task: str = DEFAULT_COMPARISON_TASK


def _cmp_key(tid: str, user: str) -> str:
    return f"{user}:{tid}"


def _blank_comparison(tid: str, task: str) -> dict:
    return {"ticket": tid, "task": task, "status": "running", "started_at": time.time(),
            "scripted": True,
            "modes": [{"mode": m.key, "label": m.label, "blurb": m.blurb,
                       "steered": m.steered, "status": "queued", "result": None}
                      for m in cmp_mod.MODES]}


def _persist_mode_result(tid: str, user: str, res: dict) -> None:
    """Append this mode's run to the ticket, replacing any earlier run for the
    same mode so re-running a comparison does not pile up stale entries."""
    t = tickets.get(tid, user)
    if not t:
        return
    runs = [r for r in (t.get("runs") or []) if r.get("mode") != res["mode"]]
    runs.append({"brief_id": res["brief_id"], "mode": res["mode"],
                 "provider": res["provider"], "at": res["at"], "result": res})
    tickets.update(tid, user, runs=runs)


@app.post("/api/tickets/{tid}/comparison")
def start_comparison(tid: str, req: RunComparison, request: Request,
                     user: str = Depends(require_session)):
    """Run the same bundled task three ways, sequentially, in the background."""
    _owned_ticket(tid, user)
    if req.task not in COMPARISON_TASKS:
        raise HTTPException(400, "the comparison runs on a bundled scripted task: "
                                 + ", ".join(sorted(COMPARISON_TASKS)))
    key = _cmp_key(tid, user)
    with COMPARISON_LOCK:
        cur = COMPARISONS.get(key)
        if cur and cur["status"] == "running":
            raise HTTPException(409, "a comparison is already running for this ticket")
        COMPARISONS[key] = _blank_comparison(tid, req.task)

    if not ledger.hit("comparison:" + client_ip(request)):
        with COMPARISON_LOCK:
            COMPARISONS.pop(key, None)
        raise HTTPException(429, "rate limit: too many requests from your IP, try later")
    if not conc.acquire():             # one slot for the whole sequential set
        with COMPARISON_LOCK:
            COMPARISONS.pop(key, None)
        raise HTTPException(503, "too many concurrent runs; try again shortly")

    task_dir = COMPARISON_TASKS[req.task]

    def worker():
        state = COMPARISONS.get(key)
        try:
            for mode in cmp_mod.MODES:
                _set_mode(key, mode.key, "running", None)
                # Each mode reserves like any other run. enforce_cost=False: these
                # are offline mock costs, so they are accounted but cannot block.
                res_id = ledger.reserve(user, client_ip(request), 2.0,
                                        enforce_cost=False)
                result = None
                try:
                    result = cmp_mod.run_mode(engine, mode, task_dir, req.task, user)
                finally:
                    if res_id.ok:
                        ledger.settle(res_id.id, (result or {}).get("cost_usd", 0.0))
                _persist_mode_result(tid, user, result)
                _set_mode(key, mode.key, "done", result)
            with COMPARISON_LOCK:
                st = COMPARISONS.get(key)
                if st:
                    st["status"] = "done"
                    st["deltas"] = cmp_mod.deltas([m["result"] for m in st["modes"]
                                                   if m["result"]])
                    st["finished_at"] = time.time()
        except Exception as e:                     # never let the worker die quietly
            log.exception("three-mode comparison failed for ticket %s", tid)
            with COMPARISON_LOCK:
                st = COMPARISONS.get(key)
                if st:
                    st["status"] = "error"
                    st["error"] = f"{type(e).__name__}: {e}"
                    for m in st["modes"]:
                        if m["status"] in ("queued", "running"):
                            m["status"] = "error"
        finally:
            conc.release()

    threading.Thread(target=worker, daemon=True).start()
    return COMPARISONS[key]


def _set_mode(key: str, mode_key: str, status: str, result: dict | None) -> None:
    with COMPARISON_LOCK:
        st = COMPARISONS.get(key)
        if not st:
            return
        for m in st["modes"]:
            if m["mode"] == mode_key:
                m["status"] = status
                if result:
                    m["result"] = result
                    m["brief_id"] = result["brief_id"]


def _comparison_from_ticket(tid: str, user: str) -> dict | None:
    """Rebuild a finished comparison from what was persisted on the ticket, so a
    reload (or a different browser) still sees the last result."""
    t = tickets.get(tid, user)
    if not t:
        return None
    by = {r.get("mode"): r for r in (t.get("runs") or []) if r.get("result")}
    if not all(k in by for k in cmp_mod.MODE_KEYS):
        return None
    modes = []
    for m in cmp_mod.MODES:
        res = by[m.key]["result"]
        modes.append({"mode": m.key, "label": m.label, "blurb": m.blurb,
                      "steered": m.steered, "status": "done", "result": res,
                      "brief_id": res["brief_id"]})
    return {"ticket": tid, "task": None, "status": "done", "scripted": True,
            "modes": modes, "deltas": cmp_mod.deltas([m["result"] for m in modes]),
            "restored": True}


@app.get("/api/tickets/{tid}/comparison")
def get_comparison(tid: str, user: str = Depends(require_session)):
    _owned_ticket(tid, user)
    live = COMPARISONS.get(_cmp_key(tid, user))
    return {"comparison": live or _comparison_from_ticket(tid, user),
            "tasks": sorted(COMPARISON_TASKS)}


@app.get("/api/tickets/{tid}/comparison/stream")
async def stream_comparison(tid: str, user: str = Depends(require_session)):
    """Progress for the running comparison: one `state` event per change."""
    import asyncio
    _owned_ticket(tid, user)                     # 404 before a byte is streamed
    key = _cmp_key(tid, user)

    async def gen():
        last = None
        for _ in range(1200):                    # ~6 min ceiling
            st = COMPARISONS.get(key)
            if not st:
                yield _sse("state", {"status": "idle"}); return
            snap = json.dumps(st, sort_keys=True, default=str)
            if snap != last:
                yield _sse("state", st)
                last = snap
            if st["status"] in ("done", "error"):
                return
            await asyncio.sleep(0.3)
        yield _sse("state", {"status": "timeout"})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/tasks")
def list_tasks(user: str = Depends(require_session)):
    out = [{"name": n, "kind": k} for n, (_, k) in TASKS.items()]
    out += [{"name": n, "kind": "repo"} for n in CONNECTED.get(user, {})]
    return {"tasks": out}


class ConnectRepo(BaseModel):
    url: str


@app.post("/api/repos/connect")
def connect_repo(req: ConnectRepo, request: Request, user: str = Depends(require_session)):
    """Shallow-clone a public GitHub repo and turn it into a runnable repo task.

    Read-only and offline: nothing is pushed back, and no agent runs here — the
    caller starts a normal brief against the returned handle (mock adapter only,
    so FC_ALLOW_LIVE is untouched by this path). The handle is registered against
    the caller's tenant only; another user never sees it.
    """
    if not ledger.hit("connect:" + client_ip(request)):
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

    CONNECTED.setdefault(user, {})[handle] = tdir
    return {"task": handle, "adapter": "mock", "kind": "repo", "test_command": cmd,
            "protected_paths": github_source.DEFAULT_PROTECTED,
            "tests_detected": github_source.has_tests(info.path),
            "repo": {"owner": info.owner, "name": info.name, "url": info.url,
                     "default_branch": info.default_branch,
                     "file_count": info.file_count, "size_mb": info.size_mb}}


# --- differentiator reports (computed lazily on first request, then cached) ---
# The cache is shared across tenants *on purpose*: every report is computed from
# repo-bundled fixture tasks in a throwaway directory (see the four functions
# below — none of them read the runs/events stores or any connected repo), so it
# holds no user data. Reading one still requires a session.
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
def get_report(kind: str, user: str = Depends(require_session)):
    if kind not in _REPORT_FNS:
        raise HTTPException(404, "unknown report")
    r = _REPORTS.get(kind)
    if r is None:
        _REPORTS[kind] = {"status": "computing"}
        threading.Thread(target=_compute_report, args=(kind,), daemon=True).start()
        return {"status": "computing"}
    return r


@app.get("/api/briefs")
def list_briefs(user: str = Depends(require_session)):
    out = []
    for r in engine.runs.list_all(user_id=user):
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
async def stream(bid: str, user: str = Depends(require_session)):
    import asyncio
    owned_run(bid, user)                            # 404 before a byte is streamed

    async def gen():
        seen = 0
        for _ in range(2400):                       # ~12 min ceiling
            r = engine.get(bid, user)
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


# The SPA shell and its stylesheet are public, like index.html itself; every API
# route behind them still requires a session.
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
