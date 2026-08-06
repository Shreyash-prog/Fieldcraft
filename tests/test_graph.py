"""Graph orchestration — model routing, nodes, executor, per-node measurement."""
import tempfile
from pathlib import Path
from fieldcraft_loop.store import EventStore
from fieldcraft_loop.repo_task import RepoTask, copy_repo
from fieldcraft_graph.models import Graph, Edge, GraphState, NodeResult
from fieldcraft_graph.nodes import PlanNode, CodeNode, VerifyNode, CriticNode, IntegrateNode, ReviewNode
from fieldcraft_graph.executor import GraphExecutor
from fieldcraft_graph.graphs import build_linear_graph, build_parallel_graph
from fieldcraft_graph.measure import graph_aar, per_node
from tests.conftest import REPO_TASK


def _fresh():
    d = Path(tempfile.mkdtemp()); wd = d / "wd"
    copy_repo(RepoTask.load(REPO_TASK), wd)
    ex = GraphExecutor(EventStore(d / "e.db"), "B")
    st = GraphState({"task_dir": REPO_TASK, "workdir": str(wd)})
    return ex, st


# --- model ---
def test_routing_prefers_conditional_then_default():
    g = Graph("a", {}, [Edge("a", "cond", when=lambda s: s.get("go")), Edge("a", "def")])
    assert g.next("a", GraphState({"go": True})) == "cond"
    assert g.next("a", GraphState({"go": False})) == "def"

def test_state_scoped_isolates():
    s = GraphState({"x": 1})
    s2 = s.scoped({"_item": "z"})
    assert s2["x"] == 1 and s2["_item"] == "z" and "_item" not in s


# --- nodes ---
def test_plan_decomposes_textkit():
    _, st = _fresh()
    r = PlanNode().run(st)
    ids = {t["id"] for t in r.outputs["sub_tasks"]}
    assert ids == {"slug", "casing"}

def test_code_scoped_writes_one_file():
    _, st = _fresh()
    st["_item"] = {"id": "slug", "file": "textkit/slug.py"}
    r = CodeNode().run(st)
    assert "textkit/slug.py" in r.outputs["diff"] and "casing" not in r.outputs["diff"]

def test_verify_detects_convergence():
    _, st = _fresh()
    st["sub_tasks"] = [{"id": "slug", "file": "textkit/slug.py"}, {"id": "casing", "file": "textkit/casing.py"}]
    for t in st["sub_tasks"]:
        CodeNode(scope=t).run(st)
    r = VerifyNode().run(st)
    assert r.outputs["converged"] and r.outputs["verdict"]["tests"] == "8/8"

def test_critic_flags_forbidden_content():
    st = GraphState({"diff": "+++ b/x.py\n+api_key = \"AKIA1234567890ABCDEF\"\n+# TODO fix\n"})
    r = CriticNode().run(st)
    assert r.outputs["critic_flag"] in ("hardcoded_secret", "leftover_todo")

def test_critic_clean_passes():
    st = GraphState({"diff": "+++ b/x.py\n+def f(): return 1\n"})
    assert CriticNode().run(st).outputs["critic_flag"] == ""

def test_integrate_flags_conflict():
    _, st = _fresh()
    st["_prefanout"] = {}
    st["sub_tasks"] = [{"id": "a", "file": "textkit/slug.py"}, {"id": "b", "file": "textkit/slug.py"}]
    assert IntegrateNode().run(st).outputs["conflict"] is True


# --- routing with critic ---
def test_linear_graph_routes_critic_flag_back_to_code():
    g = build_linear_graph()
    assert g.next("critic", GraphState({"critic_flag": "leftover_todo"})) == "code"
    assert g.next("critic", GraphState({"critic_flag": ""})) == "review"
    assert g.next("review", GraphState({"approved": True})) is None
    assert g.next("review", GraphState({"approved": False})) == "code"


# --- executor: the payoff ---
def test_linear_converges_in_two_rounds():
    ex, st = _fresh()
    ex.run(build_linear_graph(), st)
    assert st["converged"] and st["approved"] and ex.round == 2

def test_parallel_converges_in_one_round():
    ex, st = _fresh()
    ex.run(build_parallel_graph(), st)
    assert st["converged"] and st["approved"] and ex.round == 1

def test_events_logged_to_store():
    ex, st = _fresh()
    ex.run(build_parallel_graph(), st)
    types = {e["type"] for e in ex.store.events("B")}
    assert {"graph_start", "plan", "turn_done", "integrate", "verdict", "review", "graph_end"} <= types

def test_per_node_measurement():
    ex, st = _fresh()
    ex.run(build_parallel_graph(), st)
    a = graph_aar(st, ex.round)
    kinds = {n["kind"] for n in a["per_node"]}
    assert {"plan", "code", "integrate", "verify", "critic", "review"} == kinds
    code = next(n for n in a["per_node"] if n["kind"] == "code")
    assert code["runs"] == 2 and code["cost_usd"] > 0        # two parallel coder branches
