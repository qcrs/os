from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkRunReport,
    QualityFloorResult,
)
from v2.runtime import TelemetryEmitter, TelemetryEvent
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


def load_sample_family(directory: Path) -> list[MinimalBenchmarkSample]:
    return [
        MinimalBenchmarkSample.from_path(path)
        for path in sorted(directory.glob("*.json"))
    ]


def _quality_floor_from_smoke(smoke: SmokeResult) -> QualityFloorResult:
    return QualityFloorResult(
        quality_floor_pass=smoke.compiler_status == "compiled" and smoke.artifact_state == "verified",
        deterministic_checks_passed=smoke.artifact_state == "verified",
        fact_coverage_passed=smoke.replay_class in {"exact_replay", "validated_replay"},
        llm_judge_passed=None,
        quality_floor_fail_reason=""
        if smoke.artifact_state == "verified"
        else "artifact_not_verified",
    )


def _report_from_smoke(sample: MinimalBenchmarkSample, smoke: SmokeResult) -> BenchmarkRunReport:
    return BenchmarkRunReport(
        layer=BenchmarkLayer.L0,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        metrics={
            "telemetry_event_count": float(smoke.telemetry_event_count),
            "registry_path_length": float(len(smoke.registry_path)),
            "output_artifact_path_length": float(len(smoke.output_artifact_path)),
        },
    )


def _case_from_smoke(sample: MinimalBenchmarkSample, smoke: SmokeResult) -> BenchmarkCaseReport:
    return BenchmarkCaseReport(
        task_id=sample.task_id,
        task_family=sample.task_family,
        quality_floor=_quality_floor_from_smoke(smoke),
        replay_class=smoke.replay_class,
        telemetry_event_count=smoke.telemetry_event_count,
        output_artifact_hash=smoke.output_artifact_hash,
        output_artifact_path=smoke.output_artifact_path,
        workspace_root=smoke.workspace_root,
        session_state=smoke.session_state,
        metrics={
            **dict(sorted(smoke.task_metrics.items())),
            "response_count": float(len(smoke.response_sequence)),
        },
    )


def _family_report_to_dict(report: BenchmarkFamilyReport) -> dict[str, object]:
    return {
        "suite_id": report.suite_id,
        "layer": report.layer.value,
        "task_family": report.task_family,
        "eligible_for_headline": report.eligible_for_headline,
        "aggregated_metrics": dict(sorted(report.aggregated_metrics.items())),
        "telemetry_summary": dict(sorted(report.telemetry_summary.items())),
        "cases": [
            {
                "task_id": case.task_id,
                "task_family": case.task_family,
                "replay_class": case.replay_class,
                "telemetry_event_count": case.telemetry_event_count,
                "output_artifact_hash": case.output_artifact_hash,
                "output_artifact_path": case.output_artifact_path,
                "workspace_root": case.workspace_root,
                "session_state": case.session_state,
                "quality_floor": {
                    "quality_floor_pass": case.quality_floor.quality_floor_pass,
                    "deterministic_checks_passed": case.quality_floor.deterministic_checks_passed,
                    "fact_coverage_passed": case.quality_floor.fact_coverage_passed,
                    "llm_judge_passed": case.quality_floor.llm_judge_passed,
                    "quality_floor_fail_reason": case.quality_floor.quality_floor_fail_reason,
                    "schema_version": case.quality_floor.schema_version,
                },
                "metrics": dict(sorted(case.metrics.items())),
            }
            for case in report.cases
        ],
    }


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
    return smoke, _report_from_smoke(sample, smoke)


def run_minimal_benchmark_family(
    *,
    samples: list[MinimalBenchmarkSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "minimal-family",
) -> BenchmarkFamilyReport:
    cases: list[BenchmarkCaseReport] = []
    suite_emitter = TelemetryEmitter()
    for sample in samples:
        smoke = run_smoke(
            workspace_root=workspace_root,
            runtime_root=runtime_root,
            socket_path=socket_path.with_name(f"{socket_path.stem}-{sample.task_id}{socket_path.suffix}"),
            request_text=sample.request_text,
            task_id=sample.task_id,
        )
        cases.append(_case_from_smoke(sample, smoke))
        suite_emitter.emit(
            TelemetryEvent.create(
                trace_id=f"suite:{suite_id}",
                task_id=sample.task_id,
                event_type="TASK_SUMMARY_METRICS",
                metrics=smoke.task_metrics,
            )
        )

    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": float(sum(case.telemetry_event_count for case in cases)),
    }
    telemetry_summary = suite_emitter.summarize_suite([case.task_id for case in cases])
    task_family = cases[0].task_family if cases else "financial_report_analysis"
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    family_report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=BenchmarkLayer.L0,
        task_family=task_family,
        cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
        report_path=str(report_path),
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(stable_json_dumps(_family_report_to_dict(family_report)) + "\n", encoding="utf-8")
    return family_report


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
    family = run_minimal_benchmark_family(
        samples=load_sample_family(Path(__file__).with_name("samples") / "minimal_family"),
        workspace_root=Path("/tmp/statebus-v2-benchmark-family/workspaces"),
        runtime_root=Path("/tmp/statebus-v2-benchmark-family/runtime"),
        socket_path=Path("/tmp/statebus-v2-benchmark-family/control.sock"),
    )
    print(f"task_id={sample.task_id}")
    print(f"quality_floor_pass={report.quality_floor.quality_floor_pass}")
    print(f"replay_class={smoke.replay_class}")
    print(f"telemetry_event_count={smoke.telemetry_event_count}")
    print(f"family_case_count={len(family.cases)}")
    print(f"family_quality_floor_pass_count={int(family.aggregated_metrics['quality_floor_pass_count'])}")
    print(f"family_report_path={family.report_path}")


if __name__ == "__main__":
    main()
