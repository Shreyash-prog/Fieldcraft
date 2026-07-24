"""Compile a Field Guide into the two forms the loop consumes:

1. an always-loaded, token-bounded **context string** injected into the agent
   prompt (high-signal: test strategy, conventions, traps, top of the module map);
2. a lightweight **retrieval index** the agent can query on demand
   (keyword/inverted index over guide sections + module symbols).
"""
from __future__ import annotations

import re
from collections import defaultdict

from .models import FieldGuide


def compile_context(guide: FieldGuide, budget_chars: int = 1400) -> str:
    """High-signal context, bounded so it never blows the prompt."""
    parts = [f"Field Guide for `{guide.repo}` (commit {guide.commit})."]
    if guide.test_strategy:
        parts.append("Test strategy: " + guide.test_strategy)
    if guide.traps:
        parts.append("Traps to respect:\n" + "\n".join(f"- {t}" for t in guide.traps))
    if guide.conventions:
        parts.append("Conventions:\n" + "\n".join(f"- {c}" for c in guide.conventions[:4]))
    key_mods = [m for m in guide.modules if m.kind != "test" and m.symbols][:8]
    if key_mods:
        parts.append("Key modules:\n" + "\n".join(
            f"- {m.path}: {', '.join(m.symbols[:6])}" for m in key_mods))
    text = "\n\n".join(parts)
    return text if len(text) <= budget_chars else text[:budget_chars].rsplit("\n", 1)[0] + "\n…"


class RetrievalIndex:
    """Tiny inverted index over guide sections + module symbols."""

    def __init__(self, guide: FieldGuide):
        self.docs: list[tuple[str, str]] = []      # (label, text)
        for m in guide.modules:
            self.docs.append((m.path, m.path + " " + " ".join(m.symbols) + " " + m.summary))
        for t in guide.traps:
            self.docs.append(("trap", t))
        for c in guide.conventions:
            self.docs.append(("convention", c))
        for k, v in guide.glossary.items():
            self.docs.append((f"glossary:{k}", f"{k} {v}"))
        self.index: dict[str, set[int]] = defaultdict(set)
        for i, (_, text) in enumerate(self.docs):
            for tok in self._tok(text):
                self.index[tok].add(i)

    @staticmethod
    def _tok(s: str) -> list[str]:
        s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)   # BehavioralGrader -> Behavioral Grader
        s = s.replace("_", " ")                          # run_pytest -> run pytest
        return [w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 1]

    def search(self, query: str, k: int = 5) -> list[tuple[str, str]]:
        hits: dict[int, int] = defaultdict(int)
        for tok in self._tok(query):
            for i in self.index.get(tok, ()):
                hits[i] += 1
        ranked = sorted(hits.items(), key=lambda kv: -kv[1])[:k]
        return [self.docs[i] for i, _ in ranked]
