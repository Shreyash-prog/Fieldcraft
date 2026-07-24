# fieldcraft_guide — the Field Guide (Phase 3)

A per-codebase brain that makes the agent start a task already oriented. Point it
at any Python repo and get a usable Field Guide in seconds.

```bash
python -m fieldcraft_guide bootstrap <repo>        # scan -> FIELD_GUIDE.md + field_guide.json
python -m fieldcraft_guide context  <repo>         # the compiled agent context
python -m fieldcraft_guide search   <repo> "query" # query the guide
python -m fieldcraft_guide.impact                  # measure with-vs-without on the sample task
```

## What it does

- **bootstrap.py** — deterministic scan: module map (AST symbols), house conventions
  (type-hint/docstring coverage, `__future__` annotations, dataclasses), a glossary of
  central symbols, curated **traps** (from `NOTES.md` + acceptance criteria), and the
  test strategy. Pinned to the git commit for drift detection. (An optional LLM pass
  can add per-module summaries.)
- **compile.py** — turns the guide into (1) a token-bounded **context string** injected
  into the agent prompt and (2) a **retrieval index** the agent can query.
- **impact.py** — runs the same Brief with and without the compiled guide and reports the
  efficiency delta.

## Why it matters

Fieldcraft measures how effectively a human+AI loop delivers, and **context is the
biggest lever on that**. The Field Guide makes the lever real: on the sample task it
takes the loop from 2 iterations to 1 (2x cheaper to converge) by flagging a known
trap up front instead of letting the review loop rediscover it. Guide quality is
now a measurable input to delivery efficiency — which is the whole thesis.

Both the mock (`GuidedMockAdapter`) and live (`ClaudeCodeLoopAdapter`) agents accept
the compiled context, so the controller is unchanged.
