"""Deployment settings, from environment with safe defaults.

Every limit that protects a public deployment (spend, rate, concurrency,
sandbox timeout) is configurable here so it can be tuned per environment without
code changes.
"""
from __future__ import annotations

import os


def _int(k: str, d: int) -> int:
    try:
        return int(os.environ.get(k, d))
    except ValueError:
        return d


def _float(k: str, d: float) -> float:
    try:
        return float(os.environ.get(k, d))
    except ValueError:
        return d


class Settings:
    # per-IP: how many briefs may be started per rolling hour
    briefs_per_hour = _int("FC_BRIEFS_PER_HOUR", 10)
    # how many briefs may run at once (bounds threads and cost)
    max_concurrent = _int("FC_MAX_CONCURRENT", 4)
    # global spend ceiling per day across all live runs (durable; see ledger.py)
    daily_cost_cap_usd = _float("FC_DAILY_COST_CAP_USD", 5.0)
    # per-tenant slice of that ceiling, so one user can't drain the whole day
    user_daily_cost_cap_usd = _float("FC_USER_DAILY_COST_CAP_USD", 1.0)
    # hard clamp on any single run's budget
    max_budget_per_run_usd = _float("FC_MAX_BUDGET_PER_RUN_USD", 1.0)
    # hard clamp on iterations per run
    max_iterations_cap = _int("FC_MAX_ITERATIONS", 6)
    # kill a test subprocess that runs too long (sandbox safety)
    pytest_timeout_s = _int("FC_PYTEST_TIMEOUT_S", 30)
    # --- ticket context (A2): repo + PDFs attached to a ticket ---
    # biggest single PDF accepted as ticket context
    max_pdf_mb = _float("FC_MAX_PDF_MB", 10.0)
    # how many PDFs one ticket may carry
    max_pdfs_per_ticket = _int("FC_MAX_PDFS_PER_TICKET", 10)
    # page ceiling per PDF (bounds extraction time and stored text)
    max_pdf_pages = _int("FC_MAX_PDF_PAGES", 200)
    # allow the live agent / judge (needs a key); off => mock+behavioral only
    allow_live = os.environ.get("FC_ALLOW_LIVE", "1") == "1"
    # comma-separated allowed CORS origins ("*" for any)
    cors_origins = os.environ.get("FC_CORS_ORIGINS", "*")


settings = Settings()
