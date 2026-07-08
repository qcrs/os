from __future__ import annotations

from pathlib import Path

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkComparatorModeReport,
    BenchmarkComparatorSuiteReport,
    BenchmarkFamilyReport,
    BenchmarkSuiteReport,
    QualityFloorResult,
)
from v2.utils import stable_json_dumps


def quality_floor_to_dict(result: QualityFloorResult) -> dict[str, object]:
    return {
        "quality_floor_pass": result.quality_floor_pass,
        "deterministic_checks_passed": result.deterministic_checks_passed,
        "fact_coverage_passed": result.fact_coverage_passed,
        "llm_judge_passed": result.llm_judge_passed,
        "quality_floor_fail_reason": result.quality_floor_fail_reason,
        "schema_version": result.schema_version,
    }


def case_report_to_dict(case: BenchmarkCaseReport) -> dict[str, object]:
    return {
        "task_id": case.task_id,
        "task_family": case.task_family,
        "replay_class": case.replay_class,
        "telemetry_event_count": case.telemetry_event_count,
        "output_artifact_hash": case.output_artifact_hash,
        "output_artifact_path": case.output_artifact_path,
        "workspace_root": case.workspace_root,
        "session_state": case.session_state,
        "comparison_tags": list(case.comparison_tags),
        "audit_paths": dict(sorted(case.audit_paths.items())),
        "audit_summary": dict(sorted(case.audit_summary.items())),
        "quality_floor": quality_floor_to_dict(case.quality_floor),
        "metrics": dict(sorted(case.metrics.items())),
    }


def family_report_to_dict(report: BenchmarkFamilyReport) -> dict[str, object]:
    payload = {
        "suite_id": report.suite_id,
        "layer": report.layer.value,
        "task_family": report.task_family,
        "metadata": dict(sorted(report.metadata.items())),
        "report_path": report.report_path,
        "profile": {
            "description": report.profile.description,
            "structured_control_enabled": report.profile.structured_control_enabled,
            "semantic_pruning_enabled": report.profile.semantic_pruning_enabled,
            "replay_enabled": report.profile.replay_enabled,
            "multi_attempt_enabled": report.profile.multi_attempt_enabled,
            "force_first_attempt_trap": report.profile.force_first_attempt_trap,
            "hermetic_runtime_root": report.profile.hermetic_runtime_root,
        },
        "eligible_for_headline": report.eligible_for_headline,
        "missing_reason": report.missing_reason,
        "aggregated_metrics": dict(sorted(report.aggregated_metrics.items())),
        "telemetry_summary": dict(sorted(report.telemetry_summary.items())),
        "replay_class_distribution": dict(sorted(report.replay_class_distribution.items())),
        "quality_floor_breakdown": dict(sorted(report.quality_floor_breakdown.items())),
        "cases": [case_report_to_dict(case) for case in report.cases],
    }
    if "eligible_for_replay_headline" in report.metadata:
        payload["eligible_for_quality_headline"] = report.eligible_for_headline
        payload["eligible_for_replay_headline"] = bool(report.metadata.get("eligible_for_replay_headline", False))
        payload["headline_scope"] = str(report.metadata.get("headline_scope", "quality_only"))
    return payload


def suite_report_to_dict(report: BenchmarkSuiteReport) -> dict[str, object]:
    l3_report = report.layer_reports[3] if len(report.layer_reports) > 3 else None
    payload = {
        "suite_id": report.suite_id,
        "task_family": report.task_family,
        "metadata": dict(sorted(report.metadata.items())),
        "report_path": report.report_path,
        "markdown_report_path": report.markdown_report_path,
        "family_case_count": report.family_case_count,
        "waterfall_metrics": dict(sorted(report.waterfall_metrics.items())),
        "comparison_summary": dict(sorted(report.comparison_summary.items())),
        "evidence_pack": dict(report.evidence_pack),
        "layers": [family_report_to_dict(layer_report) for layer_report in report.layer_reports],
    }
    if l3_report is not None:
        payload["L3_case_count"] = l3_report.aggregated_metrics.get("case_count", report.family_case_count)
        payload["L3_quality_pass_count"] = l3_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
    if "state_pool_mode_used" in report.metadata:
        payload["state_pool_mode_used"] = report.metadata["state_pool_mode_used"]
        payload["state_pool_mode_requested"] = report.metadata.get("state_pool_mode_requested", "")
        payload["memfd_transfer_count"] = report.metadata.get("memfd_transfer_count", 0.0)
        payload["memfd_publish_count"] = report.metadata.get("memfd_publish_count", 0.0)
        payload["memfd_bytes_transferred"] = report.metadata.get("memfd_bytes_transferred", 0.0)
    if "formal_task_families" in report.metadata:
        payload["families"] = list(report.metadata.get("formal_task_families", []))
        payload["family_count"] = report.metadata.get("formal_task_family_count", len(payload["families"]))
    if bool(report.metadata.get("formal_text_protocol_benchmark", False)):
        payload["formal_text_protocol_benchmark"] = True
        for key in (
            "text_L0_total_tokens",
            "text_L0_prompt_tokens",
            "text_L0_prompt_bytes",
            "text_L0_control_bytes",
            "text_L0_quality_pass_count",
            "protocol_L3_total_tokens",
            "protocol_L3_prompt_tokens",
            "protocol_L3_prompt_bytes",
            "protocol_L3_control_bytes",
            "protocol_L3_quality_pass_count",
            "protocol_vs_text_token_delta",
            "protocol_vs_text_prompt_token_delta",
            "protocol_vs_text_prompt_bytes_delta",
            "protocol_vs_text_control_bytes_delta",
            "protocol_vs_text_quality_pass_delta",
        ):
            if key in report.comparison_summary:
                payload[key] = report.comparison_summary[key]
    if "eligible_for_replay_headline" in report.metadata:
        payload["eligible_for_quality_headline"] = bool(report.metadata.get("eligible_for_quality_headline", False))
        payload["eligible_for_replay_headline"] = bool(report.metadata.get("eligible_for_replay_headline", False))
        payload["headline_scope"] = str(report.metadata.get("headline_scope", "quality_only"))
        payload["replay_gate_reason"] = str(report.metadata.get("replay_gate_reason", ""))
        payload["replay_admissibility_audit"] = dict(report.metadata.get("replay_admissibility_audit", {}))
    return payload


def continuous_collection_report_to_dict(report: BenchmarkContinuousCollectionReport) -> dict[str, object]:
    history_backed_only_family_count = int(report.collection_summary.get("history_backed_only_family_count", 0.0))
    return {
        "suite_id": report.suite_id,
        "report_path": report.report_path,
        "eligible_for_headline": report.eligible_for_headline,
        "eligible_for_quality_headline": report.eligible_for_quality_headline,
        "eligible_for_replay_headline": report.eligible_for_replay_headline,
        "headline_scope": (
            "replay_admissible"
            if report.eligible_for_replay_headline
            else (
                "history_backed_only"
                if report.eligible_for_quality_headline and history_backed_only_family_count > 0
                else ("quality_only" if report.eligible_for_quality_headline else "not_eligible")
            )
        ),
        "metadata": dict(sorted(report.metadata.items())),
        "markdown_report_path": report.markdown_report_path,
        "collection_summary": dict(sorted(report.collection_summary.items())),
        "admissibility_summary": dict(sorted(report.admissibility_summary.items())),
        "evidence_pack": dict(report.evidence_pack),
        "family_reports": [suite_report_to_dict(family_report) for family_report in report.family_reports],
    }


def comparator_mode_report_to_dict(report: BenchmarkComparatorModeReport) -> dict[str, object]:
    return {
        "suite_id": report.suite_id,
        "role_path_mode": report.role_path_mode,
        "task_family": report.task_family,
        "benchmark_tier": report.benchmark_tier,
        "claim_level": report.claim_level,
        "delta_direction": "statebus_minus_external",
        "eligible_for_headline": report.eligible_for_headline,
        "comparison_valid": report.comparison_valid,
        "invalid_reason": report.invalid_reason,
        "missing_reason": report.missing_reason,
        "comparison_summary": dict(sorted(report.comparison_summary.items())),
        "headline_metrics": dict(sorted(report.headline_metrics.items())),
        "debug_metrics": dict(sorted(report.debug_metrics.items())),
        "fairness_manifest": dict(sorted(report.fairness_manifest.items())),
        "external_report": family_report_to_dict(report.external_report),
        "statebus_report": family_report_to_dict(report.statebus_report),
        "report_path": report.report_path,
        "markdown_report_path": report.markdown_report_path,
    }


def comparator_suite_report_to_dict(report: BenchmarkComparatorSuiteReport) -> dict[str, object]:
    return {
        "suite_id": report.suite_id,
        "task_family": report.task_family,
        "benchmark_tier": report.benchmark_tier,
        "claim_level": report.claim_level,
        "metadata": dict(sorted(report.metadata.items())),
        "comparison_summary": dict(sorted(report.comparison_summary.items())),
        "report_path": report.report_path,
        "markdown_report_path": report.markdown_report_path,
        "mode_reports": [comparator_mode_report_to_dict(mode_report) for mode_report in report.mode_reports],
    }


def write_json_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


def write_markdown_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
