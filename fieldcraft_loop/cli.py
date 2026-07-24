from __future__ import annotations
import argparse, json, sys, uuid
from pathlib import Path
from .models import Brief
from .store import EventStore
from .controller import Controller

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fieldcraft_loop")
    ap.add_argument("--task", default=str(ROOT / "sample_task"))
    ap.add_argument("--adapter", choices=["mock", "claude"], default="mock",
                    help="the agent driving each turn: scripted mock, or live Claude Code")
    ap.add_argument("--grader", choices=["behavioral", "tooluse"], default="behavioral",
                    help="verification judge: deterministic probes, or the Claude forced-tool-use judge")
    ap.add_argument("--review", choices=["auto", "human"], default="auto",
                    help="who reviews each turn: automated verifier feedback, or you (human-in-the-loop)")
    ap.add_argument("--max-iterations", type=int, default=5)
    ap.add_argument("--budget", type=float, default=2.0)
    ap.add_argument("--out", default=str(ROOT / "out"))
    a = ap.parse_args(argv)

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    store = EventStore(out / "events.db")
    brief = Brief(brief_id="BRIEF-" + uuid.uuid4().hex[:6],
                  goal="Implement redact_pii so all tests and acceptance criteria pass",
                  task_dir=a.task, max_iterations=a.max_iterations, budget_usd=a.budget)

    if a.grader == "tooluse":
        from fieldcraft_aar.grader_tooluse import ClaudeToolUseGrader
        grader = ClaudeToolUseGrader()
    else:
        grader = None  # controller defaults to BehavioralGrader

    if a.adapter == "claude":
        from .live_adapter import ClaudeCodeLoopAdapter
        adapter = ClaudeCodeLoopAdapter()
    else:
        adapter = None  # controller defaults to ProgressiveMockAdapter

    from .review import AutoReviewer, HumanReviewer
    reviewer = HumanReviewer() if a.review == "human" else AutoReviewer()

    aar = Controller(store, adapter=adapter, grader=grader, reviewer=reviewer).run(brief, out / "work")

    print(f"\n=== EVENT LOG · {brief.brief_id} ===")
    for e in store.events(brief.brief_id):
        extra = ""
        p = e["payload"]
        if e["type"] == "turn_done":
            extra = f"  ${p['cost_usd']}  {p['note']}"
        elif e["type"] == "verdict":
            extra = f"  score={p['score']}  tests={p['tests']}  criteria={p['criteria_met']}/{p['criteria_total']}"
            for c in p.get("criteria", []):
                mark = "PASS" if c["verdict"] == "met" else "FAIL"
                ev = f" — {c['evidence']}" if c.get("evidence") else ""
                extra += f"\n           · {c['id']} {mark}{ev}"
        elif e["type"] == "changes_requested":
            extra = f"  {len(p['directives'])} directive(s) -> next turn"
        elif e["type"] in ("approved", "budget_exceeded", "max_iterations"):
            extra = f"  {p}"
        print(f"  it{e['turn']}  {e['state']:18}{e['type']:18}{extra}")

    print(f"\n=== LOOP AAR ===")
    for k, v in aar.items():
        print(f"  {k:26} {v}")
    (out / "loop_aar.json").write_text(json.dumps(aar, indent=2))
    print(f"\nwrote {out/'loop_aar.json'} and {out/'events.db'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
