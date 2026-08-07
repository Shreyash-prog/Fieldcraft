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


def test_the_drawer_uses_the_shared_runner():
    """B2 extracted this so two surfaces could share it. B4a retired the second
    surface (the Run-a-task page), so the drawer is now the only caller — but the
    runner stays a self-contained component, which is what made the removal safe."""
    assert "function createRunner(host)" in INDEX
    assert "DRAWER_RUN=createRunner(el('rnHost'))" in INDEX
    assert INDEX.count("createRunner(") == 2          # 1 definition + 1 use


def test_the_module_global_brief_id_is_gone():
    """Run state used to be a single module-global BID, which is why only one run
    could be live at a time."""
    assert "let BID=null" not in INDEX
    assert not re.search(r"\bBID\s*=\s*d\.brief_id", INDEX)


def test_the_old_single_run_dom_ids_are_gone():
    """The Run-a-task page's hand-written status/review/AAR cards are now produced
    by the runner; leftover ids would mean two copies of the same UI."""
    for dead in ('id="statusCard"', 'id="reviewCard"', 'id="aarCard"',
                 'id="revBody"', 'id="aarMetrics"', 'id="timeline"',
                 # and B4a took the host they were replaced by, with the page
                 'id="runHost"'):
        assert dead not in INDEX, f"{dead} should be gone"
    assert 'id="rnHost"' in INDEX, "the drawer's runner host must remain"


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


# =============================================================================
# B4a: the Run-a-task page is gone, and it stranded nothing
# =============================================================================

def test_the_run_a_task_page_is_gone():
    for dead in ('id="v-run"', 'id="n-run"', "nav('run')",
                 'id="startBtn"', 'id="createCard"', 'id="polProtected"'):
        assert dead not in INDEX, f"{dead} should have gone with the Run-a-task page"
    assert "'run'" not in INDEX.split("const VIEWS=")[1].split("]")[0]


def test_the_page_only_helpers_went_with_it():
    """buildPolicy moved to per-ticket governance; loadTasks/connectRepo were the
    old form's own helpers."""
    for dead in ("function buildPolicy", "async function loadTasks",
                 "async function connectRepo(", "function start()"):
        assert dead not in INDEX, f"{dead} is unused now and should be gone"


def test_the_shared_run_viewer_survived():
    """The drawer rides on it — removing the page must not take it along."""
    assert "function createRunner(host)" in INDEX
    assert "DRAWER_RUN=createRunner(el('rnHost'))" in INDEX
    assert INDEX.count("createRunner(") == 2, "one definition + the drawer's use"


def test_the_helpers_the_runner_depends_on_survived():
    for kept in ("function diffViewer", "function verdictBlock", "function splitDiff",
                 "function pickTab", "function evNode", "function renderTimeline"):
        assert kept in INDEX, f"{kept} is used by the run viewer and must stay"


def test_the_board_surfaces_are_all_still_wired():
    for kept in ("function runTicketOnce(tid)", "function wireTicketRun(t)",
                 "function saveGovernance(tid", "function loadComparison(tid)",
                 "function loadTryIt()", "function connectRepoToTicket(tid)",
                 "async function loadPdfs(tid)"):
        assert kept in INDEX, f"{kept} should be untouched by the removal"


def test_the_backend_run_endpoints_stayed():
    """Only the page went. The ticket runs ride on these."""
    routes = {r.path for r in server.app.routes}
    for path in ("/api/briefs", "/api/briefs/{bid}/stream",
                 "/api/briefs/{brief_id}/review", "/api/tickets/{tid}/runs"):
        assert path in routes, f"{path} must survive the page removal"


def test_a_plain_brief_can_still_be_created_without_the_page():
    """The shared machinery is still reachable and working."""
    c = TestClient(server.app)
    r = c.post("/api/briefs", json={"adapter": "mock", "review": "auto"})
    assert r.status_code == 200 and r.json()["brief_id"].startswith("BRIEF-")


def test_removing_a_governance_policy_is_two_step():
    """Loosening governance should not happen on one click, like deleting."""
    assert "function armGovClear(tid)" in INDEX
    assert "Remove policy…" in INDEX          # the arming button
    assert 'id="govClearYes"' in INDEX and 'id="govClearNo"' in INDEX
    assert "This ticket's runs become ungoverned" in INDEX


# =============================================================================
# B4a: the Overview speaks to a user, not an engineer
# =============================================================================

def _overview() -> str:
    i = INDEX.index('<section id="v-overview"')
    return INDEX[i:INDEX.index("</section>", i)]


def test_the_overview_drops_the_engine_jargon():
    ov = _overview().lower()
    for jargon in ("event-sourced", "llm-as-judge", "flywheel", "event store",
                   "adapter", "grader", "engine", "field guide"):
        assert jargon not in ov, f"the overview should not say {jargon!r}"


def test_the_overview_frames_the_two_halves():
    ov = _overview()
    assert "Measure" in ov and "Govern" in ov
    assert "ov-half measure" in ov and "ov-half govern" in ov


def test_the_overview_points_at_what_a_user_can_do():
    ov = _overview()
    assert "nav('tryit')" in ov and "nav('board')" in ov
    assert "nav('run')" not in ov, "it must not link to the page that was removed"


def test_the_overview_keeps_the_scripted_disclosure():
    assert "scripted and offline" in _overview()


def test_the_stream_reader_resets_events_on_reconnect():
    """The stream replays the full event log each time it is opened, and the
    runner reopens it after every review — appending would duplicate the whole
    timeline once per review turn."""
    i = INDEX.index("function openStream(){")
    block = INDEX[i:i + 500]
    assert "events=[];" in block, "openStream must reset the buffer before reconnecting"


def test_the_stream_endpoint_really_replays_from_the_start():
    """Why the reset is needed, asserted against the server rather than assumed."""
    c = TestClient(server.app)
    t = make(c)
    bid = c.post(f"/api/tickets/{t['id']}/runs", json={"review": "auto"}).json()["brief_id"]
    import time
    for _ in range(400):
        if server.engine.get(bid)["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.15)
    seen = []
    for _ in range(2):                       # connect twice, like a review does
        with c.stream("GET", f"/api/briefs/{bid}/stream") as s:
            seen.append("".join(s.iter_text()).count("event: event"))
    assert seen[0] == seen[1] > 0, "each connection replays the whole log"
