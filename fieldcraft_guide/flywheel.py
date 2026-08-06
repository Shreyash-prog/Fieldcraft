"""Field Guide maintenance flywheel — runs teach the guide.

A run that fails a criterion (or test) on its first attempt and then fixes it is
*evidence* the Field Guide was missing a trap. The flywheel extracts that as a
proposed trap; a human approves it; it's written to the guide's learned-traps
store — so the next run on that codebase is guided and converges faster.

Guards against noise/gaming: a proposal must come from a genuine
failed-then-fixed signal, is de-duplicated against known traps, and is **never
auto-applied** — a human approves each one (consistent with the loop's HITL).
"""
from __future__ import annotations

import re
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Proposal:
    text: str
    evidence: str
    source: str = ""
    status: str = "proposed"


def _kw(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", s.lower()))


def _is_dup(text: str, existing: list[str]) -> bool:
    t = _kw(text)
    return any(len(t & _kw(e)) >= 2 for e in existing)


def discover(events: list[dict], existing_traps: list[str]) -> list[Proposal]:
    """Extract proposed traps from a run's event log (failed-then-fixed signals)."""
    verdicts = [e["payload"] for e in events if e["type"] == "verdict"]
    if not verdicts:
        return []
    first, last = verdicts[0], verdicts[-1]
    final_ok = "/" in last.get("tests", "") and last["tests"].split("/")[0] == last["tests"].split("/")[1]
    proposals: list[Proposal] = []

    # single-file: criteria unmet on turn 1, met by the end
    last_met = {c["id"] for c in last.get("criteria", []) if c["verdict"] == "met"}
    for c in first.get("criteria", []):
        if c["verdict"] != "met" and c["id"] in last_met:
            label = c.get("text") or c["id"]
            text = f"{label}: missed on the first attempt ({c['evidence']}). Handle it up front."
            if not _is_dup(text, existing_traps):
                proposals.append(Proposal(text=text, evidence=c["id"]))

    # repo: tests failing on turn 1, passing by the end
    fixed = set(first.get("failing_tests", [])) - set(last.get("failing_tests", []))
    if fixed and final_ok:
        mods = sorted({f.split("::")[0].split("/")[-1].replace("test_", "").replace(".py", "")
                       for f in fixed})
        text = (f"Tests for {', '.join(mods)} failed on the first attempt; "
                f"handle those cases up front.")
        if not _is_dup(text, existing_traps):
            proposals.append(Proposal(text=text, evidence=", ".join(sorted(fixed))))
    return proposals


def approve(proposal: Proposal, task_dir: str | Path) -> Path:
    """Write an approved trap to the guide's learned-traps store."""
    d = Path(task_dir) / ".fieldguide"
    d.mkdir(exist_ok=True)
    f = d / "learned.md"
    if not f.exists():
        f.write_text("# Learned (flywheel)\n## Traps\n")
    with f.open("a") as fh:
        fh.write(f"- {proposal.text}\n")
    proposal.status = "approved"
    return f


def demo(task_dir: str | Path) -> dict:
    """End-to-end, measurable: a blind run teaches the guide a trap; the next run
    is guided and converges faster. Operates on a throwaway copy so the real task
    is untouched, and strips any seeded trap so the guide genuinely starts blind."""
    from fieldcraft_loop.engine import Engine
    from .bootstrap import bootstrap
    src = Path(task_dir)
    work = Path(tempfile.mkdtemp()) / "task"
    shutil.copytree(src, work)
    notes = work / "NOTES.md"
    if notes.exists():
        notes.write_text("# Notes\n")            # simulate a guide that knows no traps yet

    e = Engine(tempfile.mkdtemp())
    b1 = e.create({"adapter": "guided", "review": "auto"}, str(work))
    e.advance(b1)
    run1 = e.aar(e.get(b1))
    props = discover(e.get_events(b1), bootstrap(work).traps)
    for p in props:
        p.source = b1
        approve(p, work)                          # human-approve (auto in the demo)

    b2 = e.create({"adapter": "guided", "review": "auto"}, str(work))
    e.advance(b2)
    run2 = e.aar(e.get(b2))
    return {"proposals": [p.text for p in props],
            "run1_iterations": run1["iterations"], "run2_iterations": run2["iterations"],
            "learned_traps": bootstrap(work).traps}


def main(argv=None) -> int:
    import sys
    task = (argv or sys.argv[1:] or ["sample_task"])[0]
    r = demo(task)
    print("=== Field Guide flywheel ===")
    print(f"  run 1 (blind):   {r['run1_iterations']} iterations")
    for p in r["proposals"]:
        print(f"  proposed trap:   {p}")
    print(f"  run 2 (learned): {r['run2_iterations']} iterations")
    if r["run2_iterations"] < r["run1_iterations"]:
        print(f"  -> guide learned from one run; next run converged "
              f"{r['run1_iterations'] - r['run2_iterations']} iteration(s) faster")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
