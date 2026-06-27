from __future__ import annotations

from pathlib import Path

from v2.benchmark import MinimalBenchmarkSample, run_minimal_benchmark


def test_minimal_benchmark_runs_formal_sample(tmp_path: Path) -> None:
    smoke, report = run_minimal_benchmark(
        sample=MinimalBenchmarkSample(
            task_id="sample-1",
            request_text=(
                '{"task_family":"financial_report_analysis","intent_op":"compare_metric",'
                '"required_outputs":["summary_text"],"arguments":{"ticker":"ACME","quarter":"2026Q1"}}'
            ),
        ),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert smoke.compiler_status == "compiled"
    assert report.layer.value == "L0"
    assert report.quality_floor.quality_floor_pass is True
    assert report.eligible_for_headline is True

