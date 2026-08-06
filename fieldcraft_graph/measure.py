"""Per-node measurement — the graph makes 'where's the improvable gap?' answerable
at the role level, not just per run."""
from __future__ import annotations

from collections import defaultdict


def per_node(state) -> list[dict]:
    agg = defaultdict(lambda: {"runs": 0, "cost_usd": 0.0, "wall_s": 0.0})
    for m in state.node_metrics:
        a = agg[m["kind"]]
        a["runs"] += 1
        a["cost_usd"] += m["cost_usd"]
        a["wall_s"] += m["wall_s"]
    return [{"kind": k, "runs": v["runs"], "cost_usd": round(v["cost_usd"], 4),
             "wall_s": round(v["wall_s"], 3)} for k, v in agg.items()]


def graph_aar(state, rounds: int) -> dict:
    nodes = per_node(state)
    return {"converged": bool(state.get("converged")), "approved": bool(state.get("approved")),
            "rounds": rounds, "verdict": (state.get("verdict") or {}).get("tests"),
            "per_node": nodes,
            "total_cost": round(sum(n["cost_usd"] for n in nodes), 4)}
