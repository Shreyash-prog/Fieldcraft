"""Durable spend + rate accounting (HARDENING P0-4).

The two properties that matter: the cap survives a restart, and parallel
reserves can never oversell it. Everything runs against a tmp SQLite file.
"""
import threading

import pytest
from fastapi.testclient import TestClient

from fieldcraft_web import server
from fieldcraft_web.ledger import Denied, Ledger, Reservation, utc_day

DAY = 86400


class Clock:
    """An injectable clock so day boundaries are testable without waiting."""

    def __init__(self, t: float = 1_770_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def ledger(tmp_path, name="ledger.db", **kw) -> Ledger:
    kw.setdefault("global_cap", 5.0)
    kw.setdefault("user_cap", 1.0)
    kw.setdefault("rate_per_hour", 10)
    return Ledger(tmp_path / name, **kw)


# --- the core P0-4 property: durability -------------------------------------

def test_spend_survives_a_restart(tmp_path):
    first = ledger(tmp_path, global_cap=1.0, user_cap=1.0)
    r = first.reserve("u-a", "1.1.1.1", 0.40)
    assert r.ok and first.settle(r.id, 0.40)
    assert first.remaining_global() == pytest.approx(0.60)
    del first                                        # the process dies here

    reopened = ledger(tmp_path, global_cap=1.0, user_cap=1.0)
    assert reopened.remaining_global() == pytest.approx(0.60)   # not reset to the cap
    assert reopened.spent_user("u-a") == pytest.approx(0.40)
    over = reopened.reserve("u-a", "1.1.1.1", 0.75)             # 0.40 + 0.75 > 1.00
    assert not over.ok and over.limit == "global_daily"

def test_an_unsettled_reservation_also_survives_a_restart(tmp_path):
    first = ledger(tmp_path, global_cap=1.0, user_cap=1.0)
    r = first.reserve("u-a", "1.1.1.1", 0.80)                   # never settled
    del first
    reopened = ledger(tmp_path, global_cap=1.0, user_cap=1.0)
    assert reopened.remaining_global() == pytest.approx(0.20)   # money still held
    assert reopened.settle(r.id, 0.10)                          # settles across the restart
    assert reopened.remaining_global() == pytest.approx(0.90)


# --- global vs per-user ------------------------------------------------------

def test_user_cap_does_not_block_another_user(tmp_path):
    lg = ledger(tmp_path, global_cap=5.0, user_cap=1.0)
    a = lg.reserve("u-a", "1.1.1.1", 1.0)
    assert a.ok
    denied = lg.reserve("u-a", "1.1.1.1", 0.10)                 # A is done for the day
    assert not denied.ok and denied.limit == "user_daily"
    assert lg.reserve("u-b", "2.2.2.2", 1.0).ok                 # B is unaffected

def test_global_cap_blocks_everyone(tmp_path):
    lg = ledger(tmp_path, global_cap=2.0, user_cap=1.0)
    assert lg.reserve("u-a", "1.1.1.1", 1.0).ok
    assert lg.reserve("u-b", "2.2.2.2", 1.0).ok                 # global now full
    for user, ip in (("u-a", "1.1.1.1"), ("u-b", "2.2.2.2"), ("u-c", "3.3.3.3")):
        d = lg.reserve(user, ip, 0.01)
        assert not d.ok and d.limit == "global_daily", user     # even a fresh user

def test_rate_limit_is_denied_by_name(tmp_path):
    lg = ledger(tmp_path, rate_per_hour=2)
    assert lg.reserve("u-a", "1.1.1.1", 0.01).ok
    assert lg.reserve("u-a", "1.1.1.1", 0.01).ok
    d = lg.reserve("u-a", "1.1.1.1", 0.01)
    assert not d.ok and d.limit == "rate"
    assert lg.reserve("u-a", "9.9.9.9", 0.01).ok                # a different IP is fine

def test_offline_runs_record_spend_without_enforcing_the_caps(tmp_path):
    lg = ledger(tmp_path, global_cap=0.10, user_cap=0.10)
    r = lg.reserve("u-a", "1.1.1.1", 5.0, enforce_cost=False)   # mock run, way over
    assert r.ok and lg.spent_global() == pytest.approx(5.0)     # still accounted
    assert not lg.reserve("u-a", "1.1.1.1", 0.01).ok            # and it blocks live spend


# --- reserve / settle / release ---------------------------------------------

def test_settle_reconciles_down(tmp_path):
    lg = ledger(tmp_path)
    r = lg.reserve("u-a", "1.1.1.1", 1.0)
    assert lg.spent_global() == pytest.approx(1.0)              # held while running
    lg.settle(r.id, 0.18)
    assert lg.spent_global() == pytest.approx(0.18)
    assert lg.spent_user("u-a") == pytest.approx(0.18)

def test_settle_reconciles_up(tmp_path):
    lg = ledger(tmp_path)
    r = lg.reserve("u-a", "1.1.1.1", 0.50)
    lg.settle(r.id, 0.90)                                       # overran the estimate
    assert lg.spent_global() == pytest.approx(0.90)

def test_settle_is_idempotent(tmp_path):
    lg = ledger(tmp_path)
    r = lg.reserve("u-a", "1.1.1.1", 1.0)
    assert lg.settle(r.id, 0.20) is True
    assert lg.settle(r.id, 5.00) is False                       # second call changes nothing
    assert lg.spent_global() == pytest.approx(0.20)
    assert lg.settle("RSV-nope", 1.0) is False

def test_release_frees_the_amount_and_the_rate_slot(tmp_path):
    lg = ledger(tmp_path, rate_per_hour=1)
    r = lg.reserve("u-a", "1.1.1.1", 1.0)
    assert lg.release(r.id) is True
    assert lg.spent_global() == 0.0 and lg.spent_user("u-a") == 0.0
    assert lg.reserve("u-a", "1.1.1.1", 1.0).ok                 # rate slot given back
    assert lg.release(r.id) is False                            # already released

def test_release_after_settle_does_nothing(tmp_path):
    lg = ledger(tmp_path)
    r = lg.reserve("u-a", "1.1.1.1", 1.0)
    lg.settle(r.id, 0.30)
    assert lg.release(r.id) is False
    assert lg.spent_global() == pytest.approx(0.30)

def test_denied_reserve_records_nothing(tmp_path):
    lg = ledger(tmp_path, global_cap=1.0, user_cap=1.0)
    lg.settle(lg.reserve("u-a", "1.1.1.1", 1.0).id, 1.0)
    assert isinstance(lg.reserve("u-b", "2.2.2.2", 0.5), Denied)
    assert lg.spent_global() == pytest.approx(1.0)              # the denial cost nothing
    assert lg.spent_user("u-b") == 0.0


# --- windows -----------------------------------------------------------------

def test_yesterdays_spend_does_not_count_today(tmp_path):
    clock = Clock()
    lg = ledger(tmp_path, global_cap=1.0, user_cap=1.0, clock=clock)
    lg.settle(lg.reserve("u-a", "1.1.1.1", 1.0).id, 1.0)
    assert not lg.reserve("u-a", "1.1.1.1", 0.5).ok             # today is full

    clock.advance(DAY)                                          # the UTC day rolls over
    assert utc_day(clock()) != utc_day(clock() - DAY)
    assert lg.remaining_global() == pytest.approx(1.0)          # fresh window
    assert lg.reserve("u-a", "1.1.1.1", 1.0).ok

def test_rate_window_is_a_rolling_hour(tmp_path):
    clock = Clock()
    lg = ledger(tmp_path, rate_per_hour=1, clock=clock)
    assert lg.reserve("u-a", "1.1.1.1", 0.01, enforce_cost=False).ok
    assert not lg.reserve("u-a", "1.1.1.1", 0.01, enforce_cost=False).ok
    clock.advance(3601)
    assert lg.reserve("u-a", "1.1.1.1", 0.01, enforce_cost=False).ok

def test_old_rows_are_pruned(tmp_path):
    clock = Clock()
    lg = ledger(tmp_path, clock=clock)
    lg.reserve("u-a", "1.1.1.1", 0.01)
    clock.advance(3 * DAY)
    lg.reserve("u-a", "1.1.1.1", 0.01)                          # prunes on write
    assert lg.db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == 3


# --- concurrency -------------------------------------------------------------

@pytest.mark.parametrize("threads,fits", [(20, 4)])
def test_parallel_reserves_never_oversell_the_cap(tmp_path, threads, fits):
    """N threads race for a cap that fits only M. Exactly M may win."""
    each = 0.25
    lg = ledger(tmp_path, global_cap=each * fits, user_cap=each * fits,
                rate_per_hour=0)                                # rate off: test the money
    results, start = [], threading.Barrier(threads)

    def go():
        start.wait()
        results.append(lg.reserve("u-shared", "1.1.1.1", each))

    ts = [threading.Thread(target=go) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]

    won = [r for r in results if r.ok]
    assert len(won) == fits
    assert all(isinstance(r, Reservation) for r in won)
    assert lg.spent_global() == pytest.approx(each * fits)      # never over the cap
    assert lg.remaining_global() == pytest.approx(0.0)
    assert {r.limit for r in results if not r.ok} == {"global_daily"}

def test_parallel_rate_limiting_never_oversells(tmp_path):
    allowed, threads = 3, 20
    lg = ledger(tmp_path, rate_per_hour=allowed)
    ok, start = [], threading.Barrier(threads)

    def go():
        start.wait()
        ok.append(lg.hit("1.1.1.1"))

    ts = [threading.Thread(target=go) for _ in range(threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(ok) == allowed and lg.rate_used("1.1.1.1") == allowed


# --- wired into the app ------------------------------------------------------

def test_a_mock_run_reserves_and_settles(monkeypatch, tmp_path):
    """Offline runs go through the same reserve/settle path, so it is exercised."""
    import time
    lg = ledger(tmp_path, global_cap=100.0, user_cap=100.0, rate_per_hour=100)
    monkeypatch.setattr(server, "ledger", lg)
    c = TestClient(server.app)

    bid = c.post("/api/briefs", json={"adapter": "mock", "review": "auto"}).json()["brief_id"]
    rid = server.engine.get(bid)["config"]["reservation_id"]
    assert rid.startswith("RSV-")
    for _ in range(80):
        if c.get(f"/api/briefs/{bid}").json()["status"] in ("done", "needs_human", "error"):
            break
        time.sleep(0.25)
    for _ in range(20):                                   # settle happens in _drive's thread
        if lg.spent_global() != pytest.approx(1.0):
            break
        time.sleep(0.1)
    settled = lg.spent_global()
    assert 0 < settled < 1.0                              # reconciled down from the budget
    assert settled == pytest.approx(server.engine.get(bid)["total_cost"])

def test_over_cap_create_is_429_naming_the_cap(monkeypatch, tmp_path):
    lg = ledger(tmp_path, global_cap=0.05, user_cap=0.05, rate_per_hour=100)
    monkeypatch.setattr(server, "ledger", lg)
    monkeypatch.setattr(server.settings, "allow_live", True)
    c = TestClient(server.app)
    r = c.post("/api/briefs", json={"adapter": "claude", "review": "auto", "budget": 1.0})
    assert r.status_code == 429 and "daily spend cap" in r.json()["detail"]

def test_healthz_reads_the_durable_ledger(monkeypatch, tmp_path):
    lg = ledger(tmp_path, global_cap=2.0)
    lg.settle(lg.reserve("u-a", "1.1.1.1", 0.5).id, 0.5)
    monkeypatch.setattr(server, "ledger", lg)
    assert TestClient(server.app).get("/healthz").json()["daily_cost_remaining"] == pytest.approx(1.5)

def test_a_503_gives_the_reservation_back(monkeypatch, tmp_path):
    lg = ledger(tmp_path, global_cap=100.0, user_cap=100.0, rate_per_hour=100)
    monkeypatch.setattr(server, "ledger", lg)
    monkeypatch.setattr(server, "conc", server.Concurrency(0))      # no slots
    r = TestClient(server.app).post("/api/briefs", json={"adapter": "mock"})
    assert r.status_code == 503
    assert lg.spent_global() == 0.0 and lg.rate_used("testclient") == 0
