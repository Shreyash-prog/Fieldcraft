#!/usr/bin/env python3
"""Generate a labeled fixture set for judge calibration.

Composes candidate redact_pii implementations across a behavior grid, then
labels each by EXECUTING the acceptance-criteria probes (executable ground
truth) — so labels are correct by construction, not by hand-guessing.
Output: sample_task/fixtures/*.py + labels.json
"""
from __future__ import annotations
import json, shutil, sys, tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from fieldcraft_aar.effectiveness import BehavioralGrader

FIX = ROOT / "sample_task" / "fixtures"
CRITERIA = json.loads((ROOT / "sample_task" / "criteria.json").read_text())

EMAIL = {"A": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
         "B": r"\S+@\S+\.\S+", "none": None}
PHONE = {"correct": r"(?<!\w)(?:\+?\d{1,2}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\w)",
         "dashed": r"\d{3}-\d{3}-\d{4}", "none": None}


def build(email, phone, mangle, break_idem):
    L = ["import re"]
    L.append(f"_E = re.compile(r'''{email}''')" if email else "_E = None")
    L.append(f"_P = re.compile(r'''{phone}''')" if phone else "_P = None")
    L += ["", "def redact_pii(text):", "    if not text:", "        return text",
          "    out = text", "    if _E:", "        out = _E.sub('[EMAIL]', out)",
          "    if _P:", "        out = _P.sub('[PHONE]', out)"]
    if mangle:
        L += ["    out = out.upper()"]
    if break_idem:
        L += ["    out = '[r] ' + out"]
    L += ["    return out", ""]
    return "\n".join(L)


def label(src: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        wd = Path(td); (wd / "redact.py").write_text(src)
        return {v.id: v.verdict for v in BehavioralGrader().grade(wd, CRITERIA, "")}


def main():
    if FIX.exists():
        shutil.rmtree(FIX)
    FIX.mkdir(parents=True)
    fixtures, idx = [], 0
    for ek, ev in EMAIL.items():
        for pk, pv in PHONE.items():
            for mangle in (0, 1):
                for bi in (0, 1):
                    idx += 1
                    src = build(ev, pv, mangle, bi)
                    name = f"gen_{idx:03d}.py"
                    (FIX / name).write_text(src)
                    fixtures.append({"file": name, "labels": label(src),
                                     "meta": {"email": ek, "phone": pk, "mangle": mangle, "break_idem": bi}})
    for name, src in {"stub.py": "def redact_pii(text):\n    return text\n",
                      "empty_out.py": "def redact_pii(text):\n    return ''\n"}.items():
        (FIX / name).write_text(src)
        fixtures.append({"file": name, "labels": label(src), "meta": {"special": name}})

    (FIX / "labels.json").write_text(json.dumps({"fixtures": fixtures}, indent=2))
    combos = Counter(tuple(sorted(f["labels"].items())) for f in fixtures)
    met = Counter()
    for f in fixtures:
        for cid, v in f["labels"].items():
            met[cid] += (v == "met")
    print(f"generated {len(fixtures)} fixtures, {len(fixtures)*len(CRITERIA)} binary judgments")
    print(f"distinct label combinations: {len(combos)} of 16 possible")
    print(f"met counts per criterion: {dict(met)} (of {len(fixtures)})")


if __name__ == "__main__":
    main()
