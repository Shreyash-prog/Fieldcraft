"""Board tickets — CRUD, tenant isolation, validation, and the forward-looking
fields the run phase will populate."""
import pytest
from fastapi.testclient import TestClient

from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from fieldcraft_loop.ticket_store import (DESCRIPTION_MAX, RUN_MODES, STATUSES,
                                          TITLE_MAX, TicketStore)

CODES = "alpha-code,beta-code"


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """A fresh ticket store per test (the server's is process-global)."""
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    return server.tickets


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth",
                        Auth(codes=CODES, secret="test-signing-key", salt=b"fixed-test-salt"))


def session(code: str) -> TestClient:
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    assert c.cookies.get(COOKIE)
    return c


def make(client: TestClient, **body) -> dict:
    r = client.post("/api/tickets", json={"title": "Ship the thing", **body})
    assert r.status_code == 200, r.text
    return r.json()


# --- happy paths -------------------------------------------------------------

def test_create_returns_a_ticket():
    c = TestClient(server.app)
    t = make(c, description="Wire the widget to the doohickey")
    assert t["id"].startswith("TCK-")
    assert t["title"] == "Ship the thing" and t["status"] == "backlog"
    assert t["created_at"] > 0 and t["updated_at"] > 0

def test_create_accepts_an_explicit_status():
    c = TestClient(server.app)
    assert make(c, status="review")["status"] == "review"

def test_list_is_newest_first():
    c = TestClient(server.app)
    first, second = make(c, title="older"), make(c, title="newer")
    body = c.get("/api/tickets").json()
    assert [t["id"] for t in body["tickets"]][:2] == [second["id"], first["id"]]
    assert body["statuses"] == list(STATUSES)

def test_get_one():
    c = TestClient(server.app)
    t = make(c)
    assert c.get(f"/api/tickets/{t['id']}").json()["id"] == t["id"]

def test_get_unknown_is_404():
    assert TestClient(server.app).get("/api/tickets/TCK-nope").status_code == 404

def test_patch_updates_fields_and_bumps_updated_at():
    c = TestClient(server.app)
    t = make(c)
    r = c.patch(f"/api/tickets/{t['id']}", json={"title": "Renamed", "description": "New body"})
    assert r.status_code == 200
    got = r.json()
    assert got["title"] == "Renamed" and got["description"] == "New body"
    assert got["updated_at"] >= t["updated_at"] and got["created_at"] == t["created_at"]

def test_status_change_moves_the_card():
    c = TestClient(server.app)
    t = make(c)
    for status in ("in_progress", "review", "done"):
        assert c.patch(f"/api/tickets/{t['id']}", json={"status": status}).json()["status"] == status
    assert c.get(f"/api/tickets/{t['id']}").json()["status"] == "done"

def test_delete_removes_it():
    c = TestClient(server.app)
    t = make(c)
    assert c.delete(f"/api/tickets/{t['id']}").json()["ok"] is True
    assert c.get(f"/api/tickets/{t['id']}").status_code == 404
    assert c.delete(f"/api/tickets/{t['id']}").status_code == 404


# --- validation --------------------------------------------------------------

@pytest.mark.parametrize("bad", ["nope", "BACKLOG", "", "in progress", "done "])
def test_bad_status_is_rejected_on_create(bad):
    r = TestClient(server.app).post("/api/tickets", json={"title": "t", "status": bad})
    assert r.status_code == 400 and "status must be one of" in r.json()["detail"]

def test_bad_status_is_rejected_on_patch():
    c = TestClient(server.app)
    t = make(c)
    assert c.patch(f"/api/tickets/{t['id']}", json={"status": "shipped"}).status_code == 400
    assert c.get(f"/api/tickets/{t['id']}").json()["status"] == "backlog"   # unchanged

@pytest.mark.parametrize("title", ["", "   ", "\n\t"])
def test_empty_title_is_rejected(title):
    assert TestClient(server.app).post("/api/tickets", json={"title": title}).status_code == 400

def test_empty_title_is_rejected_on_patch():
    c = TestClient(server.app)
    t = make(c)
    assert c.patch(f"/api/tickets/{t['id']}", json={"title": "  "}).status_code == 400

def test_long_strings_are_clamped():
    c = TestClient(server.app)
    t = make(c, title="T" * 5000, description="D" * 50_000)
    assert len(t["title"]) == TITLE_MAX and len(t["description"]) == DESCRIPTION_MAX

def test_titles_are_trimmed():
    assert make(TestClient(server.app), title="  padded  ")["title"] == "padded"


# --- tenant isolation --------------------------------------------------------

def test_another_user_cannot_see_or_change_my_ticket(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    assert a.get(f"/api/tickets/{t['id']}").status_code == 200
    assert b.get(f"/api/tickets/{t['id']}").status_code == 404        # not 403
    assert b.patch(f"/api/tickets/{t['id']}", json={"title": "hijacked"}).status_code == 404
    assert b.delete(f"/api/tickets/{t['id']}").status_code == 404
    assert a.get(f"/api/tickets/{t['id']}").json()["title"] == "Ship the thing"

def test_list_shows_only_my_tickets(secured):
    a, b = session("alpha-code"), session("beta-code")
    mine, theirs = make(a, title="mine"), make(b, title="theirs")
    assert [t["id"] for t in a.get("/api/tickets").json()["tickets"]] == [mine["id"]]
    assert [t["id"] for t in b.get("/api/tickets").json()["tickets"]] == [theirs["id"]]

def test_tickets_require_a_session(secured):
    anon = TestClient(server.app)
    assert anon.get("/api/tickets").status_code == 401
    assert anon.post("/api/tickets", json={"title": "x"}).status_code == 401
    assert anon.get("/api/tickets/TCK-x").status_code == 401
    assert anon.patch("/api/tickets/TCK-x", json={"title": "x"}).status_code == 401
    assert anon.delete("/api/tickets/TCK-x").status_code == 401


# --- the fields the run phase will populate ---------------------------------

def test_forward_looking_fields_start_empty():
    t = make(TestClient(server.app))
    assert t["repo_url"] is None and t["repo_task_handle"] is None
    assert t["pdf_context_ids"] == [] and t["runs"] == []

def test_store_can_attach_a_repo_and_pdf_context(store):
    t = store.create("u-a", "t")
    got = store.update(t["id"], "u-a", repo_url="https://github.com/o/r",
                       repo_task_handle="o/r (connected)", pdf_context_ids=["doc-1", "doc-2"])
    assert got["repo_url"] == "https://github.com/o/r"
    assert got["pdf_context_ids"] == ["doc-1", "doc-2"]
    assert store.get(t["id"], "u-a")["repo_task_handle"] == "o/r (connected)"

def test_store_records_one_run_per_mode(store):
    t = store.create("u-a", "t")
    for mode in RUN_MODES:
        store.attach_run(t["id"], "u-a", f"BRIEF-{mode[:4]}", mode, provider="claude")
    runs = store.get(t["id"], "u-a")["runs"]
    assert [r["mode"] for r in runs] == list(RUN_MODES)
    assert all(r["brief_id"].startswith("BRIEF-") and r["provider"] == "claude" for r in runs)

def test_store_rejects_an_unknown_run_mode(store):
    t = store.create("u-a", "t")
    with pytest.raises(ValueError, match="mode must be one of"):
        store.attach_run(t["id"], "u-a", "BRIEF-x", "vibes")

def test_store_scopes_every_read_and_write(store):
    t = store.create("u-a", "mine")
    assert store.get(t["id"], "u-b") is None
    assert store.update(t["id"], "u-b", title="hijacked") is None
    assert store.attach_run(t["id"], "u-b", "BRIEF-x", "autonomous") is None
    assert store.delete(t["id"], "u-b") is False
    assert store.get(t["id"], "u-a")["title"] == "mine"

def test_migrate_adds_the_run_phase_columns_in_place(tmp_path):
    """A tickets table from before the run-phase fields is upgraded, not replaced."""
    import sqlite3, time
    p = tmp_path / "old.db"
    db = sqlite3.connect(p)
    db.execute("""CREATE TABLE tickets(id TEXT PRIMARY KEY, user_id TEXT NOT NULL,
                  title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'backlog',
                  created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
    db.execute("INSERT INTO tickets VALUES('TCK-old','u-a','kept','body','review',?,?)",
               (time.time(), time.time()))
    db.commit(); db.close()

    s = TicketStore(p)
    t = s.get("TCK-old", "u-a")
    assert t["title"] == "kept" and t["status"] == "review"
    assert t["pdf_context_ids"] == [] and t["runs"] == []          # NULL reads as empty
    assert s.attach_run("TCK-old", "u-a", "BRIEF-1", "autonomous")["runs"][0]["mode"] == "autonomous"


def test_static_assets_are_served():
    r = TestClient(server.app).get("/static/app.css")
    assert r.status_code == 200 and "text/css" in r.headers["content-type"]
