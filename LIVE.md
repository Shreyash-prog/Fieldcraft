# Running Fieldcraft against a real agent (Claude Code)

The loop's live path drives **Claude Code** through the develop→verify→iterate
loop for real. The LLM's behavior is non-deterministic and can only be validated
with the real CLI + your key — but the **integration boundary** (invocation,
output parsing, file integrity, error/timeout/no-op handling) is hardened and
covered by an offline robustness suite.

## Prerequisites

- Claude Code CLI installed and authenticated (`claude` on your PATH), **or**
  set `FC_CLAUDE_BIN` to its path.
- For the tool-use judge: `ANTHROPIC_API_KEY` set.

## Run it

```bash
# live agent, deterministic judge, auto review
python -m fieldcraft_loop --adapter claude

# fully live: real agent + LLM judge + you as reviewer
python -m fieldcraft_loop --adapter claude --grader tooluse --review human

# in the web POC: choose "claude" / "tool-use" in the form (needs FC_ALLOW_LIVE=1)
```

## What the adapter handles (robustness)

- **Preflight** — a clear error if the CLI is missing (before any file I/O).
- **Timeout** — each turn is bounded by `FC_AGENT_TIMEOUT_S` (default 300s), with
  one retry on a transient failure.
- **Test-file integrity** — if the agent edits the test file, the edit is reverted.
  An agent must not make tests pass by changing the tests.
- **No-op detection** — an empty diff is surfaced, not silently looped on.
- **Error / malformed output** — non-zero exits, `is_error` results, and non-JSON
  output are caught and surfaced into the turn note instead of crashing.

## Env knobs

| Var | Default | Meaning |
|---|---|---|
| `FC_CLAUDE_BIN` | `claude` | path to the CLI |
| `FC_AGENT_TIMEOUT_S` | `300` | per-turn timeout |
| `FC_PYTEST_TIMEOUT_S` | `60` | verification timeout |

## Verify the integration offline (no key)

```bash
python tools/live_robustness_check.py
```

Drives the real adapter against a contract-conformant fake CLI and checks the
full loop plus every failure branch.

## Troubleshooting

- **`LiveAgentError: 'claude' not found`** — install Claude Code or set `FC_CLAUDE_BIN`.
- **CLI rejects `--permission-mode acceptEdits`** — your CLI version differs; adjust
  the flag in `fieldcraft_loop/live_adapter.py` (`_invoke`).
- **Doesn't converge** — raise `--max-iterations`; real agents sometimes need more turns.
- **Cost** — bound it with the per-run budget (the loop stops and escalates on breach).

## Honest limits

- The sample tasks are single-file; a real repo means pointing the Brief at an
  actual codebase (the next depth increment).
- Real-LLM convergence is variable — the `2 iterations` seen with mocks won't be
  exact live; read the real number from the loop AAR.

## Running on a real multi-file repository

The loop operates on multi-file repos, not just single files. A repo task
(`task.json` with `"kind": "repo"`) declares:

- `repo_dir` — the repository to copy into each run's workdir,
- `test_command` — how to verify (e.g. `["python","-m","pytest","-q"]`),
- `protected_paths` — paths the agent must not edit (e.g. `["tests/"]`).

The workdir is a full copy of the repo; verification runs the test command; the
diff spans every changed file; and if the agent edits a protected path, the edit
is **reverted** (an agent can't pass tests by rewriting them). See
`repo_tasks/textkit/` for a worked example, and run the offline robustness suite:

```bash
python tools/repo_robustness_check.py          # loop + integrity guard, no key
```

To run it live on your own repo, add a `task.json` (`kind: repo`, your
`test_command`, your `protected_paths`) and:

```bash
python -c "from fieldcraft_loop.engine import Engine; e=Engine('.fc'); \
b=e.create({'adapter':'claude','review':'human'}, 'path/to/your/repo_task'); e.advance(b)"
```

Honest scope: the multi-file machinery (copy, verify, diff, integrity, feedback,
resumable review) is tested via mock and a contract-conformant fake CLI. The
live-LLM run on a real repo is yours to validate with the `claude` CLI + key.
