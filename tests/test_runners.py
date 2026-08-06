"""Smoke-test the end-to-end runners in-process (exercises harness, calibration,
benchmark, measurement, guide impact, and the report renderers)."""
from fieldcraft_aar import cli as aar_cli, calibration
from fieldcraft_bench import run as bench
from fieldcraft_measure import run as measure, report as mreport


def test_aar_harness(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert aar_cli.main(["--adapter", "mock"]) == 0

def test_calibration_behavioral(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert calibration.main([]) == 0

def test_benchmark(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = bench.benchmark()
    assert data["agg"]["all_converged"] is True
    assert bench._dashboard(data)                       # renders HTML

def test_measurement(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = measure.measure()
    assert result["effect"]["n"] == 4
    assert mreport.render(result)                        # renders HTML


def test_guide_impact(tmp_path, monkeypatch):
    from fieldcraft_guide import impact
    monkeypatch.chdir(tmp_path)
    assert impact.main() == 0
