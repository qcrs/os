from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from v2.benchmark.continuous_task_family import ContinuousTaskFamily
from v2.benchmark.minimal_runner import LAYER_PROFILES, LAYER_SMOKE_CONFIGS
from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from v2.benchmark.reporting import (
    continuous_collection_report_to_dict,
    family_report_to_dict,
    suite_report_to_dict,
    write_json_report,
    write_markdown_report,
)
from v2.contracts import CanonicalTaskSpec
from v2.runtime.smoke import SmokeLayerConfig, SmokeResult, run_smoke


SUPPORTED_CONTINUOUS_FAMILY_IDS = {
    "csv_correlation_replay_v1",
    "csv_table_profile_v1",
    "incident_diagnosis_v2",
    "long_doc_table_v1",
    "long_doc_metric_replay_v1",
}

CONTINUOUS_TEXT_SEMANTIC_SELECTION_PROFILE = BenchmarkLayerProfile(
    layer=BenchmarkLayer.L2,
    description="formal diagnostic text handoff with same semantic selection and no semantic state transfer",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)

CONTINUOUS_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG = SmokeLayerConfig(
    layer_name="T2-continuous-text-semantic-selection",
    handoff_mode="text_collaboration",
    structured_control_enabled=False,
    semantic_pruning_enabled=True,
    semantic_state_transfer_enabled=False,
    replay_enabled=False,
    multi_attempt_enabled=False,
    force_first_attempt_trap=False,
)


@dataclass(frozen=True)
class ContinuousRoundSample:
    round_number: int
    task_id: str
    dataset_id: str
    request_text: str
    expected_facts: dict[str, object]
    quality_checks: tuple[str, ...]
    canonical_task_spec: object
    depends_on_rounds: tuple[int, ...]
    minimum_reuse_class: str
    expected_metric_effects: dict[str, object]


def _prepare_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _supported_continuous_family_ids() -> list[str]:
    return sorted(SUPPORTED_CONTINUOUS_FAMILY_IDS)


def _continuous_sample(round_) -> ContinuousRoundSample:
    canonical_task_spec = CanonicalTaskSpec(
        task_family=round_.canonical_task_spec.task_family,
        intent_op=round_.canonical_task_spec.intent_op,
        target_entities=tuple(round_.canonical_task_spec.target_entities),
        time_scope=round_.canonical_task_spec.time_scope,
        required_outputs=tuple(round_.canonical_task_spec.required_outputs),
        required_tools=tuple(round_.canonical_task_spec.required_tools),
        arguments={
            **dict(round_.canonical_task_spec.arguments),
            "quality_checks": list(round_.quality_checks),
            "reuse_contract": round_.reuse_contract.canonical_payload(),
            "depends_on_rounds": list(round_.depends_on_rounds),
        },
        schema_version=round_.canonical_task_spec.schema_version,
    )
    return ContinuousRoundSample(
        round_number=round_.round,
        task_id=round_.task_id,
        dataset_id=round_.dataset_id,
        request_text=round_.request_text,
        expected_facts=dict(round_.expected_facts),
        quality_checks=tuple(round_.quality_checks),
        canonical_task_spec=canonical_task_spec,
        depends_on_rounds=tuple(round_.depends_on_rounds),
        minimum_reuse_class=round_.reuse_contract.minimum_reuse_class,
        expected_metric_effects=dict(round_.expected_metric_effects),
    )


def _case_from_smoke(
    *,
    smoke: SmokeResult,
    sample: ContinuousRoundSample,
    layer: BenchmarkLayer,
    enforce_expected_metric_effects: bool = True,
) -> BenchmarkCaseReport:
    quality_floor = (
        _continuous_quality_floor(
            smoke_quality_floor=smoke.quality_floor,
            sample=sample,
            metrics=smoke.task_metrics,
            layer=layer,
        )
        if enforce_expected_metric_effects
        else smoke.quality_floor
    )
    return BenchmarkCaseReport(
        task_id=sample.task_id,
        task_family=smoke.audit_summary.get("task_family", sample.canonical_task_spec.task_family)
        if isinstance(smoke.audit_summary, dict)
        else sample.canonical_task_spec.task_family,
        quality_floor=quality_floor,
        replay_class=smoke.replay_class,
        telemetry_event_count=smoke.telemetry_event_count,
        output_artifact_hash=smoke.output_artifact_hash,
        output_artifact_path=smoke.output_artifact_path,
        workspace_root=smoke.workspace_root,
        session_state=smoke.session_state,
        comparison_tags=(f"round:{sample.round_number}", f"dataset:{sample.dataset_id}"),
        audit_paths={
            "replay": smoke.replay_audit_path,
            "hydration": smoke.hydration_audit_path,
            "hydration_debug": smoke.hydration_debug_audit_path,
            "artifact": smoke.artifact_audit_path,
        },
        audit_summary={
            **smoke.audit_summary,
            "round_number": sample.round_number,
            "dataset_id": sample.dataset_id,
            "quality_checks": list(sample.quality_checks),
            "depends_on_rounds": list(sample.depends_on_rounds),
            "minimum_reuse_class": sample.minimum_reuse_class,
            "expected_metric_effects": dict(sample.expected_metric_effects),
            "layer": layer.value,
        },
        metrics={
            **dict(sorted(smoke.task_metrics.items())),
            "round_number": float(sample.round_number),
            "history_dependency_count": float(len(sample.depends_on_rounds)),
        },
    )


def _apply_case_metric_contracts(
    *,
    current: BenchmarkCaseReport,
    previous_layer_case: BenchmarkCaseReport | None,
) -> BenchmarkCaseReport:
    expected_effects = {
        str(key): value
        for key, value in current.audit_summary.get("expected_metric_effects", {}).items()
    }
    if not current.quality_floor.quality_floor_pass or not expected_effects:
        return current
    layer_name = str(current.audit_summary.get("layer", ""))
    failures: list[str] = []
    metric_aliases = {
        "artifact_reuse_count": "history_artifact_reuse_count",
        "strategy_reuse_count": "history_strategy_reuse_count",
        "history_step_reduction_count": "history_step_reduction_count",
        "reuse_gain": "history_reuse_gain",
    }
    for key, expected_value in expected_effects.items():
        prefix = f"{layer_name}_"
        if not key.startswith(prefix):
            continue
        suffix = key.removeprefix(prefix)
        if suffix.endswith("_delta_max"):
            if previous_layer_case is None:
                failures.append(f"{suffix}_requires_previous_layer_case")
                continue
            metric_name = suffix.removesuffix("_delta_max")
            current_value = float(
                current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0))
            )
            previous_value = float(
                previous_layer_case.metrics.get(
                    metric_name,
                    previous_layer_case.metrics.get(metric_aliases.get(metric_name, ""), 0.0),
                )
            )
            delta = current_value - previous_value
            if delta > float(expected_value):
                failures.append(f"{metric_name}_delta_above_max:{delta:g}>{float(expected_value):g}")
            continue
        if suffix.endswith("_delta_min"):
            if previous_layer_case is None:
                failures.append(f"{suffix}_requires_previous_layer_case")
                continue
            metric_name = suffix.removesuffix("_delta_min")
            current_value = float(
                current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0))
            )
            previous_value = float(
                previous_layer_case.metrics.get(
                    metric_name,
                    previous_layer_case.metrics.get(metric_aliases.get(metric_name, ""), 0.0),
                )
            )
            delta = current_value - previous_value
            if delta < float(expected_value):
                failures.append(f"{metric_name}_delta_below_min:{delta:g}<{float(expected_value):g}")
            continue
        if suffix.endswith("_min"):
            metric_name = suffix.removesuffix("_min")
            observed = float(current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            if metric_name == "validated_replay_count":
                observed += float(current.metrics.get("exact_replay_count", 0.0))
            if metric_name == "downgrade_execution_goal_count" and float(current.metrics.get("exact_replay_count", 0.0)) > 0.0:
                continue
            if observed < float(expected_value):
                failures.append(f"{metric_name}_below_min:{observed:g}<{float(expected_value):g}")
            continue
        if suffix.endswith("_max"):
            metric_name = suffix.removesuffix("_max")
            observed = float(current.metrics.get(metric_name, current.metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            if observed > float(expected_value):
                failures.append(f"{metric_name}_above_max:{observed:g}>{float(expected_value):g}")
            continue
    if not failures:
        return current
    reason = ";".join(
        item
        for item in (
            current.quality_floor.quality_floor_fail_reason,
            "continuous_metric_contract_failed",
            *failures,
        )
        if item
    )
    return BenchmarkCaseReport(
        task_id=current.task_id,
        task_family=current.task_family,
        quality_floor=QualityFloorResult(
            quality_floor_pass=False,
            deterministic_checks_passed=current.quality_floor.deterministic_checks_passed,
            fact_coverage_passed=False,
            llm_judge_passed=current.quality_floor.llm_judge_passed,
            quality_floor_fail_reason=reason,
        ),
        replay_class=current.replay_class,
        telemetry_event_count=current.telemetry_event_count,
        output_artifact_hash=current.output_artifact_hash,
        output_artifact_path=current.output_artifact_path,
        workspace_root=current.workspace_root,
        session_state=current.session_state,
        comparison_tags=current.comparison_tags,
        audit_paths=current.audit_paths,
        audit_summary=current.audit_summary,
        metrics=current.metrics,
    )


def _continuous_quality_floor(
    *,
    smoke_quality_floor: QualityFloorResult,
    sample: ContinuousRoundSample,
    metrics: dict[str, float],
    layer: BenchmarkLayer,
) -> QualityFloorResult:
    failures: list[str] = []
    metric_aliases = {
        "artifact_reuse_count": "history_artifact_reuse_count",
        "strategy_reuse_count": "history_strategy_reuse_count",
        "history_step_reduction_count": "history_step_reduction_count",
        "reuse_gain": "history_reuse_gain",
    }
    for key, minimum in sample.expected_metric_effects.items():
        layer_prefix = f"{layer.value}_"
        if not key.startswith(layer_prefix):
            continue
        suffix = key.removeprefix(layer_prefix)
        if "_delta_" in suffix:
            continue
        observed = None
        comparator = ""
        metric_name = suffix
        if suffix.endswith("_min"):
            comparator = "min"
            metric_name = suffix.removesuffix("_min")
            observed = float(metrics.get(metric_name, metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            expected = float(minimum)
            if metric_name == "validated_replay_count":
                observed += float(metrics.get("exact_replay_count", 0.0))
            if metric_name == "downgrade_execution_goal_count" and float(metrics.get("exact_replay_count", 0.0)) > 0.0:
                continue
            if observed < expected:
                failures.append(f"{metric_name}_below_min:{observed:g}<{expected:g}")
        elif suffix.endswith("_max"):
            comparator = "max"
            metric_name = suffix.removesuffix("_max")
            observed = float(metrics.get(metric_name, metrics.get(metric_aliases.get(metric_name, ""), 0.0)))
            expected = float(minimum)
            if observed > expected:
                failures.append(f"{metric_name}_above_max:{observed:g}>{expected:g}")
        if comparator:
            continue
    if not failures:
        return smoke_quality_floor
    reason = ";".join(
        item
        for item in (smoke_quality_floor.quality_floor_fail_reason, "continuous_metric_contract_failed", *failures)
        if item
    )
    return QualityFloorResult(
        quality_floor_pass=False,
        deterministic_checks_passed=smoke_quality_floor.deterministic_checks_passed,
        fact_coverage_passed=False,
        llm_judge_passed=smoke_quality_floor.llm_judge_passed,
        quality_floor_fail_reason=reason,
    )


def _continuous_quality_headline_eligible(report: BenchmarkSuiteReport) -> bool:
    return bool(report.layer_reports) and all(layer_report.eligible_for_headline for layer_report in report.layer_reports)


def _continuous_replay_audit(
    *,
    family: ContinuousTaskFamily,
    report: BenchmarkSuiteReport,
) -> dict[str, object]:
    quality_headline_eligible = _continuous_quality_headline_eligible(report)
    l3_report = next((layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3), None)
    replay_target_rounds = family.replay_target_rounds_by_class()
    validated_target_rounds = set(replay_target_rounds["validated_replay"])
    exact_target_rounds = set(replay_target_rounds["exact_replay"])
    replay_admissible_family = bool(validated_target_rounds or exact_target_rounds)
    if l3_report is None:
        return {
            "eligible_for_replay_headline": False,
            "gate_reason": "missing_l3_report",
            "audit_mode": "replay_admissible" if replay_admissible_family else "history_backed",
            "expected_target_rounds": list(family.l3_target_nonzero_rounds()),
            "observed_replay_rounds": [],
            "observed_history_reuse_rounds": [],
            "missing_target_rounds": list(family.l3_target_nonzero_rounds()),
            "unexpected_target_rounds": [],
            "validated_target_rounds": list(replay_target_rounds["validated_replay"]),
            "exact_target_rounds": list(replay_target_rounds["exact_replay"]),
            "observed_validated_rounds": [],
            "observed_exact_rounds": [],
            "missing_validated_rounds": list(replay_target_rounds["validated_replay"]),
            "missing_exact_rounds": list(replay_target_rounds["exact_replay"]),
            "unexpected_validated_rounds": [],
            "unexpected_exact_rounds": [],
            "history_target_rounds": list(family.l3_target_nonzero_rounds()),
            "missing_history_target_rounds": list(family.l3_target_nonzero_rounds()),
            "unexpected_history_target_rounds": [],
        }

    target_nonzero_rounds = set(family.l3_target_nonzero_rounds())
    observed_validated_rounds: set[int] = set()
    observed_exact_rounds: set[int] = set()
    observed_replay_rounds: set[int] = set()
    observed_history_reuse_rounds: set[int] = set()
    required_reuse_failures: list[str] = []

    for case in l3_report.cases:
        round_number = int(case.audit_summary.get("round_number", 0) or 0)
        if round_number <= 0 or not case.quality_floor.quality_floor_pass:
            continue
        required_reuse_class = str(case.audit_summary.get("minimum_reuse_class", "")).strip()
        observed_replay_class = case.replay_class
        history_step_reduction_count = float(case.metrics.get("history_step_reduction_count", 0.0))
        history_reuse_gain = float(case.metrics.get("history_reuse_gain", 0.0))
        artifact_reuse_count = float(
            case.metrics.get("artifact_reuse_count", case.metrics.get("history_artifact_reuse_count", 0.0))
        )
        if (
            history_step_reduction_count > 0.0
            or history_reuse_gain > 0.0
            or artifact_reuse_count > 0.0
        ):
            observed_history_reuse_rounds.add(round_number)
        if observed_replay_class in {"validated_replay", "exact_replay"}:
            observed_replay_rounds.add(round_number)
        if observed_replay_class == "validated_replay":
            observed_validated_rounds.add(round_number)
        elif observed_replay_class == "exact_replay":
            observed_exact_rounds.add(round_number)
            observed_validated_rounds.add(round_number)
        if required_reuse_class == "validated_replay" and observed_replay_class not in {"validated_replay", "exact_replay"}:
            required_reuse_failures.append(f"round_{round_number}:validated_replay_missing")
        if required_reuse_class == "exact_replay" and observed_replay_class != "exact_replay":
            required_reuse_failures.append(f"round_{round_number}:exact_replay_missing")

    if replay_admissible_family:
        observed_target_rounds = observed_replay_rounds
    else:
        observed_target_rounds = observed_history_reuse_rounds
    missing_target_rounds = sorted(target_nonzero_rounds - observed_target_rounds)
    unexpected_target_rounds = sorted(observed_target_rounds - target_nonzero_rounds)
    missing_validated_rounds = sorted(validated_target_rounds - observed_validated_rounds)
    missing_exact_rounds = sorted(exact_target_rounds - observed_exact_rounds)
    unexpected_validated_rounds = sorted(observed_validated_rounds - (validated_target_rounds | exact_target_rounds))
    unexpected_exact_rounds = sorted(observed_exact_rounds - (exact_target_rounds | validated_target_rounds))

    gate_failures: list[str] = []
    if not quality_headline_eligible:
        gate_failures.append("quality_gate_failed")
    if not target_nonzero_rounds:
        gate_failures.append("no_target_nonzero_rounds_declared")
    if missing_target_rounds:
        gate_failures.append(
            "missing_target_replay_rounds" if replay_admissible_family else "missing_target_history_reuse_rounds"
        )
    if unexpected_target_rounds and replay_admissible_family:
        gate_failures.append("unexpected_replay_rounds")
    if replay_admissible_family:
        if missing_validated_rounds:
            gate_failures.append("missing_validated_target_rounds")
        if missing_exact_rounds:
            gate_failures.append("missing_exact_target_rounds")
        if unexpected_exact_rounds:
            gate_failures.append("unexpected_exact_replay_rounds")
        if required_reuse_failures:
            gate_failures.append("required_reuse_class_unmet")

    return {
        "eligible_for_replay_headline": replay_admissible_family and not gate_failures,
        "gate_reason": ";".join(gate_failures) if gate_failures else "",
        "audit_mode": "replay_admissible" if replay_admissible_family else "history_backed",
        "expected_target_rounds": sorted(target_nonzero_rounds),
        "observed_replay_rounds": sorted(observed_replay_rounds),
        "observed_history_reuse_rounds": sorted(observed_history_reuse_rounds),
        "missing_target_rounds": missing_target_rounds,
        "unexpected_target_rounds": unexpected_target_rounds,
        "validated_target_rounds": sorted(validated_target_rounds),
        "exact_target_rounds": sorted(exact_target_rounds),
        "observed_validated_rounds": sorted(observed_validated_rounds),
        "observed_exact_rounds": sorted(observed_exact_rounds),
        "missing_validated_rounds": missing_validated_rounds,
        "missing_exact_rounds": missing_exact_rounds,
        "unexpected_validated_rounds": unexpected_validated_rounds,
        "unexpected_exact_rounds": unexpected_exact_rounds,
        "required_reuse_failures": required_reuse_failures,
        "history_target_rounds": sorted(target_nonzero_rounds) if not replay_admissible_family else [],
        "missing_history_target_rounds": missing_target_rounds if not replay_admissible_family else [],
        "unexpected_history_target_rounds": unexpected_target_rounds if not replay_admissible_family else [],
    }


def _continuous_headline_scope(
    report: BenchmarkSuiteReport,
    *,
    replay_audit: dict[str, object] | None = None,
) -> str:
    if replay_audit is not None and bool(replay_audit.get("eligible_for_replay_headline", False)):
        return "replay_admissible"
    if _continuous_quality_headline_eligible(report):
        l3_report = next((layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3), None)
        if l3_report is not None and l3_report.telemetry_summary.get("history_artifact_reuse_count", 0.0) > 0.0:
            return "history_backed_only"
        return "quality_only"
    return "not_eligible"


def _replay_audit_summary_counts(replay_audit: dict[str, object]) -> dict[str, float]:
    audit_mode = str(replay_audit.get("audit_mode", "")).strip()
    history_backed = audit_mode == "history_backed"
    replay_admissible = audit_mode == "replay_admissible"
    return {
        "history_target_round_count": float(len(replay_audit.get("history_target_rounds", []))) if history_backed else 0.0,
        "history_observed_reuse_round_count": float(
            len(replay_audit.get("observed_history_reuse_rounds", []))
        )
        if history_backed
        else 0.0,
        "history_missing_target_round_count": float(
            len(replay_audit.get("missing_history_target_rounds", []))
        )
        if history_backed
        else 0.0,
        "history_additional_reuse_round_count": float(
            len(replay_audit.get("unexpected_history_target_rounds", []))
        )
        if history_backed
        else 0.0,
        "replay_target_round_count": float(len(replay_audit.get("expected_target_rounds", []))) if replay_admissible else 0.0,
        "replay_observed_round_count": float(len(replay_audit.get("observed_replay_rounds", []))) if replay_admissible else 0.0,
        "replay_missing_target_round_count": float(len(replay_audit.get("missing_target_rounds", [])))
        if replay_admissible
        else 0.0,
        "replay_unexpected_round_count": float(len(replay_audit.get("unexpected_target_rounds", [])))
        if replay_admissible
        else 0.0,
    }


def _metric_delta(
    *,
    reports_by_layer: dict[BenchmarkLayer, BenchmarkFamilyReport],
    from_layer: BenchmarkLayer,
    to_layer: BenchmarkLayer,
    metric: str,
) -> float:
    return float(reports_by_layer[to_layer].telemetry_summary.get(metric, 0.0)) - float(
        reports_by_layer[from_layer].telemetry_summary.get(metric, 0.0)
    )


_OUTER_RUNTIME_STAGE_BUCKETS = (
    "workspace_input_stage_ms",
    "runtime_signature_stage_ms",
    "codeact_execution_stage_ms",
    "execution_log_capture_stage_ms",
    "workspace_output_stage_ms",
    "runtime_driver_stage_ms",
    "telemetry_emit_stage_ms",
)

_DRIVER_STAGE_BUCKETS = (
    "runtime_non_executor_stage_ms",
    "runtime_data_plane_event_stage_ms",
    "control_plane_exchange_stage_ms",
    "executor_state_machine_stage_ms",
    "runtime_commit_finalize_stage_ms",
    "runtime_post_executor_stage_ms",
    "runtime_replay_ledger_stage_ms",
    "persist_and_reload_stage_ms",
    "registry_query_stage_ms",
)

_PERSIST_AND_RELOAD_STAGE_BUCKETS = (
    "persist_bundle_write_stage_ms",
    "persist_core_reload_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "persist_session_ledger_reload_stage_ms",
    "persist_validator_reload_stage_ms",
    "persist_semantic_manifest_reload_stage_ms",
    "persist_integrity_check_stage_ms",
    "persist_unbucketed_stage_ms",
)

_WRITE_COUNT_BUCKETS = (
    "workspace_input_direct_write_count",
    "workspace_input_bundle_write_count",
    "workspace_input_bundle_reused_count",
    "workspace_input_manifest_write_count",
    "workspace_output_bundle_write_count",
    "workspace_output_bundle_reused_count",
    "workspace_output_manifest_write_count",
    "runtime_signature_manifest_bundle_write_count",
    "telemetry_event_write_count",
    "telemetry_fact_write_count",
    "telemetry_log_handle_open_count",
    "role_prompt_slice_artifact_count",
    "workspace_files",
)


def _summary_metric(report: BenchmarkFamilyReport, key: str) -> float:
    return float(report.telemetry_summary.get(key, 0.0))


def _top_stage_buckets(stage_totals: dict[str, float], *, limit: int = 5) -> list[dict[str, object]]:
    return [
        {"bucket": key, "stage_ms": round(value, 6)}
        for key, value in sorted(stage_totals.items(), key=lambda item: (-item[1], item[0]))[:limit]
    ]


def _runtime_overhead_summary(report: BenchmarkFamilyReport) -> dict[str, object]:
    outer_stage_totals = {key: _summary_metric(report, key) for key in _OUTER_RUNTIME_STAGE_BUCKETS}
    driver_stage_totals = {key: _summary_metric(report, key) for key in _DRIVER_STAGE_BUCKETS}
    persist_breakdown_totals = {key: _summary_metric(report, key) for key in _PERSIST_AND_RELOAD_STAGE_BUCKETS}
    runtime_driver_stage_ms = _summary_metric(report, "runtime_driver_stage_ms")
    driver_observed_bucket_sum = sum(driver_stage_totals.values())
    outer_observed_bucket_sum = sum(outer_stage_totals.values())
    persist_and_reload_stage_ms = _summary_metric(report, "persist_and_reload_stage_ms")
    persist_breakdown_observed_sum = sum(persist_breakdown_totals.values())
    write_counts = {key: _summary_metric(report, key) for key in _WRITE_COUNT_BUCKETS}
    return {
        "schema_version": "statebus.runtime_overhead_summary.v1",
        "layer": report.layer.value,
        "case_count": float(report.aggregated_metrics.get("case_count", 0.0)),
        "outer_stage_totals_ms": {key: round(value, 6) for key, value in outer_stage_totals.items()},
        "driver_stage_totals_ms": {key: round(value, 6) for key, value in driver_stage_totals.items()},
        "persist_and_reload_breakdown_totals_ms": {
            key: round(value, 6) for key, value in persist_breakdown_totals.items()
        },
        "top_outer_stage_buckets": _top_stage_buckets(outer_stage_totals),
        "top_driver_stage_buckets": _top_stage_buckets(driver_stage_totals),
        "top_persist_and_reload_buckets": _top_stage_buckets(persist_breakdown_totals),
        "outer_observed_bucket_sum_stage_ms": round(outer_observed_bucket_sum, 6),
        "driver_observed_bucket_sum_stage_ms": round(driver_observed_bucket_sum, 6),
        "persist_and_reload_observed_bucket_sum_stage_ms": round(persist_breakdown_observed_sum, 6),
        "estimated_unbucketed_driver_stage_ms": round(runtime_driver_stage_ms - driver_observed_bucket_sum, 6),
        "estimated_unbucketed_persist_and_reload_stage_ms": round(
            persist_and_reload_stage_ms - persist_breakdown_observed_sum,
            6,
        ),
        "persist_and_reload_share_of_driver": round(
            0.0 if runtime_driver_stage_ms <= 0.0 else persist_and_reload_stage_ms / runtime_driver_stage_ms,
            6,
        ),
        "telemetry_write_stage_ms": round(_summary_metric(report, "telemetry_emit_stage_ms"), 6),
        "telemetry_event_write_stage_ms": round(_summary_metric(report, "telemetry_event_write_stage_ms"), 6),
        "telemetry_fact_write_stage_ms": round(_summary_metric(report, "telemetry_fact_write_stage_ms"), 6),
        "write_counts": {key: round(value, 6) for key, value in write_counts.items()},
        "role_prompt_slice_artifact_bytes_total": round(
            _summary_metric(report, "role_prompt_slice_artifact_bytes_total"),
            6,
        ),
        "optimization_read": _runtime_overhead_read(
            persist_and_reload_stage_ms=persist_and_reload_stage_ms,
            runtime_driver_stage_ms=runtime_driver_stage_ms,
            write_counts=write_counts,
        ),
    }


def _runtime_overhead_read(
    *,
    persist_and_reload_stage_ms: float,
    runtime_driver_stage_ms: float,
    write_counts: dict[str, float],
) -> str:
    if runtime_driver_stage_ms > 0.0 and persist_and_reload_stage_ms / runtime_driver_stage_ms >= 0.25:
        return "persist_and_reload_is_primary_driver_bucket"
    if write_counts.get("role_prompt_slice_artifact_count", 0.0) >= 4.0:
        return "prompt_slice_artifacts_are_visible_audit_cost"
    return "overhead_distributed_across_runtime_buckets"


def _aggregate_runtime_overhead(family_reports: tuple[BenchmarkSuiteReport, ...]) -> dict[str, object]:
    family_layer_summaries: list[dict[str, object]] = []
    outer_totals: dict[str, float] = {key: 0.0 for key in _OUTER_RUNTIME_STAGE_BUCKETS}
    driver_totals: dict[str, float] = {key: 0.0 for key in _DRIVER_STAGE_BUCKETS}
    persist_breakdown_totals: dict[str, float] = {key: 0.0 for key in _PERSIST_AND_RELOAD_STAGE_BUCKETS}
    write_totals: dict[str, float] = {key: 0.0 for key in _WRITE_COUNT_BUCKETS}
    for family_report in family_reports:
        for layer_report in family_report.layer_reports:
            overhead = _runtime_overhead_summary(layer_report)
            family_layer_summaries.append(
                {
                    "family_id": family_report.task_family,
                    "layer": layer_report.layer.value,
                    "top_driver_stage_buckets": overhead["top_driver_stage_buckets"],
                    "top_persist_and_reload_buckets": overhead["top_persist_and_reload_buckets"],
                    "persist_and_reload_share_of_driver": overhead["persist_and_reload_share_of_driver"],
                    "optimization_read": overhead["optimization_read"],
                }
            )
            for key, value in dict(overhead["outer_stage_totals_ms"]).items():
                outer_totals[key] = outer_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["driver_stage_totals_ms"]).items():
                driver_totals[key] = driver_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["persist_and_reload_breakdown_totals_ms"]).items():
                persist_breakdown_totals[key] = persist_breakdown_totals.get(key, 0.0) + float(value)
            for key, value in dict(overhead["write_counts"]).items():
                write_totals[key] = write_totals.get(key, 0.0) + float(value)
    return {
        "schema_version": "statebus.runtime_overhead_collection_summary.v1",
        "outer_stage_totals_ms": {key: round(value, 6) for key, value in outer_totals.items()},
        "driver_stage_totals_ms": {key: round(value, 6) for key, value in driver_totals.items()},
        "persist_and_reload_breakdown_totals_ms": {
            key: round(value, 6) for key, value in persist_breakdown_totals.items()
        },
        "write_count_totals": {key: round(value, 6) for key, value in write_totals.items()},
        "top_outer_stage_buckets": _top_stage_buckets(outer_totals),
        "top_driver_stage_buckets": _top_stage_buckets(driver_totals),
        "top_persist_and_reload_buckets": _top_stage_buckets(persist_breakdown_totals),
        "family_layer_summaries": family_layer_summaries,
    }


def _family_layer_evidence(report: BenchmarkFamilyReport) -> dict[str, object]:
    return {
        "layer": report.layer.value,
        "quality_floor_pass_count": float(report.quality_floor_breakdown.get("quality_floor_pass_count", 0.0)),
        "case_count": float(report.aggregated_metrics.get("case_count", 0.0)),
        "llm_prompt_bytes": float(report.telemetry_summary.get("llm_prompt_bytes", 0.0)),
        "control_bytes": float(report.telemetry_summary.get("control_bytes", 0.0)),
        "raw_evidence_bytes_seen_by_llm": float(
            report.telemetry_summary.get("raw_evidence_bytes_seen_by_llm", 0.0)
        ),
        "prompt_visible_total_bytes": float(report.telemetry_summary.get("prompt_visible_total_bytes", 0.0)),
        "prompt_scaffolding_bytes_total": float(
            report.telemetry_summary.get("prompt_scaffolding_bytes_total", 0.0)
        ),
        "semantic_state_transfer_count": float(report.telemetry_summary.get("semantic_state_transfer_count", 0.0)),
        "artifact_reuse_count": float(report.telemetry_summary.get("artifact_reuse_count", 0.0)),
        "history_step_reduction_count": float(report.telemetry_summary.get("history_step_reduction_count", 0.0)),
        "history_reuse_gain": float(report.telemetry_summary.get("history_reuse_gain", 0.0)),
        "validated_replay_count": float(report.telemetry_summary.get("validated_replay_count", 0.0)),
        "exact_replay_count": float(report.telemetry_summary.get("exact_replay_count", 0.0)),
        "skipped_step_count": float(report.telemetry_summary.get("skipped_step_count", 0.0)),
        "runtime_overhead": _runtime_overhead_summary(report),
        "report_path": report.report_path,
    }


def _case_round_evidence(case: BenchmarkCaseReport) -> dict[str, object]:
    hydration = dict(case.audit_summary.get("hydration", {})) if isinstance(case.audit_summary, dict) else {}
    replay = dict(case.audit_summary.get("replay", {})) if isinstance(case.audit_summary, dict) else {}
    return {
        "task_id": case.task_id,
        "round_number": int(case.metrics.get("round_number", 0.0)),
        "quality_floor_pass": case.quality_floor.quality_floor_pass,
        "replay_class": case.replay_class,
        "minimum_reuse_class": str(case.audit_summary.get("minimum_reuse_class", "")),
        "raw_evidence_bytes_seen_by_llm": float(case.metrics.get("raw_evidence_bytes_seen_by_llm", 0.0)),
        "prompt_visible_total_bytes": float(case.metrics.get("prompt_visible_total_bytes", 0.0)),
        "semantic_state_transfer_count": float(case.metrics.get("semantic_state_transfer_count", 0.0)),
        "artifact_reuse_count": float(case.metrics.get("artifact_reuse_count", 0.0)),
        "history_step_reduction_count": float(case.metrics.get("history_step_reduction_count", 0.0)),
        "validated_replay_count": float(case.metrics.get("validated_replay_count", 0.0)),
        "exact_replay_count": float(case.metrics.get("exact_replay_count", 0.0)),
        "skipped_step_count": float(case.metrics.get("skipped_step_count", 0.0)),
        "decision_reason": str(replay.get("decision_reason", "")),
        "compatibility_verdict": str(replay.get("compatibility_verdict", "")),
        "role_prompt_slice_ref_ids": dict(hydration.get("role_prompt_slice_ref_ids", {})),
        "role_prompt_slice_relpaths": dict(hydration.get("role_prompt_slice_relpaths", {})),
        "audit_paths": dict(sorted(case.audit_paths.items())),
        "workspace_root": case.workspace_root,
        "output_artifact_path": case.output_artifact_path,
    }


def _continuous_suite_evidence_pack(
    *,
    family: ContinuousTaskFamily,
    report: BenchmarkSuiteReport,
    replay_audit: dict[str, object],
) -> dict[str, object]:
    reports_by_layer = {layer_report.layer: layer_report for layer_report in report.layer_reports}
    l3_report = reports_by_layer.get(BenchmarkLayer.L3)
    return {
        "schema_version": "statebus.continuous_evidence_pack.v1",
        "family_id": family.family_id,
        "claim_tier": family.claim_tier,
        "headline_scope": _continuous_headline_scope(report, replay_audit=replay_audit),
        "quality_headline_eligible": _continuous_quality_headline_eligible(report),
        "replay_headline_eligible": bool(replay_audit.get("eligible_for_replay_headline", False)),
        "round_count": family.round_count,
        "reuse_edge_count": sum(len(round_.depends_on_rounds) for round_ in family.rounds),
        "layer_summaries": [_family_layer_evidence(layer_report) for layer_report in report.layer_reports],
        "runtime_overhead_summary": _aggregate_runtime_overhead((report,)),
        "l0_l3_delta": {
            metric: _metric_delta(
                reports_by_layer=reports_by_layer,
                from_layer=BenchmarkLayer.L0,
                to_layer=BenchmarkLayer.L3,
                metric=metric,
            )
            for metric in (
                "llm_prompt_bytes",
                "raw_evidence_bytes_seen_by_llm",
                "prompt_visible_total_bytes",
                "control_bytes",
                "artifact_reuse_count",
                "validated_replay_count",
                "exact_replay_count",
                "skipped_step_count",
            )
        },
        "l1_l2_non_text_delta": {
            metric: _metric_delta(
                reports_by_layer=reports_by_layer,
                from_layer=BenchmarkLayer.L1,
                to_layer=BenchmarkLayer.L2,
                metric=metric,
            )
            for metric in (
                "llm_prompt_bytes",
                "raw_evidence_bytes_seen_by_llm",
                "prompt_visible_total_bytes",
                "semantic_state_transfer_count",
            )
        },
        "replay_admissibility_audit": dict(replay_audit),
        "round_evidence": [_case_round_evidence(case) for case in (l3_report.cases if l3_report else ())],
    }


def _continuous_collection_evidence_pack(
    *,
    report: BenchmarkContinuousCollectionReport,
) -> dict[str, object]:
    return {
        "schema_version": "statebus.continuous_collection_evidence_pack.v1",
        "suite_id": report.suite_id,
        "headline_scope": (
            "replay_admissible"
            if report.eligible_for_replay_headline
            else (
                "history_backed_only"
                if report.eligible_for_quality_headline
                and report.collection_summary.get("history_backed_only_family_count", 0.0) > 0.0
                else ("quality_only" if report.eligible_for_quality_headline else "not_eligible")
            )
        ),
        "collection_summary": dict(sorted(report.collection_summary.items())),
        "runtime_overhead_summary": _aggregate_runtime_overhead(report.family_reports),
        "family_evidence": [
            {
                "family_id": family_report.task_family,
                "headline_scope": str(family_report.metadata.get("headline_scope", "")),
                "quality_headline_eligible": bool(family_report.metadata.get("eligible_for_quality_headline", False)),
                "replay_headline_eligible": bool(family_report.metadata.get("eligible_for_replay_headline", False)),
                "waterfall_metrics": dict(sorted(family_report.waterfall_metrics.items())),
                "comparison_summary": dict(sorted(family_report.comparison_summary.items())),
                "l0_l3_delta": dict(family_report.evidence_pack.get("l0_l3_delta", {})),
                "l1_l2_non_text_delta": dict(family_report.evidence_pack.get("l1_l2_non_text_delta", {})),
                "runtime_overhead_summary": dict(family_report.evidence_pack.get("runtime_overhead_summary", {})),
                "replay_gate_reason": str(family_report.metadata.get("replay_gate_reason", "")),
                "report_path": family_report.report_path,
                "markdown_report_path": family_report.markdown_report_path,
            }
            for family_report in report.family_reports
        ],
        "admissibility_summary": dict(sorted(report.admissibility_summary.items())),
    }


def _continuous_suite_markdown(evidence_pack: dict[str, object]) -> str:
    lines = [
        f"# Continuous Evidence Pack: {evidence_pack['family_id']}",
        "",
        f"- headline_scope: `{evidence_pack['headline_scope']}`",
        f"- quality_headline_eligible: `{evidence_pack['quality_headline_eligible']}`",
        f"- replay_headline_eligible: `{evidence_pack['replay_headline_eligible']}`",
        f"- round_count: `{evidence_pack['round_count']}`",
        "",
        "## L0-L3 Delta",
    ]
    for key, value in dict(evidence_pack["l0_l3_delta"]).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## L1-L2 Non-Text Delta"])
    for key, value in dict(evidence_pack["l1_l2_non_text_delta"]).items():
        lines.append(f"- {key}: `{value}`")
    overhead = dict(evidence_pack.get("runtime_overhead_summary", {}))
    lines.extend(["", "## Runtime Overhead"])
    for bucket in overhead.get("top_driver_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- driver {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    for bucket in overhead.get("top_outer_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- outer {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    lines.extend(["", "## Layer Summaries", "| layer | quality | llm_prompt_bytes | raw_evidence | prompt_visible | semantic | replay |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
    for layer in evidence_pack["layer_summaries"]:
        layer_payload = dict(layer)
        replay_total = float(layer_payload.get("validated_replay_count", 0.0)) + float(
            layer_payload.get("exact_replay_count", 0.0)
        )
        lines.append(
            f"| {layer_payload['layer']} | {layer_payload['quality_floor_pass_count']} | "
            f"{layer_payload['llm_prompt_bytes']} | {layer_payload['raw_evidence_bytes_seen_by_llm']} | "
            f"{layer_payload['prompt_visible_total_bytes']} | {layer_payload['semantic_state_transfer_count']} | "
            f"{replay_total} |"
        )
    lines.extend(["", "## Round Evidence", "| round | task | replay_class | min_reuse | raw_evidence | prompt_visible | skipped | audit |", "| ---: | --- | --- | --- | ---: | ---: | ---: | --- |"])
    for case in evidence_pack["round_evidence"]:
        case_payload = dict(case)
        audit_path = dict(case_payload.get("audit_paths", {})).get("replay", "")
        lines.append(
            f"| {case_payload['round_number']} | {case_payload['task_id']} | {case_payload['replay_class']} | "
            f"{case_payload['minimum_reuse_class']} | {case_payload['raw_evidence_bytes_seen_by_llm']} | "
            f"{case_payload['prompt_visible_total_bytes']} | {case_payload['skipped_step_count']} | `{audit_path}` |"
        )
    return "\n".join(lines)


def _continuous_collection_markdown(evidence_pack: dict[str, object]) -> str:
    lines = [
        f"# Continuous Collection Evidence Pack: {evidence_pack['suite_id']}",
        "",
        f"- headline_scope: `{evidence_pack['headline_scope']}`",
        "",
        "## Collection Summary",
    ]
    for key, value in dict(evidence_pack["collection_summary"]).items():
        lines.append(f"- {key}: `{value}`")
    overhead = dict(evidence_pack.get("runtime_overhead_summary", {}))
    lines.extend(["", "## Runtime Overhead"])
    for bucket in overhead.get("top_driver_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- driver {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    for bucket in overhead.get("top_outer_stage_buckets", []):
        bucket_payload = dict(bucket)
        lines.append(f"- outer {bucket_payload['bucket']}: `{bucket_payload['stage_ms']}` ms")
    lines.extend(["", "## Family Evidence", "| family | scope | quality | replay | raw L0-L3 delta | prompt L0-L3 delta | report |", "| --- | --- | --- | --- | ---: | ---: | --- |"])
    for family in evidence_pack["family_evidence"]:
        family_payload = dict(family)
        l0_l3 = dict(family_payload.get("l0_l3_delta", {}))
        lines.append(
            f"| {family_payload['family_id']} | {family_payload['headline_scope']} | "
            f"{family_payload['quality_headline_eligible']} | {family_payload['replay_headline_eligible']} | "
            f"{l0_l3.get('raw_evidence_bytes_seen_by_llm', 0.0)} | {l0_l3.get('llm_prompt_bytes', 0.0)} | "
            f"`{family_payload['report_path']}` |"
        )
    return "\n".join(lines)


def run_continuous_benchmark_family(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    layer: BenchmarkLayer,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    profile_override: BenchmarkLayerProfile | None = None,
    smoke_config_override: SmokeLayerConfig | None = None,
    report_layer_label: str | None = None,
    enforce_expected_metric_effects: bool = True,
    metadata_extra: dict[str, object] | None = None,
    persistence_profile: str = "audit_full",
) -> BenchmarkFamilyReport:
    if family.family_id not in SUPPORTED_CONTINUOUS_FAMILY_IDS:
        raise ValueError(
            "continuous execution is only implemented for "
            f"{', '.join(sorted(SUPPORTED_CONTINUOUS_FAMILY_IDS))}, got {family.family_id}"
        )

    profile = profile_override or LAYER_PROFILES[layer]
    layer_workspace_root = _prepare_dir(workspace_root)
    layer_runtime_root = _prepare_dir(runtime_root)
    base_smoke_config = smoke_config_override or LAYER_SMOKE_CONFIGS[layer]
    smoke_config = SmokeLayerConfig(
        **{
            **base_smoke_config.__dict__,
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "persistence_profile": persistence_profile,
        }
    )
    history_runtime_root_by_round: dict[int, Path] = {}
    raw_cases: list[BenchmarkCaseReport] = []

    for round_ in family.rounds:
        sample = _continuous_sample(round_)
        round_runtime_root = layer_runtime_root / sample.task_id
        history_runtime_roots: tuple[Path, ...] = tuple(
            history_runtime_root_by_round[dep]
            for dep in sample.depends_on_rounds
            if dep in history_runtime_root_by_round
        )
        smoke = run_smoke(
            workspace_root=layer_workspace_root,
            runtime_root=round_runtime_root,
            socket_path=socket_path.with_name(
                f"{socket_path.stem}-{layer.value.lower()}-{sample.round_number:02d}{socket_path.suffix}"
            ),
            request_text=sample.request_text,
            canonical_task_spec=sample.canonical_task_spec,
            task_id=sample.task_id,
            layer_config=smoke_config,
            expected_facts=sample.expected_facts,
            history_runtime_roots=history_runtime_roots,
            seed_replay_memory=False,
        )
        history_runtime_root_by_round[sample.round_number] = round_runtime_root
        raw_cases.append(
            _case_from_smoke(
                smoke=smoke,
                sample=sample,
                layer=layer,
                enforce_expected_metric_effects=enforce_expected_metric_effects,
            )
        )

    previous_layer_cases_by_task_id: dict[str, BenchmarkCaseReport] = {}
    layer_order = list(BenchmarkLayer)
    previous_layer: BenchmarkLayer | None = None
    layer_index = layer_order.index(layer)
    if layer_index > 0:
        previous_layer = layer_order[layer_index - 1]
    if previous_layer is not None:
        previous_report_json = runtime_root.parent / previous_layer.value / "benchmark_reports" / f"{suite_id}-{previous_layer.value}.json"
        if previous_report_json.exists():
            report_payload = json.loads(previous_report_json.read_text(encoding="utf-8"))
            for case_payload in report_payload.get("cases", []):
                task_id = str(case_payload.get("task_id", "")).strip()
                if not task_id:
                    continue
                previous_layer_cases_by_task_id[task_id] = BenchmarkCaseReport(
                    task_id=task_id,
                    task_family=str(case_payload.get("task_family", "")),
                    quality_floor=QualityFloorResult(**dict(case_payload.get("quality_floor", {}))),
                    replay_class=str(case_payload.get("replay_class", "")),
                    telemetry_event_count=int(case_payload.get("telemetry_event_count", 0)),
                    output_artifact_hash=str(case_payload.get("output_artifact_hash", "")),
                    output_artifact_path=str(case_payload.get("output_artifact_path", "")),
                    workspace_root=str(case_payload.get("workspace_root", "")),
                    session_state=str(case_payload.get("session_state", "")),
                    comparison_tags=tuple(str(item) for item in case_payload.get("comparison_tags", [])),
                    audit_paths={str(k): str(v) for k, v in dict(case_payload.get("audit_paths", {})).items()},
                    audit_summary=dict(case_payload.get("audit_summary", {})),
                    metrics={str(k): float(v) for k, v in dict(case_payload.get("metrics", {})).items()},
                )
    cases = (
        [
            _apply_case_metric_contracts(
                current=case,
                previous_layer_case=previous_layer_cases_by_task_id.get(case.task_id),
            )
            for case in raw_cases
        ]
        if enforce_expected_metric_effects
        else raw_cases
    )

    aggregated_metrics = {
        "case_count": float(len(cases)),
        "quality_floor_pass_count": float(sum(1 for case in cases if case.quality_floor.quality_floor_pass)),
        "telemetry_event_count": float(sum(case.telemetry_event_count for case in cases)),
    }
    telemetry_summary: dict[str, float] = {}
    for case in cases:
        for key, value in case.metrics.items():
            telemetry_summary[key] = telemetry_summary.get(key, 0.0) + float(value)
    replay_class_distribution: dict[str, float] = {}
    for case in cases:
        replay_class_distribution[case.replay_class] = replay_class_distribution.get(case.replay_class, 0.0) + 1.0
    quality_floor_breakdown = {
        "deterministic_checks_passed_count": float(
            sum(1 for case in cases if case.quality_floor.deterministic_checks_passed)
        ),
        "fact_coverage_passed_count": float(sum(1 for case in cases if case.quality_floor.fact_coverage_passed)),
        "quality_floor_pass_count": aggregated_metrics["quality_floor_pass_count"],
    }
    report_label = report_layer_label or layer.value
    metadata = {
        "benchmark_tier": "formal",
        "claim_level": "first_pass",
        "family_id": family.family_id,
        "claim_tier": family.claim_tier,
        "manifest_path": family.manifest_path,
        "display_name": family.display_name,
        "round_count": family.round_count,
        "dataset_ids": [dataset.dataset_id for dataset in family.datasets],
        "reuse_edge_count": sum(len(round_.depends_on_rounds) for round_ in family.rounds),
        "continuous_execution": True,
        "history_backed_replay_enabled": layer == BenchmarkLayer.L3,
        "role_path_mode": role_path_mode,
        "embedding_mode": embedding_mode,
        "layer_contract_gate_enabled": enforce_expected_metric_effects and layer in {BenchmarkLayer.L2, BenchmarkLayer.L3},
    }
    if metadata_extra:
        metadata.update(metadata_extra)
    report_path = layer_runtime_root / "benchmark_reports" / f"{suite_id}-{report_label}.json"
    report = BenchmarkFamilyReport(
        suite_id=suite_id,
        layer=layer,
        task_family=family.family_id,
        profile=profile,
        cases=tuple(cases),
        aggregated_metrics=aggregated_metrics,
        telemetry_summary=telemetry_summary,
        replay_class_distribution=replay_class_distribution,
        quality_floor_breakdown=quality_floor_breakdown,
        metadata=metadata,
        report_path=str(report_path),
    )
    write_json_report(report_path, family_report_to_dict(report))
    return report


def run_continuous_text_semantic_selection_family(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    persistence_profile: str = "audit_full",
) -> BenchmarkFamilyReport:
    return run_continuous_benchmark_family(
        family=family,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        suite_id=suite_id,
        layer=BenchmarkLayer.L2,
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        profile_override=CONTINUOUS_TEXT_SEMANTIC_SELECTION_PROFILE,
        smoke_config_override=CONTINUOUS_TEXT_SEMANTIC_SELECTION_SMOKE_CONFIG,
        report_layer_label="T2",
        enforce_expected_metric_effects=False,
        metadata_extra={
            "baseline_kind": "internal_text_same_semantic_selection",
            "carrier_kind": "text_collaboration_same_selected_evidence",
            "claim_level": "diagnostic",
            "comparison_contract": "same_mainline_text_handoff_semantic_selection_without_state_ref",
            "diagnostic_claim_scope": "isolates_semantic_selection_from_non_text_state_transfer",
            "formal_comparator_eligible": False,
            "semantic_state_transfer_enabled": False,
            "uses_semantic_state_ref": False,
        },
        persistence_profile=persistence_profile,
    )


def run_continuous_benchmark_suite(
    *,
    family: ContinuousTaskFamily,
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    persistence_profile: str = "audit_full",
) -> BenchmarkSuiteReport:
    layer_reports = tuple(
        run_continuous_benchmark_family(
            family=family,
            workspace_root=workspace_root / layer.value,
            runtime_root=runtime_root / layer.value,
            socket_path=socket_path.with_name(f"{socket_path.stem}-{layer.value.lower()}{socket_path.suffix}"),
            suite_id=suite_id,
            layer=layer,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            persistence_profile=persistence_profile,
        )
        for layer in BenchmarkLayer
    )
    suite_stub = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
    )
    quality_headline_eligible = _continuous_quality_headline_eligible(suite_stub)
    replay_audit = _continuous_replay_audit(family=family, report=suite_stub)
    replay_headline_eligible = bool(replay_audit["eligible_for_replay_headline"])
    headline_scope = _continuous_headline_scope(suite_stub, replay_audit=replay_audit)
    replay_summary_counts = _replay_audit_summary_counts(replay_audit)
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    markdown_report_path = runtime_root / "benchmark_reports" / f"{suite_id}.evidence.md"
    evidence_stub = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
    )
    evidence_pack = _continuous_suite_evidence_pack(
        family=family,
        report=evidence_stub,
        replay_audit=replay_audit,
    )
    report = BenchmarkSuiteReport(
        suite_id=suite_id,
        task_family=family.family_id,
        layer_reports=layer_reports,
        waterfall_metrics={
            "L0_case_count": float(len(layer_reports[0].cases)),
            "L1_control_bytes": layer_reports[1].telemetry_summary.get("control_bytes", 0.0),
            "L2_semantic_state_transfer_count": layer_reports[2].telemetry_summary.get(
                "semantic_state_transfer_count", 0.0
            ),
            "L3_history_runtime_root_count": layer_reports[3].telemetry_summary.get(
                "history_runtime_root_count", 0.0
            ),
            "L3_artifact_reuse_count": layer_reports[3].telemetry_summary.get("artifact_reuse_count", 0.0),
            "L3_reuse_gain": layer_reports[3].telemetry_summary.get("reuse_gain", 0.0),
            "L3_history_reuse_gain": layer_reports[3].telemetry_summary.get("history_reuse_gain", 0.0),
            "L3_history_step_reduction_count": layer_reports[3].telemetry_summary.get(
                "history_step_reduction_count", 0.0
            ),
        },
        comparison_summary={
            "layer_count": float(len(layer_reports)),
            "successful_layer_count": float(sum(1 for report_ in layer_reports if not report_.missing_reason)),
            "round_count": float(family.round_count),
            "reuse_edge_count": float(sum(len(round_.depends_on_rounds) for round_ in family.rounds)),
            **replay_summary_counts,
        },
        evidence_pack=evidence_pack,
        metadata={
            "benchmark_tier": "formal",
            "claim_level": "first_pass",
            "family_id": family.family_id,
            "claim_tier": family.claim_tier,
            "manifest_path": family.manifest_path,
            "continuous_execution": True,
            "eligible_for_quality_headline": quality_headline_eligible,
            "eligible_for_replay_headline": replay_headline_eligible,
            "replay_gate_reason": str(replay_audit.get("gate_reason", "")),
            "headline_scope": headline_scope,
            "replay_admissibility_audit": replay_audit,
            "supported_continuous_execution_families": _supported_continuous_family_ids(),
        },
        family_case_count=family.round_count,
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    write_json_report(report_path, suite_report_to_dict(report))
    write_markdown_report(markdown_report_path, _continuous_suite_markdown(evidence_pack))
    return report


def run_continuous_benchmark_collection(
    *,
    families: tuple[ContinuousTaskFamily, ...],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str,
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    collection_scope: str = "formal_continuous_task_families",
    persistence_profile: str = "audit_full",
) -> BenchmarkContinuousCollectionReport:
    if not families:
        raise ValueError("continuous benchmark collection requires at least one family")

    family_reports: list[BenchmarkSuiteReport] = []
    for family in families:
        family_slug = family.family_id.removesuffix("_v1")
        family_reports.append(
            run_continuous_benchmark_suite(
                family=family,
                workspace_root=workspace_root / family_slug,
                runtime_root=runtime_root / family_slug,
                socket_path=socket_path.with_name(f"{socket_path.stem}-{family_slug}{socket_path.suffix}"),
                suite_id=f"{suite_id}-{family_slug}",
                role_path_mode=role_path_mode,
                embedding_mode=embedding_mode,
                persistence_profile=persistence_profile,
            )
        )

    replay_summary_counts_by_family = [
        _replay_audit_summary_counts(dict(report.metadata.get("replay_admissibility_audit", {})))
        for report in family_reports
    ]
    collection_summary = {
        "family_count": float(len(family_reports)),
        "continuous_round_count": float(sum(report.family_case_count for report in family_reports)),
        "successful_family_count": float(sum(1 for report in family_reports if report.layer_reports)),
        "quality_headline_eligible_family_count": float(
            sum(
                1
                for report in family_reports
                if _continuous_quality_headline_eligible(report)
            )
        ),
        "replay_headline_eligible_family_count": float(
            sum(1 for report in family_reports if bool(report.metadata.get("eligible_for_replay_headline", False)))
        ),
        "history_backed_only_family_count": float(
            sum(1 for report in family_reports if _continuous_headline_scope(report, replay_audit=report.metadata.get("replay_admissibility_audit")) == "history_backed_only")
        ),
        "L2_semantic_state_transfer_count": float(
            sum(report.waterfall_metrics.get("L2_semantic_state_transfer_count", 0.0) for report in family_reports)
        ),
        "L3_artifact_reuse_count": float(
            sum(report.waterfall_metrics.get("L3_artifact_reuse_count", 0.0) for report in family_reports)
        ),
        "L3_reuse_gain": float(sum(report.waterfall_metrics.get("L3_reuse_gain", 0.0) for report in family_reports)),
        "L3_history_reuse_gain": float(
            sum(report.waterfall_metrics.get("L3_history_reuse_gain", 0.0) for report in family_reports)
        ),
        "L3_history_step_reduction_count": float(
            sum(report.waterfall_metrics.get("L3_history_step_reduction_count", 0.0) for report in family_reports)
        ),
        "history_backed_reuse_count": float(
            sum(
                layer_report.telemetry_summary.get("history_artifact_reuse_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "validated_replay_count": float(
            sum(
                layer_report.telemetry_summary.get("validated_replay_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "exact_replay_count": float(
            sum(
                layer_report.telemetry_summary.get("exact_replay_count", 0.0)
                for report in family_reports
                for layer_report in report.layer_reports
            )
        ),
        "history_target_round_count": float(
            sum(summary["history_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_observed_reuse_round_count": float(
            sum(summary["history_observed_reuse_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_missing_target_round_count": float(
            sum(summary["history_missing_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "history_additional_reuse_round_count": float(
            sum(summary["history_additional_reuse_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_target_round_count": float(
            sum(summary["replay_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_observed_round_count": float(
            sum(summary["replay_observed_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_missing_target_round_count": float(
            sum(summary["replay_missing_target_round_count"] for summary in replay_summary_counts_by_family)
        ),
        "replay_unexpected_round_count": float(
            sum(summary["replay_unexpected_round_count"] for summary in replay_summary_counts_by_family)
        ),
    }
    admissibility_summary = {
        report.task_family: {
            "L3_replay_class_distribution": dict(
                next(
                    layer_report.replay_class_distribution
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            "L3_history_artifact_reuse_count": float(
                next(
                    layer_report.telemetry_summary.get("history_artifact_reuse_count", 0.0)
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            "L3_history_reuse_gain": float(
                next(
                    layer_report.telemetry_summary.get("history_reuse_gain", 0.0)
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            "L3_history_step_reduction_count": float(
                next(
                    layer_report.telemetry_summary.get("history_step_reduction_count", 0.0)
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            "L3_validated_replay_count": float(
                next(
                    layer_report.telemetry_summary.get("validated_replay_count", 0.0)
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            "L3_exact_replay_count": float(
                next(
                    layer_report.telemetry_summary.get("exact_replay_count", 0.0)
                    for layer_report in report.layer_reports
                    if layer_report.layer == BenchmarkLayer.L3
                )
            ),
            **_replay_audit_summary_counts(dict(report.metadata.get("replay_admissibility_audit", {}))),
            "eligible_for_replay_headline": bool(report.metadata.get("eligible_for_replay_headline", False)),
            "headline_scope": _continuous_headline_scope(
                report,
                replay_audit=report.metadata.get("replay_admissibility_audit"),
            ),
            "replay_gate_reason": str(report.metadata.get("replay_gate_reason", "")),
            "replay_admissibility_audit": dict(report.metadata.get("replay_admissibility_audit", {})),
        }
        for report in family_reports
    }
    report_path = runtime_root / "benchmark_reports" / f"{suite_id}.json"
    markdown_report_path = runtime_root / "benchmark_reports" / f"{suite_id}.evidence.md"
    report_stub = BenchmarkContinuousCollectionReport(
        suite_id=suite_id,
        family_reports=tuple(family_reports),
        collection_summary=collection_summary,
        admissibility_summary=admissibility_summary,
        metadata={
            "benchmark_tier": "formal",
            "claim_level": "first_pass",
            "continuous_execution": True,
            "family_count": len(family_reports),
            "supported_continuous_execution_families": [family.family_id for family in families],
            "role_path_mode": role_path_mode,
            "embedding_mode": embedding_mode,
            "collection_scope": collection_scope,
        },
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    evidence_pack = _continuous_collection_evidence_pack(report=report_stub)
    report = BenchmarkContinuousCollectionReport(
        suite_id=suite_id,
        family_reports=tuple(family_reports),
        collection_summary=collection_summary,
        admissibility_summary=admissibility_summary,
        evidence_pack=evidence_pack,
        metadata=report_stub.metadata,
        report_path=str(report_path),
        markdown_report_path=str(markdown_report_path),
    )
    write_json_report(report_path, continuous_collection_report_to_dict(report))
    write_markdown_report(markdown_report_path, _continuous_collection_markdown(evidence_pack))
    return report
