from __future__ import annotations

import argparse
import csv
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = REPO_ROOT / "runs"

DEFAULT_INPUTS = {
    "communication_authoritative": {
        "report": RUNS_ROOT
        / "superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623"
        / "benchmark_results.json",
        "compare": RUNS_ROOT
        / "superiority_comm_v1_api_repeat3_post_rerun_after_summarizer_patch_rollback_20260623"
        / "benchmark_compare.csv",
    },
    "communication_support": {
        "report": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair"
        / "benchmark_results.json",
        "compare": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_summarizer_schema_native_contract_repair"
        / "benchmark_compare.csv",
    },
    "communication_current_baseline_support": {
        "report": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_protocol_summarizer_authority_split_hotfix"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_protocol_summarizer_authority_split_hotfix"
        / "benchmark_results.json",
        "compare": RUNS_ROOT
        / "superiority_comm_v1_api_repeat1_post_protocol_summarizer_authority_split_hotfix"
        / "benchmark_compare.csv",
    },
    "memory": {
        "report": RUNS_ROOT
        / "superiority_memory_v1_api_repeat3_post_replay_contract_hardening"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "superiority_memory_v1_api_repeat3_post_replay_contract_hardening"
        / "benchmark_results.json",
        "compare": RUNS_ROOT
        / "superiority_memory_v1_api_repeat3_post_replay_contract_hardening"
        / "benchmark_compare.csv",
    },
    "typed_state_consumer": {
        "report": RUNS_ROOT
        / "typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "typed_state_consumer_sensitivity_v3_api_repeat1_current_branch_refresh_20260623"
        / "benchmark_results.json",
    },
    "typed_state_mechanism": {
        "report": RUNS_ROOT
        / "typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623"
        / "benchmark_report.md",
        "results": RUNS_ROOT
        / "typed_state_mechanism_v3_api_repeat1_current_branch_refresh_20260623"
        / "benchmark_results.json",
    },
}

REPORT_FLOAT_PATTERNS = {
    "planner_one_shot_valid_rate": r"Planner one-shot valid rate:\s*`([0-9.]+)`",
    "llm_total_tokens_delta": r"llm_total_tokens_delta \| `?(-?[0-9.]+)`?",
    "task_ms_delta": r"task_ms_delta \| `?(-?[0-9.]+)`?",
    "summarizer_total_tokens_delta": r"summarizer_total_tokens_delta \| `?(-?[0-9.]+)`?",
    "summarize_ms_delta": r"summarize_ms_delta \| `?(-?[0-9.]+)`?",
    "missing_decision_failure_rate": r"missing_decision_failure_rate \| ([0-9.]+) \|",
    "wrong_decision_mistool_rate": r"wrong_decision_mistool_rate \| ([0-9.]+) \|",
}

REPORT_INT_PATTERNS = {
    "planner_repair_attempts": r"Planner repair attempts:\s*`([0-9]+)`",
}

REPORT_STR_PATTERNS = {
    "communication_gate": r"Communication gate:\s*`([^`]+)`",
    "formal_stability_gate": r"Formal stability gate:\s*`([^`]+)`",
    "cross_lane_actual_parity": r"Cross-lane actual parity:\s*`([^`]+)`",
    "memory_replay_gate": r"Memory replay gate:\s*`([^`]+)`",
}


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _artifact_paths(spec: dict[str, Path]) -> list[str]:
    return [_relative(path) for path in spec.values()]


def parse_report_metrics(report_text: str) -> dict[str, object]:
    metrics: dict[str, object] = {}
    for key, pattern in REPORT_FLOAT_PATTERNS.items():
        match = re.search(pattern, report_text)
        if match:
            metrics[key] = float(match.group(1))
    for key, pattern in REPORT_INT_PATTERNS.items():
        match = re.search(pattern, report_text)
        if match:
            metrics[key] = int(match.group(1))
    for key, pattern in REPORT_STR_PATTERNS.items():
        match = re.search(pattern, report_text)
        if match:
            metrics[key] = match.group(1).strip()
    return metrics


def load_benchmark_artifact(paths: dict[str, Path]) -> dict[str, object]:
    report_path = paths["report"]
    results_path = paths["results"]
    compare_path = paths.get("compare")
    report_text = report_path.read_text(encoding="utf-8")
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    compare_rows: list[dict[str, str]] = []
    if compare_path and compare_path.exists():
        with compare_path.open("r", encoding="utf-8", newline="") as handle:
            compare_rows = list(csv.DictReader(handle))
    return {
        "report_path": _relative(report_path),
        "results_path": _relative(results_path),
        "compare_path": _relative(compare_path) if compare_path else None,
        "report_text": report_text,
        "report_metrics": parse_report_metrics(report_text),
        "manifest": payload.get("manifest", {}),
        "summary": payload.get("summary", {}),
        "compare_rows": compare_rows,
    }


def _mode_case_contract(summary: dict[str, object], mode: str) -> dict[str, object]:
    return (
        summary.get(mode, {}).get("misfire_audit", {}).get("case_contract", {})
        if isinstance(summary.get(mode), dict)
        else {}
    )


def _mode_aggregate(summary: dict[str, object], mode: str) -> dict[str, object]:
    return summary.get(mode, {}).get("aggregate", {}) if isinstance(summary.get(mode), dict) else {}


def _mode_stability(summary: dict[str, object], mode: str) -> dict[str, object]:
    return summary.get(mode, {}).get("stability", {}) if isinstance(summary.get(mode), dict) else {}


def _stability_mean(stability: dict[str, object], key: str) -> float:
    value = stability.get(key, {})
    if isinstance(value, dict):
        return _safe_float(value.get("mean"))
    return _safe_float(value)


def _pair_delta(artifact: dict[str, object], metric: str) -> float:
    summary = artifact["summary"]
    text_value = _safe_float(_mode_aggregate(summary, "text").get(metric))
    protocol_value = _safe_float(_mode_aggregate(summary, "protocol").get(metric))
    return protocol_value - text_value


def _pair_stability_delta(artifact: dict[str, object], metric: str) -> float:
    summary = artifact["summary"]
    text_value = _stability_mean(_mode_stability(summary, "text"), metric)
    protocol_value = _stability_mean(_mode_stability(summary, "protocol"), metric)
    return protocol_value - text_value


def _communication_scalar_snapshot(artifact: dict[str, object]) -> dict[str, float]:
    return {
        "llm_total_tokens_delta": _pair_delta(artifact, "llm_total_tokens"),
        "task_ms_delta": _pair_delta(artifact, "task_ms"),
        "planner_total_tokens_delta": _pair_delta(artifact, "planner_total_tokens"),
        "summarizer_total_tokens_delta": _pair_delta(artifact, "summarizer_total_tokens"),
        "planner_ms_delta": _pair_stability_delta(artifact, "planner_ms"),
        "summarize_ms_delta": _pair_stability_delta(artifact, "summarize_ms"),
    }


def _communication_release_item(
    *,
    passed: bool,
    reason: str,
    evidence: dict[str, object],
    artifact_paths: list[str],
) -> dict[str, object]:
    return {
        "passed": bool(passed),
        "reason": reason,
        "evidence": evidence,
        "artifact_paths": artifact_paths,
    }


def build_communication_closure_ledger(
    *,
    communication_authoritative: dict[str, object],
    communication_support: dict[str, object],
) -> dict[str, object]:
    auth_manifest = communication_authoritative["manifest"]
    auth_summary = communication_authoritative["summary"]
    support_manifest = communication_support["manifest"]
    support_summary = communication_support["summary"]
    auth_metrics = _communication_scalar_snapshot(communication_authoritative)
    support_metrics = _communication_scalar_snapshot(communication_support)
    auth_report = communication_authoritative["report_metrics"]
    support_report = communication_support["report_metrics"]
    auth_case_protocol = _mode_case_contract(auth_summary, "protocol")
    auth_case_text = _mode_case_contract(auth_summary, "text")
    support_case_protocol = _mode_case_contract(support_summary, "protocol")
    support_case_text = _mode_case_contract(support_summary, "text")
    auth_failures = auth_manifest.get("headline_gates", {}).get("communication_gate", {}).get(
        "contest_formal_coverage_gate",
        {},
    )
    auth_parity = auth_manifest.get("cross_lane_actual_parity", {})
    support_parity = support_manifest.get("cross_lane_actual_parity", {})

    active_object_frozen = (
        str(auth_manifest.get("task_pack_type", "")).strip() == "superiority_comm_v1"
        and str(support_manifest.get("task_pack_type", "")).strip() == "superiority_comm_v1"
    )
    repeat_consistency_ok = (
        support_metrics["llm_total_tokens_delta"] < 0.0
        and support_metrics["task_ms_delta"] <= 0.0
        and auth_metrics["llm_total_tokens_delta"] < 0.0
        and auth_metrics["task_ms_delta"] <= 0.0
    )
    aggregate_direction_ok = (
        auth_metrics["llm_total_tokens_delta"] < 0.0
        and auth_metrics["task_ms_delta"] <= 0.0
    )
    planner_stability_ok = (
        _safe_float(auth_report.get("planner_one_shot_valid_rate")) == 1.0
        and _safe_int(auth_report.get("planner_repair_attempts")) == 0
        and _safe_float(support_report.get("planner_one_shot_valid_rate")) == 1.0
        and _safe_int(support_report.get("planner_repair_attempts")) == 0
    )
    quality_floor_ok = all(
        [
            _safe_float(auth_case_protocol.get("wrong_family_rate")) == 0.0,
            _safe_float(auth_case_text.get("wrong_family_rate")) == 0.0,
            _safe_float(support_case_protocol.get("wrong_family_rate")) == 0.0,
            _safe_float(support_case_text.get("wrong_family_rate")) == 0.0,
            _safe_float(auth_case_protocol.get("route_exact_rate"))
            >= _safe_float(auth_case_text.get("route_exact_rate")),
            _safe_float(support_case_protocol.get("route_exact_rate"))
            >= _safe_float(support_case_text.get("route_exact_rate")),
            _safe_float(auth_case_protocol.get("exact_match_rate"))
            >= _safe_float(auth_case_text.get("exact_match_rate")),
            _safe_float(support_case_protocol.get("exact_match_rate"))
            >= _safe_float(support_case_text.get("exact_match_rate")),
        ]
    )
    failure_hygiene_ok = all(
        [
            _safe_int(auth_summary.get("text", {}).get("failure_count")) == 0,
            _safe_int(auth_summary.get("protocol", {}).get("failure_count")) == 0,
            _safe_int(auth_summary.get("text", {}).get("unexpected_task_failure_count")) == 0,
            _safe_int(auth_summary.get("protocol", {}).get("unexpected_task_failure_count")) == 0,
            _safe_int(auth_summary.get("text", {}).get("run_failure_count")) == 0,
            _safe_int(auth_summary.get("protocol", {}).get("run_failure_count")) == 0,
            _safe_int(support_summary.get("text", {}).get("failure_count")) == 0,
            _safe_int(support_summary.get("protocol", {}).get("failure_count")) == 0,
            _safe_int(support_summary.get("text", {}).get("unexpected_task_failure_count")) == 0,
            _safe_int(support_summary.get("protocol", {}).get("unexpected_task_failure_count")) == 0,
            _safe_int(support_summary.get("text", {}).get("run_failure_count")) == 0,
            _safe_int(support_summary.get("protocol", {}).get("run_failure_count")) == 0,
            bool(auth_failures.get("surface_complete")),
            not auth_parity.get("missing_in_text"),
            not auth_parity.get("missing_in_protocol"),
            not support_parity.get("missing_in_text"),
            not support_parity.get("missing_in_protocol"),
        ]
    )
    residual_boundary_ok = all(
        [
            planner_stability_ok,
            repeat_consistency_ok,
            auth_metrics["summarizer_total_tokens_delta"] <= 0.0,
            support_metrics["summarizer_total_tokens_delta"] <= 0.0,
            auth_metrics["summarize_ms_delta"] >= 0.0,
            support_metrics["summarize_ms_delta"] >= 0.0,
        ]
    )
    mismatch_ids = set(str(task_id) for task_id in auth_parity.get("mismatch_task_ids", []))
    parity_isolation_ok = (
        bool(auth_parity.get("applicable"))
        and mismatch_ids.issubset({"rr-billing-clean"})
        and bool(auth_parity.get("shared_task_count")) == bool(auth_failures.get("matched_pair_count"))
        and not bool(auth_manifest.get("cross_lane_actual_parity_headline_blocking", True))
        and quality_floor_ok
    )

    release_ledger = {
        "active_object_frozen": _communication_release_item(
            passed=active_object_frozen,
            reason=(
                "Active communication object remains frozen on superiority_comm_v1."
                if active_object_frozen
                else "Communication active object drifted away from superiority_comm_v1."
            ),
            evidence={
                "authoritative_pack_type": auth_manifest.get("task_pack_type"),
                "support_pack_type": support_manifest.get("task_pack_type"),
            },
            artifact_paths=[
                communication_authoritative["results_path"],
                communication_support["results_path"],
            ],
        ),
        "repeat_consistency_ok": _communication_release_item(
            passed=repeat_consistency_ok,
            reason=(
                "Repeat=1 support and authoritative repeat=3 keep negative llm_total_tokens_delta and non-positive task_ms_delta."
                if repeat_consistency_ok
                else "Repeat direction is not consistently positive across repeat=1 support and authoritative repeat=3."
            ),
            evidence={
                "repeat1": support_metrics,
                "repeat3": auth_metrics,
            },
            artifact_paths=[
                communication_support["results_path"],
                communication_authoritative["results_path"],
                communication_support["compare_path"],
                communication_authoritative["compare_path"],
            ],
        ),
        "aggregate_direction_ok": _communication_release_item(
            passed=aggregate_direction_ok,
            reason=(
                "Authoritative repeat=3 keeps negative llm_total_tokens_delta and non-positive task_ms_delta."
                if aggregate_direction_ok
                else "Authoritative repeat=3 no longer preserves the required aggregate direction."
            ),
            evidence=auth_metrics,
            artifact_paths=[
                communication_authoritative["results_path"],
                communication_authoritative["compare_path"],
            ],
        ),
        "planner_stability_ok": _communication_release_item(
            passed=planner_stability_ok,
            reason=(
                "Planner is flattened at 1.00 one-shot valid rate and 0 repair in both support and authoritative artifacts."
                if planner_stability_ok
                else "Planner stability is not yet flattened to 1.00 / 0 repair across the artifact family."
            ),
            evidence={
                "repeat1_planner_one_shot_valid_rate": support_report.get("planner_one_shot_valid_rate"),
                "repeat1_planner_repair_attempts": support_report.get("planner_repair_attempts"),
                "repeat3_planner_one_shot_valid_rate": auth_report.get("planner_one_shot_valid_rate"),
                "repeat3_planner_repair_attempts": auth_report.get("planner_repair_attempts"),
            },
            artifact_paths=[
                communication_support["report_path"],
                communication_authoritative["report_path"],
            ],
        ),
        "quality_floor_ok": _communication_release_item(
            passed=quality_floor_ok,
            reason=(
                "Wrong-family stays at 0 and route/exact quality does not degrade relative to text across support and authoritative artifacts."
                if quality_floor_ok
                else "Quality floor shows wrong-family leakage or route/exact degradation."
            ),
            evidence={
                "repeat1_protocol_case_contract": support_case_protocol,
                "repeat1_text_case_contract": support_case_text,
                "repeat3_protocol_case_contract": auth_case_protocol,
                "repeat3_text_case_contract": auth_case_text,
            },
            artifact_paths=[
                communication_support["results_path"],
                communication_authoritative["results_path"],
            ],
        ),
        "failure_hygiene_ok": _communication_release_item(
            passed=failure_hygiene_ok,
            reason=(
                "No unexpected failures, run failures, row loss, or missing paired rows are visible in the communication artifact family."
                if failure_hygiene_ok
                else "Failure hygiene is not clean: unexpected failures or paired-row coverage issues remain."
            ),
            evidence={
                "repeat1_failure_counts": {
                    "text": support_summary.get("text", {}).get("failure_count"),
                    "protocol": support_summary.get("protocol", {}).get("failure_count"),
                    "text_unexpected": support_summary.get("text", {}).get("unexpected_task_failure_count"),
                    "protocol_unexpected": support_summary.get("protocol", {}).get("unexpected_task_failure_count"),
                },
                "repeat3_failure_counts": {
                    "text": auth_summary.get("text", {}).get("failure_count"),
                    "protocol": auth_summary.get("protocol", {}).get("failure_count"),
                    "text_unexpected": auth_summary.get("text", {}).get("unexpected_task_failure_count"),
                    "protocol_unexpected": auth_summary.get("protocol", {}).get("unexpected_task_failure_count"),
                },
                "repeat3_coverage_gate": auth_failures,
            },
            artifact_paths=[
                communication_support["results_path"],
                communication_authoritative["results_path"],
            ],
        ),
        "residual_boundary_ok": _communication_release_item(
            passed=residual_boundary_ok,
            reason=(
                "Residual is bounded to summarize_ms while planner is flat and summarizer tokens already favor protocol."
                if residual_boundary_ok
                else "Residual is not yet bounded to a summarize_ms-only surface."
            ),
            evidence={
                "repeat1": {
                    "summarizer_total_tokens_delta": support_metrics["summarizer_total_tokens_delta"],
                    "summarize_ms_delta": support_metrics["summarize_ms_delta"],
                    "planner_ms_delta": support_metrics["planner_ms_delta"],
                },
                "repeat3": {
                    "summarizer_total_tokens_delta": auth_metrics["summarizer_total_tokens_delta"],
                    "summarize_ms_delta": auth_metrics["summarize_ms_delta"],
                    "planner_ms_delta": auth_metrics["planner_ms_delta"],
                },
            },
            artifact_paths=[
                communication_support["results_path"],
                communication_authoritative["results_path"],
                communication_support["compare_path"],
                communication_authoritative["compare_path"],
            ],
        ),
        "parity_isolation_ok": _communication_release_item(
            passed=parity_isolation_ok,
            reason=(
                "Cross-lane parity divergence is isolated to rr-billing-clean and remains diagnostic-only without polluting quality floor."
                if parity_isolation_ok
                else "Parity divergence is not isolated enough to remain diagnostic-only."
            ),
            evidence={
                "cross_lane_actual_parity_headline_blocking": auth_manifest.get(
                    "cross_lane_actual_parity_headline_blocking"
                ),
                "mismatch_task_ids": sorted(mismatch_ids),
                "shared_task_count": auth_parity.get("shared_task_count"),
                "matched_pair_count": auth_failures.get("matched_pair_count"),
            },
            artifact_paths=[
                communication_authoritative["results_path"],
                communication_authoritative["report_path"],
            ],
        ),
    }

    release_ledger_all_passed = all(
        bool(item.get("passed")) for item in release_ledger.values()
    )
    authoritative_gate_status = str(auth_report.get("communication_gate", "")).strip() or (
        "pass"
        if bool(auth_manifest.get("headline_gates", {}).get("communication_gate", {}).get("allowed"))
        else "withheld"
    )
    withheld_reasons = list(
        auth_manifest.get("headline_gates", {})
        .get("communication_gate", {})
        .get("withheld_reasons", [])
    )
    if authoritative_gate_status != "pass" and not withheld_reasons:
        withheld_reasons = [
            key
            for key, item in release_ledger.items()
            if not bool(item.get("passed"))
        ]
    if authoritative_gate_status != "pass" and release_ledger_all_passed and not withheld_reasons:
        withheld_reasons = ["authoritative_gate_still_withheld"]
    if authoritative_gate_status == "pass":
        summary_sentence = (
            "Communication gate is already released: repeat=1 and repeat=3 stay positive, planner is flat, and residuals are bounded."
        )
    elif release_ledger_all_passed:
        summary_sentence = (
            "Frozen release-ledger items are satisfied, but the authoritative communication artifact still reports withheld under the current gate semantics."
        )
    else:
        summary_sentence = (
            "Communication remains withheld because at least one frozen release-ledger item is still unmet."
        )

    return {
        "release_ledger": release_ledger,
        "release_ledger_all_passed": release_ledger_all_passed,
        "communication_gate_status": authoritative_gate_status,
        "formal_stability_gate_status": str(auth_report.get("formal_stability_gate", "")).strip()
        or (
            "pass"
            if bool(auth_manifest.get("headline_gates", {}).get("formal_stability_gate", {}).get("allowed"))
            else "not_yet"
        ),
        "withheld_reasons": withheld_reasons,
        "authoritative_observed_status": {
            "communication_gate": authoritative_gate_status,
            "formal_stability_gate": auth_report.get("formal_stability_gate"),
            "cross_lane_actual_parity": auth_report.get("cross_lane_actual_parity"),
        },
        "summary_sentence": summary_sentence,
    }


def _current_git_clean() -> bool:
    try:
        status = subprocess.run(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return False
    return status == ""


def build_repeat10_admission_verdict(
    *,
    communication_closure: dict[str, object],
) -> dict[str, object]:
    object_definition_frozen = bool(
        communication_closure["release_ledger"]["active_object_frozen"]["passed"]
    )
    communication_gate_already_passed = (
        str(communication_closure.get("communication_gate_status", "")).strip() == "pass"
    )
    only_remaining_issue_is_repeat_depth = bool(
        communication_gate_already_passed
        and str(communication_closure.get("formal_stability_gate_status", "")).strip() == "not_yet"
    )
    no_unfrozen_hotfix_in_flight = _current_git_clean()
    admitted = bool(
        object_definition_frozen
        and communication_gate_already_passed
        and only_remaining_issue_is_repeat_depth
        and no_unfrozen_hotfix_in_flight
    )
    if admitted:
        summary_sentence = (
            "Repeat-10 is admitted because communication closure is already released and repeat depth is the only remaining formal-stability question."
        )
    else:
        summary_sentence = (
            "Repeat-10 is not admitted because communication closure is not yet formally released as a passed object-level gate."
        )
    return {
        "admitted": admitted,
        "object_definition_frozen": object_definition_frozen,
        "communication_gate_already_passed": communication_gate_already_passed,
        "only_remaining_issue_is_repeat_depth": only_remaining_issue_is_repeat_depth,
        "no_unfrozen_hotfix_in_flight": no_unfrozen_hotfix_in_flight,
        "summary_sentence": summary_sentence,
    }


def build_memory_final_role_verdict(*, memory_artifact: dict[str, object]) -> dict[str, object]:
    report_metrics = memory_artifact["report_metrics"]
    memory_gate = str(report_metrics.get("memory_replay_gate", "")).strip()
    effect_established = memory_gate == "pass"
    return {
        "role": "required_secondary_verdict",
        "effect_established": effect_established,
        "superiority_established": False,
        "allowed_claims": [
            "runtime replay effect established",
            "exact-replay-backed effect established",
        ],
        "forbidden_claims": [
            "memory superiority established",
            "overall superiority established",
        ],
        "missing_evidence": {
            "net_savings_evidence": True,
            "stability_evidence": True,
            "safety_evidence": True,
        },
        "primary_artifacts": [
            memory_artifact["report_path"],
            memory_artifact["results_path"],
            memory_artifact["compare_path"],
        ],
        "summary_sentence": (
            "Memory remains a required secondary verdict: replay effect is established, but superiority is not."
        ),
    }


def build_typed_state_final_role_verdict(
    *,
    typed_state_mechanism_artifact: dict[str, object],
    typed_state_consumer_artifact: dict[str, object],
) -> dict[str, object]:
    mechanism_summary = typed_state_mechanism_artifact["summary"]["protocol"]
    consumer_summary = typed_state_consumer_artifact["summary"]["protocol"]
    mechanism_case = mechanism_summary.get("misfire_audit", {}).get("case_contract", {})
    mechanism_variants = mechanism_summary.get("mechanism_audit", {}).get("slimming_variants", {})
    consumer_transfer_truth = consumer_summary.get("transfer_truth", {})
    consumer_sensitivity = (
        consumer_summary.get("mechanism_audit", {}).get("typed_state_consumer_sensitivity_v3", {})
    )
    mechanism_established = all(
        [
            _safe_float(mechanism_case.get("route_exact_rate")) == 1.0,
            _safe_float(mechanism_case.get("tool_exact_rate")) == 1.0,
            _safe_float(mechanism_case.get("wrong_family_rate")) == 0.0,
            "state_packet_minimal" in mechanism_variants,
        ]
    )
    minimal_packet_consumed = (
        _safe_float(consumer_transfer_truth.get("typed_executor_minimal_expected_consumption_rate")) > 0.0
    )
    negative_control_triggered = all(
        [
            _safe_float(consumer_sensitivity.get("missing_decision_failure_rate")) == 1.0,
            _safe_float(consumer_sensitivity.get("wrong_decision_mistool_rate")) == 1.0,
        ]
    )
    return {
        "role": "required_secondary_state_transfer_verdict",
        "mechanism_established": mechanism_established,
        "minimal_packet_consumed": minimal_packet_consumed,
        "negative_control_triggered": negative_control_triggered,
        "allowed_claims": [
            "non-text state-transfer mechanism established",
            "minimal decision packet is really consumed",
            "destructive negative controls trigger as contracted",
        ],
        "forbidden_claims": [
            "typed-state is the active communication headline",
            "typed-state alone closes communication superiority",
        ],
        "primary_artifacts": [
            typed_state_mechanism_artifact["report_path"],
            typed_state_mechanism_artifact["results_path"],
            typed_state_consumer_artifact["report_path"],
            typed_state_consumer_artifact["results_path"],
        ],
        "summary_sentence": (
            "Typed-state remains a required secondary state-transfer verdict rather than the communication headline."
        ),
    }


def build_delivery_status(*, repeat10_admission: dict[str, object]) -> dict[str, object]:
    return {
        "host_runnable": True,
        "repeat10_validated": bool(repeat10_admission.get("admitted")),
        "openeuler_validated": False,
    }


def render_final_evidence_program_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render_final_evidence_program_md(payload: dict[str, object]) -> str:
    communication = payload["communication_closure"]
    release_ledger = communication["release_ledger"]
    memory_verdict = payload["memory_final_role"]
    typed_state_verdict = payload["typed_state_final_role"]
    repeat10 = payload["repeat10_admission"]
    delivery_status = payload["delivery_status"]
    lines = [
        "# Final Evidence Program",
        "",
        f"- Generated at: `{datetime.now().isoformat(timespec='seconds')}`",
        f"- Communication gate status: `{communication['communication_gate_status']}`",
        f"- Formal stability gate status: `{communication['formal_stability_gate_status']}`",
        "",
        "## Communication Closure Ledger",
        "",
        "| item | passed | reason |",
        "| --- | --- | --- |",
    ]
    for key, item in release_ledger.items():
        lines.append(
            f"| {key} | {'yes' if item['passed'] else 'no'} | {item['reason']} |"
        )
    lines.extend(
        [
            "",
            f"- Summary: {communication['summary_sentence']}",
            f"- Withheld reasons: `{communication['withheld_reasons']}`",
            "",
            "## Repeat-10 Admission",
            "",
            f"- Admitted: `{'yes' if repeat10['admitted'] else 'no'}`",
            f"- Object definition frozen: `{'yes' if repeat10['object_definition_frozen'] else 'no'}`",
            f"- Communication gate already passed: `{'yes' if repeat10['communication_gate_already_passed'] else 'no'}`",
            f"- Only remaining issue is repeat depth: `{'yes' if repeat10['only_remaining_issue_is_repeat_depth'] else 'no'}`",
            f"- No unfrozen hotfix in flight: `{'yes' if repeat10['no_unfrozen_hotfix_in_flight'] else 'no'}`",
            f"- Summary: {repeat10['summary_sentence']}",
            "",
            "## Memory Final Role",
            "",
            f"- Role: `{memory_verdict['role']}`",
            f"- Effect established: `{'yes' if memory_verdict['effect_established'] else 'no'}`",
            f"- Superiority established: `{'yes' if memory_verdict['superiority_established'] else 'no'}`",
            f"- Allowed claims: `{memory_verdict['allowed_claims']}`",
            f"- Forbidden claims: `{memory_verdict['forbidden_claims']}`",
            "",
            "## Typed-State Final Role",
            "",
            f"- Role: `{typed_state_verdict['role']}`",
            f"- Mechanism established: `{'yes' if typed_state_verdict['mechanism_established'] else 'no'}`",
            f"- Minimal packet consumed: `{'yes' if typed_state_verdict['minimal_packet_consumed'] else 'no'}`",
            f"- Negative control triggered: `{'yes' if typed_state_verdict['negative_control_triggered'] else 'no'}`",
            f"- Allowed claims: `{typed_state_verdict['allowed_claims']}`",
            f"- Forbidden claims: `{typed_state_verdict['forbidden_claims']}`",
            "",
            "## Delivery Status",
            "",
            f"- host_runnable: `{'yes' if delivery_status['host_runnable'] else 'no'}`",
            f"- repeat10_validated: `{'yes' if delivery_status['repeat10_validated'] else 'no'}`",
            f"- openeuler_validated: `{'yes' if delivery_status['openeuler_validated'] else 'no'}`",
            "",
            "## Overall Next Move",
            "",
            f"- {payload['overall_next_move']}",
        ]
    )
    return "\n".join(lines) + "\n"


def build_final_evidence_program(
    *,
    communication_authoritative: dict[str, object],
    communication_support: dict[str, object],
    memory_artifact: dict[str, object],
    typed_state_consumer_artifact: dict[str, object],
    typed_state_mechanism_artifact: dict[str, object],
    input_paths: dict[str, object],
) -> dict[str, object]:
    communication_closure = build_communication_closure_ledger(
        communication_authoritative=communication_authoritative,
        communication_support=communication_support,
    )
    repeat10_admission = build_repeat10_admission_verdict(
        communication_closure=communication_closure,
    )
    memory_final_role = build_memory_final_role_verdict(memory_artifact=memory_artifact)
    typed_state_final_role = build_typed_state_final_role_verdict(
        typed_state_mechanism_artifact=typed_state_mechanism_artifact,
        typed_state_consumer_artifact=typed_state_consumer_artifact,
    )
    delivery_status = build_delivery_status(repeat10_admission=repeat10_admission)
    return {
        "inputs": input_paths,
        "communication_closure": communication_closure,
        "repeat10_admission": repeat10_admission,
        "memory_final_role": memory_final_role,
        "typed_state_final_role": typed_state_final_role,
        "delivery_status": delivery_status,
        "overall_next_move": (
            "Keep the final evidence program as the release ledger source-of-truth, and use it to decide whether any future communication repeat-10 admission review is justified."
        ),
    }


def _commands_md(out_dir: Path) -> str:
    command = [sys.executable, str(Path(__file__).relative_to(REPO_ROOT))]
    lines = [
        "# Commands",
        "",
        f"- `{shlex.join(command)}`",
        f"- output_dir: `{_relative(out_dir)}`",
    ]
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write the frozen final evidence program from current authoritative offline artifacts.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory. Default: runs/final_evidence_program_<timestamp>",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    out_dir = args.out if args.out else RUNS_ROOT / f"final_evidence_program_{timestamp()}"
    ensure_dir(out_dir)

    loaded_inputs = {
        key: load_benchmark_artifact(value)
        for key, value in DEFAULT_INPUTS.items()
        if key != "communication_current_baseline_support"
    }
    input_paths = {
        key: {
            inner_key: _relative(inner_value)
            for inner_key, inner_value in value.items()
            if inner_value.exists()
        }
        for key, value in DEFAULT_INPUTS.items()
    }
    payload = build_final_evidence_program(
        communication_authoritative=loaded_inputs["communication_authoritative"],
        communication_support=loaded_inputs["communication_support"],
        memory_artifact=loaded_inputs["memory"],
        typed_state_consumer_artifact=loaded_inputs["typed_state_consumer"],
        typed_state_mechanism_artifact=loaded_inputs["typed_state_mechanism"],
        input_paths=input_paths,
    )

    (out_dir / "final_evidence_program.json").write_text(
        render_final_evidence_program_json(payload),
        encoding="utf-8",
    )
    (out_dir / "FINAL_EVIDENCE_PROGRAM.md").write_text(
        render_final_evidence_program_md(payload),
        encoding="utf-8",
    )
    (out_dir / "COMMANDS.md").write_text(_commands_md(out_dir), encoding="utf-8")
    print(_relative(out_dir))


if __name__ == "__main__":
    main()
