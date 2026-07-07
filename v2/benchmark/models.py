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
class BenchmarkLayerProfile:
    layer: BenchmarkLayer
    description: str
    structured_control_enabled: bool
    semantic_pruning_enabled: bool
    replay_enabled: bool
    multi_attempt_enabled: bool = False
    force_first_attempt_trap: bool = False
    hermetic_runtime_root: bool = True


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
    comparison_tags: tuple[str, ...] = ()
    audit_paths: dict[str, str] = field(default_factory=dict)
    audit_summary: dict[str, object] = field(default_factory=dict)

    @property
    def eligible_for_headline(self) -> bool:
        return self.quality_floor.quality_floor_pass


@dataclass(frozen=True)
class BenchmarkFamilyReport:
    suite_id: str
    layer: BenchmarkLayer
    task_family: str
    profile: BenchmarkLayerProfile
    cases: tuple[BenchmarkCaseReport, ...]
    aggregated_metrics: dict[str, float] = field(default_factory=dict)
    telemetry_summary: dict[str, float] = field(default_factory=dict)
    replay_class_distribution: dict[str, float] = field(default_factory=dict)
    quality_floor_breakdown: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    report_path: str = ""
    missing_reason: str = ""

    @property
    def eligible_for_headline(self) -> bool:
        return not self.missing_reason and bool(self.cases) and all(case.eligible_for_headline for case in self.cases)


@dataclass(frozen=True)
class BenchmarkSuiteReport:
    suite_id: str
    task_family: str
    layer_reports: tuple[BenchmarkFamilyReport, ...]
    waterfall_metrics: dict[str, float] = field(default_factory=dict)
    comparison_summary: dict[str, float] = field(default_factory=dict)
    evidence_pack: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    family_case_count: int = 0
    report_path: str = ""
    markdown_report_path: str = ""


@dataclass(frozen=True)
class BenchmarkContinuousCollectionReport:
    suite_id: str
    family_reports: tuple[BenchmarkSuiteReport, ...]
    collection_summary: dict[str, float] = field(default_factory=dict)
    admissibility_summary: dict[str, object] = field(default_factory=dict)
    evidence_pack: dict[str, object] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    report_path: str = ""
    markdown_report_path: str = ""

    @property
    def eligible_for_quality_headline(self) -> bool:
        return bool(self.family_reports) and all(
            bool(report.layer_reports) and all(layer_report.eligible_for_headline for layer_report in report.layer_reports)
            for report in self.family_reports
        )

    @property
    def eligible_for_replay_headline(self) -> bool:
        family_count = len(self.family_reports)
        if family_count == 0:
            return False
        replay_eligible_family_count = int(self.collection_summary.get("replay_headline_eligible_family_count", 0.0))
        return self.eligible_for_quality_headline and replay_eligible_family_count == family_count

    @property
    def eligible_for_headline(self) -> bool:
        return self.eligible_for_replay_headline


@dataclass(frozen=True)
class BenchmarkComparatorModeReport:
    suite_id: str
    role_path_mode: str
    task_family: str
    external_report: BenchmarkFamilyReport
    statebus_report: BenchmarkFamilyReport
    comparison_summary: dict[str, float] = field(default_factory=dict)
    headline_metrics: dict[str, float] = field(default_factory=dict)
    debug_metrics: dict[str, float] = field(default_factory=dict)
    fairness_manifest: dict[str, object] = field(default_factory=dict)
    comparison_valid: bool = False
    invalid_reason: str = ""
    benchmark_tier: str = "dev"
    claim_level: str = "prototype"
    report_path: str = ""
    markdown_report_path: str = ""
    missing_reason: str = ""

    @property
    def eligible_for_headline(self) -> bool:
        return (
            self.comparison_valid
            and not self.missing_reason
            and self.external_report.eligible_for_headline
            and self.statebus_report.eligible_for_headline
            and bool(self.headline_metrics)
        )


@dataclass(frozen=True)
class BenchmarkComparatorSuiteReport:
    suite_id: str
    task_family: str
    mode_reports: tuple[BenchmarkComparatorModeReport, ...]
    comparison_summary: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)
    benchmark_tier: str = "dev"
    claim_level: str = "prototype"
    report_path: str = ""
    markdown_report_path: str = ""

    def canonical_payload(self) -> dict[str, object]:
        payload = {
            "suite_id": self.suite_id,
            "task_family": self.task_family,
            "benchmark_tier": self.benchmark_tier,
            "claim_level": self.claim_level,
            "metadata": dict(sorted(self.metadata.items())),
            "comparison_summary": dict(sorted(self.comparison_summary.items())),
            "report_path": self.report_path,
            "markdown_report_path": self.markdown_report_path,
            "mode_reports": [
                {
                    "role_path_mode": report.role_path_mode,
                    "missing_reason": report.missing_reason,
                    "comparison_valid": report.comparison_valid,
                    "invalid_reason": report.invalid_reason,
                    "benchmark_tier": report.benchmark_tier,
                    "claim_level": report.claim_level,
                    "report_path": report.report_path,
                    "markdown_report_path": report.markdown_report_path,
                }
                for report in self.mode_reports
            ],
        }
        for key in (
            "strict_equal_quality_comparison_valid",
            "quality_superiority_comparison_valid",
            "formal_quality_superiority_claim_allowed",
            "formal_efficiency_superiority_claim_allowed",
            "formal_external_claim_kind",
            "formal_superiority_claim_allowed",
            "formal_efficiency_claim_allowed",
            "fixed_answer_external_comparison_valid",
            "formal_compare_scope_label",
            "formal_compare_case_count",
            "formal_compare_family_count",
            "formal_registry_case_count",
            "formal_registry_family_count",
            "formal_compare_full_registry_coverage",
            "state_pool_mode_requested",
            "state_pool_mode_used",
            "memfd_transfer_count",
            "memfd_publish_count",
            "memfd_bytes_transferred",
        ):
            if key in self.metadata:
                payload[key] = self.metadata[key]
        for key, value in self.comparison_summary.items():
            if key.endswith("_quality_floor_pass_count") or key.endswith("_tokens_delta") or key.endswith("_task_ms_delta"):
                payload[key] = value
        return payload
