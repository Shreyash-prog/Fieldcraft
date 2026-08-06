"""Deployment guards — rate limiter, cost tracker, concurrency."""
from fieldcraft_web.limits import RateLimiter, CostTracker, Concurrency


def test_rate_limiter_blocks_over_limit():
    rl = RateLimiter(per_hour=2)
    assert [rl.allow("ip") for _ in range(4)] == [True, True, False, False]
    assert rl.allow("other-ip") is True                 # per-key

def test_cost_tracker_accumulates():
    c = CostTracker()
    c.add(1.5); c.add(2.0)
    assert c.remaining(5.0) == 1.5

def test_concurrency_guard():
    c = Concurrency(2)
    assert c.acquire() and c.acquire()
    assert c.acquire() is False
    c.release()
    assert c.acquire() is True
