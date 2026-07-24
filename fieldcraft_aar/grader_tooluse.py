"""LLM-as-judge grader using Claude forced tool-use.

The judge is *forced* to call `record_judgments`, so every acceptance criterion
comes back as a structured, binary (met/unmet), evidence-cited verdict — no
free-text parsing, no room to hedge. This is the reliable-judgment primitive the
whole measurement layer leans on. Needs ANTHROPIC_API_KEY; the offline path uses
BehavioralGrader instead.
"""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from .effectiveness import Grader
from .models import CriterionVerdict

_TOOL = {
    "name": "record_judgments",
    "description": "Record a binary met/unmet judgment, with cited evidence, for every acceptance criterion.",
    "input_schema": {
        "type": "object",
        "properties": {
            "judgments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "criterion_id": {"type": "string"},
                        "verdict": {"type": "string", "enum": ["met", "unmet"]},
                        "evidence": {"type": "string",
                                     "description": "Cite the specific code or behavior that justifies the verdict."},
                    },
                    "required": ["criterion_id", "verdict", "evidence"],
                },
            }
        },
        "required": ["judgments"],
    },
}


class ClaudeToolUseGrader(Grader):
    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    def grade(self, workdir: Path, criteria: list[dict], diff: str,
              module: str = "redact") -> list[CriterionVerdict]:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")

        code = (workdir / f"{module}.py").read_text()
        rubric = "\n".join(f'- {c["id"]}: {c["text"]}' for c in criteria)
        prompt = (
            "Judge this implementation against each acceptance criterion. "
            "Call record_judgments exactly once with a binary verdict and cited evidence for every criterion.\n\n"
            f"Acceptance criteria:\n{rubric}\n\nImplementation (redact.py):\n{code}\n"
        )
        body = json.dumps({
            "model": self.model,
            "max_tokens": 1500,
            "tools": [_TOOL],
            "tool_choice": {"type": "tool", "name": "record_judgments"},
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={"content-type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())

        tool_input = next((b["input"] for b in data.get("content", [])
                           if b.get("type") == "tool_use"), {"judgments": []})
        by_id = {c["id"]: c["text"] for c in criteria}
        return [CriterionVerdict(
            id=j["criterion_id"], text=by_id.get(j["criterion_id"], ""),
            verdict=j["verdict"], rationale=j.get("evidence", ""),
        ) for j in tool_input["judgments"]]
