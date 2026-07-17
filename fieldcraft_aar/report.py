"""Write aar.json and a self-contained one-page HTML report (inline SVG, no deps).

The report is intentionally plain — an engineer's instrument, not a marketing
page. It shows the three metric families per run and the constant-effectiveness
comparison as a cost-vs-effectiveness scatter.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

from .models import AAR, RunResult


def write_json(aar: AAR, path: Path) -> None:
    path.write_text(json.dumps(aar.to_dict(), indent=2))


def write_html(aar: AAR, path: Path) -> None:
    path.write_text(_html(aar))


# ----------------------------------------------------------------------------
def _html(aar: AAR) -> str:
    rows = "\n".join(_run_card(r) for r in aar.runs)
    cmp = aar.comparison
    chart = _scatter(aar.runs)
    verdict = html.escape(cmp.get("verdict", ""))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fieldcraft AAR — {html.escape(aar.task)}</title>
<style>
 :root{{--ink:#16202b;--mut:#5a6b78;--line:#dde3e8;--ok:#0c6d5e;--warn:#9c5a1e;--bg:#f6f7f9}}
 *{{box-sizing:border-box}}
 body{{font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Helvetica,Arial;color:var(--ink);
   background:var(--bg);margin:0;padding:32px}}
 .wrap{{max-width:860px;margin:0 auto}}
 h1{{font-size:22px;margin:0 0 2px}} .sub{{color:var(--mut);font-size:13px;margin:0 0 22px}}
 .mono{{font-family:ui-monospace,Menlo,Consolas,monospace}}
 .verdict{{background:#fff;border:1px solid var(--line);border-left:4px solid var(--ok);
   border-radius:8px;padding:14px 16px;margin:0 0 22px;font-size:15px}}
 .grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
 @media(max-width:680px){{.grid{{grid-template-columns:1fr}}}}
 .card{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px}}
 .card h2{{font-size:14px;margin:0 0 12px;display:flex;justify-content:space-between;align-items:baseline}}
 .tag{{font:600 11px ui-monospace,monospace;letter-spacing:.04em;color:var(--mut)}}
 .fam{{font:600 10px ui-monospace,monospace;letter-spacing:.08em;text-transform:uppercase;
   color:var(--mut);margin:12px 0 4px}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 td{{padding:3px 0}} td:last-child{{text-align:right;font-family:ui-monospace,Menlo,monospace}}
 .met{{color:var(--ok)}} .unmet{{color:var(--warn)}}
 .chart{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;margin:22px 0}}
 .foot{{color:var(--mut);font-size:12px;margin-top:20px}}
 .foot code{{background:#eef1f3;padding:1px 5px;border-radius:4px}}
</style></head><body><div class="wrap">
<h1>Fieldcraft — After-Action Review</h1>
<p class="sub">task: <span class="mono">{html.escape(aar.task)}</span> · generated {html.escape(aar.generated_at)}
 · adapter: <span class="mono">{html.escape(aar.runs[0].adapter if aar.runs else '')}</span></p>
<div class="verdict"><b>Comparison.</b> {verdict}</div>
<div class="chart"><div class="fam">Efficiency at constant effectiveness</div>{chart}</div>
<div class="grid">{rows}</div>
<p class="foot">Effectiveness is measured by really running the task's tests plus acceptance grading.
 Efficiency and usage-quality are derived from the run trace. Swap the adapter to
 <code>claude</code> to measure a live Claude Code run; the metrics are model-agnostic.</p>
</div></body></html>"""


def _run_card(r: RunResult) -> str:
    e, f, u = r.effectiveness, r.efficiency, r.usage_quality
    crits = "".join(
        f'<tr><td>{html.escape(c.text)}</td>'
        f'<td class="{"met" if c.verdict=="met" else "unmet"}">{c.verdict}</td></tr>'
        for c in e.criteria
    )
    return f"""<div class="card">
 <h2>{html.escape(r.condition)} <span class="tag">spec {u.spec_completeness}</span></h2>
 <div class="fam">Effectiveness</div>
 <table>
  <tr><td>tests passing</td><td>{e.tests_passed}/{e.tests_total}</td></tr>
  <tr><td>criteria met</td><td>{e.criteria_met}/{len(e.criteria)}</td></tr>
  <tr><td>score</td><td>{e.score}</td></tr>
  {crits}
 </table>
 <div class="fam">Efficiency</div>
 <table>
  <tr><td>cost</td><td>${f.cost_usd}</td></tr>
  <tr><td>turns</td><td>{f.turns}</td></tr>
  <tr><td>tool calls</td><td>{f.tool_calls}</td></tr>
  <tr><td>wall clock</td><td>{f.wall_clock_s}s</td></tr>
 </table>
 <div class="fam">AI-usage quality</div>
 <table>
  <tr><td>turns to converge</td><td>{u.turns_to_converge}</td></tr>
  <tr><td>rework turns</td><td>{u.rework_turns}</td></tr>
  <tr><td>directive efficiency</td><td>{u.directive_efficiency}</td></tr>
 </table>
</div>"""


def _scatter(runs: list[RunResult]) -> str:
    """Cost (y) vs effectiveness (x). Same x, different y == the wedge."""
    if not runs:
        return ""
    W, H, P = 620, 220, 44
    max_cost = max(r.efficiency.cost_usd for r in runs) or 1.0
    ymax = max_cost * 1.25
    x0, x1 = 0.80, 1.02  # effectiveness axis window

    def px(eff):  # effectiveness -> x pixel
        return P + (eff - x0) / (x1 - x0) * (W - 2 * P)

    def py(cost):  # cost -> y pixel (inverted)
        return H - P - (cost / ymax) * (H - 2 * P)

    pts, labels = [], []
    for r in runs:
        cx, cy = px(r.effectiveness.score), py(r.efficiency.cost_usd)
        colour = "#0c6d5e" if r.efficiency.cost_usd == min(x.efficiency.cost_usd for x in runs) else "#9c5a1e"
        pts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="{colour}"/>')
        labels.append(
            f'<text x="{cx:.1f}" y="{cy-12:.1f}" font-size="11" text-anchor="middle" '
            f'font-family="ui-monospace,monospace" fill="#16202b">'
            f'{html.escape(r.condition)} · ${r.efficiency.cost_usd}</text>'
        )
    grid = (
        f'<line x1="{P}" y1="{H-P}" x2="{W-P}" y2="{H-P}" stroke="#c8d0d6"/>'
        f'<line x1="{P}" y1="{P}" x2="{P}" y2="{H-P}" stroke="#c8d0d6"/>'
        f'<text x="{W-P}" y="{H-P+22}" font-size="11" text-anchor="end" fill="#5a6b78" '
        f'font-family="ui-monospace,monospace">effectiveness &#8594;</text>'
        f'<text x="{P-8}" y="{P-6}" font-size="11" text-anchor="end" fill="#5a6b78" '
        f'font-family="ui-monospace,monospace">cost</text>'
    )
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" xmlns="http://www.w3.org/2000/svg">'
            + grid + "".join(pts) + "".join(labels) + "</svg>")
