# Fieldcraft

**Run AI coding agents through a governed develop→verify→iterate loop, and measure how effectively the human+AI actually delivered.**

Coding agents made *building* cheap. What's still hard is directing them safely and knowing whether the delivery was good — faster, cheaper, correct — and where the improvable gap is. Fieldcraft is the orchestration + measurement layer for that: a governed loop with human-in-the-loop review, a calibrated evaluation layer, per-codebase context, and a measurement science that reports effects **with honest uncertainty**.

Everything here is runnable. The offline paths need no API key.

```bash
pip install -r requirements.txt
python -m fieldcraft_loop            # watch the governed loop converge (mock agent)
python -m fieldcraft_bench           # the multi-task benchmark + dashboard
python -m fieldcraft_measure         # the measurement report (with uncertainty)
python -m uvicorn fieldcraft_web.server:app --port 8000   # the web POC -> http://127.0.0.1:8000
```

## The pieces

| Package | What it is | Try it |
|---|---|---|
| `fieldcraft_aar/` | **Measurement harness** — instruments one AI-assisted run: effectiveness (real tests + acceptance grading), efficiency (cost, turns), operator quality. Hybrid heuristic + LLM-as-judge (Claude forced tool-use). Judge **calibration** (agreement + Cohen's kappa). | `python -m fieldcraft_aar --adapter mock` / `python -m fieldcraft_aar.calibration` |
| `fieldcraft_loop/` | **Governed loop** — an event-sourced state machine driving develop→verify→iterate, with a Turn Assembler, budget/iteration circuit breakers, human-in-the-loop review, and a **resumable Engine** whose state survives restarts. Mock, guided, and live (Claude Code) agents behind one interface. | `python -m fieldcraft_loop [--adapter mock\|claude] [--grader behavioral\|tooluse] [--review auto\|human]` |
| `fieldcraft_guide/` | **Field Guide** — bootstrap any repo into per-codebase context (module map, conventions, traps, retrieval); measurably cuts iterations. A **maintenance flywheel** learns new traps from runs (human-approved) so the guide improves over time. | `python -m fieldcraft_guide bootstrap <repo>` / `python -m fieldcraft_guide.impact` / `python -m fieldcraft_guide flywheel <task>` |
| `fieldcraft_bench/` | **Multi-task benchmark** — runs the suite blind vs Field-Guide-guided and renders a cross-run dashboard. | `python -m fieldcraft_bench` |
| `fieldcraft_measure/` | **Measurement science** — difficulty-normalized efficiency, a validity gate (integrity), aggregate effects with **bootstrap CIs + a sign test**, reporting power honestly. | `python -m fieldcraft_measure` |
| `fieldcraft_web/` | **POC** — FastAPI + single-page UI over the resumable engine; human review in the browser. Hardened for deploy (rate limits, spend caps, sandboxed execution, health check). | `uvicorn fieldcraft_web.server:app` |
| `fieldcraft_graph/` | **Graph orchestration** — the loop re-expressed as a routed graph of role nodes (plan, code, verify, critic, review, integrate). Conditional edges, parallel **fan-out** of the coder across a planner's sub-tasks, and **per-node measurement**. | `python -m fieldcraft_graph` |
| `fieldcraft_gov/` | **Governance** — a declarative policy engine (editable/protected paths, forbidden content like secrets/eval/network, command allowlist, approval thresholds) that reverts violations and logs them, plus a scoped-credential model (least-privilege, expiring, auditable grants). | `python -m fieldcraft_gov` |

## Design notes

- **Event-sourced.** Every transition is an append-only event (SQLite). The run *is* the log — auditable, replayable, resumable, and the measurement layer derives from it rather than needing separate instrumentation.
- **Model-agnostic seam.** Agents (mock / guided / live Claude Code) and judges (behavioral / Claude forced tool-use) are swappable; the controller and engine don't change.
- **Composable.** The develop→verify→iterate loop is one graph; a critic gate, a planner fan-out, or an integrator join are just more nodes and edges. The executor is event-sourced, so per-node cost/latency measurement falls out — and a decomposable task converges in fewer rounds via parallel coders.
- **Governed.** A policy layer controls what an agent may change (beyond just tests) and reverts violations; credentials are scoped, short-lived, and audited. Every policy decision is an event, so governance is replayable.
- **Honest by construction.** Effectiveness is invalid if the agent tampers with tests; efficiency is compared only at constant effectiveness; the measurement layer reports uncertainty and refuses to overclaim at small N.

## Tasks & tools

- `sample_task/`, `tasks/` — self-contained coding tasks (stub, tests, acceptance criteria, staged + full solutions, curated traps, manifest).
- `tools/` — fixture generator, a contract-conformant fake Claude CLI, and the offline robustness + stats checks (`python tools/live_robustness_check.py`, `python tools/measure_stats_check.py`).

## Running live / deploying

`LIVE.md` covers running against the real `claude` CLI; `DEPLOY.md` covers containerizing and deploying the POC. Live runs need `ANTHROPIC_API_KEY` / an authenticated CLI.

## Status

A working system and design exploration, not a shipped product. The loop, evaluation, Field Guide, benchmark, measurement, and web POC are real and tested.
