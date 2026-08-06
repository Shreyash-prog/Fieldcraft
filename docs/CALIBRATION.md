# Judge calibration — measured results

The measurement layer leans on an LLM judge for open-ended acceptance criteria, so
the judge itself has to be calibrated against ground truth before any score it
produces means anything. This file records what was actually measured, so the
number in the README is backed by a committed artifact rather than a memory.

**Headline:** mean Cohen's kappa **0.886** across 5 live runs (range 0.856–0.916,
SD 0.022), **94.5%** agreement over 152 forced-tool-use judgments per run. Perfect
agreement on 3 of 4 criteria; all error is concentrated in AC4 (idempotence), where
the judge is **conservative** — it says `unmet` when the truth is `met`, never the
reverse.

## Method

| | |
|---|---|
| Harness | `fieldcraft_aar/calibration.py` (`python -m fieldcraft_aar.calibration --grader tooluse`) |
| Judge | `ClaudeToolUseGrader` — Claude via the Anthropic Messages API, **forced tool use** (`tool_choice` = `record_judgments`), so every criterion returns a binary met/unmet verdict with cited evidence; no free-text parsing |
| Model | `claude-sonnet-4-6`, `max_tokens` 1500, default temperature |
| Task | `sample_task/` (PII redaction) |
| Fixtures | 38 hand-labeled candidate implementations in `sample_task/fixtures/` (`gen_001`–`gen_036`, `stub.py`, `empty_out.py`), labels in `fixtures/labels.json` |
| Criteria | AC1 emails masked · AC2 phones masked · AC3 plain text preserved · AC4 idempotent |
| Judgments | 38 fixtures × 4 criteria = **152 binary judgments per run**; 5 runs = 760 total |
| Statistic | Overall agreement, per-criterion agreement, and Cohen's kappa (agreement corrected for chance) |
| Conditions | Live Anthropic API, 5 independent runs over the same fixture set |

The judge sees only the candidate implementation and the criteria — never the
labels, and never the behavioral probes that the offline grader uses.

## Raw results

| Run | Cohen's kappa | Agreement | AC1 | AC2 | AC3 | AC4 |
|---|---|---|---|---|---|---|
| 1 | 0.878 | 0.941 | 1.000 | 1.000 | 1.000 | 0.763 |
| 2 | 0.891 | 0.947 | 1.000 | 1.000 | 1.000 | 0.789 |
| 3 | 0.916 | 0.961 | 1.000 | 1.000 | 1.000 | 0.842 |
| 4 | 0.856 | 0.928 | 1.000 | 1.000 | 1.000 | 0.711 |
| 5 | 0.891 | 0.947 | 1.000 | 1.000 | 1.000 | 0.789 |
| **mean** | **0.886** | **0.945** | 1.000 | 1.000 | 1.000 | 0.779 |
| range | 0.856–0.916 | 0.928–0.961 | — | — | — | 0.711–0.842 |
| SD | 0.022 | 0.012 | 0.000 | 0.000 | 0.000 | 0.048 |

Per-criterion columns are agreement rates over that criterion's 38 judgments.
SD is the sample standard deviation (n−1) over the five runs.

Implied disagreement counts, derived from the rates above (152 judgments per run,
38 per criterion — each rate maps to exactly one integer count):

| Run | Disagreements / 152 | of which AC4 |
|---|---|---|
| 1 | 9 | 9 |
| 2 | 8 | 8 |
| 3 | 6 | 6 |
| 4 | 11 | 11 |
| 5 | 8 | 8 |
| **total** | **42 / 760** | **42** |

## The AC4 finding

Every disagreement in every run — 42 of 42 — was the same shape:

> judge predicted **`unmet`**, ground truth **`met`**, on **AC4 (idempotent)**.

There were **no false `met` verdicts** anywhere in the five runs. The judge never
passed an implementation that should have failed; it only failed implementations
that should have passed.

The misses concentrate on idempotence *edge-case* fixtures — `empty_out.py` and
part of the `gen_0NN` set — where idempotence holds but is not evident from a
straightforward reading of the code (e.g. the redacted output is empty or already
contains no further match, so re-running is trivially a no-op). Reasoning about
"applying this twice changes nothing" from source alone is harder than checking
"does this mask an email", which is why AC1–AC3 are perfect and AC4 is not.

Two consequences worth stating plainly:

- **The bias direction is the safe one.** A conservative judge under-reports
  effectiveness; it does not manufacture success. A score produced with this judge
  is a floor, not a ceiling.
- **It is systematic, not random.** The same fixture family fails across runs, so
  most of the run-to-run kappa variance (0.856–0.916) is the judge flipping on a
  handful of borderline idempotence cases, not broad instability.

## What this does and does not establish

**Does:** the forced-tool-use judge agrees with hand labels at kappa 0.886 ± 0.022
on this task, its variance across repeated live runs is now *measured* rather than
assumed, and its failure mode is characterized and one-directional.

**Does not:**

- **One fixture set, one task.** 38 fixtures of a single PII-redaction task. This
  is not a broad study, and the number should not be read as "the judge is 0.886
  on your criteria."
- **Not held out.** The fixtures are fixed and committed, so they can be tuned
  against (Goodhart). A refreshed held-out set is still outstanding.
- **Five runs is a small sample.** The SD is a rough stability estimate, not a
  tight confidence interval.
- **One model, one prompt, one point in time.** Re-run after any model, prompt, or
  criteria change — this result does not transfer across them.

Tracked as HARDENING **P1-3** (partially addressed): held-out calibration set,
ensemble/disagreement-flagging, and cross-task calibration remain future work.

## Reproducing

```bash
export ANTHROPIC_API_KEY=sk-ant-...
python -m fieldcraft_aar.calibration --grader tooluse
```

Prints fixtures, judgments, agreement, kappa, per-criterion agreement, and every
disagreement with the fixture, criterion, predicted verdict, and label. The
offline default (`--grader behavioral`) runs the deterministic probe grader
instead and needs no key.
