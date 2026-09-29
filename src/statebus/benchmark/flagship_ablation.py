from __future__ import annotations

from pathlib import Path

from statebus.benchmark.comparator_runner import compare_fixed_answer_with_external
from statebus.benchmark.continuous_runner import (
    run_continuous_benchmark_collection,
    run_continuous_text_semantic_selection_family,
)
from statebus.benchmark.continuous_task_family import ContinuousTaskFamily
from statebus.benchmark.fixed_answer_runner import (
    FixedAnswerSample,
    run_fixed_answer_internal_carrier_compare_suite,
    run_fixed_answer_suite,
    run_fixed_answer_text_semantic_selection_family,
)
from statebus.benchmark.models import (
    BenchmarkContinuousCollectionReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkSuiteReport,
)
from statebus.benchmark.reporting import write_json_report, write_markdown_report


def _metric(report: BenchmarkFamilyReport, key: str) -> float:
    if key in report.telemetry_summary:
        return float(report.telemetry_summary[key])
    if key in report.aggregated_metrics:
        return float(report.aggregated_metrics[key])
    return 0.0


_COST_SUMMARY_KEYS = (
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "llm_wall_ms",
    "prompt_scaffolding_bytes_total",
    "control_bytes",
    "runtime_driver_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_bundle_write_stage_ms",
    "semantic_state_ref_count",
    "shared_memory_publish_count",
    "mmap_publish_count",
    "memory_commit_count",
    "memory_match_count",
    "memory_candidate_count",
    "memory_ref_count",
    "codeact_plan_stage_count",
    "codeact_plan_action_count",
    "codeact_execution_stage_ms",
    "role_prompt_slice_artifact_count",
    "role_prompt_slice_artifact_bytes_total",
)


def _cost_summary(report: BenchmarkFamilyReport) -> dict[str, float]:
    return {key: _metric(report, key) for key in _COST_SUMMARY_KEYS}


def _layer_by_name(report: BenchmarkSuiteReport, layer: BenchmarkLayer) -> BenchmarkFamilyReport:
    for layer_report in report.layer_reports:
        if layer_report.layer == layer:
            return layer_report
    raise ValueError(f"missing layer {layer.value} in {report.suite_id}")


def _delta(from_report: BenchmarkFamilyReport, to_report: BenchmarkFamilyReport, key: str) -> float:
    return _metric(to_report, key) - _metric(from_report, key)


def _pct_reduction(from_value: float, to_value: float) -> float:
    if from_value <= 0.0:
        return 0.0
    return max((from_value - to_value) / from_value * 100.0, 0.0)


def _sub_socket(socket_path: Path, name: str) -> Path:
    # AF_UNIX paths are short on Linux; keep flagship child sockets compact
    # because family/layer runners append their own suffixes.
    return socket_path.with_name(f"fg-{name}.sock")


def _family_evidence(
    *,
    family_report: BenchmarkSuiteReport,
    text_semantic_report: BenchmarkFamilyReport | None,
) -> dict[str, object]:
    l0 = _layer_by_name(family_report, BenchmarkLayer.L0)
    l1 = _layer_by_name(family_report, BenchmarkLayer.L1)
    l2 = _layer_by_name(family_report, BenchmarkLayer.L2)
    l3 = _layer_by_name(family_report, BenchmarkLayer.L3)
    t2_payload: dict[str, object] = {}
    if text_semantic_report is not None:
        t2_payload = {
            "report_path": text_semantic_report.report_path,
            "quality_floor_pass_count": _metric(text_semantic_report, "quality_floor_pass_count"),
            **_cost_summary(text_semantic_report),
            "llm_prompt_bytes": _metric(text_semantic_report, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(text_semantic_report, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(text_semantic_report, "prompt_visible_total_bytes"),
            "semantic_state_transfer_count": _metric(text_semantic_report, "semantic_state_transfer_count"),
            "semantic_selection_text_delta_vs_l1": {
                "llm_prompt_bytes": _delta(l1, text_semantic_report, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _delta(
                    l1,
                    text_semantic_report,
                    "raw_evidence_bytes_seen_by_llm",
                ),
                "prompt_visible_total_bytes": _delta(l1, text_semantic_report, "prompt_visible_total_bytes"),
            },
            "non_text_transfer_delta_l2_vs_text_same_selection": {
                "llm_prompt_bytes": _delta(text_semantic_report, l2, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _delta(
                    text_semantic_report,
                    l2,
                    "raw_evidence_bytes_seen_by_llm",
                ),
                "prompt_visible_total_bytes": _delta(text_semantic_report, l2, "prompt_visible_total_bytes"),
                "semantic_state_transfer_count": _delta(
                    text_semantic_report,
                    l2,
                    "semantic_state_transfer_count",
                ),
            },
        }
    return {
        "family_id": family_report.task_family,
        "report_path": family_report.report_path,
        "headline_scope": str(family_report.metadata.get("headline_scope", "")),
        "quality_headline_eligible": bool(family_report.metadata.get("eligible_for_quality_headline", False)),
        "replay_headline_eligible": bool(family_report.metadata.get("eligible_for_replay_headline", False)),
        "l0_internal_pure_text": {
            "report_path": l0.report_path,
            "quality_floor_pass_count": _metric(l0, "quality_floor_pass_count"),
            **_cost_summary(l0),
            "llm_prompt_bytes": _metric(l0, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(l0, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(l0, "prompt_visible_total_bytes"),
            "semantic_state_transfer_count": _metric(l0, "semantic_state_transfer_count"),
        },
        "l1_structured_full_evidence": {
            "report_path": l1.report_path,
            "quality_floor_pass_count": _metric(l1, "quality_floor_pass_count"),
            **_cost_summary(l1),
            "llm_prompt_bytes": _metric(l1, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(l1, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(l1, "prompt_visible_total_bytes"),
            "semantic_state_transfer_count": _metric(l1, "semantic_state_transfer_count"),
            "control_delta_vs_l0": _delta(l0, l1, "control_bytes"),
            "prompt_scaffolding_delta_vs_l0": _delta(l0, l1, "prompt_scaffolding_bytes_total"),
        },
        "t2_text_same_semantic_selection": t2_payload,
        "l2_structured_semantic_state": {
            "report_path": l2.report_path,
            "quality_floor_pass_count": _metric(l2, "quality_floor_pass_count"),
            **_cost_summary(l2),
            "llm_prompt_bytes": _metric(l2, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(l2, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(l2, "prompt_visible_total_bytes"),
            "semantic_state_transfer_count": _metric(l2, "semantic_state_transfer_count"),
            "raw_evidence_reduction_pct_vs_l1": _pct_reduction(
                _metric(l1, "raw_evidence_bytes_seen_by_llm"),
                _metric(l2, "raw_evidence_bytes_seen_by_llm"),
            ),
            "prompt_visible_reduction_pct_vs_l1": _pct_reduction(
                _metric(l1, "prompt_visible_total_bytes"),
                _metric(l2, "prompt_visible_total_bytes"),
            ),
        },
        "l3_memory_replay": {
            "report_path": l3.report_path,
            "quality_floor_pass_count": _metric(l3, "quality_floor_pass_count"),
            **_cost_summary(l3),
            "llm_prompt_bytes": _metric(l3, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(l3, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(l3, "prompt_visible_total_bytes"),
            "artifact_reuse_count": _metric(l3, "artifact_reuse_count"),
            "history_step_reduction_count": _metric(l3, "history_step_reduction_count"),
            "validated_replay_count": _metric(l3, "validated_replay_count"),
            "exact_replay_count": _metric(l3, "exact_replay_count"),
            "skipped_step_count": _metric(l3, "skipped_step_count"),
            "raw_evidence_reduction_pct_vs_l0": _pct_reduction(
                _metric(l0, "raw_evidence_bytes_seen_by_llm"),
                _metric(l3, "raw_evidence_bytes_seen_by_llm"),
            ),
            "prompt_visible_reduction_pct_vs_l0": _pct_reduction(
                _metric(l0, "prompt_visible_total_bytes"),
                _metric(l3, "prompt_visible_total_bytes"),
            ),
        },
    }


def _collection_evidence(
    *,
    report: BenchmarkContinuousCollectionReport,
    text_semantic_reports: tuple[BenchmarkFamilyReport, ...],
) -> list[dict[str, object]]:
    text_by_family = {text_report.task_family: text_report for text_report in text_semantic_reports}
    return [
        _family_evidence(
            family_report=family_report,
            text_semantic_report=text_by_family.get(family_report.task_family),
        )
        for family_report in report.family_reports
    ]


def _non_text_state_stress_summary(
    *,
    continuous_evidence: list[dict[str, object]],
    continuous_replay_evidence: list[dict[str, object]],
) -> dict[str, object]:
    families: list[dict[str, object]] = []
    for group_name, evidence_items in (
        ("continuous", continuous_evidence),
        ("continuous_replay", continuous_replay_evidence),
    ):
        for item in evidence_items:
            family = dict(item)
            l2 = dict(family.get("l2_structured_semantic_state", {}))
            t2 = dict(family.get("t2_text_same_semantic_selection", {}))
            delta = dict(t2.get("non_text_transfer_delta_l2_vs_text_same_selection", {}))
            llm_prompt_delta = float(delta.get("llm_prompt_bytes", 0.0))
            prompt_visible_delta = float(delta.get("prompt_visible_total_bytes", 0.0))
            raw_evidence_delta = float(delta.get("raw_evidence_bytes_seen_by_llm", 0.0))
            l2_transfer_count = float(l2.get("semantic_state_transfer_count", 0.0))
            t2_transfer_count = float(t2.get("semantic_state_transfer_count", 0.0))
            llm_prompt_saved = max(-llm_prompt_delta, 0.0)
            prompt_visible_saved = max(-prompt_visible_delta, 0.0)
            stress_fail_reasons: list[str] = []
            if not bool(family.get("quality_headline_eligible", False)):
                stress_fail_reasons.append("quality_headline_not_eligible")
            if group_name == "continuous_replay" and not bool(family.get("replay_headline_eligible", False)):
                stress_fail_reasons.append("replay_headline_not_eligible")
            if l2_transfer_count <= 0.0:
                stress_fail_reasons.append("semantic_state_transfer_missing")
            if t2_transfer_count != 0.0:
                stress_fail_reasons.append("text_control_transferred_semantic_state")
            if llm_prompt_saved <= 0.0 and prompt_visible_saved <= 0.0:
                stress_fail_reasons.append("no_extra_state_ref_prompt_saving_vs_t2")
            stress_pass = (
                not stress_fail_reasons
            )
            families.append(
                {
                    "family_id": str(family.get("family_id", "")),
                    "group": group_name,
                    "headline_scope": str(family.get("headline_scope", "")),
                    "quality_headline_eligible": bool(family.get("quality_headline_eligible", False)),
                    "replay_headline_eligible": bool(family.get("replay_headline_eligible", False)),
                    "stress_pass": stress_pass,
                    "l2_semantic_state_transfer_count": l2_transfer_count,
                    "t2_semantic_state_transfer_count": t2_transfer_count,
                    "llm_prompt_delta_l2_vs_t2": llm_prompt_delta,
                    "prompt_visible_delta_l2_vs_t2": prompt_visible_delta,
                    "raw_evidence_delta_l2_vs_t2": raw_evidence_delta,
                    "llm_prompt_saved_by_state_ref_bytes": llm_prompt_saved,
                    "prompt_visible_saved_by_state_ref_bytes": prompt_visible_saved,
                    "stress_fail_reasons": stress_fail_reasons,
                    "family_claim_scope": "non_text_state_claimable" if stress_pass else "diagnostic_only",
                    "interpretation": (
                        "non_text_state_transfer_has_extra_prompt_saving"
                        if prompt_visible_saved > 0.0
                        else (
                            "non_text_state_transfer_has_scaffolding_saving"
                            if llm_prompt_saved > 0.0
                            else "semantic_selection_dominates_this_family"
                        )
                    ),
                }
            )
    ranked = sorted(
        families,
        key=lambda payload: (
            -float(payload["prompt_visible_saved_by_state_ref_bytes"]),
            -float(payload["llm_prompt_saved_by_state_ref_bytes"]),
            str(payload["family_id"]),
        ),
    )
    failure_reason_counts: dict[str, int] = {}
    for family in families:
        for reason in family["stress_fail_reasons"]:
            failure_reason_counts[str(reason)] = failure_reason_counts.get(str(reason), 0) + 1
    per_family_stress_result = {
        str(family["family_id"]): {
            "pass": bool(family["stress_pass"]),
            "reason": str(family["stress_fail_reasons"][0]) if family["stress_fail_reasons"] else "",
            "reasons": list(family["stress_fail_reasons"]),
            "scope": str(family["family_claim_scope"]),
            "group": str(family["group"]),
            "llm_prompt_saved": float(family["llm_prompt_saved_by_state_ref_bytes"]),
            "visible_saved": float(family["prompt_visible_saved_by_state_ref_bytes"]),
            "interpretation": str(family["interpretation"]),
        }
        for family in ranked
    }
    return {
        "schema_version": "statebus.non_text_state_stress_summary.v1",
        "stress_family_count": len(families),
        "stress_pass_family_count": sum(1 for family in families if bool(family["stress_pass"])),
        "stress_fail_family_count": sum(1 for family in families if not bool(family["stress_pass"])),
        "claimable_non_text_state_family_count": sum(1 for family in families if bool(family["stress_pass"])),
        "diagnostic_only_family_count": sum(1 for family in families if not bool(family["stress_pass"])),
        "stress_failure_reason_counts": dict(sorted(failure_reason_counts.items())),
        "total_llm_prompt_saved_by_state_ref_bytes": sum(
            float(family["llm_prompt_saved_by_state_ref_bytes"]) for family in families
        ),
        "total_prompt_visible_saved_by_state_ref_bytes": sum(
            float(family["prompt_visible_saved_by_state_ref_bytes"]) for family in families
        ),
        "top_prompt_visible_saving_family": ranked[0] if ranked else {},
        "per_family_stress_result": per_family_stress_result,
        "families": ranked,
        "claim_boundary": (
            "This stress summary isolates L2 StateRef/semantic-state transfer from T2 text handoff with the same semantic selection. "
            "It does not claim KV or hidden-state transfer."
        ),
    }


def _fixed_answer_evidence(
    *,
    ladder_report: BenchmarkSuiteReport,
    text_semantic_report: BenchmarkFamilyReport,
    carrier_report,
    external_report,
) -> dict[str, object]:
    l0 = _layer_by_name(ladder_report, BenchmarkLayer.L0)
    l1 = _layer_by_name(ladder_report, BenchmarkLayer.L1)
    l2 = _layer_by_name(ladder_report, BenchmarkLayer.L2)
    l3 = _layer_by_name(ladder_report, BenchmarkLayer.L3)
    return {
        "task_family": ladder_report.task_family,
        "ladder_report_path": ladder_report.report_path,
        "carrier_compare_report_path": carrier_report.report_path,
        "text_same_semantic_selection_report_path": text_semantic_report.report_path,
        "external_compare_report_path": external_report.report_path,
        "internal_text_carrier": {
            "comparison_valid": bool(carrier_report.mode_reports[0].comparison_valid) if carrier_report.mode_reports else False,
            "claim_scope": "same_mainline_internal_text_vs_structured_carrier_only",
            "summary": dict(carrier_report.comparison_summary),
        },
        "text_same_semantic_selection": {
            "quality_floor_pass_count": _metric(text_semantic_report, "quality_floor_pass_count"),
            **_cost_summary(text_semantic_report),
            "llm_prompt_bytes": _metric(text_semantic_report, "llm_prompt_bytes"),
            "raw_evidence_bytes_seen_by_llm": _metric(text_semantic_report, "raw_evidence_bytes_seen_by_llm"),
            "prompt_visible_total_bytes": _metric(text_semantic_report, "prompt_visible_total_bytes"),
            "semantic_state_transfer_count": _metric(text_semantic_report, "semantic_state_transfer_count"),
            "semantic_selection_text_delta_vs_l1": {
                "llm_prompt_bytes": _delta(l1, text_semantic_report, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _delta(l1, text_semantic_report, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _delta(l1, text_semantic_report, "prompt_visible_total_bytes"),
            },
            "non_text_transfer_delta_l2_vs_text_same_selection": {
                "llm_prompt_bytes": _delta(text_semantic_report, l2, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _delta(text_semantic_report, l2, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _delta(text_semantic_report, l2, "prompt_visible_total_bytes"),
                "semantic_state_transfer_count": _delta(text_semantic_report, l2, "semantic_state_transfer_count"),
            },
        },
        "layer_summary": {
            "L0": {
                "quality_floor_pass_count": _metric(l0, "quality_floor_pass_count"),
                **_cost_summary(l0),
                "llm_prompt_bytes": _metric(l0, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _metric(l0, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _metric(l0, "prompt_visible_total_bytes"),
            },
            "L1": {
                "quality_floor_pass_count": _metric(l1, "quality_floor_pass_count"),
                **_cost_summary(l1),
                "llm_prompt_bytes": _metric(l1, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _metric(l1, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _metric(l1, "prompt_visible_total_bytes"),
            },
            "L2": {
                "quality_floor_pass_count": _metric(l2, "quality_floor_pass_count"),
                **_cost_summary(l2),
                "llm_prompt_bytes": _metric(l2, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _metric(l2, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _metric(l2, "prompt_visible_total_bytes"),
            },
            "L3": {
                "quality_floor_pass_count": _metric(l3, "quality_floor_pass_count"),
                **_cost_summary(l3),
                "llm_prompt_bytes": _metric(l3, "llm_prompt_bytes"),
                "raw_evidence_bytes_seen_by_llm": _metric(l3, "raw_evidence_bytes_seen_by_llm"),
                "prompt_visible_total_bytes": _metric(l3, "prompt_visible_total_bytes"),
                "reuse_gain": _metric(l3, "reuse_gain"),
            },
        },
        "external_pure_text": {
            "comparison_valid": bool(external_report.mode_reports[0].comparison_valid) if external_report.mode_reports else False,
            "invalid_reason": str(external_report.mode_reports[0].invalid_reason) if external_report.mode_reports else "",
            "formal_superiority_claim_allowed": bool(external_report.metadata.get("formal_superiority_claim_allowed", False)),
            "claim_restriction": str(external_report.metadata.get("claim_restriction", "")),
            "summary": dict(external_report.comparison_summary),
        },
    }


def _build_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# StateBus Non-Text Flagship Ablation",
        "",
        f"- suite_id: `{payload['suite_id']}`",
        f"- role_path_mode: `{payload['role_path_mode']}`",
        f"- embedding_mode: `{payload['embedding_mode']}`",
        f"- claim_level: `{payload['claim_level']}`",
        "",
        "## Baseline Contracts",
        "",
    ]
    for item in payload["baseline_contracts"]:
        contract = dict(item)
        lines.append(f"- {contract['id']}: {contract['description']}")
    fixed = dict(payload["fixed_answer_evidence"])
    external = dict(fixed["external_pure_text"])
    lines.extend(
        [
            "",
            "## Fixed-Answer Controls",
            "",
            f"- internal_carrier_valid: `{dict(fixed['internal_text_carrier'])['comparison_valid']}`",
            f"- external_comparator_valid: `{external['comparison_valid']}`",
            f"- external_invalid_reason: `{external['invalid_reason']}`",
            "",
            "## Continuous Flagship Evidence",
            "",
            "| family | scope | L2 raw reduction vs L1 | L3 raw reduction vs L0 | L3 replay | T2 semantic transfers |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for group_name in ("continuous_evidence", "continuous_replay_evidence"):
        for family_payload in payload[group_name]:
            family = dict(family_payload)
            l2 = dict(family["l2_structured_semantic_state"])
            l3 = dict(family["l3_memory_replay"])
            t2 = dict(family.get("t2_text_same_semantic_selection", {}))
            replay_total = float(l3.get("validated_replay_count", 0.0)) + float(l3.get("exact_replay_count", 0.0))
            lines.append(
                f"| {family['family_id']} | {family['headline_scope']} | "
                f"{l2['raw_evidence_reduction_pct_vs_l1']:.2f}% | "
                f"{l3['raw_evidence_reduction_pct_vs_l0']:.2f}% | "
                f"{replay_total:.0f} | {float(t2.get('semantic_state_transfer_count', 0.0)):.0f} |"
            )
    stress = dict(payload.get("non_text_state_stress_summary", {}))
    top_stress = dict(stress.get("top_prompt_visible_saving_family", {}))
    lines.extend(
        [
            "",
            "## Non-Text State Stress Summary",
            "",
            f"- stress_pass_family_count: `{stress.get('stress_pass_family_count', 0)}`",
            f"- stress_fail_family_count: `{stress.get('stress_fail_family_count', 0)}`",
            f"- diagnostic_only_family_count: `{stress.get('diagnostic_only_family_count', 0)}`",
            f"- total_llm_prompt_saved_by_state_ref_bytes: `{stress.get('total_llm_prompt_saved_by_state_ref_bytes', 0.0)}`",
            f"- total_prompt_visible_saved_by_state_ref_bytes: `{stress.get('total_prompt_visible_saved_by_state_ref_bytes', 0.0)}`",
            f"- top_prompt_visible_saving_family: `{top_stress.get('family_id', '')}`",
            "",
            "| family | group | claim_scope | fail_reasons |",
            "| --- | --- | --- | --- |",
        ]
    )
    for family in stress.get("families", []):
        family_payload = dict(family)
        fail_reasons = ",".join(str(item) for item in family_payload.get("stress_fail_reasons", [])) or "-"
        lines.append(
            f"| {family_payload.get('family_id', '')} | {family_payload.get('group', '')} | "
            f"{family_payload.get('family_claim_scope', '')} | {fail_reasons} |"
        )
    lines.extend(
        [
            "",
            "## Claim Discipline",
            "",
        ]
    )
    for item in payload["claim_level_after_fix"]:
        lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


def run_non_text_flagship_ablation_report(
    *,
    fixed_samples: list[FixedAnswerSample],
    continuous_families: tuple[ContinuousTaskFamily, ...],
    replay_families: tuple[ContinuousTaskFamily, ...],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "statebus-non-text-flagship-ablation",
    role_path_mode: str = "deterministic",
    embedding_mode: str = "deterministic",
    persistence_profile: str = "audit_full",
) -> dict[str, object]:
    benchmark_report_root = runtime_root / "benchmark_reports"
    fixed_ladder = run_fixed_answer_suite(
        samples=fixed_samples,
        workspace_root=workspace_root / "fixed-ladder",
        runtime_root=runtime_root / "fixed-ladder",
        socket_path=_sub_socket(socket_path, "fx"),
        suite_id=f"{suite_id}-fixed-ladder",
        role_path_modes=(role_path_mode,),
        embedding_mode=embedding_mode,
        statebus_mode="cold-start",
        seed_replay_memory=False,
        benchmark_tier="dev",
        claim_level="diagnostic",
        persistence_profile=persistence_profile,
    )
    fixed_t2 = run_fixed_answer_text_semantic_selection_family(
        samples=fixed_samples,
        workspace_root=workspace_root / "fixed-text-semantic-selection",
        runtime_root=runtime_root / "fixed-text-semantic-selection",
        socket_path=_sub_socket(socket_path, "ft2"),
        suite_id=f"{suite_id}-fixed-text-semantic-selection",
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        persistence_profile=persistence_profile,
    )
    carrier_report = run_fixed_answer_internal_carrier_compare_suite(
        samples=fixed_samples,
        workspace_root=workspace_root / "fixed-carrier-compare",
        runtime_root=runtime_root / "fixed-carrier-compare",
        socket_path=_sub_socket(socket_path, "fc"),
        suite_id=f"{suite_id}-carrier-compare",
        role_path_modes=(role_path_mode,),
        embedding_mode=embedding_mode,
        statebus_mode="cold-start",
        benchmark_tier="dev",
        claim_level="diagnostic",
        persistence_profile=persistence_profile,
    )
    external_report = compare_fixed_answer_with_external(
        samples=fixed_samples,
        workspace_root=workspace_root / "fixed-external-compare",
        runtime_root=runtime_root / "fixed-external-compare",
        socket_path=_sub_socket(socket_path, "fe"),
        suite_id=f"{suite_id}-external-compare",
        role_path_modes=(role_path_mode,),
        embedding_mode=embedding_mode,
        statebus_mode="cold-start",
        seed_replay_memory=False,
        benchmark_tier="dev",
        claim_level="diagnostic",
        persistence_profile=persistence_profile,
    )
    continuous_report = run_continuous_benchmark_collection(
        families=continuous_families,
        workspace_root=workspace_root / "continuous",
        runtime_root=runtime_root / "continuous",
        socket_path=_sub_socket(socket_path, "co"),
        suite_id=f"{suite_id}-continuous",
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        persistence_profile=persistence_profile,
    )
    continuous_t2_reports = tuple(
        run_continuous_text_semantic_selection_family(
            family=family,
            workspace_root=workspace_root / "continuous-text-semantic-selection" / family.family_id,
            runtime_root=runtime_root / "continuous-text-semantic-selection" / family.family_id,
            socket_path=_sub_socket(socket_path, f"ct{index}"),
            suite_id=f"{suite_id}-continuous-text-semantic-selection-{family.family_id}",
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            persistence_profile=persistence_profile,
        )
        for index, family in enumerate(continuous_families, start=1)
    )
    replay_report = run_continuous_benchmark_collection(
        families=replay_families,
        workspace_root=workspace_root / "continuous-replay",
        runtime_root=runtime_root / "continuous-replay",
        socket_path=_sub_socket(socket_path, "cr"),
        suite_id=f"{suite_id}-continuous-replay",
        role_path_mode=role_path_mode,
        embedding_mode=embedding_mode,
        collection_scope="formal_replay_task_families",
        persistence_profile=persistence_profile,
    )
    replay_t2_reports = tuple(
        run_continuous_text_semantic_selection_family(
            family=family,
            workspace_root=workspace_root / "continuous-replay-text-semantic-selection" / family.family_id,
            runtime_root=runtime_root / "continuous-replay-text-semantic-selection" / family.family_id,
            socket_path=_sub_socket(socket_path, f"rt{index}"),
            suite_id=f"{suite_id}-continuous-replay-text-semantic-selection-{family.family_id}",
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            persistence_profile=persistence_profile,
        )
        for index, family in enumerate(replay_families, start=1)
    )
    continuous_evidence = _collection_evidence(
        report=continuous_report,
        text_semantic_reports=continuous_t2_reports,
    )
    continuous_replay_evidence = _collection_evidence(
        report=replay_report,
        text_semantic_reports=replay_t2_reports,
    )
    payload: dict[str, object] = {
        "schema_version": "statebus.non_text_flagship_ablation.v1",
        "suite_id": suite_id,
        "role_path_mode": role_path_mode,
        "embedding_mode": embedding_mode,
        "claim_level": "first_pass_with_diagnostic_text_controls",
        "baseline_contracts": [
            {
                "id": "L0_internal_pure_text_carrier",
                "description": "same StateBus runtime, same four-role graph, same scorer, text handoff, full evidence, no semantic pruning, no replay",
            },
            {
                "id": "T2_text_same_semantic_selection",
                "description": "same StateBus runtime and selected evidence, text handoff only, semantic pruning enabled, semantic state transfer disabled",
            },
            {
                "id": "external_pure_text_four_role",
                "description": "separate four-role pure-text baseline; debug-only until fairness gate passes",
            },
        ],
        "fixed_answer_evidence": _fixed_answer_evidence(
            ladder_report=fixed_ladder,
            text_semantic_report=fixed_t2,
            carrier_report=carrier_report,
            external_report=external_report,
        ),
        "continuous_collection_report_path": continuous_report.report_path,
        "continuous_replay_collection_report_path": replay_report.report_path,
        "continuous_evidence": continuous_evidence,
        "continuous_replay_evidence": continuous_replay_evidence,
        "non_text_state_stress_summary": _non_text_state_stress_summary(
            continuous_evidence=continuous_evidence,
            continuous_replay_evidence=continuous_replay_evidence,
        ),
        "claim_level_after_fix": [
            "Can claim L1 structured carrier reduces control/scaffolding only under same-mainline internal carrier controls.",
            "Can claim L2 semantic selection/pruning reduces raw evidence and prompt-visible bytes on continuous long/table task families.",
            "Can claim T2 isolates semantic selection from non-text state transfer; if T2 and L2 prompt bytes are close, current prompt savings are mostly selection, not KV-style hidden-state transfer.",
            "Can claim L3 memory/replay reduces repeated steps only where validated/exact replay or history-backed reuse counters are non-zero.",
            "Cannot claim formal external pure-text superiority until external comparator fairness gate passes.",
            "Cannot claim API token savings from deterministic runs; role_path_mode=api must be rerun for token evidence.",
            "Cannot claim KV cache / hidden-state handoff as implemented.",
        ],
    }
    payload["report_path"] = str(benchmark_report_root / f"{suite_id}.json")
    payload["markdown_report_path"] = str(benchmark_report_root / f"{suite_id}.md")
    write_json_report(Path(str(payload["report_path"])), payload)
    write_markdown_report(Path(str(payload["markdown_report_path"])), _build_markdown(payload))
    return payload
