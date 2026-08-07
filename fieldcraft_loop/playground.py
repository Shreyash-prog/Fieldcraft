"""The "Try it" catalogue — four curated tasks, each with a story.

The three-mode comparison already produces the honest result (steering buys
efficiency, a rubber-stamp reviewer buys nothing). What it does not do is explain
*why* the steered run was faster — the numbers land without the reason. This
module is the missing half: each curated task carries a plain-language **goal**,
**catch** and **steering** line, so a first-time visitor reads the trap before
the run and recognises it in the result.

The stories are not decoration and they are not free text bolted on afterwards.
Each `catch` describes the *actual* trap the scripted task encodes: the unsteered
turn-1 attempt fails a test that names it, the steering brief names it up front,
and that difference is the whole reason mode 2 converges a turn earlier. A test
pins the pairing, so a story cannot drift away from the task it describes.

Everything here is scripted and bundled — no live agent, no network, no repo.
"""
from __future__ import annotations

from pathlib import Path

from .task import Task

_ROOT = Path(__file__).resolve().parent.parent

# Curated order, most interesting first. `normalize_csv_row` leads because
# idempotence is a real data-engineering property with a real failure mode
# (a pipeline re-run corrupting rows it already processed), not a toy bug.
CURATED: tuple[tuple[str, Path], ...] = (
    ("normalize_csv_row", _ROOT / "tasks" / "normalize_csv_row"),
    ("redact_pii", _ROOT / "sample_task"),
    ("parse_bool", _ROOT / "tasks" / "parse_bool"),
    ("truncate_words", _ROOT / "tasks" / "truncate_words"),
    # The one that demonstrates the other half of the product: the catch here is
    # a policy violation, and the lesson is that the gate caught it.
    ("secure_api_key", _ROOT / "tasks" / "secure_api_key"),
)
TASK_IDS = tuple(name for name, _ in CURATED)
STORY_FIELDS = ("title", "goal", "catch", "steering")


def task_dir(task_id: str) -> Path | None:
    return dict(CURATED).get(task_id)


def _policy_of(task_dir: Path) -> dict | None:
    """The governance policy a task declares, if any (stored-intent shape)."""
    import json
    try:
        return json.loads((task_dir / "task.json").read_text()).get("policy")
    except (OSError, ValueError):
        return None


def story_for(task_id: str) -> dict | None:
    """The presentable story for one curated task, or None if it has none."""
    d = task_dir(task_id)
    if d is None:
        return None
    t = Task.load(d)
    s = dict(t.story or {})
    if not all(s.get(f) for f in STORY_FIELDS):
        return None
    return {"id": task_id, "title": s["title"], "goal": s["goal"],
            "catch": s["catch"], "steering": s["steering"],
            "why_it_matters": s.get("why_it_matters", ""),
            "featured": bool(s.get("featured", False)),
            # "measure" (steering changes efficiency) or "govern" (the gate
            # catches a violation). The playground applies `policy` to the
            # ticket before running a govern task, so the enforcement is real.
            "kind": s.get("kind", "measure"),
            "policy": t.story.get("policy") or _policy_of(d),
            # Surfaced so the UI can say *which* words the steering brief carried
            # — the mechanism, not a claim about it.
            "trap_keywords": list(t.trap_keywords)}


def catalogue() -> list[dict]:
    """Every curated task that has a complete story, in curated order."""
    return [s for s in (story_for(tid) for tid in TASK_IDS) if s]
