"""Demo: run the linear loop-as-graph and the decompose→parallel graph on a
multi-file repo; show per-node metrics and the decomposition win.

    python -m fieldcraft_graph
"""
import sys
import tempfile
from pathlib import Path

from fieldcraft_loop.store import EventStore
from fieldcraft_loop.repo_task import RepoTask, copy_repo
from fieldcraft_graph.models import GraphState
from fieldcraft_graph.executor import GraphExecutor
from fieldcraft_graph.graphs import build_linear_graph, build_parallel_graph
from fieldcraft_graph.measure import graph_aar

ROOT = Path(__file__).resolve().parent.parent


def _run(graph, tag):
    d = Path(tempfile.mkdtemp())
    wd = d / "wd"
    copy_repo(RepoTask.load(ROOT / "repo_tasks" / "textkit"), wd)
    ex = GraphExecutor(EventStore(d / "e.db"), "B-" + tag)
    st = GraphState({"task_dir": str(ROOT / "repo_tasks" / "textkit"), "workdir": str(wd)})
    ex.run(graph, st)
    return graph_aar(st, ex.round)


def main() -> int:
    print("=== Fieldcraft graph orchestration ===")
    for tag, g in (("linear (loop-as-graph)", build_linear_graph()),
                   ("parallel (decompose)", build_parallel_graph())):
        a = _run(g, tag.split()[0])
        print(f"\n{tag}: converged={a['converged']} rounds={a['rounds']} "
              f"tests={a['verdict']} cost=${a['total_cost']}")
        for n in a["per_node"]:
            print(f"    {n['kind']:10} runs={n['runs']}  ${n['cost_usd']}")
    lin = _run(build_linear_graph(), "l")["rounds"]
    par = _run(build_parallel_graph(), "p")["rounds"]
    print(f"\n→ decomposition + parallel coders converged in {par} round "
          f"vs {lin} for the sequential loop on the same task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
