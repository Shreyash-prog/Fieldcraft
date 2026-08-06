"""Field Guide — bootstrap, trap extraction, compiled context, retrieval."""
from fieldcraft_guide.bootstrap import bootstrap
from fieldcraft_guide.compile import compile_context, RetrievalIndex
from tests.conftest import TASK, REPO_TASK


def test_bootstrap_extracts_traps_and_modules():
    g = bootstrap(TASK)
    assert any("phone" in t.lower() for t in g.traps)
    assert g.modules and any(m.symbols for m in g.modules)

def test_compiled_context_includes_trap():
    ctx = compile_context(bootstrap(TASK))
    assert "phone" in ctx.lower()

def test_retrieval_finds_trap():
    g = bootstrap(TASK)
    hits = RetrievalIndex(g).search("phone number formats")
    assert any("phone" in text.lower() for _, text in hits)

def test_bootstrap_multifile_repo():
    g = bootstrap(REPO_TASK)
    assert any("casing" in t.lower() for t in g.traps)
