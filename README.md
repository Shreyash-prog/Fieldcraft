# Fieldcraft

**Measuring how effectively people deliver with AI.**

Coding agents made *building* cheap. What almost nobody measures is the *delivery*: when an engineer works a task with an AI agent, did they ship faster, cheaper, and better — and where is the improvable gap? Agent-reliability tooling grades the *agent*. Fieldcraft grades the *human + AI loop*.

This repo is two things, in order of importance:

- **A working v0 (`fieldcraft_aar/`)** — a small, runnable harness that instruments an AI-assisted coding task and emits an After-Action Review: effectiveness, efficiency, and how well the operator drove the agent.
- **A design exploration (`docs/architecture.md`)** — the larger system this measurement layer belongs to.

---

## Run it — 30 seconds, no credentials

```bash
pip install -r requirements.txt
python -m fieldcraft_aar --adapter mock
# → out/aar.json and a self-contained out/aar_report.html
```

![After-Action Review report](assets/aar_report.png)

The demo runs the same task two ways — a rich-context run and a thin-context run. Both reach **identical effectiveness** (all tests pass, all acceptance criteria met), but one costs **2.2× the other**, with the gap attributed to input context quality. That delta is invisible to agent-reliability scoring, and it is the whole point.

Effectiveness is **real** — the harness actually runs the task's `pytest` suite and probes the resulting code against each acceptance criterion. Only the run *trace* (cost/turns) is replayed in mock mode.

---

## What it measures

| Family | Answers | Signals |
|---|---|---|
| **Effectiveness** | Was the outcome good? | tests passing, acceptance criteria met, composite score |
| **Efficiency** | What did it cost? | cost (USD), turns, tool calls, wall-clock |
| **AI-usage quality** | How well did the operator drive the AI? | turns-to-converge, rework turns, directive efficiency, input spec completeness |

Efficiency is compared **only at constant effectiveness** — "used less" counts as better *only when the outcome is held equal*, never for cutting corners.

---

## Live mode

```bash
python -m fieldcraft_aar --adapter claude --grader claude --conditions rich_context
```

Runs a real Claude Code session (`claude -p --output-format json`) in a fresh workdir and parses its cost/turns. The `RunAdapter` seam is the design: the metrics are **model- and framework-agnostic** — point it at any agent that edits a repo, and the measurement layer doesn't care which model produced the work.

---

## Layout

```
fieldcraft_aar/      the harness: adapters · effectiveness · telemetry · aar · report
sample_task/         a small PII-redaction task (stub, tests, criteria, reference solution)
scenarios/           recorded run traces for offline mock mode
docs/architecture.md the broader design this slice belongs to
```

---

## The bigger picture

This harness is one layer of a larger design for AI-assisted forward-deployed engineering — trust boundary, execution model, verification, governance, and this measurement layer. That design lives in [`docs/architecture.md`](docs/architecture.md), written as an exploration.

To be clear about status: **the measurement slice in this repo runs; the full architecture is a design, not a shipped system.** The interesting, differentiated, and *built* part is the measurement of human + AI delivery.

---

## Status & limits

- **v0.** The mock scenarios are illustrative traces; live mode produces real numbers.
- **Fair cross-operator comparison needs N.** Difficulty-adjusting real, different tasks to isolate operator skill improves with data — it is a direction, not a solved ranking engine. Standardized benchmark tasks (like the sample) give clean apples-to-apples soonest.
- Effectiveness rests on test quality — passing tests narrow the correctness gap, they don't close it.

## License

MIT — see [LICENSE](LICENSE).
