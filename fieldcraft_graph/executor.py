"""Graph executor — event-sourced, conditional routing, parallel fan-out.

Reuses the loop's EventStore, so every node execution is an event and the run
is auditable and (because state is explicit) resumable. Fan-out runs a node once
per item over a state list, in parallel threads, then rejoins at the next node.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fieldcraft_loop.models import State
from fieldcraft_loop.repo_task import snapshot
from .models import Graph, GraphState


class GraphExecutor:
    def __init__(self, store, bid: str):
        self.store = store
        self.bid = bid
        self.round = 0

    def run(self, graph: Graph, state: GraphState, max_steps: int = 60) -> GraphState:
        self.store.append(self.bid, 0, State.READY, "graph_start", {"entry": graph.entry})
        cur, steps = graph.entry, 0
        while cur is not None and steps < max_steps:
            node = graph.nodes[cur]
            steps += 1
            if node.kind == "code":
                self.round += 1
            if getattr(node, "fanout", None):
                self._fanout(node, state)
            else:
                self._apply(node, node.run(state), state)
            cur = graph.next(cur, state)
        self.store.append(self.bid, self.round, State.DONE, "graph_end",
                          {"converged": bool(state.get("converged")),
                           "approved": bool(state.get("approved")), "rounds": self.round})
        return state

    def _apply(self, node, res, state) -> None:
        state.update(res.outputs)
        state.record(node.id, node.kind, res)
        for et, ep in res.events:
            self.store.append(self.bid, self.round, State.WORKING, et, {**ep, "node": node.id})

    def _fanout(self, node, state) -> None:
        items = state[node.fanout]
        state["_prefanout"] = snapshot(Path(state["workdir"]))
        results = {}
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(items)))) as ex:
            futs = {ex.submit(node.run, state.scoped({"_item": it})): it for it in items}
            for f in as_completed(futs):
                results[futs[f]["id"]] = f.result()
        for it in items:                                # deterministic order for the log
            r = results[it["id"]]
            state.record(node.id, node.kind, r)
            for et, ep in r.events:
                self.store.append(self.bid, self.round, State.WORKING, et,
                                  {**ep, "node": node.id, "branch": it["id"]})
