# Fieldcraft test suite

Real pytest coverage of the framework itself (not the sample tasks). No API key
required — the live-agent path is covered via output-parsing/preflight units and,
in the robustness scripts, a contract-conformant fake CLI.

```bash
pip install -r requirements.txt
pytest                 # runs tests/
```

## What's covered

| File | Layer | Key properties pinned |
|---|---|---|
| `test_measure.py` | measurement science | sign test / min-N / paired effect (hand-checked values), efficiency-captured, operator quality, validity gate |
| `test_store.py` | event store | ordered brief-scoped replay, persistence across reopen |
| `test_feedback.py` | Turn Assembler | criterion & failing-test directives, comment classification |
| `test_effectiveness.py` | behavioral grader | contains / raises / idempotent probes, module param |
| `test_engine.py` | resumable engine | auto run, human review, **survives restart**, budget & iteration circuit breakers, guided speedup |
| `test_repo_task.py` | multi-file repo | stub/stage/solution tallies, protected-path reversion, multi-file diff, repo loop |
| `test_guide.py` | Field Guide | trap extraction, compiled context, retrieval |
| `test_limits.py` | deploy guards | rate limiter, cost tracker, concurrency |
| `test_live_adapter.py` | live adapter | JSON/error/malformed parsing, missing-CLI preflight |
| `test_web.py` | web API | health, request clamps, full auto run over HTTP, 404 |
| `test_flywheel.py` | Field Guide flywheel | trap discovery (single/repo), dedup, approval persistence, self-improvement 2→1 |
| `test_graph.py` | graph orchestration | routing, plan/code/verify/critic/integrate nodes, linear=2 rounds vs parallel=1, event logging, per-node metrics |
| `test_gov.py` | governance | policy engine (paths/content/command/approval), diff enforcement + revert, scoped credentials (scope/expiry/revoke/audit), engine integration |

Plus standalone robustness scripts: `tools/live_robustness_check.py`,
`tools/repo_robustness_check.py`, `tools/measure_stats_check.py`.

## Coverage

```bash
pip install pytest-cov
pytest --cov=fieldcraft_aar --cov=fieldcraft_loop --cov=fieldcraft_guide \
       --cov=fieldcraft_measure --cov=fieldcraft_web --cov=fieldcraft_bench --cov-report=term
```

**96 tests · 86% line coverage.** `.coveragerc` omits only trivial `__main__.py`
shims and `grader_tooluse.py` (requires a live API key). Core runtime is 90–100%
(engine 90, live_adapter 92, repo_task 94; store/stats/metrics/feedback 100).
The remaining uncovered lines are the argparse CLI wrappers and legacy Phase-1
harness adapters.
