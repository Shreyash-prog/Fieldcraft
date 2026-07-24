# fieldcraft_web — the POC (FastAPI + single-page UI)

A browser front end over the governed loop: create a Brief, watch the agent work
it turn-by-turn, step in as the human reviewer (approve / request changes / reject),
and see the run scored in an After-Action Review dashboard.

## Run

```bash
pip install -r requirements-web.txt
python -m uvicorn fieldcraft_web.server:app --reload --port 8000
# open http://127.0.0.1:8000
```

Defaults (mock agent, behavioral judge, human review) run fully offline — no key.
For the live agent/judge, pick `claude` / `tool-use` in the form (needs the
`claude` CLI and `ANTHROPIC_API_KEY`).

## How it works

- **server.py** — FastAPI. Each Brief runs the loop on a background thread; in
  human-review mode the thread blocks at the `WebReviewer` until the browser posts
  a decision. State is the event log (SQLite) + a small in-memory run registry.
- **web_reviewer.py** — publishes the pending review (diff + verdict) and blocks on
  a queue for the browser's decision; same `ReviewDecision` contract as the CLI.
- **static/index.html** — one file, no build step. Polls the event log, renders each
  turn's diff + per-criterion verdict, shows the review panel when it's your turn,
  and draws the AAR dashboard on completion.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/briefs` | create + start a run (`adapter`, `grader`, `review`, `max_iterations`, `budget`) |
| GET  | `/api/briefs/{id}` | status + AAR |
| GET  | `/api/briefs/{id}/events` | the event log |
| GET  | `/api/briefs/{id}/pending` | the pending review (diff + verdict) |
| POST | `/api/briefs/{id}/review` | submit a decision (`approve` / `changes` + `comment` / `reject`) |
