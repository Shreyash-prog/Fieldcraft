"""Run the task suite blind vs Field-Guide-guided and produce a cross-run dashboard.

For each task we run the governed loop twice (auto review): once with a blind
agent and once with the compiled Field Guide. Aggregating across tasks turns the
single-task story ("2 iterations, 2x cheaper") into a distribution — real
evidence rather than one anecdote.

    python -m fieldcraft_bench
"""
from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path

from fieldcraft_loop.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
TASKS = {
    "redact_pii": ROOT / "sample_task",
    "slugify": ROOT / "tasks" / "slugify",
    "parse_bool": ROOT / "tasks" / "parse_bool",
    "chunk": ROOT / "tasks" / "chunk",
}


def _run(engine: Engine, task_dir: Path, adapter: str) -> dict:
    bid = engine.create({"adapter": adapter, "review": "auto"}, str(task_dir))
    engine.advance(bid)
    return engine.aar(engine.get(bid))


def benchmark() -> dict:
    rows = []
    with tempfile.TemporaryDirectory() as td:
        engine = Engine(td)
        for name, d in TASKS.items():
            blind = _run(engine, d, "mock")
            guided = _run(engine, d, "guided")
            rows.append({
                "task": name,
                "blind_iters": blind["iterations"], "guided_iters": guided["iterations"],
                "blind_cost": blind["total_cost_usd"], "guided_cost": guided["total_cost_usd"],
                "blind_done": blind["final_state"] == "done", "guided_done": guided["final_state"] == "done",
            })
    n = len(rows)
    tot_bi = sum(r["blind_iters"] for r in rows)
    tot_gi = sum(r["guided_iters"] for r in rows)
    tot_bc = round(sum(r["blind_cost"] for r in rows), 4)
    tot_gc = round(sum(r["guided_cost"] for r in rows), 4)
    agg = {
        "tasks": n,
        "avg_blind_iters": round(tot_bi / n, 2), "avg_guided_iters": round(tot_gi / n, 2),
        "total_blind_cost": tot_bc, "total_guided_cost": tot_gc,
        "tasks_improved": sum(1 for r in rows if r["guided_iters"] < r["blind_iters"]),
        "iters_speedup": round(tot_bi / tot_gi, 2) if tot_gi else None,
        "cost_speedup": round(tot_bc / tot_gc, 2) if tot_gc else None,
        "all_converged": all(r["blind_done"] and r["guided_done"] for r in rows),
    }
    return {"rows": rows, "agg": agg}


# ---------------------------------------------------------------------------
def _dashboard(data: dict) -> str:
    rows, a = data["rows"], data["agg"]
    cards = [
        ("tasks", a["tasks"]),
        ("avg iterations", f'{a["avg_blind_iters"]} → {a["avg_guided_iters"]}'),
        ("total cost", f'${a["total_blind_cost"]} → ${a["total_guided_cost"]}'),
        ("tasks improved", f'{a["tasks_improved"]}/{a["tasks"]}'),
        ("convergence speedup", f'{a["iters_speedup"]}×'),
        ("all converged", "yes" if a["all_converged"] else "no"),
    ]
    card_html = "".join(
        f'<div class="metric"><div class="n">{html.escape(str(v))}</div>'
        f'<div class="l">{html.escape(l)}</div></div>' for l, v in cards)

    maxi = max(max(r["blind_iters"], r["guided_iters"]) for r in rows)
    bar_w, gap, grp = 26, 10, 90
    W = 60 + len(rows) * grp
    H = 200
    bars = ""
    for i, r in enumerate(rows):
        x = 50 + i * grp
        for j, (key, colour) in enumerate((("blind_iters", "#9c5a1e"), ("guided_iters", "#0c6d5e"))):
            h = round(r[key] / maxi * 130)
            bx = x + j * (bar_w + 4)
            bars += (f'<rect x="{bx}" y="{160-h}" width="{bar_w}" height="{h}" fill="{colour}" rx="3"/>'
                     f'<text x="{bx+bar_w/2}" y="{155-h}" font-size="11" text-anchor="middle" '
                     f'font-family="ui-monospace,monospace" fill="#16202b">{r[key]}</text>')
        bars += (f'<text x="{x+bar_w+2}" y="178" font-size="11" text-anchor="middle" fill="#5a6b78" '
                 f'font-family="ui-monospace,monospace">{html.escape(r["task"])}</text>')
    chart = (f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">'
             f'<line x1="46" y1="160" x2="{W-10}" y2="160" stroke="#c8d0d6"/>{bars}'
             f'<rect x="{W-150}" y="12" width="11" height="11" fill="#9c5a1e" rx="2"/>'
             f'<text x="{W-134}" y="22" font-size="11" fill="#5a6b78">blind</text>'
             f'<rect x="{W-90}" y="12" width="11" height="11" fill="#0c6d5e" rx="2"/>'
             f'<text x="{W-74}" y="22" font-size="11" fill="#5a6b78">guided</text></svg>')

    trs = "".join(
        f'<tr><td>{html.escape(r["task"])}</td><td>{r["blind_iters"]}</td>'
        f'<td>{r["guided_iters"]}</td><td>{r["blind_iters"]-r["guided_iters"]}</td>'
        f'<td>${r["blind_cost"]}</td><td>${r["guided_cost"]}</td></tr>' for r in rows)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fieldcraft — benchmark</title><style>
 :root{{--ink:#16202b;--mut:#5a6b78;--line:#dde3e8;--teal:#0c6d5e;--bg:#f6f7f9}}
 body{{font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;color:var(--ink);background:var(--bg);margin:0;padding:32px}}
 .wrap{{max-width:820px;margin:0 auto}} h1{{font-size:21px;margin:0 0 2px}}
 .sub{{color:var(--mut);font-size:13px;margin:0 0 22px}}
 .card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:18px}}
 .fam{{font:600 10px ui-monospace,monospace;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);margin:0 0 12px}}
 .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:16px}}
 .metric .n{{font:700 20px ui-monospace,monospace}} .metric .l{{font-size:12px;color:var(--mut)}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 th,td{{text-align:right;padding:7px 8px;border-bottom:1px solid var(--line)}}
 th:first-child,td:first-child{{text-align:left;font-family:ui-monospace,monospace}}
 th{{font:600 11px ui-monospace,monospace;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}}
</style></head><body><div class="wrap">
<h1>Fieldcraft — multi-task benchmark</h1>
<p class="sub">Governed loop across {a['tasks']} tasks · blind agent vs Field-Guide-guided · auto review</p>
<div class="card"><div class="metrics">{card_html}</div></div>
<div class="card"><div class="fam">Iterations to converge · blind vs guided</div>{chart}</div>
<div class="card"><div class="fam">Per-task</div>
<table><tr><th>task</th><th>blind iters</th><th>guided iters</th><th>saved</th><th>blind $</th><th>guided $</th></tr>
{trs}</table></div>
<p class="sub">Every run really executes the task's tests + acceptance grading. The Field Guide's
edge is surfacing each task's trap up front, so the guided agent skips the rework turn.</p>
</div></body></html>"""


def main() -> int:
    data = benchmark()
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    (out / "bench.json").write_text(json.dumps(data, indent=2))
    (out / "bench_report.html").write_text(_dashboard(data))
    a = data["agg"]
    print("=== Fieldcraft multi-task benchmark ===")
    for r in data["rows"]:
        print(f"  {r['task']:11} blind: {r['blind_iters']} iters / ${r['blind_cost']}   "
              f"guided: {r['guided_iters']} iters / ${r['guided_cost']}")
    print(f"\n  {a['tasks']} tasks · avg iterations {a['avg_blind_iters']} -> {a['avg_guided_iters']} "
          f"· {a['iters_speedup']}x faster to converge · {a['tasks_improved']}/{a['tasks']} improved "
          f"· all converged: {a['all_converged']}")
    print(f"  wrote {out/'bench_report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
