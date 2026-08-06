"""Live adapter — output parsing and preflight (no key needed)."""
import pytest
from pathlib import Path
from fieldcraft_loop.live_adapter import ClaudeCodeLoopAdapter, LiveAgentError


def test_parse_success():
    r = ClaudeCodeLoopAdapter._parse('{"total_cost_usd":0.12,"num_turns":3}', "", 0)
    assert r["error"] is None and r["cost"] == 0.12 and r["num_turns"] == 3

def test_parse_is_error():
    r = ClaudeCodeLoopAdapter._parse('{"is_error":true,"error":"boom"}', "", 0)
    assert r["error"] == "boom" and r["retryable"] is True

def test_parse_malformed():
    r = ClaudeCodeLoopAdapter._parse("<<garbage>>", "stderr msg", 1)
    assert r["error"] and r["cost"] == 0.0

def test_preflight_missing_cli(tmp_path):
    a = ClaudeCodeLoopAdapter()
    a.cli = "/nonexistent/claude-xyz"
    with pytest.raises(LiveAgentError):
        a.turn(Path("sample_task"), tmp_path, "", 1)
