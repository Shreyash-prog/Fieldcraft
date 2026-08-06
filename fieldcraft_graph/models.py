"""Graph model — nodes, conditional edges, shared state, node results.

The develop→verify→iterate loop is just one graph over these primitives. Richer
topologies (a critic gate, a planner fan-out, an integrator join) are expressed
by adding nodes and edges — the executor doesn't change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class NodeResult:
    """What a node returns: state deltas, cost/latency, and events to log."""
    outputs: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    wall_s: float = 0.0
    events: list[tuple[str, dict]] = field(default_factory=list)   # (type, payload)
    note: str = ""


@dataclass
class Edge:
    src: str
    dst: str | None                                  # None => terminal
    when: Callable[["GraphState"], bool] | None = None   # None => default/unconditional
    label: str = ""


@dataclass
class Graph:
    entry: str
    nodes: dict[str, object]                         # id -> Node
    edges: list[Edge]

    def out_edges(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.src == node_id]

    def next(self, node_id: str, state: "GraphState") -> str | None:
        """First matching conditional edge, else first unconditional edge."""
        outs = self.out_edges(node_id)
        for e in outs:
            if e.when is not None and e.when(state):
                return e.dst
        for e in outs:
            if e.when is None:
                return e.dst
        return None


class GraphState(dict):
    """Shared, threaded state. dict subclass so nodes read/write plainly, plus
    a couple of conveniences and a per-node metrics ledger."""

    @property
    def node_metrics(self) -> list[dict]:
        return self.setdefault("_node_metrics", [])

    def record(self, node_id: str, kind: str, res: NodeResult) -> None:
        self.node_metrics.append({"node": node_id, "kind": kind,
                                  "cost_usd": round(res.cost_usd, 4),
                                  "wall_s": round(res.wall_s, 3)})

    def scoped(self, extra: dict) -> "GraphState":
        s = GraphState(self)
        s.update(extra)
        return s
