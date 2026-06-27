from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from v2.contracts import BENCHMARK_QUALITY_FLOOR_SCHEMA_VERSION


class BenchmarkLayer(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


@dataclass(frozen=True)
class QualityFloorResult:
    quality_floor_pass: bool
    deterministic_checks_passed: bool
    fact_coverage_passed: bool
    llm_judge_passed: bool | None = None
    quality_floor_fail_reason: str = ""
    schema_version: str = BENCHMARK_QUALITY_FLOOR_SCHEMA_VERSION


@dataclass(frozen=True)
class BenchmarkRunReport:
    layer: BenchmarkLayer
    task_family: str
    quality_floor: QualityFloorResult
    metrics: dict[str, float] = field(default_factory=dict)
    missing_reason: str = ""

    @property
    def eligible_for_headline(self) -> bool:
        return self.quality_floor.quality_floor_pass


@dataclass(frozen=True)
class BenchmarkCaseReport:
    task_id: str
    task_family: str
    quality_floor: QualityFloorResult
    replay_class: str
    telemetry_event_count: int
    output_artifact_hash: str
    output_artifact_path: str
    workspace_root: str
    session_state: str = ""
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def eligible_for_headline(self) -> bool:
        return self.quality_floor.quality_floor_pass


@dataclass(frozen=True)
class BenchmarkFamilyReport:
    suite_id: str
    layer: BenchmarkLayer
    task_family: str
    cases: tuple[BenchmarkCaseReport, ...]
    aggregated_metrics: dict[str, float] = field(default_factory=dict)
    telemetry_summary: dict[str, float] = field(default_factory=dict)
    report_path: str = ""

    @property
    def eligible_for_headline(self) -> bool:
        return bool(self.cases) and all(case.eligible_for_headline for case in self.cases)
