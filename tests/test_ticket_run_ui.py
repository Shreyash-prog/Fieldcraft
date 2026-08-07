"""The drawer's single-run surface (B2).

Two kinds of check here, and they are different in strength:

* **Structural checks over `index.html`.** The load-bearing claim of B2 is that
  the SSE-reading and review-submitting logic was *extracted*, not copied — so
  these assert there is exactly one of each in the file and that both surfaces go
  through it. A grep is a weak test of behaviour but a strong test of
  duplication, which is precisely the thing that would rot here.
* **Backend checks** of the endpoint the drawer calls, reusing B1's machinery.

The rendered result is verified in the browser, not here; these tests cannot
execute the DOM.
"""
import re

import pytest
from fastapi.testclient import TestClient

from fieldcraft_loop.ticket_store import TicketStore
from fieldcraft_web import server
from fieldcraft_web.auth import COOKIE, Auth
from fieldcraft_web.ledger import Ledger
from tests.conftest import ROOT

INDEX = (ROOT / "fieldcraft_web" / "static" / "index.html").read_text()
CSS = (ROOT / "fieldcraft_web" / "static" / "app.css").read_text()
CODES = "alpha-code,beta-code"


@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "tickets", TicketStore(tmp_path / "tickets.db"))
    monkeypatch.setattr(server, "CONNECTED", {})


@pytest.fixture
def secured(monkeypatch):
    monkeypatch.setattr(server, "auth", Auth(codes=CODES, secret="test-signing-key",
                                             salt=b"fixed-test-salt"))


def session(code):
    c = TestClient(server.app)
    assert c.post("/api/session", json={"code": code}).status_code == 200
    return c


def make(client):
    return client.post("/api/tickets", json={"title": "Work this"}).json()


# =============================================================================
# the runner was extracted, not copied
# =============================================================================

def test_there_is_exactly_one_run_stream_reader():
    """The whole point of B2's refactor. A second EventSource on the brief stream
    means someone forked the run loop instead of reusing the runner."""
    assert INDEX.count("new EventSource(`/api/briefs/") == 1


def test_there_is_exactly_one_review_submitter():
    assert len(re.findall(r"/api/briefs/\$\{[A-Za-z]+\}/review", INDEX)) == 1


def test_both_surfaces_use_the_shared_runner():
    assert "function createRunner(host)" in INDEX
    # the Run-a-task page
    assert "RUNA = RUNA || createRunner(el('runHost'))" in INDEX
    # the ticket drawer
    assert "DRAWER_RUN=createRunner(el('rnHost'))" in INDEX
    assert INDEX.count("createRunner(") == 3          # 1 definition + 2 uses


def test_the_module_global_brief_id_is_gone():
    """Run state used to be a single module-global BID, which is why only one run
    could be live at a time."""
    assert "let BID=null" not in INDEX
    assert not re.search(r"\bBID\s*=\s*d\.brief_id", INDEX)


def test_the_old_single_run_dom_ids_are_gone():
    """The Run-a-task page's hand-written status/review/AAR cards are now produced
    by the runner; leftover ids would mean two copies of the same UI."""
    for dead in ('id="statusCard"', 'id="reviewCard"', 'id="aarCard"',
                 'id="revBody"', 'id="aarMetrics"', 'id="timeline"'):
        assert dead not in INDEX, f"{dead} should have been replaced by the runner"
    assert 'id="runHost"' in INDEX


def test_the_runner_renders_timeline_review_and_aar():
    for cls in (".rn-tl", ".rn-review", ".rn-verdict", ".rn-acts", ".rn-aar", ".rn-pill"):
        assert cls in INDEX, f"the runner should own {cls}"
    assert ".rn-review{border:2px solid var(--amber)}" in CSS.replace("\n", "")


def test_the_review_actions_are_all_three_decisions():
    for kind in ("approve", "changes", "reject"):
        assert f'data-kind="{kind}"' in INDEX


# =============================================================================
# the drawer's run section
# =============================================================================

def test_the_drawer_has_a_run_section_calling_the_b1_endpoint():
    assert "/api/tickets/${tid}/runs" in INDEX
    assert 'id="rnGo"' in INDEX and "function runTicketOnce(tid)" in INDEX


def test_review_mode_is_a_visible_choice_not_a_hidden_knob():
    """Thesis-central: human-in-the-loop vs autonomous must be prominent."""
    assert 'id="rnReview"' in INDEX
    assert 'data-r="human"' in INDEX and 'data-r="auto"' in INDEX
    assert "Who reviews the work" in INDEX
    # ...and each option explains itself
    assert "RN_NOTES" in INDEX and "pauses after each turn" in INDEX


def test_the_engine_knobs_are_collapsed_by_default():
    """Advanced must be a <details> with no `open`, holding adapter/grader/maxit."""
    m = re.search(r'<details class="pol rn-adv"([^>]*)>', INDEX)
    assert m, "the Advanced block should be a collapsible <details>"
    assert "open" not in m.group(1), "Advanced must start collapsed"
    for knob in ('id="rnAdapter"', 'id="rnGrader"', 'id="rnMaxit"'):
        assert knob in INDEX


def test_the_run_section_reflects_the_connected_repo():
    assert "repo_task_handle" in INDEX and 'id="rnTarget"' in INDEX
    assert "No repository is connected" in INDEX


def test_a_429_is_surfaced_as_a_daily_limit_message():
    """B1.5's deferred decision: the single-run path refuses synchronously, so the
    cap block must be legible rather than a silent no-op."""
    assert "r.status===429" in INDEX
    assert "Daily limit reached" in INDEX


def test_the_comparison_section_still_exists_and_is_distinguished():
    assert 'id="cmpBody"' in INDEX
    assert "Three-mode comparison" in INDEX
    assert "Not a single run" in INDEX, "the two run options should be told apart"


def test_the_drawer_runner_is_stopped_when_the_drawer_closes():
    """Otherwise an open SSE connection leaks per ticket opened."""
    close = INDEX[INDEX.index("function closeDrawer()"):][:400]
    assert "DRAWER_RUN.stop()" in close


def test_the_drawer_runner_is_rebuilt_per_ticket():
    """Per-ticket state: opening a second ticket must not inherit the first's
    stream, which a module-global runner would do."""
    assert "wireTicketRun(t)" in INDEX
    wire = INDEX[INDEX.index("function wireTicketRun(t)"):][:400]
    assert "DRAWER_RUN=createRunner" in wire


# =============================================================================
# the endpoint behind the button (reuses B1)
# =============================================================================

def test_the_drawer_body_shape_is_accepted_by_the_endpoint():
    """Exactly what runTicketOnce posts."""
    c = TestClient(server.app)
    t = make(c)
    r = c.post(f"/api/tickets/{t['id']}/runs",
               json={"review": "auto", "adapter": "mock",
                     "grader": "behavioral", "max_iterations": 5})
    assert r.status_code == 200, r.text
    assert r.json()["brief_id"].startswith("BRIEF-")


def test_a_human_review_run_from_the_drawer_pauses_and_streams():
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs",
                 json={"review": "human", "adapter": "mock",
                       "grader": "behavioral", "max_iterations": 5}).json()["brief_id"]
    import time
    for _ in range(400):
        if server.engine.get(bid)["status"] == "awaiting_review":
            break
        time.sleep(0.15)
    assert server.engine.get(bid)["status"] == "awaiting_review"

    with c.stream("GET", f"/api/briefs/{bid}/stream") as s:
        body = "".join(s.iter_text())
    assert "awaiting_review" in body and "event: state" in body

    assert c.post(f"/api/briefs/{bid}/review", json={"kind": "approve"}).status_code == 200
    assert server.engine.get(bid)["status"] == "done"


def test_two_tickets_run_independently():
    """Per-ticket state, proven on the backend: two tickets each get their own
    run and neither is attached to the other."""
    c = TestClient(server.app)
    t1, t2 = make(c), make(c)
    b1 = c.post(f"/api/tickets/{t1['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    b2 = c.post(f"/api/tickets/{t2['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    assert b1 != b2
    assert [r["brief_id"] for r in c.get(f"/api/tickets/{t1['id']}/runs").json()["runs"]] == [b1]
    assert [r["brief_id"] for r in c.get(f"/api/tickets/{t2['id']}/runs").json()["runs"]] == [b2]


def test_the_cap_refusal_the_drawer_renders_is_a_real_429(tmp_path, monkeypatch):
    """The message the UI shows is only honest if the endpoint really 429s."""
    monkeypatch.setattr(server, "ledger",
                        Ledger(tmp_path / "cap.db", global_cap=100.0, user_cap=1.0,
                               rate_per_hour=1000))
    monkeypatch.setattr(server.settings, "allow_live", True)
    c = TestClient(server.app)
    t = make(c)
    burn = server.ledger.reserve("legacy", "1.2.3.4", 1.0, enforce_cost=True)
    server.ledger.settle(burn.id, 1.0)

    r = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto", "adapter": "claude"})
    assert r.status_code == 429
    assert r.json()["detail"]


def test_tenancy_still_holds_on_the_drawer_path(secured):
    a, b = session("alpha-code"), session("beta-code")
    t = make(a)
    assert b.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).status_code == 404
