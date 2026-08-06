"""Packaging regression guard.

A deployment once shipped an image built from a per-package `COPY` list, so
`fieldcraft_bench`/`measure`/`guide`/`gov` were missing: the Reports tab raised
ModuleNotFoundError and a run's background worker died silently on the same
import. These tests pin both halves of that — every package imports, and the
build context ships every package.
"""
import fnmatch
import importlib
import pkgutil

import pytest

from tests.conftest import ROOT

PACKAGES = sorted(p.name for p in ROOT.iterdir()
                  if p.is_dir() and p.name.startswith("fieldcraft_") and (p / "__init__.py").exists())
# Data the loop reads at runtime; missing from the image = a run that cannot start.
DATA_DIRS = ["sample_task", "tasks", "repo_tasks", "tools", "fieldcraft_web/static"]


def test_the_package_list_is_not_empty():
    assert len(PACKAGES) >= 8, PACKAGES


@pytest.mark.parametrize("name", PACKAGES)
def test_package_imports(name):
    assert importlib.import_module(name)


@pytest.mark.parametrize("name", PACKAGES)
def test_every_submodule_imports(name):
    """`import fieldcraft_bench` succeeding says nothing about `.run` — the
    Reports tab imports submodules lazily, which is how this broke in production."""
    pkg = importlib.import_module(name)
    for mod in pkgutil.walk_packages(pkg.__path__, prefix=f"{name}."):
        if mod.name.endswith("__main__"):
            continue                       # these run a demo on import, by design
        importlib.import_module(mod.name)


def test_lazily_imported_report_modules_resolve():
    """The exact imports the Reports endpoints make, up front."""
    from fieldcraft_bench.run import benchmark                # noqa: F401
    from fieldcraft_measure.run import measure                # noqa: F401
    from fieldcraft_guide.flywheel import demo                # noqa: F401
    from fieldcraft_gov.report import governance_summary      # noqa: F401
    from fieldcraft_gov.credentials import CredentialBroker   # noqa: F401
    from fieldcraft_graph.executor import GraphExecutor       # noqa: F401


# --- the build context actually ships all of it ------------------------------

def _dockerignore_patterns() -> list[str]:
    return [ln.strip() for ln in (ROOT / ".dockerignore").read_text().splitlines()
            if ln.strip() and not ln.startswith("#")]


def _ignored(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pat.rstrip("/")) or
               fnmatch.fnmatch(path.split("/")[0], pat.rstrip("/"))
               for pat in _dockerignore_patterns())


def test_dockerfile_copies_the_whole_project():
    body = (ROOT / "Dockerfile").read_text()
    copies = [ln.split()[1:] for ln in body.splitlines() if ln.startswith("COPY ")]
    assert [".", "."] in copies, (
        "the image must COPY the whole project; a per-package list ships an app "
        f"that only fails at runtime. Found: {copies}")


@pytest.mark.parametrize("name", PACKAGES + DATA_DIRS)
def test_dockerignore_does_not_exclude_shipped_code(name):
    assert not _ignored(name), f".dockerignore excludes {name} from the image"


def test_task_assets_are_not_excluded():
    """Adapters read acceptance_criteria.md / NOTES.md at runtime, so a blanket
    *.md exclusion would ship tasks the loop cannot describe."""
    for asset in ("repo_tasks/textkit/acceptance_criteria.md",
                  "repo_tasks/textkit/task.json",
                  "fieldcraft_web/static/index.html"):
        assert (ROOT / asset).exists(), asset
        assert not _ignored(asset), asset

def test_verification_ignores_an_ancestor_pytest_config(tmp_path):
    """A workdir under a tree with its own pytest.ini must still be graded on its
    own tests. `addopts = -q` there used to stack with ours into `-qq`, which drops
    the summary line run_pytest parses — the run then scored 0/0 forever."""
    import shutil
    from fieldcraft_aar.effectiveness import run_pytest

    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\naddopts = -q\n")
    wd = tmp_path / "data" / "work" / "BRIEF-x"
    wd.mkdir(parents=True)
    for f in ("redact.py", "test_redact.py"):
        shutil.copy2(ROOT / "sample_task" / f, wd / f)

    passed, total, _ = run_pytest(wd)
    assert total > 0 and passed > 0, "an ancestor pytest.ini hijacked verification"


def test_repo_verification_ignores_an_ancestor_pytest_config(tmp_path):
    """Same hazard on the repo-task path, whose command comes from task.json."""
    import sys
    from fieldcraft_loop.repo_task import RepoTask, copy_repo, run_tests
    from tests.conftest import REPO_TASK

    (tmp_path / "pytest.ini").write_text("[pytest]\ntestpaths = tests\naddopts = -q\n")
    wd = tmp_path / "data" / "work" / "BRIEF-x"
    wd.parent.mkdir(parents=True)
    copy_repo(RepoTask.load(REPO_TASK), wd)
    passed, total, _ = run_tests(wd, [sys.executable, "-m", "pytest", "-q"])
    assert (passed, total) == (1, 8), "an ancestor pytest.ini hijacked verification"


def test_a_repos_own_pytest_config_is_left_alone(tmp_path):
    """The guard must not strip addopts a connected repo actually needs."""
    from fieldcraft_loop.repo_task import _ambient_config_guard

    wd = tmp_path / "w"
    wd.mkdir()
    assert _ambient_config_guard(wd, ["python", "-m", "pytest", "-q"]) == ["-o", "addopts="]
    (wd / "pytest.ini").write_text("[pytest]\n")
    assert _ambient_config_guard(wd, ["python", "-m", "pytest", "-q"]) == []
    assert _ambient_config_guard(tmp_path, ["make", "test"]) == []


def test_dockerignore_still_excludes_the_junk():
    for junk in ("__pycache__", "out", "app.db", ".git", ".pytest_cache", ".venv"):
        assert _ignored(junk), f".dockerignore should exclude {junk}"
