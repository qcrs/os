from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.models import BenchmarkLayer, BenchmarkRunReport, QualityFloorResult
from v2.runtime.smoke import SmokeResult, run_smoke
from v2.utils import stable_json_dumps


@dataclass(frozen=True)
class MinimalBenchmarkSample:
    task_id: str
    request_text: str
    expected_artifact_type: str = "json"
    task_family: str = "financial_report_analysis"

    @classmethod
    def from_path(cls, path: Path) -> "MinimalBenchmarkSample":
        payload = json.loads(path.read_text(encoding="utf-8"))
        request_text = payload["request_text"]
        if not isinstance(request_text, str):
            request_text = stable_json_dumps(request_text)
        return cls(
            task_id=str(payload["task_id"]),
            request_text=request_text,
            expected_artifact_type=str(payload.get("expected_artifact_type", "json")),
            task_family=str(payload.get("task_family", "financial_report_analysis")),
        )


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
        request_text=sample.request_text,
        task_id=sample.task_id,
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
    sample = MinimalBenchmarkSample.from_path(
        Path(__file__).with_name("samples") / "minimal_financial_report_sample.json"
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
