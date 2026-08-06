"""Canonical graphs. The linear loop and a decompose→parallel→integrate graph —
both over the same nodes and executor."""
from __future__ import annotations

from .models import Graph, Edge
from .nodes import PlanNode, CodeNode, IntegrateNode, VerifyNode, CriticNode, ReviewNode


def build_linear_graph(review_mode: str = "auto") -> Graph:
    nodes = {"code": CodeNode(), "verify": VerifyNode(),
             "critic": CriticNode(), "review": ReviewNode(mode=review_mode)}
    edges = [
        Edge("code", "verify"),
        Edge("verify", "critic"),
        Edge("critic", "code", when=lambda s: bool(s.get("critic_flag")), label="flag→code"),
        Edge("critic", "review"),
        Edge("review", None, when=lambda s: bool(s.get("approved")), label="approved"),
        Edge("review", "code", label="changes→code"),
    ]
    return Graph("code", nodes, edges)


def build_parallel_graph(review_mode: str = "auto") -> Graph:
    code = CodeNode()
    code.fanout = "sub_tasks"                          # fan the coder out over the plan
    nodes = {"plan": PlanNode(), "code": code, "integrate": IntegrateNode(),
             "verify": VerifyNode(), "critic": CriticNode(), "review": ReviewNode(mode=review_mode)}
    edges = [
        Edge("plan", "code"),
        Edge("code", "integrate"),
        Edge("integrate", "verify"),
        Edge("verify", "critic"),
        Edge("critic", "code", when=lambda s: bool(s.get("critic_flag")), label="flag→code"),
        Edge("critic", "review"),
        Edge("review", None, when=lambda s: bool(s.get("approved")), label="approved"),
        Edge("review", "code", label="changes→code"),
    ]
    return Graph("plan", nodes, edges)
