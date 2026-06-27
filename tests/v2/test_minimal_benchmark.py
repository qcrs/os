from __future__ import annotations

import json
from pathlib import Path

from v2.benchmark import (
    MinimalBenchmarkSample,
    load_sample_family,
    run_minimal_benchmark,
    run_minimal_benchmark_family,
)


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


def test_minimal_benchmark_sample_family_loads_multiple_samples() -> None:
    family = load_sample_family(Path("v2/benchmark/samples/minimal_family"))
    assert len(family) == 2
    assert family[0].task_id == "benchmark-sample-1"
    assert family[1].task_id == "benchmark-sample-2"


def test_minimal_benchmark_family_runs_and_persists_report(tmp_path: Path) -> None:
    family_samples = load_sample_family(Path("v2/benchmark/samples/minimal_family"))
    family_report = run_minimal_benchmark_family(
        samples=family_samples,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="family-suite-test",
    )
    assert len(family_report.cases) == 2
    assert family_report.eligible_for_headline is True
    assert family_report.aggregated_metrics["case_count"] == 2.0
    assert family_report.aggregated_metrics["quality_floor_pass_count"] == 2.0
    assert family_report.cases[0].output_artifact_hash != family_report.cases[1].output_artifact_hash

    report_path = Path(family_report.report_path)
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["suite_id"] == "family-suite-test"
    assert payload["aggregated_metrics"]["case_count"] == 2.0
    assert len(payload["cases"]) == 2
