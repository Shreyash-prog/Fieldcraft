"""Demo: a run whose agent tries to exfiltrate a secret is caught by policy.

    python -m fieldcraft_gov
"""
import sys, tempfile
from pathlib import Path
from fieldcraft_loop.engine import Engine
from fieldcraft_loop.repo_task import apply_patch, snapshot, multi_file_diff
from fieldcraft_aar.models import RunTrace, Turn
from fieldcraft_gov.report import governance_summary
from fieldcraft_gov.credentials import CredentialBroker

ROOT = Path(__file__).resolve().parent.parent


class _Violator:
    def turn(self, task_dir, workdir, feedback, turn_index):
        before = snapshot(workdir)
        apply_patch(Path(task_dir) / ".solution", workdir)
        (workdir / "config.py").write_text('API_KEY = "AKIA1234567890ABCDEF"\n')
        return RunTrace(condition="t1", adapter="violator", spec_completeness=0.9,
                        turns=[Turn(cost_usd=0.09, tool_calls=3, event="progress", note="")],
                        wall_clock_s=1.0, diff=multi_file_diff(before, snapshot(workdir)))


def main() -> int:
    print("=== governance demo ===")
    e = Engine(tempfile.mkdtemp())
    e._adapter = lambda cfg: _Violator()
    b = e.create({"adapter": "mock", "review": "auto",
                  "policy": {"editable_paths": ["textkit/**", "config.py"],
                             "protected_paths": ["tests/"]}},
                 str(ROOT / "repo_tasks" / "textkit"))
    e.advance(b)
    gov = governance_summary(e.get_events(b))
    print(f"  run: {e.aar(e.get(b))['final_state']}  (converged on the legit fix)")
    print(f"  policy reverted: {gov['files_reverted']}")
    print(f"  violations: {[v['kind'] + ':' + v['ref'] for v in gov['violations']]}")

    print("\n=== scoped credentials ===")
    br = CredentialBroker()
    g = br.issue("BRIEF-x", ["repo:read", "tests:run"], ttl_s=300)
    print(f"  grant {g.grant_id} scope={sorted(g.capabilities)}")
    print(f"  tests:run allowed? {br.check(g.grant_id, 'tests:run')}")
    print(f"  repo:write allowed? {br.check(g.grant_id, 'repo:write')}  (least privilege)")
    br.revoke(g.grant_id)
    print(f"  after revoke, tests:run allowed? {br.check(g.grant_id, 'tests:run')}")
    print(f"  audit entries: {len(br.audit)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
