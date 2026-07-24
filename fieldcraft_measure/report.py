"""Render the measurement report — the defensible-in-review artifact.

Shows the three families per task, efficiency normalized to the best-known path,
and the aggregate Field-Guide effect *with uncertainty and an honest power
statement*, plus a methods-and-limits section.
"""
from __future__ import annotations

import html


def _card(label, value, sub=""):
    s = f'<div class="l2">{html.escape(sub)}</div>' if sub else ""
    return (f'<div class="metric"><div class="n">{html.escape(str(value))}</div>'
            f'<div class="l">{html.escape(label)}</div>{s}</div>')


def render(result: dict) -> str:
    cards, e = result["cards"], result["effect"]
    sig = ("statistically significant" if e["significant_05"]
           else f"NOT significant at N={e['n']} (need N≥{e['min_n_for_sig']})")
    agg = "".join([
        _card("mean effect", f'+{e["mean"]}', "efficiency captured, guided − blind"),
        _card("95% CI (bootstrap)", f'[{e["ci95"][0]}, {e["ci95"][1]}]'),
        _card("consistency", f'{e["n_positive"]}/{e["n"]}', "tasks improved"),
        _card("sign-test p", e["sign_test_p"], sig),
    ])
    rows = "".join(
        f'<tr><td>{html.escape(c.task)}</td><td>{html.escape(c.condition)}</td>'
        f'<td>{c.effectiveness}</td><td>{"✓" if c.valid else "✗"}</td>'
        f'<td>${c.actual_cost}</td><td>${c.reference_cost}</td>'
        f'<td>{c.efficiency_captured}</td><td>{c.operator_quality}</td></tr>'
        for c in cards)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fieldcraft — measurement report</title><style>
 :root{{--ink:#16202b;--mut:#5a6b78;--line:#dde3e8;--teal:#0c6d5e;--amber:#9c5a1e;--bg:#f6f7f9}}
 body{{font:15px/1.55 ui-sans-serif,-apple-system,Segoe UI,Roboto,Arial;color:var(--ink);background:var(--bg);margin:0;padding:32px}}
 .wrap{{max-width:840px;margin:0 auto}} h1{{font-size:21px;margin:0 0 2px}}
 .sub{{color:var(--mut);font-size:13px;margin:0 0 22px}}
 .card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin-bottom:18px}}
 .fam{{font:600 10px ui-monospace,monospace;letter-spacing:.09em;text-transform:uppercase;color:var(--mut);margin:0 0 12px}}
 .metrics{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px}}
 .metric .n{{font:700 20px ui-monospace,monospace}} .metric .l{{font-size:12px;color:var(--mut)}}
 .metric .l2{{font-size:11px;color:var(--mut);margin-top:2px}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th,td{{text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}}
 th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
 td:first-child,td:nth-child(2){{font-family:ui-monospace,monospace}}
 th{{font:600 10px ui-monospace,monospace;color:var(--mut);text-transform:uppercase;letter-spacing:.05em}}
 .methods{{font-size:13px;color:var(--ink)}} .methods li{{margin:4px 0}}
 .flag{{background:#fbf0e2;border-left:4px solid var(--amber);padding:10px 14px;border-radius:8px;font-size:13.5px}}
</style></head><body><div class="wrap">
<h1>Fieldcraft — measurement report</h1>
<p class="sub">Human+AI delivery, scored: effectiveness · efficiency (normalized) · operator quality</p>

<div class="card"><div class="fam">Field Guide effect · efficiency captured</div>
<div class="metrics">{agg}</div>
<div style="margin-top:14px" class="flag"><b>Honest read.</b> The effect is consistent
({e['n_positive']}/{e['n']} tasks) and sizable (+{e['mean']}), but at N={e['n']} the sign test is {html.escape(sig)}.
The framework reports this rather than overclaiming — the effect is directional evidence, not proof.</div></div>

<div class="card"><div class="fam">Per-task scorecards</div>
<table><tr><th>task</th><th>condition</th><th>effectiveness</th><th>valid</th>
<th>actual $</th><th>reference $</th><th>eff captured</th><th>operator q</th></tr>
{rows}</table></div>

<div class="card"><div class="fam">Methods & limits</div><ul class="methods">
<li><b>Effectiveness</b> = 0.6·test-pass-rate + 0.4·criteria-met-rate, and is <b>valid only if integrity held</b>
(the agent didn't edit the tests). Invalid runs are excluded from efficiency comparison.</li>
<li><b>Efficiency</b> is <b>normalized to the best-known path</b> (the reference = oracle cost for that task),
so it's comparable across tasks of different difficulty. "Efficiency captured" = reference / actual, capped at 1.0.</li>
<li><b>Operator quality</b> = efficiency captured, discounted by rework share — how well the human drove the loop.</li>
<li><b>Comparison at constant effectiveness only</b>: efficiency is compared solely among runs with equal
effectiveness, so "used less" never rewards a worse outcome (the Goodhart guard).</li>
<li><b>Uncertainty</b> is a bootstrap 95% CI; significance is a nonparametric sign test. Small N is reported,
not hidden. On these deterministic mock runs the per-task effect is identical, so the CI is degenerate;
on variable (live) data the same machinery yields informative intervals.</li>
</ul></div>
</div></body></html>"""
