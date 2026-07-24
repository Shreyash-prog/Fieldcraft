"""Effectiveness = authoritative test run + acceptance grading.

The test run is real (we shell out to pytest in the produced workdir). The
grader is pluggable: a deterministic behavioral grader that runs offline, and a
Claude-backed LLM-as-judge for open-ended criteria you'd wire with your key.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .models import Effectiveness, CriterionVerdict


# ----------------------------------------------------------------------------
# Authoritative test run (real)
# ----------------------------------------------------------------------------
def run_pytest(workdir: Path) -> tuple[int, int, bool]:
    """Run pytest in workdir. Returns (passed, total, all_pass).

    Bounded by FC_PYTEST_TIMEOUT_S so agent-written code can't hang the process;
    a timeout counts as a failed verification, not a crash."""
    timeout = int(os.environ.get("FC_PYTEST_TIMEOUT_S", "60"))
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"],
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 0, 0, False
    out = proc.stdout + proc.stderr
    passed = _count(out, r"(\d+)\s+passed")
    failed = _count(out, r"(\d+)\s+failed")
    errors = _count(out, r"(\d+)\s+error")
    total = passed + failed + errors
    all_pass = proc.returncode == 0 and failed == 0 and errors == 0 and passed > 0
    return passed, total, all_pass


def _count(text: str, pattern: str) -> int:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else 0


# ----------------------------------------------------------------------------
# Acceptance grading (pluggable)
# ----------------------------------------------------------------------------
class Grader:
    def grade(self, workdir: Path, criteria: list[dict], diff: str,
              module: str = "redact") -> list[CriterionVerdict]:
        raise NotImplementedError


class BehavioralGrader(Grader):
    """Deterministic, offline. Each criterion carries a `probe`: a tiny callable
    spec (input -> expected substring / equality / raises) evaluated against the
    candidate module. A real functional check, not "tests passed => all met"."""

    def grade(self, workdir: Path, criteria: list[dict], diff: str,
              module: str = "redact") -> list[CriterionVerdict]:
        mod = _load_candidate(workdir, module)
        verdicts: list[CriterionVerdict] = []
        for c in criteria:
            try:
                ok, why = _probe(mod, c["probe"])
                verdicts.append(CriterionVerdict(
                    id=c["id"], text=c["text"],
                    verdict="met" if ok else "unmet", rationale=why,
                ))
            except Exception as e:  # candidate missing / import error
                verdicts.append(CriterionVerdict(
                    id=c["id"], text=c["text"], verdict="unclear",
                    rationale=f"probe error: {e}",
                ))
        return verdicts


class ClaudeGrader(Grader):
    """LLM-as-judge for open-ended criteria. Wired for the Anthropic API; needs
    ANTHROPIC_API_KEY. Kept here so the real path is obvious, but the harness
    defaults to BehavioralGrader so it runs with zero credentials."""

    def __init__(self, model: str = "claude-sonnet-4-6"):
        self.model = model

    def grade(self, workdir: Path, criteria: list[dict], diff: str,
              module: str = "redact") -> list[CriterionVerdict]:
        import urllib.request

        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        rubric = "\n".join(f'- {c["id"]}: {c["text"]}' for c in criteria)
        prompt = (
            "You are grading a code change against acceptance criteria. "
            "Return ONLY JSON: a list of {id, verdict (met|unmet|unclear), rationale}.\n\n"
            f"Acceptance criteria:\n{rubric}\n\nDiff:\n{diff}\n"
        )
        body = json.dumps({
            "model": self.model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages", data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
        text = "".join(b.get("text", "") for b in data.get("content", []))
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        rows = json.loads(text)
        by_id = {c["id"]: c["text"] for c in criteria}
        return [CriterionVerdict(
            id=r["id"], text=by_id.get(r["id"], ""),
            verdict=r.get("verdict", "unclear"), rationale=r.get("rationale", ""),
        ) for r in rows]


def _load_candidate(workdir: Path, module_name: str):
    path = workdir / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"_cand_{module_name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _probe(module, probe: dict) -> tuple[bool, str]:
    """probe = {func, args, contains|equals|idempotent|raises}."""
    fn = getattr(module, probe["func"])
    args = probe.get("args", [])
    if "raises" in probe:
        import builtins
        exc = getattr(builtins, probe["raises"], Exception)
        try:
            fn(*args)
            return False, f"expected {probe['raises']}, none raised"
        except exc:
            return True, f"raised {probe['raises']} as expected"
        except Exception as e:  # noqa: BLE001
            return False, f"raised {type(e).__name__}, expected {probe['raises']}"
    result = fn(*args)
    if "contains" in probe:
        ok = probe["contains"] in result
        return ok, f'{probe["func"]}({args!r}) -> {result!r}; contains {probe["contains"]!r}: {ok}'
    if "equals" in probe:
        ok = result == probe["equals"]
        return ok, f'{probe["func"]}({args!r}) -> {result!r}; == {probe["equals"]!r}: {ok}'
    if probe.get("idempotent"):
        twice = fn(result)
        ok = twice == result
        return ok, f"idempotent on {args!r}: {ok}"
    return False, "no assertion in probe"


# ----------------------------------------------------------------------------
# Compose
# ----------------------------------------------------------------------------
def compute_effectiveness(workdir: Path, criteria: list[dict], diff: str, grader: Grader,
                          module: str = "redact") -> Effectiveness:
    passed, total, all_pass = run_pytest(workdir)
    verdicts = grader.grade(workdir, criteria, diff, module)
    test_rate = (passed / total) if total else 0.0
    crit_rate = (sum(1 for v in verdicts if v.verdict == "met") / len(verdicts)) if verdicts else 0.0
    score = round(0.5 * test_rate + 0.5 * crit_rate, 3)
    return Effectiveness(
        tests_total=total, tests_passed=passed, all_tests_pass=all_pass,
        criteria=verdicts, score=score,
    )
