from __future__ import annotations

from pathlib import Path

from v2.benchmark import MinimalBenchmarkSample, run_minimal_benchmark


def test_minimal_benchmark_sample_loads_from_fixture() -> None:
    sample = MinimalBenchmarkSample.from_path(
        Path("v2/benchmark/samples/minimal_financial_report_sample.json")
    )
    assert sample.task_id == "benchmark-sample-1"
    assert "financial_report_analysis" in sample.request_text


def test_minimal_benchmark_runs_formal_sample(tmp_path: Path) -> None:
    smoke, report = run_minimal_benchmark(
        sample=MinimalBenchmarkSample.from_path(
            Path("v2/benchmark/samples/minimal_financial_report_sample.json")
        ),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert smoke.compiler_status == "compiled"
    assert report.layer.value == "L0"
    assert report.quality_floor.quality_floor_pass is True
    assert report.eligible_for_headline is True
