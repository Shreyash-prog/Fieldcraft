"""Web API — health, request clamps, and a full auto run over HTTP."""
import time
import pytest
from fastapi.testclient import TestClient
from fieldcraft_web.server import app

client = TestClient(app)


def test_health():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True

def test_create_returns_brief_and_clamps():
    r = client.post("/api/briefs", json={"adapter": "mock", "review": "auto",
                                         "max_iterations": 99, "budget": 50})
    assert r.status_code == 200
    cfg = r.json()["config"]
    assert cfg["max_iterations"] <= 6 and cfg["budget"] <= 1.0        # clamped

def test_full_auto_run_completes():
    bid = client.post("/api/briefs", json={"adapter": "mock", "review": "auto"}).json()["brief_id"]
    status = None
    for _ in range(80):
        status = client.get(f"/api/briefs/{bid}").json()
        if status["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.25)
    assert status["status"] == "done"
    assert status["aar"]["iterations"] == 2
    ev = client.get(f"/api/briefs/{bid}/events").json()["events"]
    assert any(e["type"] == "verdict" for e in ev)

def test_unknown_brief_404():
    assert client.get("/api/briefs/NOPE").status_code == 404


def test_tasks_endpoint():
    tasks = client.get("/api/tasks").json()["tasks"]
    names = [t["name"] for t in tasks]
    assert "redact_pii" in names and any(t["kind"] == "repo" for t in tasks)

def test_repo_task_run_over_http():
    import time
    bid = client.post("/api/briefs", json={"task": "textkit (multi-file repo)",
                                           "adapter": "mock", "review": "auto"}).json()["brief_id"]
    for _ in range(80):
        s = client.get(f"/api/briefs/{bid}").json()
        if s["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.25)
    assert s["status"] == "done"

def test_report_endpoint_governance():
    import time
    r = None
    for _ in range(60):
        r = client.get("/api/reports/governance").json()
        if r["status"] in ("ready", "error"):
            break
        time.sleep(0.5)
    assert r["status"] == "ready"
    assert "config.py" in r["data"]["governance"]["files_reverted"]

def test_unknown_report_404():
    assert client.get("/api/reports/nope").status_code == 404


def test_history_endpoint():
    client.post("/api/briefs", json={"task": "redact_pii", "adapter": "mock", "review": "auto"})
    briefs = client.get("/api/briefs").json()["briefs"]
    assert len(briefs) >= 1 and "status" in briefs[0] and "task" in briefs[0]

def test_sse_stream_completes():
    import json as J
    bid = client.post("/api/briefs", json={"task": "redact_pii", "adapter": "mock", "review": "auto"}).json()["brief_id"]
    types, state, cur = [], None, None
    with client.stream("GET", f"/api/briefs/{bid}/stream") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event:"):
                cur = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                d = J.loads(line.split(":", 1)[1])
                if cur == "event":
                    types.append(d["type"])
                elif cur == "state":
                    state = d["status"]
    assert "verdict" in types and "approved" in types and state == "done"

def test_policy_enforced_over_http():
    import time
    bid = client.post("/api/briefs", json={"task": "redact_pii", "adapter": "mock", "review": "auto",
          "policy": {"protected_paths": ["test_redact.py"], "editable_paths": ["**"]}}).json()["brief_id"]
    for _ in range(60):
        s = client.get(f"/api/briefs/{bid}").json()
        if s["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.25)
    ev = client.get(f"/api/briefs/{bid}/events").json()["events"]
    assert any(e["type"] == "policy" for e in ev)
