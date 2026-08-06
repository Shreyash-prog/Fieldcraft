from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .bootstrap import bootstrap
from .compile import compile_context, RetrievalIndex


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fieldcraft_guide")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="scan a repo into a Field Guide")
    b.add_argument("repo"); b.add_argument("--out", default=None)
    ctx = sub.add_parser("context", help="print the compiled agent context")
    ctx.add_argument("repo")
    q = sub.add_parser("search", help="query the Field Guide")
    q.add_argument("repo"); q.add_argument("query")
    fw = sub.add_parser("flywheel", help="learn a trap from a run, show the speedup")
    fw.add_argument("repo")
    a = ap.parse_args(argv)

    if a.cmd == "flywheel":
        from .flywheel import main as fw_main
        return fw_main([a.repo])

    g = bootstrap(a.repo)
    if a.cmd == "bootstrap":
        outdir = Path(a.out or a.repo)
        (outdir / "FIELD_GUIDE.md").write_text(g.to_markdown())
        (outdir / "field_guide.json").write_text(json.dumps(g.to_dict(), indent=2))
        print(f"bootstrapped {g.repo} @ {g.commit}: {len(g.modules)} modules, "
              f"{len(g.conventions)} conventions, {len(g.traps)} traps")
        print(f"wrote {outdir/'FIELD_GUIDE.md'} and field_guide.json")
    elif a.cmd == "context":
        print(compile_context(g))
    elif a.cmd == "search":
        for label, text in RetrievalIndex(g).search(a.query):
            print(f"  [{label}] {text[:92]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
