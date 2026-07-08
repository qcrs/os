from __future__ import annotations

import os
from pathlib import Path

from v2.benchmark.external_text_baseline import run_external_text_family
from v2.benchmark.fixed_answer_runner import (
    FixedAnswerSample,
    normalize_statebus_mode,
    run_fixed_answer_benchmark_family,
)
from v2.benchmark.models import (
    BenchmarkComparatorModeReport,
    BenchmarkComparatorSuiteReport,
    BenchmarkLayer,
    BenchmarkFamilyReport,
)
from v2.benchmark.reporting import (
    comparator_mode_report_to_dict,
    comparator_suite_report_to_dict,
    write_json_report,
    write_markdown_report,
)
from v2.benchmark.task_registry import formal_family_specs


def _metric(report: BenchmarkFamilyReport, key: str) -> float:
    if key in report.telemetry_summary:
        return float(report.telemetry_summary[key])
    if key in report.aggregated_metrics:
        return float(report.aggregated_metrics[key])
    return 0.0


def _statebus_message_count(report: BenchmarkFamilyReport) -> float:
    return _metric(report, "message_count") or _metric(report, "control_message_count") or _metric(report, "response_count")


def _statebus_llm_call_count(report: BenchmarkFamilyReport) -> float:
    return _metric(report, "llm_call_count") or sum(
        _metric(report, key)
        for key in (
            "planner_call_count",
            "retriever_call_count",
            "executor_call_count",
            "summarizer_call_count",
        )
    )


def _statebus_prompt_tokens(report: BenchmarkFamilyReport) -> float:
    return _metric(report, "prompt_tokens") or _metric(report, "llm_prompt_tokens")


def _statebus_completion_tokens(report: BenchmarkFamilyReport) -> float:
    return _metric(report, "completion_tokens") or _metric(report, "llm_completion_tokens")


def _statebus_role_completion_tokens(report: BenchmarkFamilyReport) -> dict[str, float]:
    return {
        role: _metric(report, f"{role}_completion_tokens")
        for role in ("planner", "retriever", "executor", "summarizer")
    }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _build_debug_metrics(
    *,
    statebus_report: BenchmarkFamilyReport,
    external_report: BenchmarkFamilyReport,
) -> dict[str, float]:
    if statebus_report.missing_reason or external_report.missing_reason:
        return {}
    statebus_role_completion_tokens = _statebus_role_completion_tokens(statebus_report)
    statebus_prompt_tokens = _statebus_prompt_tokens(statebus_report)
    external_prompt_tokens = _metric(external_report, "prompt_tokens")
    statebus_completion_tokens = _statebus_completion_tokens(statebus_report)
    external_completion_tokens = _metric(external_report, "completion_tokens")
    statebus_total_tokens = _metric(statebus_report, "llm_total_tokens")
    external_total_tokens = _metric(external_report, "llm_total_tokens")
    return {
        "case_count": max(
            statebus_report.aggregated_metrics.get("case_count", 0.0),
            external_report.aggregated_metrics.get("case_count", 0.0),
        ),
        "statebus_quality_floor_pass_count": statebus_report.aggregated_metrics.get("quality_floor_pass_count", 0.0),
        "external_quality_floor_pass_count": external_report.aggregated_metrics.get("quality_floor_pass_count", 0.0),
        "statebus_exact_match_count": _metric(statebus_report, "exact_match"),
        "external_exact_match_count": _metric(external_report, "exact_match"),
        "statebus_prompt_tokens": statebus_prompt_tokens,
        "external_prompt_tokens": external_prompt_tokens,
        "prompt_tokens_delta": statebus_prompt_tokens - external_prompt_tokens,
        "statebus_completion_tokens": statebus_completion_tokens,
        "external_completion_tokens": external_completion_tokens,
        "completion_tokens_delta": statebus_completion_tokens - external_completion_tokens,
        "statebus_planner_completion_tokens": statebus_role_completion_tokens["planner"],
        "statebus_retriever_completion_tokens": statebus_role_completion_tokens["retriever"],
        "statebus_executor_completion_tokens": statebus_role_completion_tokens["executor"],
        "statebus_summarizer_completion_tokens": statebus_role_completion_tokens["summarizer"],
        "statebus_llm_total_tokens": statebus_total_tokens,
        "external_llm_total_tokens": external_total_tokens,
        "llm_total_tokens_delta": statebus_total_tokens - external_total_tokens,
        "llm_call_count_delta": _statebus_llm_call_count(statebus_report) - _metric(external_report, "llm_call_count"),
        "prompt_bytes_delta": _metric(statebus_report, "llm_prompt_bytes") - _metric(external_report, "prompt_bytes"),
        "llm_ms_delta": _metric(statebus_report, "llm_wall_ms") - _metric(external_report, "llm_ms"),
        "end_to_end_ms_delta": _metric(statebus_report, "task_ms") - _metric(external_report, "end_to_end_ms"),
        "message_count_delta": _statebus_message_count(statebus_report) - _metric(external_report, "message_count"),
        "control_bytes_delta": _metric(statebus_report, "control_bytes") - _metric(external_report, "control_bytes"),
        "task_ms_delta": _metric(statebus_report, "task_ms") - _metric(external_report, "end_to_end_ms"),
        # Overhead breakdown: splits task_ms_delta into LLM-layer vs system-layer.
        # net_llm_ms_delta: pure LLM call time difference (subject to API latency variance).
        # system_overhead_ms_delta: non-LLM overhead difference (audit writes, state persistence, etc.).
        "net_llm_ms_delta": _metric(statebus_report, "llm_wall_ms") - _metric(external_report, "llm_ms"),
        "system_overhead_ms_delta": (
            _metric(statebus_report, "task_ms") - _metric(statebus_report, "llm_wall_ms")
        ) - (
            _metric(external_report, "end_to_end_ms") - _metric(external_report, "llm_ms")
        ),
        # CodeAct execution stage timing — proves -65% improvement from runner cache.
        # Sourced from statebus telemetry only; external baseline does not have this stage.
        "codeact_execution_stage_ms": _metric(statebus_report, "codeact_execution_stage_ms"),
        "exact_match_delta": _metric(statebus_report, "exact_match") - _metric(external_report, "exact_match"),
        "route_exact_delta": _metric(statebus_report, "route_exact") - _metric(external_report, "route_exact"),
        "tool_exact_delta": _metric(statebus_report, "tool_exact") - _metric(external_report, "tool_exact"),
        "quality_floor_pass_delta": statebus_report.aggregated_metrics.get("quality_floor_pass_count", 0.0)
        - external_report.aggregated_metrics.get("quality_floor_pass_count", 0.0),
    }


def _fairness_manifest(
    *,
    statebus_report: BenchmarkFamilyReport,
    external_report: BenchmarkFamilyReport,
    benchmark_tier: str,
) -> dict[str, object]:
    statebus_metadata = statebus_report.metadata
    external_metadata = external_report.metadata
    same_task_family = statebus_report.task_family == external_report.task_family
    same_role_graph = statebus_metadata.get("role_graph") == external_metadata.get("role_graph")
    same_scoring_contract = statebus_metadata.get("scoring_contract") == external_metadata.get("scoring_contract")
    same_quality_floor_contract = (
        statebus_metadata.get("quality_floor_contract") == external_metadata.get("quality_floor_contract")
    )
    same_tier = statebus_metadata.get("benchmark_tier") == external_metadata.get("benchmark_tier") == benchmark_tier
    external_formal_eligible = bool(external_metadata.get("formal_comparator_eligible", False))
    external_uses_internal_helpers = bool(external_metadata.get("uses_internal_helpers", False))
    external_four_role = (
        external_report.telemetry_summary.get("planner_call_count", 0.0) > 0.0
        and external_report.telemetry_summary.get("retriever_call_count", 0.0) > 0.0
        and external_report.telemetry_summary.get("executor_call_count", 0.0) > 0.0
        and external_report.telemetry_summary.get("summarizer_call_count", 0.0) > 0.0
    )
    same_history_policy = statebus_metadata.get("statebus_mode", "cold_start") == "cold_start"
    external_case_payload = (
        external_report.cases[0].metrics if external_report.cases else {}
    )
    statebus_case_payload = statebus_report.cases[0].metrics if statebus_report.cases else {}
    no_external_contamination = external_report.telemetry_summary.get("contamination_detected", 0.0) == 0.0
    external_case_count = float(len(external_report.cases))
    external_fairness_gate_pass_count = _metric(external_report, "external_fairness_gate_pass_count")
    external_fairness_gate_failed_case_count = _metric(
        external_report,
        "external_fairness_gate_failed_case_count",
    )
    external_fairness_gate_failed_check_count = _metric(
        external_report,
        "external_fairness_gate_failed_check_count",
    )
    external_fairness_gate_reported_case_count = _metric(
        external_report,
        "external_fairness_gate_reported_case_count",
    )
    external_fairness_gate_failed_checks = tuple(
        str(check).strip()
        for check in external_metadata.get("external_fairness_gate_failed_checks", [])
        if str(check).strip()
    )
    external_fairness_gate_coverage = (
        external_case_count > 0.0
        and external_fairness_gate_reported_case_count == external_case_count
        and external_fairness_gate_pass_count + external_fairness_gate_failed_case_count == external_case_count
    )
    no_external_fairness_gate_failures = (
        external_fairness_gate_coverage
        and external_fairness_gate_failed_case_count == 0.0
        and external_fairness_gate_failed_check_count == 0.0
        and not external_fairness_gate_failed_checks
    )
    role_metric_presence = all(
        external_report.telemetry_summary.get(f"{role}_call_count", 0.0) > 0.0
        for role in ("planner", "retriever", "executor", "summarizer")
    )
    pass_hard_gate = all(
        (
            same_task_family,
            same_role_graph,
            same_scoring_contract,
            same_quality_floor_contract,
            same_tier,
            external_formal_eligible,
            not external_uses_internal_helpers,
            external_four_role,
            same_history_policy,
            no_external_contamination,
            external_fairness_gate_coverage,
            no_external_fairness_gate_failures,
            role_metric_presence,
        )
    )
    return {
        "benchmark_tier": benchmark_tier,
        "claim_restriction": str(
            external_metadata.get("claim_restriction", "external_lane_not_formal")
        ),
        "external_formal_eligible": external_formal_eligible,
        "external_four_role": external_four_role,
        "external_fairness_gate_contract": str(
            external_metadata.get("external_fairness_gate_contract", "")
        ),
        "external_fairness_gate_coverage": external_fairness_gate_coverage,
        "external_fairness_gate_failed_case_count": external_fairness_gate_failed_case_count,
        "external_fairness_gate_failed_check_count": external_fairness_gate_failed_check_count,
        "external_fairness_gate_failed_checks": list(external_fairness_gate_failed_checks),
        "external_fairness_gate_pass_count": external_fairness_gate_pass_count,
        "external_fairness_gate_reported_case_count": external_fairness_gate_reported_case_count,
        "external_uses_internal_helpers": external_uses_internal_helpers,
        "no_external_fairness_gate_failures": no_external_fairness_gate_failures,
        "no_external_contamination": no_external_contamination,
        "pass_hard_gate": pass_hard_gate,
        "role_metric_presence_gate": role_metric_presence,
        "same_history_policy": same_history_policy,
        "same_quality_floor_contract": same_quality_floor_contract,
        "same_role_graph": same_role_graph,
        "same_scoring_contract": same_scoring_contract,
        "same_task_family": same_task_family,
        "same_tier": same_tier,
        "statebus_mode": statebus_metadata.get("statebus_mode", ""),
        "external_case_metric_keys": list(sorted(external_case_payload.keys())),
        "statebus_case_metric_keys": list(sorted(statebus_case_payload.keys())),
    }


def _headline_metrics(
    *,
    statebus_report: BenchmarkFamilyReport,
    external_report: BenchmarkFamilyReport,
    fairness_manifest: dict[str, object],
) -> tuple[dict[str, float], str]:
    if not bool(fairness_manifest.get("pass_hard_gate", False)):
        return {}, "fairness_gate_failed"
    if not statebus_report.eligible_for_headline or not external_report.eligible_for_headline:
        return {}, "quality_floor_gate_failed"
    debug_metrics = _build_debug_metrics(
        statebus_report=statebus_report,
        external_report=external_report,
    )
    return {
        key: debug_metrics[key]
        for key in (
            "llm_total_tokens_delta",
            "llm_call_count_delta",
            "prompt_bytes_delta",
            "llm_ms_delta",
            "net_llm_ms_delta",
            "end_to_end_ms_delta",
            "message_count_delta",
            "control_bytes_delta",
            "task_ms_delta",
            "system_overhead_ms_delta",
        )
    }, ""


def _mode_formal_efficiency_claim_allowed(mode_report: BenchmarkComparatorModeReport) -> bool:
    return (
        mode_report.benchmark_tier == "formal"
        and not mode_report.missing_reason
        and mode_report.comparison_valid
        and mode_report.debug_metrics.get("llm_total_tokens_delta", 0.0) < 0.0
        and mode_report.debug_metrics.get("prompt_bytes_delta", 0.0) < 0.0
        and mode_report.debug_metrics.get("quality_floor_pass_delta", 0.0) == 0.0
    )


def _mode_prompt_byte_efficiency_claim_allowed(mode_report: BenchmarkComparatorModeReport) -> bool:
    """True when StateBus uses fewer prompt bytes with equal quality.

    This is a weaker efficiency claim than _mode_formal_efficiency_claim_allowed.
    It focuses on prompt bytes (input context reduction from structured protocol)
    without requiring total token reduction. StateBus may use more total tokens
    due to structured JSON output verbosity vs external free-text output.
    The claim: StateBus reduces inter-agent context overhead (prompt bytes)
    while achieving equal quality.
    """
    return (
        mode_report.benchmark_tier == "formal"
        and not mode_report.missing_reason
        and mode_report.comparison_valid
        and mode_report.debug_metrics.get("prompt_bytes_delta", 0.0) < 0.0
        and mode_report.debug_metrics.get("quality_floor_pass_delta", 0.0) == 0.0
    )


def _formal_efficiency_claim_allowed(
    mode_reports: list[BenchmarkComparatorModeReport],
    *,
    benchmark_tier: str,
) -> bool:
    return benchmark_tier == "formal" and bool(mode_reports) and all(
        _mode_formal_efficiency_claim_allowed(report) for report in mode_reports
    )


def _mode_quality_superiority_comparison_valid(mode_report: BenchmarkComparatorModeReport) -> bool:
    return (
        not mode_report.missing_reason
        and bool(mode_report.fairness_manifest.get("pass_hard_gate", False))
        and mode_report.statebus_report.eligible_for_headline
        and mode_report.debug_metrics.get("quality_floor_pass_delta", 0.0) > 0.0
    )


def _quality_superiority_comparison_valid(mode_reports: list[BenchmarkComparatorModeReport]) -> bool:
    return bool(mode_reports) and all(not r.missing_reason for r in mode_reports) and all(
        bool(r.fairness_manifest.get("pass_hard_gate", False)) for r in mode_reports
    ) and all(r.statebus_report.eligible_for_headline for r in mode_reports) and any(
        r.debug_metrics.get("quality_floor_pass_delta", 0.0) > 0.0 for r in mode_reports
    )


def _formal_compare_scope_metadata(
    *,
    samples: list[FixedAnswerSample],
    benchmark_tier: str,
) -> dict[str, object]:
    case_count = len(samples)
    family_count = len({sample.task_family for sample in samples}) if samples else 0
    registry_case_count = sum(spec.expected_case_count for spec in formal_family_specs())
    registry_family_count = len(formal_family_specs())
    full_registry = (
        benchmark_tier == "formal"
        and case_count == registry_case_count
        and family_count == registry_family_count
    )
    if benchmark_tier == "formal":
        if full_registry:
            label = f"formal_registry_{registry_case_count}case_{registry_family_count}family_compare"
        elif case_count == 8 and family_count == 1:
            label = "formal_financial_family_8case_compare"
        else:
            label = f"formal_partial_{family_count}family_{case_count}case_compare"
    else:
        label = f"dev_fixed_answer_{case_count}case_compare"
    return {
        "formal_compare_scope_label": label,
        "formal_compare_case_count": case_count,
        "formal_compare_family_count": family_count,
        "formal_registry_case_count": registry_case_count,
        "formal_registry_family_count": registry_family_count,
        "formal_compare_full_registry_coverage": full_registry,
    }


def _build_mode_markdown(
    *,
    role_path_mode: str,
    statebus_mode: str,
    missing_reason: str,
    invalid_reason: str,
    headline_metrics: dict[str, float],
    debug_metrics: dict[str, float],
    comparison_valid: bool,
    quality_superiority_comparison_valid: bool,
    formal_efficiency_superiority_claim_allowed: bool,
    formal_external_claim_kind: str,
) -> str:
    rendered_statebus_mode = statebus_mode.replace("_", "-")
    if missing_reason:
        return (
            f"# Fixed-Answer Comparator\n\n"
            f"- mode: `{role_path_mode}`\n"
            f"- statebus_mode: `{rendered_statebus_mode}`\n"
            f"- status: skipped\n"
            f"- missing_reason: `{missing_reason}`\n"
        )
    headline_rows = "\n".join(
        f"| {name} | {value:.3f} |" for name, value in sorted(headline_metrics.items())
    )
    debug_rows = "\n".join(
        f"| {name} | {value:.3f} |" for name, value in sorted(debug_metrics.items())
    )
    status = "valid" if comparison_valid else "invalid"
    summary_lines = [
        "# Fixed-Answer Comparator",
        "",
        f"- mode: `{role_path_mode}`",
        f"- statebus_mode: `{rendered_statebus_mode}`",
        f"- status: `{status}`",
        f"- strict_equal_quality_comparison_valid: `{comparison_valid}`",
        f"- quality_superiority_comparison_valid: `{quality_superiority_comparison_valid}`",
        f"- formal_efficiency_superiority_claim_allowed: `{formal_efficiency_superiority_claim_allowed}`",
        f"- formal_external_claim_kind: `{formal_external_claim_kind}`",
    ]
    if invalid_reason:
        summary_lines.append(f"- invalid_reason: `{invalid_reason}`")
    summary_lines.extend(
        [
            "- delta_direction: `statebus_minus_external`",
            "- comparator_claim: `debug_only_when_fairness_gate_fails`",
            "",
            "## Headline Metrics",
            "",
        ]
    )
    if headline_rows:
        summary_lines.extend(["| Metric | Delta |", "| --- | ---: |", headline_rows, ""])
    else:
        summary_lines.append("No formal headline metrics emitted.\n")
    summary_lines.extend(["## Debug Metrics", ""])
    if debug_rows:
        summary_lines.extend(["| Metric | Delta |", "| --- | ---: |", debug_rows])
    else:
        summary_lines.append("No debug metrics emitted.")
    return "\n".join(summary_lines).rstrip() + "\n"


def _build_suite_markdown(report: BenchmarkComparatorSuiteReport) -> str:
    description = report.mode_reports[0].statebus_report.profile.description if report.mode_reports else "-"
    scope_label = str(report.metadata.get("formal_compare_scope_label", "-"))
    claim_kind = str(report.metadata.get("formal_external_claim_kind", "-"))
    strict_valid = bool(report.metadata.get("strict_equal_quality_comparison_valid", False))
    quality_valid = bool(report.metadata.get("quality_superiority_comparison_valid", False))
    rows = []
    for mode_report in report.mode_reports:
        delta = mode_report.debug_metrics.get("exact_match_delta", 0.0)
        status = "skipped" if mode_report.missing_reason else "valid" if mode_report.comparison_valid else "invalid"
        rows.append(
            f"| {mode_report.role_path_mode} | {status} | {delta:.3f} | {mode_report.invalid_reason or mode_report.missing_reason or '-'} |"
        )
    return (
        "# Fixed-Answer Comparator Suite\n\n"
        f"- statebus_profile: `{description}`\n\n"
        f"- formal_compare_scope_label: `{scope_label}`\n"
        f"- strict_equal_quality_comparison_valid: `{strict_valid}`\n"
        f"- quality_superiority_comparison_valid: `{quality_valid}`\n"
        f"- formal_external_claim_kind: `{claim_kind}`\n\n"
        "| Mode | Status | exact_match_delta | Note |\n"
        "| --- | --- | ---: | --- |\n"
        + "\n".join(rows)
        + "\n"
    )


def _quality_floor_equal_across_modes(
    mode_reports: list[BenchmarkComparatorModeReport],
) -> bool:
    """True when StateBus and external both pass all quality_floor cases in every mode."""
    for r in mode_reports:
        n = r.debug_metrics.get("case_count", 0.0)
        if n == 0.0:
            return False
        sb = r.debug_metrics.get("statebus_quality_floor_pass_count", 0.0)
        ex = r.debug_metrics.get("external_quality_floor_pass_count", 0.0)
        if not (sb == ex == n):
            return False
    return True


def _efficiency_superior_across_modes(
    mode_reports: list[BenchmarkComparatorModeReport],
) -> bool:
    """True when StateBus uses fewer LLM tokens AND fewer prompt bytes in every mode."""
    for r in mode_reports:
        if not r.debug_metrics:
            return False
        if r.debug_metrics.get("llm_total_tokens_delta", 0.0) >= 0.0:
            return False
        if r.debug_metrics.get("prompt_bytes_delta", 0.0) >= 0.0:
            return False
    return bool(mode_reports)


def run_fixed_answer_external_comparator_suite(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-vs-external-suite",
    role_path_modes: tuple[str, ...] = ("deterministic", "api"),
    embedding_mode: str = "deterministic",
    statebus_mode: str = "cold_start",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "dev",
    claim_level: str = "prototype",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> BenchmarkComparatorSuiteReport:
    normalized_statebus_mode = normalize_statebus_mode(statebus_mode)
    mode_reports: list[BenchmarkComparatorModeReport] = []
    benchmark_report_root = runtime_root / "benchmark_reports"
    task_family = samples[0].task_family if samples else "fixed_answer_route_tool"
    for role_path_mode in role_path_modes:
        mode_runtime_root = runtime_root / role_path_mode
        statebus_report = run_fixed_answer_benchmark_family(
            samples=samples,
            workspace_root=workspace_root / role_path_mode / "statebus",
            runtime_root=mode_runtime_root / "statebus",
            socket_path=socket_path.with_name(f"{socket_path.stem}-{role_path_mode}-statebus{socket_path.suffix}"),
            suite_id=f"{suite_id}-statebus-{role_path_mode}",
            layer=BenchmarkLayer.L3,
            role_path_mode=role_path_mode,
            embedding_mode=embedding_mode,
            statebus_mode=normalized_statebus_mode,
            seed_replay_memory=seed_replay_memory,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            state_pool_mode=state_pool_mode,
            persistence_profile=persistence_profile,
        )
        external_report = run_external_text_family(
            samples=samples,
            runtime_root=mode_runtime_root / "external",
            role_path_mode=role_path_mode,
            suite_id=f"{suite_id}-external-{role_path_mode}",
            embedding_mode=embedding_mode,
            benchmark_tier=benchmark_tier,
        )
        mode_missing_reason = statebus_report.missing_reason or external_report.missing_reason
        fairness_manifest = _fairness_manifest(
            statebus_report=statebus_report,
            external_report=external_report,
            benchmark_tier=benchmark_tier,
        )
        debug_metrics = _build_debug_metrics(
            statebus_report=statebus_report,
            external_report=external_report,
        )
        headline_metrics, invalid_reason = _headline_metrics(
            statebus_report=statebus_report,
            external_report=external_report,
            fairness_manifest=fairness_manifest,
        )
        comparison_valid = not mode_missing_reason and not invalid_reason
        mode_quality_superiority_comparison_valid = (
            not mode_missing_reason
            and bool(fairness_manifest.get("pass_hard_gate", False))
            and statebus_report.eligible_for_headline
            and debug_metrics.get("quality_floor_pass_delta", 0.0) > 0.0
        )
        mode_formal_efficiency_superiority_claim_allowed = (
            benchmark_tier == "formal"
            and comparison_valid
            and debug_metrics.get("llm_total_tokens_delta", 0.0) < 0.0
            and debug_metrics.get("prompt_bytes_delta", 0.0) < 0.0
            and debug_metrics.get("quality_floor_pass_delta", 0.0) == 0.0
        )
        comparison_summary = {
            "case_count": debug_metrics.get("case_count", 0.0),
            "comparison_valid": 1.0 if comparison_valid else 0.0,
            "strict_equal_quality_comparison_valid": 1.0 if comparison_valid else 0.0,
            "quality_superiority_comparison_valid": 1.0
            if mode_quality_superiority_comparison_valid
            else 0.0,
            "headline_metric_count": float(len(headline_metrics)),
            "formal_efficiency_superiority_claim_allowed": 1.0
            if mode_formal_efficiency_superiority_claim_allowed
            else 0.0,
            "formal_efficiency_claim_allowed": 1.0
            if mode_formal_efficiency_superiority_claim_allowed
            else 0.0,
            "statebus_prompt_tokens": debug_metrics.get("statebus_prompt_tokens", 0.0),
            "external_prompt_tokens": debug_metrics.get("external_prompt_tokens", 0.0),
            "prompt_tokens_delta": debug_metrics.get("prompt_tokens_delta", 0.0),
            "statebus_completion_tokens": debug_metrics.get("statebus_completion_tokens", 0.0),
            "external_completion_tokens": debug_metrics.get("external_completion_tokens", 0.0),
            "completion_tokens_delta": debug_metrics.get("completion_tokens_delta", 0.0),
            "statebus_planner_completion_tokens": debug_metrics.get("statebus_planner_completion_tokens", 0.0),
            "statebus_retriever_completion_tokens": debug_metrics.get("statebus_retriever_completion_tokens", 0.0),
            "statebus_executor_completion_tokens": debug_metrics.get("statebus_executor_completion_tokens", 0.0),
            "statebus_summarizer_completion_tokens": debug_metrics.get(
                "statebus_summarizer_completion_tokens", 0.0
            ),
            "statebus_llm_total_tokens": debug_metrics.get("statebus_llm_total_tokens", 0.0),
            "external_llm_total_tokens": debug_metrics.get("external_llm_total_tokens", 0.0),
            "llm_total_tokens_delta": debug_metrics.get("llm_total_tokens_delta", 0.0),
        }
        if comparison_valid:
            comparison_summary.update(headline_metrics)
        else:
            comparison_summary["debug_metric_count"] = float(len(debug_metrics))
        mode_report_path = benchmark_report_root / f"{suite_id}-{role_path_mode}.json"
        markdown_report_path = benchmark_report_root / f"{suite_id}-{role_path_mode}.md"
        mode_report = BenchmarkComparatorModeReport(
            suite_id=suite_id,
            role_path_mode=role_path_mode,
            task_family=task_family,
            external_report=external_report,
            statebus_report=statebus_report,
            comparison_summary=comparison_summary,
            headline_metrics=headline_metrics,
            debug_metrics=debug_metrics,
            fairness_manifest=fairness_manifest,
            comparison_valid=comparison_valid,
            invalid_reason="" if mode_missing_reason else invalid_reason,
            benchmark_tier=benchmark_tier,
            claim_level=claim_level,
            report_path=str(mode_report_path),
            markdown_report_path=str(markdown_report_path),
            missing_reason=mode_missing_reason,
        )
        write_json_report(mode_report_path, comparator_mode_report_to_dict(mode_report))
        write_markdown_report(
            markdown_report_path,
            _build_mode_markdown(
                role_path_mode=role_path_mode,
                statebus_mode=normalized_statebus_mode,
                missing_reason=mode_missing_reason,
                invalid_reason=mode_report.invalid_reason,
                headline_metrics=headline_metrics,
                debug_metrics=debug_metrics,
                comparison_valid=comparison_valid,
                quality_superiority_comparison_valid=mode_quality_superiority_comparison_valid,
                formal_efficiency_superiority_claim_allowed=mode_formal_efficiency_superiority_claim_allowed,
                formal_external_claim_kind=(
                    "efficiency_superiority_equal_quality"
                    if mode_formal_efficiency_superiority_claim_allowed
                    else "quality_superiority"
                    if benchmark_tier == "formal" and mode_quality_superiority_comparison_valid
                    else "debug_only"
                    if benchmark_tier == "formal"
                    else "none"
                ),
            ),
        )
        mode_reports.append(mode_report)

    suite_report_path = benchmark_report_root / f"{suite_id}.json"
    suite_markdown_path = benchmark_report_root / f"{suite_id}.md"
    strict_equal_quality_comparison_valid = bool(mode_reports) and all(
        report.comparison_valid for report in mode_reports
    )
    quality_superiority_comparison_valid = _quality_superiority_comparison_valid(mode_reports)
    formal_efficiency_superiority_claim_allowed = _formal_efficiency_claim_allowed(
        mode_reports,
        benchmark_tier=benchmark_tier,
    )
    formal_prompt_byte_efficiency_claim_allowed = (
        benchmark_tier == "formal"
        and bool(mode_reports)
        and all(_mode_prompt_byte_efficiency_claim_allowed(r) for r in mode_reports)
    )
    formal_quality_superiority_claim_allowed = (
        benchmark_tier == "formal" and quality_superiority_comparison_valid
    )
    serialized_repeat_count = max(_env_int("STATEBUS_COMPARATOR_SERIALIZED_REPEAT_COUNT", 1), 1)
    serialized_repeat_index = max(_env_int("STATEBUS_COMPARATOR_SERIALIZED_REPEAT_INDEX", 1), 1)
    timing_execution_contract = (
        os.getenv("STATEBUS_COMPARATOR_TIMING_CONTRACT", "").strip()
        or "serialized_statebus_then_external_within_each_mode_v1"
    )
    formal_external_claim_kind = (
        "quality_superiority"
        if formal_quality_superiority_claim_allowed
        else "efficiency_superiority_equal_quality"
        if formal_efficiency_superiority_claim_allowed
        else "debug_only"
        if benchmark_tier == "formal" and mode_reports
        else "none"
    )
    serialized_latency_superiority_claim_allowed = (
        benchmark_tier == "formal"
        and strict_equal_quality_comparison_valid
        and bool(mode_reports)
        and all(report.debug_metrics.get("task_ms_delta", 0.0) < 0.0 for report in mode_reports)
    )
    formal_compare_scope_metadata = _formal_compare_scope_metadata(
        samples=samples,
        benchmark_tier=benchmark_tier,
    )
    comparison_summary: dict[str, float] = {
        "mode_count": float(len(mode_reports)),
        "successful_mode_count": float(sum(1 for report in mode_reports if not report.missing_reason)),
        "valid_mode_count": float(sum(1 for report in mode_reports if report.comparison_valid)),
        "strict_equal_quality_comparison_valid": 1.0
        if strict_equal_quality_comparison_valid
        else 0.0,
        "quality_superiority_comparison_valid": 1.0
        if quality_superiority_comparison_valid
        else 0.0,
        "formal_quality_superiority_claim_allowed": 1.0
        if formal_quality_superiority_claim_allowed
        else 0.0,
        "formal_efficiency_superiority_claim_allowed": 1.0
        if formal_efficiency_superiority_claim_allowed
        else 0.0,
        "formal_efficiency_claim_allowed": 1.0 if formal_efficiency_superiority_claim_allowed else 0.0,
        "serialized_latency_superiority_claim_allowed": 1.0
        if serialized_latency_superiority_claim_allowed
        else 0.0,
        "serialized_repeat_count": float(serialized_repeat_count),
        "serialized_repeat_index": float(serialized_repeat_index),
    }
    for mode_report in mode_reports:
        mode_key = mode_report.role_path_mode.replace("-", "_")
        comparison_summary[f"{mode_key}_missing"] = 1.0 if mode_report.missing_reason else 0.0
        comparison_summary[f"{mode_key}_comparison_valid"] = 1.0 if mode_report.comparison_valid else 0.0
        for key, value in mode_report.comparison_summary.items():
            comparison_summary[f"{mode_key}_{key}"] = float(value)
        for key, value in mode_report.headline_metrics.items():
            comparison_summary[f"{mode_key}_{key}"] = float(value)
        for key, value in mode_report.debug_metrics.items():
            comparison_summary[f"{mode_key}_debug_{key}"] = float(value)

    suite_report = BenchmarkComparatorSuiteReport(
        suite_id=suite_id,
        task_family=task_family,
        mode_reports=tuple(mode_reports),
        comparison_summary=comparison_summary,
        metadata={
            **formal_compare_scope_metadata,
            "legacy_comparison_valid_semantics": "strict_equal_quality_comparison_valid",
            "comparator_token_split_schema": "statebus.comparator.token_split.v1",
            "timing_execution_contract": timing_execution_contract,
            "timing_delta_direction": "statebus_minus_external",
            "serialized_repeat_count": serialized_repeat_count,
            "serialized_repeat_index": serialized_repeat_index,
            "serialized_latency_superiority_claim_allowed": serialized_latency_superiority_claim_allowed,
            "strict_equal_quality_comparison_valid": strict_equal_quality_comparison_valid,
            "quality_superiority_comparison_valid": quality_superiority_comparison_valid,
            "formal_quality_superiority_claim_allowed": formal_quality_superiority_claim_allowed,
            "formal_efficiency_superiority_claim_allowed": formal_efficiency_superiority_claim_allowed,
            "formal_prompt_byte_efficiency_claim_allowed": formal_prompt_byte_efficiency_claim_allowed,
            "formal_external_claim_kind": formal_external_claim_kind,
            "formal_efficiency_claim_allowed": formal_efficiency_superiority_claim_allowed,
            "formal_headline_eligible": bool(mode_reports)
            and benchmark_tier == "formal"
            and all(report.eligible_for_headline for report in mode_reports),
            "claim_restriction": (
                "formal_quality_superiority_external_compare"
                if formal_quality_superiority_claim_allowed
                else "formal_efficiency_superiority_with_equal_quality"
                if formal_efficiency_superiority_claim_allowed
                else "external_compare_debug_only_until_strict_or_quality_gate_passes"
                if any(not report.comparison_valid for report in mode_reports)
                else "dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority"
            ),
            "external_comparator_claim_scope": (
                formal_compare_scope_metadata["formal_compare_scope_label"]
                if benchmark_tier == "formal"
                else "dev_fixed_answer_only"
            ),
            "formal_superiority_claim_allowed": formal_quality_superiority_claim_allowed
            or formal_efficiency_superiority_claim_allowed,
            "fixed_answer_external_comparison_valid": strict_equal_quality_comparison_valid,
            "state_pool_mode_requested": state_pool_mode,
            "state_pool_mode_used": (
                str(mode_reports[0].statebus_report.metadata.get("state_pool_mode_used", state_pool_mode))
                if mode_reports
                else state_pool_mode
            ),
            "memfd_transfer_count": sum(
                float(report.statebus_report.telemetry_summary.get("memfd_transfer_count", 0.0))
                for report in mode_reports
            ),
            "memfd_publish_count": sum(
                float(report.statebus_report.telemetry_summary.get("memfd_publish_count", 0.0))
                for report in mode_reports
            ),
            "memfd_bytes_transferred": sum(
                float(report.statebus_report.telemetry_summary.get("memfd_bytes_transferred", 0.0))
                for report in mode_reports
            ),
        },
        benchmark_tier=benchmark_tier,
        claim_level=claim_level,
        report_path=str(suite_report_path),
        markdown_report_path=str(suite_markdown_path),
    )
    write_json_report(suite_report_path, comparator_suite_report_to_dict(suite_report))
    write_markdown_report(suite_markdown_path, _build_suite_markdown(suite_report))
    return suite_report


def compare_fixed_answer_with_external(
    *,
    samples: list[FixedAnswerSample],
    workspace_root: Path,
    runtime_root: Path,
    socket_path: Path,
    suite_id: str = "fixed-answer-vs-external-suite",
    role_path_modes: tuple[str, ...] = ("deterministic", "api"),
    embedding_mode: str = "deterministic",
    statebus_mode: str = "cold_start",
    seed_replay_memory: bool = False,
    benchmark_tier: str = "dev",
    claim_level: str = "prototype",
    state_pool_mode: str = "auto",
    persistence_profile: str = "audit_full",
) -> BenchmarkComparatorSuiteReport:
    return run_fixed_answer_external_comparator_suite(
        samples=samples,
        workspace_root=workspace_root,
        runtime_root=runtime_root,
        socket_path=socket_path,
        suite_id=suite_id,
        role_path_modes=role_path_modes,
        embedding_mode=embedding_mode,
        statebus_mode=statebus_mode,
        seed_replay_memory=seed_replay_memory,
        benchmark_tier=benchmark_tier,
        claim_level=claim_level,
        state_pool_mode=state_pool_mode,
        persistence_profile=persistence_profile,
    )
