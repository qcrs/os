from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.models import BenchmarkLayer, BenchmarkRunReport, QualityFloorResult
from v2.runtime.smoke import SmokeResult, run_smoke


@dataclass(frozen=True)
class MinimalBenchmarkSample:
    task_id: str
    request_text: str
    expected_artifact_type: str = "json"
    task_family: str = "financial_report_analysis"


def run_minimal_benchmark(
    *,
    sample: MinimalBenchmarkSample,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
) -> tuple[SmokeResult, BenchmarkRunReport]:
    smoke = run_smoke(
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
    )
    quality_floor = QualityFloorResult(
        quality_floor_pass=smoke.compiler_status == "compiled" and smoke.artifact_state == "verified",
        deterministic_checks_passed=smoke.artifact_state == "verified",
        fact_coverage_passed=smoke.replay_class in {"exact_replay", "validated_replay"},
        llm_judge_passed=None,
        quality_floor_fail_reason=""
        if smoke.artifact_state == "verified"
        else "artifact_not_verified",
    )
    report = BenchmarkRunReport(
        layer=BenchmarkLayer.L0,
        task_family=sample.task_family,
        quality_floor=quality_floor,
        metrics={
            "telemetry_event_count": float(smoke.telemetry_event_count),
            "registry_path_length": float(len(smoke.registry_path)),
        },
    )
    return smoke, report


def main() -> None:
    sample = MinimalBenchmarkSample(
        task_id="benchmark-sample-1",
        request_text=(
            '{"task_family":"financial_report_analysis","intent_op":"compare_metric",'
            '"required_outputs":["summary_text"],"arguments":{"ticker":"ACME","quarter":"2026Q1"}}'
        ),
    )
    smoke, report = run_minimal_benchmark(
        sample=sample,
        workspace_root=Path("/tmp/statebus-v2-benchmark/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-benchmark/runtime"),
        socket_path=Path("/tmp/statebus-v2-benchmark/control.sock"),
    )
    print(f"task_id={sample.task_id}")
    print(f"quality_floor_pass={report.quality_floor.quality_floor_pass}")
    print(f"replay_class={smoke.replay_class}")
    print(f"telemetry_event_count={smoke.telemetry_event_count}")


if __name__ == "__main__":
    main()
