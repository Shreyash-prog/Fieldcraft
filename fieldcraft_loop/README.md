# fieldcraft_loop — the governed loop (Phase 2)

An event-sourced state machine that drives a **Brief** through
`WORKING → VERIFYING → review → (iterate | done)` — the develop→verify→iterate
loop at the core of Fieldcraft.

```bash
python -m fieldcraft_loop          # runs the sample Brief through the loop
```

What happens each iteration: an agent turn edits the repo, the verifier runs the
**real** test suite plus acceptance grading, and an auto-reviewer either approves
(clean verdict → `done`) or the **Turn Assembler** classifies the failing verdict
into next-turn directives and the loop iterates. Hard stops (`max_iterations`,
`budget`) route to `needs_human`.

- **Event store** (`store.py`) — append-only SQLite log; the run's source of truth.
- **Controller** (`controller.py`) — the state machine + hard-stop circuit breakers.
- **Turn Assembler** (`feedback.py`) — verdict → classified next-turn instructions.
- **Adapter** (`progressive_adapter.py`) — feedback-driven mock agent; swap for a
  live `ClaudeCodeAdapter` and the controller is unchanged (model-agnostic seam).

The **loop-level AAR** (iterations, total cost, turns-to-converge, rework, the
effectiveness trajectory) is derived from the event log — measurement rides the
spine rather than needing separate instrumentation.

Reuses the Phase-1 verification and grading from `fieldcraft_aar/`.
