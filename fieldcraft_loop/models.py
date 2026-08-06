"""Domain models for the governed loop (Phase 2).

The loop drives a Brief through a state machine; every transition is an event in
the store, so the run is fully reconstructable and measurement rides the log.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class State(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    WORKING = "working"
    VERIFYING = "verifying"
    AWAITING_REVIEW = "awaiting_review"
    CHANGES_REQUESTED = "changes_requested"
    DONE = "done"
    NEEDS_HUMAN = "needs_human"
    ERROR = "error"          # the loop itself failed (a crashed worker, not a bad diff)


TERMINAL = {State.DONE, State.NEEDS_HUMAN, State.ERROR}


@dataclass
class Brief:
    """A unit of work handed to the loop — the ticket/spec."""
    brief_id: str
    goal: str
    task_dir: str
    max_iterations: int = 5
    budget_usd: float = 2.0


@dataclass
class Directive:
    """One classified next-turn instruction produced by the Turn Assembler."""
    type: str      # criterion_fix | global_constraint | rejection
    ref: str
    instruction: str
