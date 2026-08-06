"""Bootstrap a Field Guide from any Python repo — the flagship capability.

Deterministic and offline: walks the repo, parses each module's top-level
symbols, detects the test strategy, infers house conventions, builds a glossary,
and pulls curated traps from a NOTES.md / acceptance criteria. An optional LLM
pass (enrich.py) adds per-module summaries. The point: point Fieldcraft at an
unfamiliar codebase and get a usable brain in seconds, not the hours a human
would spend reading it.
"""
from __future__ import annotations

import ast
import subprocess
from collections import Counter
from pathlib import Path

from .models import FieldGuide, Module

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules", "out", "dist", "build", ".mypy_cache", "fixtures"}


def bootstrap(repo: str | Path, max_files: int = 400) -> FieldGuide:
    root = Path(repo).resolve()
    py = [p for p in root.rglob("*.py")
          if not any(part in SKIP_DIRS or part.startswith(".") for part in p.parts)][:max_files]

    modules, sources = [], []
    ann_fns = tot_fns = doc_fns = future_ann = dataclass_ct = 0
    names: Counter = Counter()

    for p in py:
        rel = str(p.relative_to(root))
        sources.append(rel)
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(node.name); tot_fns += 1
                if node.returns or any(a.annotation for a in node.args.args):
                    ann_fns += 1
                if ast.get_docstring(node):
                    doc_fns += 1
                names[node.name] += 1
            elif isinstance(node, ast.ClassDef):
                symbols.append(node.name); names[node.name] += 1
                if any(isinstance(d, ast.Name) and d.id == "dataclass" for d in node.decorator_list):
                    dataclass_ct += 1
        src = p.read_text(encoding="utf-8", errors="ignore")
        if "from __future__ import annotations" in src:
            future_ann += 1
        kind = "test" if (rel.startswith("test") or "/test" in rel or Path(rel).name.startswith("test_")) else \
               ("package" if Path(rel).name == "__init__.py" else "module")
        modules.append(Module(path=rel, kind=kind, symbols=symbols))

    guide = FieldGuide(
        repo=root.name,
        commit=_commit(root),
        modules=sorted(modules, key=lambda m: m.path),
        conventions=_conventions(tot_fns, ann_fns, doc_fns, future_ann, dataclass_ct),
        glossary=_glossary(names),
        traps=_traps(root),
        test_strategy=_test_strategy(modules, py),
        sources=sources,
    )
    return guide


def _commit(root: Path) -> str:
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unpinned"
    except Exception:
        return "unpinned"


def _conventions(tot, ann, doc, future_ann, dataclasses) -> list[str]:
    c = []
    if tot:
        c.append(f"Type hints on ~{round(100*ann/tot)}% of top-level functions ({ann}/{tot})")
        c.append(f"Docstrings on ~{round(100*doc/tot)}% of top-level functions")
    if future_ann:
        c.append(f"`from __future__ import annotations` used in {future_ann} file(s)")
    if dataclasses:
        c.append(f"Dataclasses used for models ({dataclasses} found)")
    return c


def _glossary(names: Counter) -> dict[str, str]:
    # surface the most recurrent/central symbols as domain vocabulary
    common = [n for n, ct in names.most_common(12) if ct >= 1 and not n.startswith("_")]
    return {n: "core symbol" for n in common[:10]}


def _traps(root: Path) -> list[str]:
    traps: list[str] = []
    # curated notes
    for cand in ("NOTES.md", "FIELD_GUIDE_SEED.md", ".fieldguide/notes.md", ".fieldguide/learned.md"):
        f = root / cand
        if f.exists():
            grab = False
            for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
                low = line.lower()
                if low.startswith("##"):
                    grab = ("trap" in low or "note" in low or "gotcha" in low)
                elif grab and line.strip().startswith(("-", "*")):
                    traps.append(line.strip().lstrip("-* ").strip())
    # notable constraints from acceptance criteria
    for f in root.rglob("*acceptance*.md"):
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            s = line.strip()
            if s.startswith(("-", "*")) and any(w in s.lower() for w in ("must", "both", "format", "edge")):
                traps.append("AC: " + s.lstrip("-* ").strip())
    return traps[:12]


def _test_strategy(modules, py_files) -> str:
    tests = [m for m in modules if m.kind == "test"]
    uses_pytest = any("import pytest" in p.read_text(encoding="utf-8", errors="ignore")
                      or "def test_" in p.read_text(encoding="utf-8", errors="ignore")
                      for p in py_files if Path(p).name.startswith("test_"))
    if not tests:
        return "No test files detected."
    fw = "pytest" if uses_pytest else "unittest/other"
    return f"{len(tests)} test file(s), {fw}-style. Run tests before declaring a task done."
