#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = Path("/home/qcrs/statebus/runs")
DEFAULT_RUN_ROOTS = {
    "core": RUNS_ROOT / "v2-local-api-non-kv-20260709_002546-core",
    "followup": RUNS_ROOT / "v2-local-api-non-kv-followup-20260709_083750",
    "lr01": RUNS_ROOT / "v2-local-api-non-kv-followup-20260709_083750-lr01",
    "flagship": RUNS_ROOT / "v2-local-api-non-kv-followup-20260709_083750-flagship",
    "flagship_family_diag": RUNS_ROOT / "v2-local-api-non-kv-followup-20260709_083750-flagship-families",
    "extras": RUNS_ROOT / "v2-local-api-non-kv-followup-20260709_083750-extras",
}
DEFAULT_AUDIT_ROOT = (
    REPO_ROOT
    / "docs"
    / "improvement"
    / "20_v2_comprehensive_truth_audit_20260706"
    / "artifacts"
    / "local_api_non_kv_followup_20260709_083750"
)
DEFAULT_OUTPUT_DIR = DEFAULT_AUDIT_ROOT / "deep_mining"


PROMPT_KEYS = (
    "llm_prompt_bytes",
    "llm_prompt_tokens",
    "llm_total_tokens",
    "prompt_visible_total_bytes",
    "prompt_scaffolding_bytes_total",
    "raw_evidence_bytes_seen_by_llm",
    "control_bytes",
    "selected_evidence_bytes",
    "pruning_gain_bytes",
    "llm_prompt_delta_l2_vs_t2",
    "prompt_visible_delta_l2_vs_t2",
    "llm_prompt_saved_by_state_ref_bytes",
    "prompt_visible_saved_by_state_ref_bytes",
    "api_prompt_tokens_delta",
    "api_llm_total_tokens_delta",
    "api_completion_tokens_delta",
    "api_debug_prompt_tokens_delta",
    "api_debug_llm_total_tokens_delta",
)

REPLAY_KEYS = (
    "validated_replay_count",
    "exact_replay_count",
    "validated_downgraded_reuse_count",
    "skipped_step_count",
    "reuse_gain",
    "history_reuse_gain",
    "history_step_reduction_count",
    "artifact_reuse_count",
    "answer_restoration_replay_count",
    "memory_match_count",
    "memory_commit_count",
    "memory_exact_replay_candidate_count",
    "replay_target_round_count",
    "replay_observed_round_count",
    "replay_missing_target_round_count",
    "replay_unexpected_round_count",
    "history_target_round_count",
    "history_observed_reuse_round_count",
    "history_missing_target_round_count",
)

TRANSPORT_KEYS = (
    "state_pool_mode_requested",
    "state_pool_mode_used",
    "transport",
    "memfd_transfer_count",
    "memfd_publish_count",
    "memfd_bytes_transferred",
    "shared_memory_publish_count",
    "mmap_publish_count",
    "semantic_state_transfer_count",
    "semantic_state_ref_count",
    "state_pool_fallback_count",
    "state_pool_memfd_mode_count",
    "state_pool_mmap_mode_count",
    "state_pool_shared_memory_mode_count",
)

OVERHEAD_KEYS = (
    "runtime_driver_stage_ms",
    "persist_and_reload_stage_ms",
    "control_plane_exchange_stage_ms",
    "telemetry_emit_stage_ms",
    "telemetry_event_write_stage_ms",
    "telemetry_fact_write_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "codeact_execution_stage_ms",
    "execution_log_capture_stage_ms",
    "runtime_signature_stage_ms",
    "runtime_commit_finalize_stage_ms",
    "runtime_data_plane_event_stage_ms",
    "runtime_non_executor_stage_ms",
    "runtime_post_executor_stage_ms",
    "runtime_replay_ledger_stage_ms",
    "persist_bundle_write_stage_ms",
    "persist_core_reload_stage_ms",
    "persist_integrity_check_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "persist_session_ledger_reload_stage_ms",
    "persist_validator_reload_stage_ms",
)

QUALITY_KEYS = (
    "quality_floor_pass_count",
    "deterministic_validator_pass",
    "fact_coverage_validator_pass",
    "deterministic_checks_passed_count",
    "fact_coverage_passed_count",
    "invalidated_artifact_count",
    "invalidation_reason_count",
    "candidate_artifact_count",
    "verified_artifact_count",
    "verified_artifact_ref_count",
    "compiler_success_count",
    "validator_report_count",
    "answer_restoration_replay_count",
)

CLAIM_KEYS = (
    "strict_equal_quality_comparison_valid",
    "quality_superiority_comparison_valid",
    "formal_superiority_claim_allowed",
    "formal_quality_superiority_claim_allowed",
    "formal_efficiency_claim_allowed",
    "formal_efficiency_superiority_claim_allowed",
    "serialized_latency_superiority_claim_allowed",
    "claim_restriction",
    "formal_compare_full_registry_coverage",
    "formal_compare_case_count",
    "formal_compare_family_count",
    "formal_external_claim_kind",
    "timing_execution_contract",
    "timing_delta_direction",
)

FAMILY_FIELDS = (
    "family_id",
    "task_family",
    "group",
    "suite_id",
    "stage",
    "source",
    "mode",
    "profile",
    "stress_pass",
    "stress_fail_reasons",
    "headline_scope",
    "quality_headline_eligible",
    "replay_headline_eligible",
    "replay_gate_reason",
    "claim_tier",
    "claim_level",
    "round_count",
    "dataset_count",
    "L0_case_count",
    "L1_case_count",
    "L2_case_count",
    "L3_case_count",
    "L3_quality_pass_count",
    "L3_validated_replay_count",
    "L3_exact_replay_count",
    "L3_skipped_step_count",
    "reuse_gain",
    "history_reuse_gain",
    "history_step_reduction_count",
    "state_transfer_count",
    "semantic_state_transfer_count",
    "artifact_reuse_count",
    "answer_restoration_replay_count",
    "llm_prompt_delta_l2_vs_t2",
    "prompt_visible_delta_l2_vs_t2",
    "llm_prompt_saved_by_state_ref_bytes",
    "prompt_visible_saved_by_state_ref_bytes",
)

ERROR_PATTERNS = {
    "traceback": re.compile(r"\bTraceback \(most recent call last\):"),
    "value_error": re.compile(r"\bValueError:"),
    "runtime_error": re.compile(r"\bRuntimeError:"),
    "json_parse_failure": re.compile(
        r"JSONDecodeError|json_valid|parse_error|failed to parse|expected json object",
        re.IGNORECASE,
    ),
    "empty_output": re.compile(r"expected json object in llm output: ''|stdout.*empty", re.IGNORECASE),
    "docker_cleanup_noise": re.compile(r"No such exec instance|No such exec|No such container", re.IGNORECASE),
    "validator_failed": re.compile(
        r"validator_failed|quality_floor_fail_reason[\"'=:\s]+(?![\"']{0,2}[,}])|metric_contract_failed",
        re.IGNORECASE,
    ),
    "unsupported_family": re.compile(r"unsupported family|only implemented for .* got|got gridops_world_v1", re.IGNORECASE),
    "no_artifact": re.compile(r"missing artifact root|missing_summary_json|execution_failed_or_missing_summary", re.IGNORECASE),
    "required_stage_fail": re.compile(r"\[fail\].*required|failed required", re.IGNORECASE),
    "stage_fail": re.compile(r"\[fail\]|exit=1|exit `1`", re.IGNORECASE),
}


def _num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1", "y"}:
            return True
        if lowered in {"false", "no", "0", "n"}:
            return False
    return None


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return f"{float(value):.3f}"
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _read_text(path: Path, max_chars: int | None = None) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if max_chars is not None and len(text) > max_chars:
        return text[:max_chars]
    return text


def _load_json(path: Path) -> tuple[Any | None, str]:
    try:
        if path.stat().st_size == 0:
            return None, "empty"
        return json.loads(path.read_text(encoding="utf-8", errors="replace")), ""
    except Exception as exc:  # noqa: BLE001 - artifact miner must preserve parse failures.
        return None, f"{type(exc).__name__}: {exc}"


def _host_path(path_text: str) -> Path:
    if not path_text or path_text == "-":
        return Path(path_text)
    if path_text.startswith("/statebus/runs/"):
        return RUNS_ROOT / path_text.removeprefix("/statebus/runs/")
    if path_text.startswith("/workspace/statebus/project/"):
        return REPO_ROOT / path_text.removeprefix("/workspace/statebus/project/")
    if path_text.startswith("/statebus/project/"):
        return REPO_ROOT / path_text.removeprefix("/statebus/project/")
    return Path(path_text)


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _stage_from_path(root: Path, path: Path) -> str:
    parts = Path(_rel(root, path)).parts
    if len(parts) >= 3 and parts[0] == "artifacts" and parts[1] == "stages":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "work":
        return parts[1]
    if len(parts) >= 2 and parts[0] == "runtime":
        return "runtime-root"
    if len(parts) >= 2 and parts[0] == "workspaces":
        return "workspaces-root"
    return ""


def _family_from_path(path: Path) -> str:
    known = (
        "csv_table_profile",
        "incident_diagnosis",
        "long_doc_table",
        "csv_correlation_replay",
        "cross_period_financial",
        "long_doc_metric_replay",
        "gridops_world",
        "financial_report_analysis",
        "multi_period_trend_analysis",
        "cross_table_join_analysis",
        "conditional_aggregation",
        "anomaly_detection",
    )
    text = str(path)
    for item in known:
        if item in text:
            return item
    return ""


def _walk_dicts(obj: Any, trail: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], dict[str, Any]]]:
    found: list[tuple[tuple[str, ...], dict[str, Any]]] = []
    if isinstance(obj, dict):
        found.append((trail, obj))
        for key, value in obj.items():
            found.extend(_walk_dicts(value, (*trail, str(key))))
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            found.extend(_walk_dicts(value, (*trail, str(idx))))
    return found


def _nested_dicts(item: dict[str, Any]) -> list[dict[str, Any]]:
    out = [item]
    for key in ("metadata", "telemetry_summary", "aggregated_metrics", "waterfall_metrics", "comparison_summary", "collection_summary", "runtime_overhead"):
        value = item.get(key)
        if isinstance(value, dict):
            out.append(value)
    metrics = item.get("metrics")
    if isinstance(metrics, dict):
        out.append(metrics)
    return out


def _first_value(item: dict[str, Any], keys: tuple[str, ...] | list[str], default: Any = "") -> Any:
    for source in _nested_dicts(item):
        for key in keys:
            if key in source and source.get(key) not in (None, ""):
                return source.get(key)
    return default


def _extract_fields(item: dict[str, Any], keys: tuple[str, ...] | list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in keys:
        value = _first_value(item, (key,), None)
        if value is not None:
            result[key] = value
    return result


def _file_type(root: Path, path: Path) -> str:
    rel = Path(_rel(root, path))
    parts = rel.parts
    name = path.name
    if name == "status.tsv":
        return "status_tsv"
    if name == "summary.json":
        return "summary_json"
    if name == "summary.md":
        return "summary_md"
    if len(parts) >= 4 and parts[0] == "artifacts" and parts[1] == "stages" and name == "stdout.json":
        return "stage_stdout_json"
    if len(parts) >= 4 and parts[0] == "artifacts" and parts[1] == "stages" and name == "console.log":
        return "stage_console_log"
    if name == "console.log":
        return "console_log"
    if "benchmark_reports" in parts and path.suffix == ".json":
        return "benchmark_report_json"
    if "benchmark_reports" in parts and path.suffix in {".md", ".markdown"}:
        return "benchmark_evidence_md"
    if name == "telemetry.json" and "logs" in parts:
        return "telemetry_json"
    if name == "artifact_audit.json" and "logs" in parts:
        return "artifact_audit_json"
    if name == "hydration_audit.json" and "logs" in parts:
        return "hydration_audit_json"
    if "prompt_slices" in parts and path.suffix == ".json":
        return "prompt_slice_json"
    if "artifact_invalidations" in parts and path.suffix == ".json":
        return "artifact_invalidation_json"
    if "memory_commits" in parts and path.suffix == ".json":
        return "memory_commit_json"
    if "hydration_accounting_audits" in parts and path.suffix == ".json":
        return "hydration_accounting_audit_json"
    if name == "ref_registry.json":
        return "ref_registry_json"
    if path.suffix == ".json":
        return "other_json"
    if path.suffix == ".log":
        return "other_log"
    return "other"


def _scan_log(path: Path) -> dict[str, Any]:
    result = {
        "has_error": False,
        "categories": [],
        "matches": {},
    }
    if not path.exists() or not path.is_file():
        return result
    categories: list[str] = []
    matches: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                for name, pattern in ERROR_PATTERNS.items():
                    if name in matches:
                        continue
                    if pattern.search(line):
                        categories.append(name)
                        matches[name] = f"{line_no}: {line.strip()[:300]}"
    except Exception as exc:  # noqa: BLE001
        categories.append("log_read_error")
        matches["log_read_error"] = f"{type(exc).__name__}: {exc}"
    result["has_error"] = bool(categories)
    result["categories"] = categories
    result["matches"] = matches
    return result


def _parse_status_rows(label: str, root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for status_path in (root / "status.tsv", root / "artifacts" / "status.tsv"):
        if not status_path.exists():
            continue
        with status_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for raw in reader:
                is_phase = "phase" in raw and "stage" not in raw
                name = raw.get("stage") or raw.get("phase") or ""
                artifact_text = raw.get("artifact", "")
                log_text = raw.get("log_path", "")
                artifact_path = _host_path(artifact_text)
                log_path = _host_path(log_text)
                artifact_exists = bool(artifact_text and artifact_text != "-" and artifact_path.exists())
                stdout_empty = bool(artifact_exists and artifact_path.name == "stdout.json" and artifact_path.stat().st_size == 0)
                artifact_json_ok = None
                parse_error = ""
                if artifact_exists and artifact_path.suffix == ".json":
                    _, parse_error = _load_json(artifact_path)
                    artifact_json_ok = not parse_error
                log_scan = _scan_log(log_path) if log_text and log_text != "-" else {"has_error": False, "categories": [], "matches": {}}
                try:
                    exit_code = int(raw.get("exit_code", "0") or 0)
                except ValueError:
                    exit_code = 999
                required = raw.get("required", "0") == "1"
                row = {
                    "run_label": label,
                    "run_root": str(root),
                    "phase_or_stage": "phase" if is_phase else "stage",
                    "stage": name,
                    "exit_code": exit_code,
                    "required": required,
                    "kind": raw.get("kind", "phase" if is_phase else ""),
                    "duration_s": raw.get("duration_s", ""),
                    "artifact_path": str(artifact_path) if artifact_text and artifact_text != "-" else "",
                    "log_path": str(log_path) if log_text and log_text != "-" else "",
                    "artifact_exists": artifact_exists,
                    "artifact_json_ok": artifact_json_ok,
                    "artifact_parse_error": parse_error,
                    "stdout_empty": stdout_empty,
                    "contains_traceback_or_error": bool(log_scan["has_error"]),
                    "error_categories": ",".join(log_scan["categories"]),
                    "first_error_matches": json.dumps(log_scan["matches"], ensure_ascii=False, sort_keys=True),
                    "optional_failure": bool(exit_code != 0 and not required),
                    "required_failure": bool(exit_code != 0 and required),
                    "note": raw.get("note", ""),
                    "status_path": str(status_path),
                }
                rows.append(row)
    return rows


def _record_metric_rows(
    *,
    rows: list[dict[str, Any]],
    row_type: str,
    keys: tuple[str, ...],
    run_label: str,
    root: Path,
    source: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, (dict, list)):
        return
    for trail, item in _walk_dicts(payload):
        fields = _extract_fields(item, keys)
        if not fields:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
        stage = _stage_from_path(root, source)
        family_id = (
            item.get("family_id")
            or item.get("task_family")
            or metadata.get("family_id")
            or metadata.get("task_family")
            or _family_from_path(source)
        )
        row = {
            "run_label": run_label,
            "stage": stage,
            "source": _rel(root, source),
            "json_path": ".".join(trail[-8:]),
            "family_id": family_id,
            "task_family": item.get("task_family", metadata.get("task_family", "")),
            "suite_id": item.get("suite_id", metadata.get("suite_id", "")),
            "layer": item.get("layer", metadata.get("layer", "")),
            "mode": item.get("role_path_mode", metadata.get("role_path_mode", "")),
            "profile": profile.get("description", item.get("persistence_profile", metadata.get("persistence_profile", ""))),
            "row_type": row_type,
        }
        row.update(fields)
        rows.append(row)


def _layer_metrics_from_evidence(evidence: dict[str, Any], layer_key: str, prefix: str) -> dict[str, Any]:
    layer = evidence.get(layer_key)
    if not isinstance(layer, dict):
        return {}
    return {
        f"{prefix}_case_count": layer.get("case_count"),
        f"{prefix}_quality_pass_count": layer.get("quality_floor_pass_count"),
        f"{prefix}_llm_prompt_bytes": layer.get("llm_prompt_bytes"),
        f"{prefix}_prompt_visible_total_bytes": layer.get("prompt_visible_total_bytes"),
        f"{prefix}_semantic_state_transfer_count": layer.get("semantic_state_transfer_count"),
        f"{prefix}_validated_replay_count": layer.get("validated_replay_count"),
        f"{prefix}_exact_replay_count": layer.get("exact_replay_count"),
        f"{prefix}_skipped_step_count": layer.get("skipped_step_count"),
        f"{prefix}_reuse_gain": layer.get("reuse_gain"),
        f"{prefix}_history_reuse_gain": layer.get("history_reuse_gain"),
        f"{prefix}_history_step_reduction_count": layer.get("history_step_reduction_count"),
        f"{prefix}_artifact_reuse_count": layer.get("artifact_reuse_count"),
        f"{prefix}_answer_restoration_replay_count": layer.get("answer_restoration_replay_count"),
    }


def _record_family_rows(
    *,
    family_rows: list[dict[str, Any]],
    run_label: str,
    root: Path,
    source: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, dict):
        return
    stage = _stage_from_path(root, source)

    for stress_key in ("non_text_state_stress_summary", "stress_summary"):
        stress = payload.get(stress_key)
        if isinstance(stress, dict):
            families = stress.get("families")
            if isinstance(families, list):
                for item in families:
                    if not isinstance(item, dict):
                        continue
                    row = {key: "" for key in FAMILY_FIELDS}
                    row.update(
                        {
                            "run_label": run_label,
                            "stage": stage,
                            "source": _rel(root, source),
                            "family_id": item.get("family_id", ""),
                            "group": item.get("group", ""),
                            "stress_pass": item.get("stress_pass"),
                            "stress_fail_reasons": item.get("stress_fail_reasons", []),
                            "headline_scope": item.get("headline_scope", ""),
                            "quality_headline_eligible": item.get("quality_headline_eligible"),
                            "replay_headline_eligible": item.get("replay_headline_eligible"),
                            "semantic_state_transfer_count": item.get("l2_semantic_state_transfer_count"),
                            "state_transfer_count": item.get("l2_semantic_state_transfer_count"),
                            "llm_prompt_delta_l2_vs_t2": item.get("llm_prompt_delta_l2_vs_t2"),
                            "prompt_visible_delta_l2_vs_t2": item.get("prompt_visible_delta_l2_vs_t2"),
                            "llm_prompt_saved_by_state_ref_bytes": item.get("llm_prompt_saved_by_state_ref_bytes"),
                            "prompt_visible_saved_by_state_ref_bytes": item.get("prompt_visible_saved_by_state_ref_bytes"),
                        }
                    )
                    family_rows.append(row)

    families = payload.get("families")
    if isinstance(families, list):
        for item in families:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            suite = item.get("suite") if isinstance(item.get("suite"), dict) else {}
            row = {key: "" for key in FAMILY_FIELDS}
            row.update(
                {
                    "run_label": run_label,
                    "stage": stage,
                    "source": _rel(root, source),
                    "family_id": item.get("family_id", evidence.get("family_id", "")),
                    "group": item.get("group", ""),
                    "suite_id": suite.get("suite_id", ""),
                    "headline_scope": evidence.get("headline_scope", suite.get("headline_scope", "")),
                    "quality_headline_eligible": evidence.get("quality_headline_eligible", suite.get("eligible_for_quality_headline")),
                    "replay_headline_eligible": evidence.get("replay_headline_eligible", suite.get("eligible_for_replay_headline")),
                    "replay_gate_reason": suite.get("replay_gate_reason", (suite.get("metadata") or {}).get("replay_gate_reason", "")),
                    "claim_tier": (suite.get("evidence_pack") or {}).get("claim_tier", (suite.get("metadata") or {}).get("claim_tier", "")),
                    "round_count": (suite.get("comparison_summary") or {}).get("round_count", (suite.get("metadata") or {}).get("round_count", "")),
                    "dataset_count": len((suite.get("metadata") or {}).get("dataset_ids", []) or []),
                }
            )
            row.update(_layer_metrics_from_evidence(evidence, "l0_internal_pure_text", "L0"))
            row.update(_layer_metrics_from_evidence(evidence, "l1_structured_full_evidence", "L1"))
            row.update(_layer_metrics_from_evidence(evidence, "l2_structured_semantic_state", "L2"))
            row.update(_layer_metrics_from_evidence(evidence, "l3_memory_replay", "L3"))
            l3 = evidence.get("l3_memory_replay") if isinstance(evidence.get("l3_memory_replay"), dict) else {}
            row.update(
                {
                    "L3_case_count": row.get("L3_case_count") or suite.get("L3_case_count", ""),
                    "L3_quality_pass_count": row.get("L3_quality_pass_count") or suite.get("L3_quality_pass_count", ""),
                    "L3_validated_replay_count": row.get("L3_validated_replay_count") or l3.get("validated_replay_count", ""),
                    "L3_exact_replay_count": row.get("L3_exact_replay_count") or l3.get("exact_replay_count", ""),
                    "L3_skipped_step_count": row.get("L3_skipped_step_count") or l3.get("skipped_step_count", ""),
                    "reuse_gain": l3.get("reuse_gain", ""),
                    "history_reuse_gain": l3.get("history_reuse_gain", ""),
                    "history_step_reduction_count": l3.get("history_step_reduction_count", ""),
                    "semantic_state_transfer_count": (evidence.get("l2_structured_semantic_state") or {}).get("semantic_state_transfer_count", ""),
                    "artifact_reuse_count": l3.get("artifact_reuse_count", ""),
                    "answer_restoration_replay_count": l3.get("answer_restoration_replay_count", ""),
                }
            )
            t2 = evidence.get("t2_text_same_semantic_selection") if isinstance(evidence.get("t2_text_same_semantic_selection"), dict) else {}
            delta = t2.get("non_text_transfer_delta_l2_vs_text_same_selection") if isinstance(t2.get("non_text_transfer_delta_l2_vs_text_same_selection"), dict) else {}
            row.update(
                {
                    "llm_prompt_delta_l2_vs_t2": delta.get("llm_prompt_bytes", row.get("llm_prompt_delta_l2_vs_t2", "")),
                    "prompt_visible_delta_l2_vs_t2": delta.get("prompt_visible_total_bytes", row.get("prompt_visible_delta_l2_vs_t2", "")),
                }
            )
            family_rows.append(row)

    family_reports = payload.get("family_reports")
    if isinstance(family_reports, list):
        for item in family_reports:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            comparison = item.get("comparison_summary") if isinstance(item.get("comparison_summary"), dict) else {}
            row = {key: "" for key in FAMILY_FIELDS}
            row.update(
                {
                    "run_label": run_label,
                    "stage": stage,
                    "source": _rel(root, source),
                    "family_id": item.get("task_family", metadata.get("family_id", "")),
                    "task_family": item.get("task_family", ""),
                    "suite_id": item.get("suite_id", ""),
                    "headline_scope": item.get("headline_scope", metadata.get("headline_scope", "")),
                    "quality_headline_eligible": item.get("eligible_for_quality_headline", metadata.get("eligible_for_quality_headline")),
                    "replay_headline_eligible": item.get("eligible_for_replay_headline", metadata.get("eligible_for_replay_headline")),
                    "replay_gate_reason": item.get("replay_gate_reason", metadata.get("replay_gate_reason", "")),
                    "claim_tier": metadata.get("claim_tier", ""),
                    "claim_level": metadata.get("claim_level", ""),
                    "round_count": comparison.get("round_count", metadata.get("round_count", "")),
                    "L3_case_count": item.get("L3_case_count", ""),
                    "L3_quality_pass_count": item.get("L3_quality_pass_count", ""),
                    "reuse_gain": (item.get("waterfall_metrics") or {}).get("L3_reuse_gain", ""),
                    "history_reuse_gain": (item.get("waterfall_metrics") or {}).get("L3_history_reuse_gain", ""),
                    "history_step_reduction_count": (item.get("waterfall_metrics") or {}).get("L3_history_step_reduction_count", ""),
                    "artifact_reuse_count": (item.get("waterfall_metrics") or {}).get("L3_artifact_reuse_count", ""),
                    "answer_restoration_replay_count": (item.get("waterfall_metrics") or {}).get("L3_answer_restoration_replay_count", ""),
                    "semantic_state_transfer_count": (item.get("waterfall_metrics") or {}).get("L2_semantic_state_transfer_count", ""),
                    "state_transfer_count": (item.get("waterfall_metrics") or {}).get("L2_semantic_state_transfer_count", ""),
                }
            )
            family_rows.append(row)


def _record_quality_rows(
    *,
    quality_rows: list[dict[str, Any]],
    failed_cases: list[dict[str, Any]],
    run_label: str,
    root: Path,
    source: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, (dict, list)):
        return
    for trail, item in _walk_dicts(payload):
        if not isinstance(item, dict):
            continue
        if not any(key in item for key in ("quality_floor_breakdown", "quality_floor", "telemetry_summary", "cases")):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        quality = item.get("quality_floor") if isinstance(item.get("quality_floor"), dict) else {}
        telemetry = item.get("telemetry_summary") if isinstance(item.get("telemetry_summary"), dict) else {}
        breakdown = item.get("quality_floor_breakdown") if isinstance(item.get("quality_floor_breakdown"), dict) else {}
        row = {
            "run_label": run_label,
            "stage": _stage_from_path(root, source),
            "source": _rel(root, source),
            "json_path": ".".join(trail[-8:]),
            "family_id": item.get("task_family", metadata.get("family_id", _family_from_path(source))),
            "layer": item.get("layer", metadata.get("layer", "")),
            "suite_id": item.get("suite_id", metadata.get("suite_id", "")),
            "quality_floor_pass": quality.get("quality_floor_pass", ""),
            "quality_floor_fail_reason": quality.get("quality_floor_fail_reason", ""),
        }
        row.update(_extract_fields(item, QUALITY_KEYS))
        row.update(_extract_fields(telemetry, QUALITY_KEYS))
        row.update(_extract_fields(breakdown, QUALITY_KEYS))
        if any(value not in ("", None) for value in row.values()):
            quality_rows.append(row)
        cases = item.get("cases")
        if isinstance(cases, list):
            for case in cases:
                if not isinstance(case, dict):
                    continue
                q = case.get("quality_floor") if isinstance(case.get("quality_floor"), dict) else {}
                passed = _boolish(q.get("quality_floor_pass"))
                if passed is False or q.get("quality_floor_fail_reason"):
                    failed_cases.append(
                        {
                            "run_label": run_label,
                            "stage": _stage_from_path(root, source),
                            "source": _rel(root, source),
                            "suite_id": item.get("suite_id", ""),
                            "family_id": case.get("task_family", item.get("task_family", metadata.get("family_id", ""))),
                            "layer": item.get("layer", ""),
                            "task_id": case.get("task_id", ""),
                            "replay_class": case.get("replay_class", ""),
                            "quality_floor_pass": q.get("quality_floor_pass", ""),
                            "quality_floor_fail_reason": q.get("quality_floor_fail_reason", ""),
                            "deterministic_checks_passed": q.get("deterministic_checks_passed", ""),
                            "fact_coverage_passed": q.get("fact_coverage_passed", ""),
                        }
                    )


def _record_claim_rows(
    *,
    claim_rows: list[dict[str, Any]],
    run_label: str,
    root: Path,
    source: Path,
    payload: Any,
) -> None:
    if not isinstance(payload, dict):
        return
    fields = _extract_fields(payload, CLAIM_KEYS)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    fields.update({key: metadata[key] for key in CLAIM_KEYS if key in metadata and key not in fields})
    if not fields:
        return
    row = {
        "run_label": run_label,
        "stage": _stage_from_path(root, source),
        "source": _rel(root, source),
        "suite_id": payload.get("suite_id", metadata.get("suite_id", "")),
        "benchmark_tier": payload.get("benchmark_tier", metadata.get("benchmark_tier", "")),
        "state_pool_mode_requested": payload.get("state_pool_mode_requested", metadata.get("state_pool_mode_requested", "")),
        "state_pool_mode_used": payload.get("state_pool_mode_used", metadata.get("state_pool_mode_used", "")),
    }
    row.update(fields)
    claim_rows.append(row)


def _record_sidecar_rows(
    *,
    sidecar_rows: list[dict[str, Any]],
    run_label: str,
    root: Path,
    source: Path,
    file_type: str,
    payload: Any,
) -> None:
    row = {
        "run_label": run_label,
        "stage": _stage_from_path(root, source),
        "source": _rel(root, source),
        "file_type": file_type,
        "family_id": _family_from_path(source),
        "reason": "",
        "status": "",
        "object_kind": "",
        "ref_kind": "",
        "bytes": source.stat().st_size if source.exists() else 0,
    }
    if isinstance(payload, dict):
        row["reason"] = str(payload.get("reason", payload.get("invalidation_reason", payload.get("quality_floor_fail_reason", ""))))
        row["status"] = str(payload.get("status", payload.get("validation_status", payload.get("memory_validation_status", ""))))
        row["object_kind"] = str(payload.get("object_kind", payload.get("artifact_kind", "")))
        row["ref_kind"] = str(payload.get("ref_kind", payload.get("kind", "")))
    sidecar_rows.append(row)


def _write_csv(path: Path, rows: list[dict[str, Any]], preferred_fields: list[str] | tuple[str, ...] = ()) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    field_set: list[str] = []
    for key in preferred_fields:
        if key not in field_set:
            field_set.append(key)
    for row in rows:
        for key in row:
            if key not in field_set:
                field_set.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_set, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _fmt(row.get(key, "")) for key in field_set})


def _render_table(headers: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(value) for value in row) + " |")
    return "\n".join(lines)


def _aggregate_transport(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("run_label", "")),
            str(row.get("stage", "")),
            str(row.get("state_pool_mode_requested", "")),
            str(row.get("transport", "")),
        )
        target = grouped.setdefault(
            key,
            {
                "run_label": key[0],
                "stage": key[1],
                "state_pool_mode_requested": key[2],
                "transport": key[3],
                "row_count": 0,
                "memfd_transfer_count": 0.0,
                "shared_memory_publish_count": 0.0,
                "mmap_publish_count": 0.0,
                "semantic_state_transfer_count": 0.0,
                "state_pool_fallback_count": 0.0,
            },
        )
        target["row_count"] += 1
        for key_name in (
            "memfd_transfer_count",
            "shared_memory_publish_count",
            "mmap_publish_count",
            "semantic_state_transfer_count",
            "state_pool_fallback_count",
        ):
            target[key_name] += _num(row.get(key_name))
    return sorted(grouped.values(), key=lambda item: (item["run_label"], item["stage"], item["state_pool_mode_requested"]))


def _aggregate_errors(stage_rows: list[dict[str, Any]], explicit_errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    counter: Counter[str] = Counter()
    examples: dict[str, dict[str, Any]] = {}
    for row in stage_rows:
        if row.get("stdout_empty"):
            counter["stdout_empty"] += 1
            examples.setdefault("stdout_empty", row)
        if row.get("required_failure"):
            counter["required_stage_fail"] += 1
            examples.setdefault("required_stage_fail", row)
        if row.get("optional_failure"):
            counter["optional_stage_fail"] += 1
            examples.setdefault("optional_stage_fail", row)
        for category in str(row.get("error_categories", "")).split(","):
            if not category:
                continue
            counter[category] += 1
            examples.setdefault(category, row)
    for item in explicit_errors:
        category = item.get("category", "")
        if category:
            counter[category] += 1
            examples.setdefault(category, item)
    for category, count in counter.most_common():
        example = examples.get(category, {})
        rows.append(
            {
                "category": category,
                "count": count,
                "example_run": example.get("run_label", ""),
                "example_stage": example.get("stage", ""),
                "example_path": example.get("log_path", example.get("source", "")),
                "example": example.get("first_error_matches", example.get("match", "")),
            }
        )
    return rows


def _build_cross_run_comparison(
    stage_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    family_rows: list[dict[str, Any]],
    transport_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def find_claim(run_label: str, stage_part: str) -> dict[str, Any] | None:
        for row in claim_rows:
            if row.get("run_label") == run_label and stage_part in str(row.get("stage", "")):
                return row
        return None

    core_lr01_stage = next((row for row in stage_rows if row.get("run_label") == "core" and "lr01_14" in str(row.get("stage", ""))), {})
    follow_lr01 = find_claim("lr01", "lr01_14")
    out.append(
        {
            "comparison": "core_lr01_vs_followup_lr01",
            "left": "core/lr01_14",
            "right": "followup-lr01/lr01_14",
            "finding": "hard external empty-output failure disappeared, but claim gates remain false",
            "left_exit": core_lr01_stage.get("exit_code", ""),
            "left_stdout_empty": core_lr01_stage.get("stdout_empty", ""),
            "right_exit": 0 if follow_lr01 else "",
            "right_formal_superiority_claim_allowed": (follow_lr01 or {}).get("formal_superiority_claim_allowed", ""),
            "right_serialized_latency_superiority_claim_allowed": (follow_lr01 or {}).get("serialized_latency_superiority_claim_allowed", ""),
            "right_claim_restriction": (follow_lr01 or {}).get("claim_restriction", ""),
        }
    )

    def stress_count(run_label: str) -> tuple[float, float]:
        by_family: dict[str, dict[str, Any]] = {}
        for row in family_rows:
            if row.get("run_label") != run_label or row.get("stress_pass") in ("", None):
                continue
            family_id = str(row.get("family_id", ""))
            if family_id and family_id not in by_family:
                by_family[family_id] = row
        if not by_family:
            return (0.0, 0.0)
        rows = list(by_family.values())
        return (sum(1 for row in rows if _boolish(row.get("stress_pass")) is True), float(len(rows)))

    core_pass, core_total = stress_count("core")
    flag_pass, flag_total = stress_count("flagship")
    diag_pass, diag_total = stress_count("flagship_family_diag")
    out.append(
        {
            "comparison": "core_flagship_vs_followup_flagship_vs_diag",
            "left": "core flagship stress",
            "right": "follow-up flagship + isolated diagnostics",
            "finding": "full follow-up flagship is 2/6 stress pass; isolated diag turns long_doc_metric_replay_v1 into a pass while incident and cross_period still fail different gates",
            "core_stress_pass": core_pass,
            "core_stress_total": core_total,
            "flagship_stress_pass": flag_pass,
            "flagship_stress_total": flag_total,
            "diag_stress_pass": diag_pass,
            "diag_stress_total": diag_total,
        }
    )

    shared = [
        row
        for row in transport_rows
        if row.get("run_label") == "extras" and "formal_api_local_shared_memory" in str(row.get("stage", ""))
    ]
    memfd_bal = [
        row
        for row in transport_rows
        if row.get("run_label") == "extras" and "formal_api_local_memfd_benchmark_balanced" in str(row.get("stage", ""))
    ]
    out.append(
        {
            "comparison": "extras_shared_memory_vs_memfd_benchmark_balanced",
            "left": "x21/x23b shared_memory",
            "right": "x24 memfd benchmark_balanced",
            "finding": "both backends complete formal 25-case paths; transport evidence differs by publish/transfer counters, not by quality headline",
            "shared_rows": len(shared),
            "shared_memory_publish_count": sum(_num(row.get("shared_memory_publish_count")) for row in shared),
            "memfd_rows": len(memfd_bal),
            "memfd_transfer_count": sum(_num(row.get("memfd_transfer_count")) for row in memfd_bal),
        }
    )

    return out


def analyze(run_roots: dict[str, Path], output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stage_rows: list[dict[str, Any]] = []
    family_rows: list[dict[str, Any]] = []
    prompt_rows: list[dict[str, Any]] = []
    replay_rows: list[dict[str, Any]] = []
    transport_rows: list[dict[str, Any]] = []
    overhead_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    claim_rows: list[dict[str, Any]] = []
    sidecar_rows: list[dict[str, Any]] = []
    explicit_errors: list[dict[str, Any]] = []
    file_inventory_rows: list[dict[str, Any]] = []
    json_load_errors: list[dict[str, Any]] = []
    file_type_counts: Counter[str] = Counter()
    run_file_counts: dict[str, Counter[str]] = defaultdict(Counter)
    seen_files: set[Path] = set()

    for label, root in run_roots.items():
        if not root.exists():
            continue
        stage_rows.extend(_parse_status_rows(label, root))
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            file_type = _file_type(root, path)
            file_type_counts[file_type] += 1
            run_file_counts[label][file_type] += 1
            file_inventory_rows.append(
                {
                    "run_label": label,
                    "run_root": str(root),
                    "file_type": file_type,
                    "stage": _stage_from_path(root, path),
                    "path": _rel(root, path),
                    "bytes": path.stat().st_size,
                }
            )
            if file_type in {"stage_console_log", "console_log"}:
                scan = _scan_log(path)
                for category in scan["categories"]:
                    explicit_errors.append(
                        {
                            "run_label": label,
                            "stage": _stage_from_path(root, path),
                            "source": _rel(root, path),
                            "category": category,
                            "match": scan["matches"].get(category, ""),
                        }
                    )
                continue
            if not file_type.endswith("_json") and file_type != "other_json":
                continue
            should_load = file_type in {
                "summary_json",
                "stage_stdout_json",
                "benchmark_report_json",
                "telemetry_json",
                "artifact_audit_json",
                "hydration_audit_json",
                "prompt_slice_json",
                "artifact_invalidation_json",
                "memory_commit_json",
                "hydration_accounting_audit_json",
                "ref_registry_json",
            }
            if not should_load:
                continue
            payload, error = _load_json(path)
            if error:
                json_load_errors.append(
                    {
                        "run_label": label,
                        "stage": _stage_from_path(root, path),
                        "file_type": file_type,
                        "path": _rel(root, path),
                        "error": error,
                    }
                )
                if error == "empty":
                    explicit_errors.append(
                        {
                            "run_label": label,
                            "stage": _stage_from_path(root, path),
                            "source": _rel(root, path),
                            "category": "stdout_empty" if path.name == "stdout.json" else "json_empty",
                            "match": "0 byte JSON artifact",
                        }
                    )
                else:
                    explicit_errors.append(
                        {
                            "run_label": label,
                            "stage": _stage_from_path(root, path),
                            "source": _rel(root, path),
                            "category": "json_parse_failure",
                            "match": error,
                        }
                    )
                continue
            _record_family_rows(family_rows=family_rows, run_label=label, root=root, source=path, payload=payload)
            _record_metric_rows(rows=prompt_rows, row_type=file_type, keys=PROMPT_KEYS, run_label=label, root=root, source=path, payload=payload)
            _record_metric_rows(rows=replay_rows, row_type=file_type, keys=REPLAY_KEYS, run_label=label, root=root, source=path, payload=payload)
            _record_metric_rows(rows=transport_rows, row_type=file_type, keys=TRANSPORT_KEYS, run_label=label, root=root, source=path, payload=payload)
            _record_metric_rows(rows=overhead_rows, row_type=file_type, keys=OVERHEAD_KEYS, run_label=label, root=root, source=path, payload=payload)
            _record_quality_rows(quality_rows=quality_rows, failed_cases=failed_cases, run_label=label, root=root, source=path, payload=payload)
            _record_claim_rows(claim_rows=claim_rows, run_label=label, root=root, source=path, payload=payload)
            if file_type in {
                "artifact_invalidation_json",
                "memory_commit_json",
                "hydration_accounting_audit_json",
                "artifact_audit_json",
                "hydration_audit_json",
                "ref_registry_json",
            }:
                _record_sidecar_rows(sidecar_rows=sidecar_rows, run_label=label, root=root, source=path, file_type=file_type, payload=payload)

    transport_summary_rows = _aggregate_transport(transport_rows)
    error_rows = _aggregate_errors(stage_rows, explicit_errors)
    cross_run_rows = _build_cross_run_comparison(stage_rows, claim_rows, family_rows, transport_rows)

    _write_csv(output_dir / "stage_inventory.csv", stage_rows)
    _write_csv(output_dir / "file_inventory.csv", file_inventory_rows)
    _write_csv(output_dir / "family_matrix.csv", family_rows, ("run_label", *FAMILY_FIELDS))
    _write_csv(output_dir / "prompt_token_byte_matrix.csv", prompt_rows)
    _write_csv(output_dir / "replay_reuse_matrix.csv", replay_rows)
    _write_csv(output_dir / "state_transport_backend_matrix.csv", transport_rows)
    _write_csv(output_dir / "state_transport_backend_summary.csv", transport_summary_rows)
    _write_csv(output_dir / "runtime_overhead_matrix.csv", overhead_rows)
    _write_csv(output_dir / "quality_artifact_validation_matrix.csv", quality_rows)
    _write_csv(output_dir / "failed_validator_cases.csv", failed_cases)
    _write_csv(output_dir / "claim_validity_matrix.csv", claim_rows)
    _write_csv(output_dir / "sidecar_artifact_matrix.csv", sidecar_rows)
    _write_csv(output_dir / "error_taxonomy.csv", error_rows)
    _write_csv(output_dir / "json_load_errors.csv", json_load_errors)
    _write_csv(output_dir / "cross_run_comparison.csv", cross_run_rows)

    run_file_counts_json = {
        label: dict(counter)
        for label, counter in sorted(run_file_counts.items())
    }
    stage_counter = Counter()
    for row in stage_rows:
        if row.get("phase_or_stage") == "stage":
            stage_counter["stage"] += 1
        else:
            stage_counter["phase"] += 1
        if row.get("required_failure"):
            stage_counter["required_failure"] += 1
        if row.get("optional_failure"):
            stage_counter["optional_failure"] += 1

    summary = {
        "schema_version": "statebus.v2_local_api_non_kv_followup_mining.v1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "run_roots": {label: str(path) for label, path in run_roots.items() if path.exists()},
        "output_dir": str(output_dir),
        "counts": {
            "scanned_file_count": len(seen_files),
            "stage_or_phase_row_count": len(stage_rows),
            "stage_count": stage_counter["stage"],
            "phase_count": stage_counter["phase"],
            "required_failure_count": stage_counter["required_failure"],
            "optional_failure_count": stage_counter["optional_failure"],
            "file_type_counts": dict(file_type_counts),
            "run_file_type_counts": run_file_counts_json,
            "json_load_error_count": len(json_load_errors),
            "family_matrix_rows": len(family_rows),
            "prompt_matrix_rows": len(prompt_rows),
            "replay_matrix_rows": len(replay_rows),
            "transport_matrix_rows": len(transport_rows),
            "runtime_overhead_rows": len(overhead_rows),
            "quality_rows": len(quality_rows),
            "failed_validator_case_rows": len(failed_cases),
            "claim_rows": len(claim_rows),
            "sidecar_rows": len(sidecar_rows),
            "error_taxonomy_categories": len(error_rows),
        },
        "stage_failures": [row for row in stage_rows if row.get("exit_code") != 0],
        "error_taxonomy": error_rows,
        "claim_gate_failures": [
            row
            for row in claim_rows
            if str(row.get("formal_superiority_claim_allowed", "")).lower() in {"false", "0"}
            or str(row.get("serialized_latency_superiority_claim_allowed", "")).lower() in {"false", "0"}
            or row.get("claim_restriction")
        ],
        "cross_run_comparison": cross_run_rows,
        "output_files": {
            "stage_inventory_csv": str(output_dir / "stage_inventory.csv"),
            "family_matrix_csv": str(output_dir / "family_matrix.csv"),
            "prompt_token_byte_matrix_csv": str(output_dir / "prompt_token_byte_matrix.csv"),
            "replay_reuse_matrix_csv": str(output_dir / "replay_reuse_matrix.csv"),
            "state_transport_backend_matrix_csv": str(output_dir / "state_transport_backend_matrix.csv"),
            "runtime_overhead_matrix_csv": str(output_dir / "runtime_overhead_matrix.csv"),
            "quality_artifact_validation_matrix_csv": str(output_dir / "quality_artifact_validation_matrix.csv"),
            "claim_validity_matrix_csv": str(output_dir / "claim_validity_matrix.csv"),
            "error_taxonomy_csv": str(output_dir / "error_taxonomy.csv"),
            "cross_run_comparison_csv": str(output_dir / "cross_run_comparison.csv"),
        },
    }
    (output_dir / "deep_mining_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_markdown_readout(output_dir / "deep_mining_readout.md", summary, stage_rows, error_rows, claim_rows, family_rows, cross_run_rows)
    return summary


def _write_markdown_readout(
    path: Path,
    summary: dict[str, Any],
    stage_rows: list[dict[str, Any]],
    error_rows: list[dict[str, Any]],
    claim_rows: list[dict[str, Any]],
    family_rows: list[dict[str, Any]],
    cross_run_rows: list[dict[str, Any]],
) -> None:
    counts = summary["counts"]
    failed_stage_rows = [row for row in stage_rows if row.get("exit_code") != 0]
    def unique_stress_rows(label: str) -> list[dict[str, Any]]:
        by_family: dict[str, dict[str, Any]] = {}
        for row in family_rows:
            if row.get("run_label") != label or row.get("stress_pass") in ("", None):
                continue
            family_id = str(row.get("family_id", ""))
            if family_id and family_id not in by_family:
                by_family[family_id] = row
        return list(by_family.values())

    flagship_stress = unique_stress_rows("flagship")
    diag_stress = unique_stress_rows("flagship_family_diag")
    lines = [
        "# StateBus v2 local API non-KV follow-up deep mining readout",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Scanned files: `{counts['scanned_file_count']}`",
        f"- Stage rows: `{counts['stage_count']}`; phase rows: `{counts['phase_count']}`",
        f"- Stage stdout JSON: `{counts['file_type_counts'].get('stage_stdout_json', 0)}`",
        f"- Benchmark report JSON: `{counts['file_type_counts'].get('benchmark_report_json', 0)}`",
        f"- Telemetry JSON: `{counts['file_type_counts'].get('telemetry_json', 0)}`",
        f"- Prompt slice JSON: `{counts['file_type_counts'].get('prompt_slice_json', 0)}`",
        f"- JSON load errors: `{counts['json_load_error_count']}`",
        "",
        "## Stage Failures",
    ]
    if failed_stage_rows:
        lines.append(
            _render_table(
                ["Run", "Stage/Phase", "Required", "Exit", "Optional Fail", "Required Fail", "Categories"],
                [
                    [
                        row.get("run_label", ""),
                        row.get("stage", ""),
                        row.get("required", ""),
                        row.get("exit_code", ""),
                        row.get("optional_failure", ""),
                        row.get("required_failure", ""),
                        row.get("error_categories", ""),
                    ]
                    for row in failed_stage_rows
                ],
            )
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Error Taxonomy"])
    if error_rows:
        lines.append(
            _render_table(
                ["Category", "Count", "Example Run", "Example Stage", "Example Path"],
                [
                    [
                        row.get("category", ""),
                        row.get("count", ""),
                        row.get("example_run", ""),
                        row.get("example_stage", ""),
                        row.get("example_path", ""),
                    ]
                    for row in error_rows
                ],
            )
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Claim Gates"])
    selected_claims = [
        row
        for row in claim_rows
        if "compare" in str(row.get("stage", "")) or "latency" in str(row.get("stage", ""))
    ][:30]
    if selected_claims:
        lines.append(
            _render_table(
                ["Run", "Stage", "Strict Equal", "Quality Superiority", "Formal Claim", "Latency Claim", "Restriction"],
                [
                    [
                        row.get("run_label", ""),
                        row.get("stage", ""),
                        row.get("strict_equal_quality_comparison_valid", ""),
                        row.get("quality_superiority_comparison_valid", ""),
                        row.get("formal_superiority_claim_allowed", ""),
                        row.get("serialized_latency_superiority_claim_allowed", ""),
                        row.get("claim_restriction", ""),
                    ]
                    for row in selected_claims
                ],
            )
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Flagship Stress"])
    for title, rows in (("Full follow-up flagship", flagship_stress), ("Isolated failed-family diagnostics", diag_stress)):
        lines.append(f"### {title}")
        if rows:
            lines.append(
                _render_table(
                    ["Family", "Pass", "Reasons", "Quality", "Replay", "LLM Saved", "Visible Saved"],
                    [
                        [
                            row.get("family_id", ""),
                            row.get("stress_pass", ""),
                            row.get("stress_fail_reasons", ""),
                            row.get("quality_headline_eligible", ""),
                            row.get("replay_headline_eligible", ""),
                            row.get("llm_prompt_saved_by_state_ref_bytes", ""),
                            row.get("prompt_visible_saved_by_state_ref_bytes", ""),
                        ]
                        for row in rows
                    ],
                )
            )
        else:
            lines.append("- none")
    lines.extend(["", "## Cross-Run Comparisons"])
    lines.append(
        _render_table(
            ["Comparison", "Finding"],
            [[row.get("comparison", ""), row.get("finding", "")] for row in cross_run_rows],
        )
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only miner for StateBus v2 local API non-KV follow-up artifacts.",
    )
    parser.add_argument(
        "--run-root",
        action="append",
        default=[],
        help="Additional run root as LABEL=PATH. Defaults cover the 20260709 non-KV core/follow-up roots.",
    )
    parser.add_argument(
        "--only-provided-roots",
        action="store_true",
        help="Use only --run-root entries instead of the default 20260709 roots.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory. Default: {DEFAULT_OUTPUT_DIR}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_roots: dict[str, Path] = {} if args.only_provided_roots else dict(DEFAULT_RUN_ROOTS)
    for entry in args.run_root:
        if "=" not in entry:
            raise SystemExit(f"--run-root must be LABEL=PATH, got {entry!r}")
        label, path_text = entry.split("=", 1)
        run_roots[label] = Path(path_text).expanduser().resolve()
    summary = analyze(run_roots=run_roots, output_dir=args.output_dir)
    print(json.dumps({"output_dir": str(args.output_dir), "counts": summary["counts"]}, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
