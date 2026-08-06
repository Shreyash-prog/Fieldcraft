"""Multi-file repo tasks — copy, verify, diff, protected-path integrity, loop."""
from pathlib import Path
from fieldcraft_loop.repo_task import (RepoTask, copy_repo, apply_patch, run_tests,
                                       snapshot, multi_file_diff, is_protected,
                                       revert_protected, compute_repo_effectiveness)
from fieldcraft_loop.engine import Engine
from tests.conftest import REPO_TASK


def test_stub_stage_solution(tmp_path):
    t = RepoTask.load(REPO_TASK)
    wd = tmp_path / "w"; copy_repo(t, wd)
    assert run_tests(wd, t.test_command)[0] == 1                     # stub: 1/8
    apply_patch(Path(t.dir) / ".stages/stage1", wd)
    assert run_tests(wd, t.test_command)[0] == 4                     # stage1: 4/8
    apply_patch(Path(t.dir) / ".solution", wd)
    p, tot, fail = run_tests(wd, t.test_command)
    assert p == 8 and tot == 8 and fail == []                       # solution: 8/8

def test_is_protected():
    assert is_protected("tests/test_x.py", ["tests/"])
    assert not is_protected("textkit/slug.py", ["tests/"])

def test_revert_protected(tmp_path):
    t = RepoTask.load(REPO_TASK)
    wd = tmp_path / "w"; copy_repo(t, wd)
    before = snapshot(wd)
    (wd / "tests" / "test_slug.py").write_text("def test_ok():\n assert True\n")
    reverted = revert_protected(before, wd, t.protected_paths)
    assert "tests/test_slug.py" in reverted
    assert (wd / "tests" / "test_slug.py").read_text() == before["tests/test_slug.py"]

def test_multi_file_diff(tmp_path):
    before = {"a.py": "x\n"}; after = {"a.py": "y\n", "b.py": "new\n"}
    d = multi_file_diff(before, after)
    assert "a/a.py" in d and "b/b.py" in d

def test_repo_effectiveness(tmp_path):
    t = RepoTask.load(REPO_TASK)
    wd = tmp_path / "w"; copy_repo(t, wd)
    eff = compute_repo_effectiveness(wd, t.test_command)
    assert eff.tests_total == 8 and eff.tests_passed == 1 and not eff.all_tests_pass

def test_repo_loop_converges(datadir):
    e = Engine(datadir)
    b = e.create({"adapter": "mock", "review": "auto"}, REPO_TASK)
    e.advance(b)
    a = e.aar(e.get(b))
    assert a["final_state"] == "done" and a["iterations"] == 2
