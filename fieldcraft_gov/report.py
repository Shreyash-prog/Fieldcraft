"""Governance summary from a run's event log."""
from __future__ import annotations


def governance_summary(events: list[dict]) -> dict:
    pol = [e["payload"] for e in events if e["type"] == "policy"]
    reverted = [p for e in pol for p in e.get("reverted", [])]
    violations = [v for e in pol for v in e.get("violations", [])]
    return {
        "policy_checks": len(pol),
        "files_reverted": sorted(set(reverted)),
        "violations": violations,
        "blocked": any(e.get("decision") == "blocked" for e in pol),
    }
