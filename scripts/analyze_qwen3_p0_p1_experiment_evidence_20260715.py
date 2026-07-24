#!/usr/bin/env python3
"""Static, reproducible evidence audit for the Qwen3 P0/P1 experiment set.

The program never imports StateBus runtime code and only reads its three input
roots.  It intentionally treats summaries as one artifact among many: all
JSON/JSONL files are enumerated and parsed before the stage and claim ledgers
are written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable


DEFAULT_FULL_ROOT = Path("/home/qcrs/statebus/runs/full_qwen3_full_p1_20260715_001059")
DEFAULT_REPAIR_LOG = Path(
    "/home/qcrs/statebus/runs/full_qwen3_full_p1_fix_20260715_001459/logs/01_pytest_v2.log"
)
DEFAULT_P1_ROOT = Path("/home/qcrs/statebus/runs/post_full_p1_qwen3_repaired_20260715_083121")
DEFAULT_OUTPUT_ROOT = Path(
    "docs/improvement/22_qwen3_p0_p1_experiment_evidence_audit_20260715"
)
SCRIPT_VERSION = "20260715.8"
JSON_SUFFIXES = {".json", ".jsonl"}
ROLE_NAMES = ("planner", "retriever", "executor", "summarizer")
CSV_COLUMNS = [
    "run_group", "stage", "variant", "transport", "role_path_mode",
    "embedding_mode", "layer", "semantic_base_layer", "control_lane", "workspace_lane",
    "family", "case_id", "round", "repeat",
    "system_identity", "source_path", "metric_field_paths", "missing_metric_fields",
    "missing_metric_reason", "quality_pass", "replay_class",
    "state_ref_count", "state_bytes", "agent_call_count", "tool_call_count",
    "llm_total_tokens", "prompt_tokens", "completion_tokens", "prompt_bytes",
    "prompt_visible_bytes", "prompt_scaffolding_bytes_total", "external_evidence_bytes",
    "non_external_prompt_visible_bytes", "raw_evidence_bytes_seen_by_llm",
    "selected_evidence_bytes", "full_corpus_bytes", "pruning_gain_bytes",
    "control_bytes", "control_message_count", "rendered_role_request_count",
    "memory_match_count", "memory_ref_count", "memory_candidate_count",
    "exact_replay_count", "validated_replay_count", "answer_restoration_replay_count",
    "artifact_reuse_count", "history_artifact_reuse_count", "history_strategy_reuse_count",
    "skipped_step_count", "reuse_gain", "history_reuse_gain",
    "memfd_bytes_transferred", "logit_state_transfer_count", "logit_state_bytes",
    "wall_time_ms", "state_pool_mode", "fallback_count", "state_pool_fallback_count", "prefix_queries",
    "prefix_hits", "prefix_hit_rate", "output_hash", "notes",
]
TAINT_COLUMNS = [
    "run_group", "stage", "case_id", "role", "request_index", "source_path",
    "fragment_hash", "match_rule", "match_count", "unique_type", "field_path",
    "excerpt", "upstream_source", "role_contract_judgment", "severity",
    "classification", "code_path", "conclusion",
]
CLAIM_COLUMNS = [
    "mechanism", "claim", "code_evidence", "run_evidence", "data_evidence",
    "executed", "artifact_data", "downstream_consumption", "fair_ab_evidence",
    "claim_level", "claim_status", "boundary",
]
ROLE_CASE_COLUMNS = [
    "run_group", "stage", "layer", "family", "case_id", "role", "source_path",
    "role_call_count", "hydrated_bytes", "hydrated_item_count", "memory_bytes",
    "memory_item_count", "artifact_bytes", "artifact_item_count", "text_bytes",
    "text_item_count", "table_bytes", "table_item_count", "state_ref_count",
    "prompt_bytes", "prompt_visible_bytes", "prompt_scaffolding_bytes",
    "non_external_prompt_visible_bytes", "completion_tokens", "replay_class", "quality_pass",
]
TAINT_ROLLUP_COLUMNS = [
    "run_group", "stage", "case_id", "role", "match_rule", "severity",
    "raw_occurrence_count", "unique_fragment_count", "unique_source_count", "conclusion",
]
STAGE_INTEGRITY_COLUMNS = [
    "run_group", "stage", "purpose", "historical_status", "status_tsv_status",
    "stdout_status_signal", "stdout_artifact_status", "stderr_artifact_status",
    "run_log_mentions_stage", "subreport_file_count", "workspace_file_count",
    "workspace_parse_error_count", "artifact_status", "consistency_status", "coverage_status",
    "artifact_file_count", "parse_error_count", "empty_file_count", "statebus_case_records",
    "external_case_records", "quality_numerator", "quality_denominator", "key_metrics",
    "failure_or_anomaly", "integrity_detail", "supported_claim", "unsupported_claim", "artifact_paths",
]
COMPARISON_COLUMNS = [
    "comparison_id", "comparison_scope", "run_group", "stage", "family", "case_id",
    "baseline_layer", "treatment_layer", "baseline_source_path", "treatment_source_path",
    "match_status", "quality_comparable_numerator", "quality_comparable_denominator",
    "baseline_quality_pass", "treatment_quality_pass", "baseline_prompt_visible_bytes",
    "treatment_prompt_visible_bytes", "prompt_visible_bytes_delta",
    "prompt_visible_bytes_reduction_ratio", "baseline_prompt_tokens", "treatment_prompt_tokens",
    "prompt_tokens_delta", "prompt_tokens_reduction_ratio", "baseline_total_tokens",
    "treatment_total_tokens", "total_tokens_delta", "total_tokens_reduction_ratio",
    "baseline_wall_time_ms", "treatment_wall_time_ms", "wall_time_ms_delta",
    "baseline_state_ref_count", "treatment_state_ref_count", "claim_boundary",
]
PREFIX_PAIR_COLUMNS = [
    "repeat_index", "order", "evidence_file", "pair_summary_path", "pair_summary_parse_status",
    "pair_ok", "counter_claim_allowed", "all_completion_contracts_valid",
    "shared_queries", "shared_hits", "shared_hit_rate", "shared_warm_ttft_mean_ms",
    "independent_queries", "independent_hits", "independent_hit_rate",
    "independent_warm_ttft_mean_ms", "shared_minus_independent_warm_ttft_ms",
    "pair_validation_status", "failure_or_anomaly",
]
PREFIX_COUNTER_COLUMNS = [
    "source", "scope", "source_path", "mode", "request_count", "counter_queries",
    "counter_hits", "reported_hit_rate", "recomputed_hit_rate", "hit_rate_matches_report",
    "warm_ttft_mean_ms", "warm_ttft_median_ms", "warm_ttft_p95_ms", "claim_boundary",
]
LATENCY_REPEAT_COLUMNS = [
    "row_type", "metric", "repeat_index", "source_path", "comparison_valid", "value",
    "count", "sum", "median", "p90_linear", "p95_linear", "reported_value",
    "matches_report", "claim_boundary",
]
MECHANISM_COLUMNS = [
    "mechanism", "static_review_evidence", "anchor_static_review_evidence", "executed_path_evidence",
    "artifact_data_evidence", "downstream_consumption_evidence", "fair_ab_evidence",
    "evidence_level", "claim_status", "claim_boundary",
]
CONTEST_COLUMNS = [
    "contest_requirement", "code_mechanism", "raw_experiment_evidence", "proven_content",
    "fairness_or_quality_evidence", "risk_or_gap", "claim_level", "claim_status",
]
LOGIT_PARTICIPATION_COLUMNS = [
    "scope", "primary_metric_row_count", "all_parsed_artifact_count",
    "all_parsed_logit_field_occurrence_count", "positive_transfer_metric_row_count",
    "transfer_count_sum", "logit_byte_measurement_row_count", "logit_byte_sum",
    "entropy_measurement_row_count", "confidence_gate_trigger_sum",
    "configuration_evidence", "actual_generation_evidence", "raw_value_evidence",
    "raw_artifact_paths", "raw_field_paths", "state_ref_registration_evidence",
    "receiver_evidence", "downstream_consumption_evidence",
    "route_tool_retry_fallback_effect_evidence", "fair_ab_evidence", "claim_status",
    "claim_boundary",
]
ISSUE_COLUMNS = [
    "priority", "phenomenon", "root_cause_or_hypothesis", "artifact_evidence", "code_location",
    "conclusion_impact", "severity", "minimum_repair", "regression_risk", "minimum_validation",
]


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def number(value: Any) -> float | None:
    if is_number(value):
        return float(value)
    return None


def as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    return None


def find_value(payload: Any, names: Iterable[str]) -> Any:
    wanted = {name.lower() for name in names}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in wanted:
                return value
        for value in payload.values():
            found = find_value(value, wanted)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = find_value(value, wanted)
            if found is not None:
                return found
    return None


def find_all_values(payload: Any, names: Iterable[str], path: str = "$") -> list[tuple[str, Any]]:
    wanted = {name.lower() for name in names}
    result: list[tuple[str, Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child = f"{path}.{key}"
            if str(key).lower() in wanted:
                result.append((child, value))
            result.extend(find_all_values(value, wanted, child))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            result.extend(find_all_values(value, wanted, f"{path}[{index}]"))
    return result


def classify_file(path: Path) -> str:
    lower = path.as_posix().lower()
    name = path.name.lower()
    if "rendered_llm_requests" in lower or "rendered_request" in name:
        return "rendered_request"
    if "telemetry" in lower:
        return "telemetry"
    if "workspace" in lower and "/inputs/" in lower:
        return "workspace_input"
    if "workspace" in lower and "/outputs/" in lower:
        return "workspace_output"
    if "benchmark_report" in lower or "benchmark_reports" in lower:
        return "benchmark_report"
    if "manifest" in name:
        return "manifest"
    if name.endswith(".jsonl"):
        return "jsonl"
    if name.endswith(".json"):
        return "json"
    if name.endswith(".csv"):
        return "csv"
    if name.endswith(".md"):
        return "md"
    if name.endswith(".log") or name.endswith(".txt"):
        return "log"
    if name.endswith((".yaml", ".yml", ".env")):
        return "configuration"
    return "other"


def relative_stage(path: Path) -> tuple[str | None, str | None, str | None, str | None]:
    """Return stage, layer/variant, case and repeat inferred from an artifact path."""
    parts = path.parts
    stage = None
    variant = None
    case_id = None
    repeat = None
    if "stages" in parts:
        index = parts.index("stages")
        if index + 1 < len(parts):
            stage = parts[index + 1]
        if index + 2 < len(parts) and parts[index + 2].startswith("repeat"):
            repeat = parts[index + 2]
    if "workspaces" in parts:
        index = parts.index("workspaces")
        if index + 1 < len(parts):
            variant = parts[index + 1]
        if index + 2 < len(parts):
            case_id = parts[index + 2]
    if case_id is None and "runtime" in parts:
        index = parts.index("runtime")
        if index + 1 < len(parts):
            variant = variant or parts[index + 1]
    return stage, variant, case_id, repeat


def workspace_lane(path: Path) -> str | None:
    """Return the lane between a workspace root and a case/log directory."""
    parts = path.parts
    if "workspaces" not in parts:
        return None
    index = parts.index("workspaces") + 1
    tail = list(parts[index:])
    for marker in ("logs", "inputs", "outputs", "manifest", "tmp"):
        if marker in tail:
            tail = tail[:tail.index(marker)]
            break
    if len(tail) < 2:
        return None
    # The last component is normally the task workspace. Everything before it
    # identifies the runner/layer/control lane.
    return "/".join(tail[:-1])


def control_lane_for_path(path: Path) -> tuple[str | None, bool]:
    lane = workspace_lane(path)
    if not lane:
        return None, False
    lowered = lane.lower()
    if "text-semantic-selection" in lowered:
        return "text_same_semantic_selection", True
    if "fixed-ladder" in lowered or "continuous-ladder" in lowered:
        return "ladder", False
    if "carrier-compare" in lowered:
        return "carrier_compare", False
    if "external-compare" in lowered:
        return "external_compare", False
    return None, False


def direct_metric_number(metrics: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = number(metrics.get(name))
        if value is not None:
            return value
    return None


def direct_metric_text(metrics: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = metrics.get(name)
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return None


# These are the raw metric aliases understood by the normalized task-metric
# ledger.  The generated CSV records the concrete artifact#JSONPath values,
# rather than relying on a reader to infer where a normalized value came from.
TRACKED_METRIC_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "quality_pass": ("quality_pass", "quality_ok", "quality_floor_pass", "fact_coverage_validator_pass", "passed"),
    "replay_class": ("replay_class",),
    "state_ref_count": ("semantic_state_transfer_count", "state_ref_count", "memfd_transfer_count"),
    "state_bytes": ("semantic_state_bytes", "state_bytes", "memfd_bytes_transferred"),
    "agent_call_count": tuple(f"{role}_call_count" for role in ROLE_NAMES),
    "tool_call_count": ("tool_call_count", "executor_tool_call_count"),
    "llm_total_tokens": ("llm_total_tokens", "total_tokens"),
    "prompt_tokens": ("llm_prompt_tokens", "prompt_tokens"),
    "completion_tokens": ("llm_completion_tokens", "completion_tokens"),
    "prompt_bytes": ("prompt_bytes", "llm_prompt_bytes"),
    "prompt_visible_bytes": ("prompt_visible_bytes", "prompt_visible_total_bytes"),
    "prompt_scaffolding_bytes_total": ("prompt_scaffolding_bytes_total",),
    "external_evidence_bytes": ("external_evidence_bytes",),
    "non_external_prompt_visible_bytes": ("non_external_prompt_visible_bytes",),
    "raw_evidence_bytes_seen_by_llm": ("raw_evidence_bytes_seen_by_llm",),
    "selected_evidence_bytes": ("selected_evidence_bytes",),
    "full_corpus_bytes": ("full_corpus_bytes",),
    "pruning_gain_bytes": ("pruning_gain_bytes",),
    "control_bytes": ("control_bytes",),
    "control_message_count": ("control_message_count",),
    "rendered_role_request_count": ("rendered_role_request_count",),
    "memory_match_count": ("memory_match_count",),
    "memory_ref_count": ("memory_ref_count",),
    "memory_candidate_count": ("memory_candidate_count",),
    "exact_replay_count": ("exact_replay_count",),
    "validated_replay_count": ("validated_replay_count",),
    "answer_restoration_replay_count": ("answer_restoration_replay_count",),
    "artifact_reuse_count": ("artifact_reuse_count",),
    "history_artifact_reuse_count": ("history_artifact_reuse_count",),
    "history_strategy_reuse_count": ("history_strategy_reuse_count",),
    "skipped_step_count": ("skipped_step_count",),
    "reuse_gain": ("reuse_gain",),
    "history_reuse_gain": ("history_reuse_gain",),
    "memfd_bytes_transferred": ("memfd_bytes_transferred",),
    "logit_state_transfer_count": ("logit_state_transfer_count",),
    "logit_state_bytes": ("logit_state_bytes",),
    "wall_time_ms": ("task_ms", "wall_time_ms", "total_time_ms", "llm_wall_ms"),
    "state_pool_mode": ("state_pool_mode_used", "state_pool_mode", "state_pool_memfd_mode_count", "state_pool_shared_memory_mode_count", "state_pool_mmap_mode_count"),
    "fallback_count": ("fallback_count", "runtime_fallback_count"),
    "state_pool_fallback_count": ("state_pool_fallback_count",),
    "prefix_queries": ("vllm_prefix_observed_query_delta", "prefix_query_delta"),
    "prefix_hits": ("vllm_prefix_observed_hit_delta", "prefix_hit_delta"),
    "prefix_hit_rate": ("vllm_prefix_observed_query_delta", "prefix_query_delta", "vllm_prefix_observed_hit_delta", "prefix_hit_delta"),
    "output_hash": ("output_hash", "output_artifact_hash"),
}


def qualified_field_path(path: Path, json_path: str) -> str:
    return f"{path}#{json_path}"


def metric_field_provenance(
    row: dict[str, Any],
    path: Path,
    payload: dict[str, Any],
    metric_payload: dict[str, Any],
    supplement: dict[str, Any],
) -> dict[str, str]:
    """Return trace paths and explicit null reasons for normalized metrics."""
    metric_root = "$.metrics" if metric_payload is payload.get("metrics") else "$"
    field_paths: dict[str, list[str]] = {}
    missing: list[str] = []
    missing_reasons: dict[str, str] = {}
    supplemental_paths = supplement.get("_field_paths") if isinstance(supplement.get("_field_paths"), dict) else {}
    for field, aliases in TRACKED_METRIC_FIELD_ALIASES.items():
        paths = [
            qualified_field_path(path, f"{metric_root}.{name}")
            for name in aliases
            if name in metric_payload
        ]
        if field in {"quality_pass", "output_hash", "replay_class", "state_pool_mode"}:
            paths.extend(
                qualified_field_path(path, json_path)
                for json_path, value in find_all_values(payload, aliases)
                if value is not None
            )
        if field == "output_hash":
            for alias in aliases:
                paths.extend(str(item) for item in supplemental_paths.get(alias, []) if item)
        paths = sorted(set(paths))
        if paths:
            field_paths[field] = paths
        if row.get(field) is None:
            missing.append(field)
            if paths:
                missing_reasons[field] = (
                    "recognized source field is null, non-scalar, non-finite, or has an undefined denominator; "
                    "retained as null and never zero-filled"
                )
            else:
                missing_reasons[field] = (
                    "absent from the selected primary metric artifact (or its retained workspace supplement); "
                    "retained as null and never zero-filled"
                )
    return {
        "metric_field_paths": stable_json(field_paths),
        "missing_metric_fields": stable_json(missing),
        "missing_metric_reason": stable_json(missing_reasons),
    }


def duplicate_object_count(payload: Any) -> int:
    """Count duplicate top-level/request objects without treating repeated keys as duplicates."""
    candidates: list[Any] = []
    if isinstance(payload, list):
        candidates = [item for item in payload if isinstance(item, (dict, list))]
    elif isinstance(payload, dict) and isinstance(payload.get("requests"), list):
        candidates = [item for item in payload["requests"] if isinstance(item, (dict, list))]
    if not candidates:
        return 0
    hashes = [sha256_text(stable_json(item)) for item in candidates]
    return len(hashes) - len(set(hashes))


def required_shape_diagnostics(path: Path, payload: Any) -> tuple[str, str | None, bool]:
    """Report only shape requirements that are known from the artifact filename."""
    missing: list[str] = []
    if not isinstance(payload, (dict, list)):
        return "invalid_root_shape", "object_or_array", True
    lower = path.as_posix().lower()
    if path.name == "task_metrics.json" and not isinstance(payload, dict):
        missing.append("object")
    if "rendered_llm_requests" in lower:
        if not isinstance(payload, dict):
            missing.append("object")
        elif not isinstance(payload.get("requests"), list):
            missing.append("requests[]")
    if path.name == "pair_summary.json" and not isinstance(payload, dict):
        missing.append("object")
    if path.name == "repeat_summary.json" and "prefix_parity" in lower:
        if not isinstance(payload, dict):
            missing.append("object")
        else:
            for key in ("pairs", "shared", "independent"):
                if key not in payload:
                    missing.append(key)
    if missing:
        return "missing_required_shape", ";".join(missing), True
    return "shape_ok", None, False


def parse_json(path: Path) -> tuple[Any | None, str | None, int]:
    if path.stat().st_size == 0:
        return None, "empty file", 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle), None, 1
    except (UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}", 0


def parse_jsonl(path: Path) -> tuple[list[Any], str | None, int]:
    records: list[Any] = []
    errors: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    records.append(json.loads(stripped))
                except json.JSONDecodeError as exc:
                    errors.append(f"line {line_no}: {exc.msg}")
    except (UnicodeDecodeError, OSError) as exc:
        return [], f"{type(exc).__name__}: {exc}", 0
    return records, "; ".join(errors) if errors else None, len(records)


def json_schema(payload: Any) -> str:
    if isinstance(payload, dict):
        explicit = payload.get("schema_version")
        if explicit:
            return str(explicit)
        return "object:" + ",".join(sorted(str(key) for key in payload)[:12])
    if isinstance(payload, list):
        return "array"
    return type(payload).__name__


def inventory_root(label: str, root: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[Path, Any]]:
    entries: list[dict[str, Any]] = []
    parsed: dict[Path, Any] = {}
    counts: Counter[str] = Counter()
    parse_errors: list[dict[str, str]] = []
    empty_files: list[str] = []
    missing_schema_files: list[str] = []
    missing_shape_files: list[dict[str, str]] = []
    duplicate_object_files: list[dict[str, Any]] = []
    json_records = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        category = classify_file(path)
        stat = path.stat()
        entry: dict[str, Any] = {
            "run_group": label,
            "root": str(root),
            "container_root": "/statebus/runs/" + root.name,
            "relative_path": path.relative_to(root).as_posix(),
            "category": category,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": sha256_file(path),
            "parse_status": "not_applicable",
            "schema": None,
            "schema_status": "not_applicable",
            "required_shape_status": "not_applicable",
            "missing_required_shape": None,
            "duplicate_object_count": None,
            "record_count": None,
            "parse_error": None,
        }
        counts[category] += 1
        if path.suffix == ".json":
            payload, error, record_count = parse_json(path)
            entry["parse_status"] = "ok" if error is None else "error"
            entry["schema"] = json_schema(payload) if error is None else None
            entry["record_count"] = record_count
            entry["parse_error"] = error
            if error is None:
                parsed[path] = payload
                json_records += record_count
                explicit_schema = isinstance(payload, dict) and payload.get("schema_version") is not None
                entry["schema_status"] = "explicit" if explicit_schema else "inferred_or_missing"
                shape_status, missing_shape, shape_error = required_shape_diagnostics(path, payload)
                entry["required_shape_status"] = shape_status
                entry["missing_required_shape"] = missing_shape
                entry["duplicate_object_count"] = duplicate_object_count(payload)
                if not explicit_schema:
                    missing_schema_files.append(entry["relative_path"])
                if shape_error:
                    missing_shape_files.append({"path": entry["relative_path"], "missing": missing_shape or "unknown"})
                if entry["duplicate_object_count"]:
                    duplicate_object_files.append({"path": entry["relative_path"], "count": entry["duplicate_object_count"]})
            else:
                parse_errors.append({"path": entry["relative_path"], "error": error})
                if error == "empty file":
                    empty_files.append(entry["relative_path"])
        elif path.suffix == ".jsonl":
            payload, error, record_count = parse_jsonl(path)
            entry["parse_status"] = "ok" if error is None else "partial_error"
            entry["schema"] = json_schema(payload[0]) if payload else "jsonl_empty"
            entry["record_count"] = record_count
            entry["parse_error"] = error
            parsed[path] = payload
            json_records += record_count
            explicit_schema = bool(payload) and isinstance(payload[0], dict) and payload[0].get("schema_version") is not None
            entry["schema_status"] = "explicit_first_record" if explicit_schema else "inferred_or_missing"
            shape_status, missing_shape, shape_error = required_shape_diagnostics(path, payload)
            entry["required_shape_status"] = shape_status
            entry["missing_required_shape"] = missing_shape
            entry["duplicate_object_count"] = duplicate_object_count(payload)
            if not explicit_schema:
                missing_schema_files.append(entry["relative_path"])
            if shape_error:
                missing_shape_files.append({"path": entry["relative_path"], "missing": missing_shape or "unknown"})
            if entry["duplicate_object_count"]:
                duplicate_object_files.append({"path": entry["relative_path"], "count": entry["duplicate_object_count"]})
            if error is not None:
                parse_errors.append({"path": entry["relative_path"], "error": error})
        entries.append(entry)
    json_like = sum(1 for entry in entries if Path(entry["relative_path"]).suffix in JSON_SUFFIXES)
    parsed_ok = sum(1 for entry in entries if entry["parse_status"] == "ok")
    return entries, {
        "root": str(root),
        "container_root": "/statebus/runs/" + root.name,
        "file_count": len(entries),
        "file_types": dict(sorted(counts.items())),
        "json_or_jsonl_count": json_like,
        "parsed_ok_count": parsed_ok,
        "parse_error_count": len(parse_errors),
        "parse_errors": parse_errors,
        "empty_file_count": len(empty_files),
        "empty_files": empty_files,
        "missing_schema_file_count": len(missing_schema_files),
        "missing_schema_files": missing_schema_files,
        "missing_required_shape_file_count": len(missing_shape_files),
        "missing_required_shape_files": missing_shape_files,
        "duplicate_object_file_count": len(duplicate_object_files),
        "duplicate_object_files": duplicate_object_files,
        "json_record_count": json_records,
    }, parsed


def nested_metric(payload: dict[str, Any], *names: str) -> Any:
    found = find_value(payload, names)
    return found


def first_number(payload: dict[str, Any], *names: str) -> float | None:
    return number(nested_metric(payload, *names))


def first_text(payload: dict[str, Any], *names: str) -> str | None:
    value = nested_metric(payload, *names)
    return str(value) if value is not None and not isinstance(value, (dict, list)) else None


def metric_row(
    run_group: str,
    root: Path,
    path: Path,
    payload: dict[str, Any],
    supplement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supplement = supplement or {}
    stage, variant, path_case, repeat = relative_stage(path)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metric_payload = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    case_id = first_text(payload, "task_id", "case_id", "id") or first_text(supplement, "task_id", "case_id") or path_case
    if path.name == "task_metrics.json" and path.parent.name == "logs":
        # Metrics live at <workspace>/logs/task_metrics.json.  The generic
        # workspace parser cannot know how many runner-specific prefixes occur.
        case_id = path.parent.parent.name
    quality = find_value(
        payload,
        ("quality_pass", "quality_ok", "quality_floor_pass", "fact_coverage_validator_pass", "passed"),
    )
    if quality is None and isinstance(result, dict):
        quality = find_value(result, ("quality_pass", "quality_ok", "passed"))
    prompt_tokens = direct_metric_number(metric_payload, "llm_prompt_tokens", "prompt_tokens")
    completion_tokens = direct_metric_number(metric_payload, "llm_completion_tokens", "completion_tokens")
    total_tokens = direct_metric_number(metric_payload, "llm_total_tokens", "total_tokens")
    prefix_queries = direct_metric_number(metric_payload, "vllm_prefix_observed_query_delta", "prefix_query_delta")
    prefix_hits = direct_metric_number(metric_payload, "vllm_prefix_observed_hit_delta", "prefix_hit_delta")
    state_count = direct_metric_number(metric_payload, "semantic_state_transfer_count", "state_ref_count")
    state_bytes = direct_metric_number(metric_payload, "semantic_state_bytes", "state_bytes")
    if state_count is None:
        state_count_components = [
            value for value in (
                direct_metric_number(metric_payload, "memfd_transfer_count"),
            ) if value is not None
        ]
        state_count = sum(state_count_components) if state_count_components else None
    if state_bytes is None:
        state_byte_components = [
            value for value in (
                direct_metric_number(metric_payload, "memfd_bytes_transferred"),
            ) if value is not None
        ]
        state_bytes = sum(state_byte_components) if state_byte_components else None
    role_call_components = [
        value for value in (
            direct_metric_number(metric_payload, f"{role}_call_count") for role in ROLE_NAMES
        ) if value is not None
    ]
    role_calls = sum(role_call_components) if role_call_components else None
    state_pool_mode = direct_metric_text(metric_payload, "state_pool_mode_used", "state_pool_mode") or first_text(payload, "state_pool_mode_used", "state_pool_mode")
    if state_pool_mode is None:
        state_pool_mode = (
            "memfd" if direct_metric_number(metric_payload, "state_pool_memfd_mode_count") else
            "shared_memory" if direct_metric_number(metric_payload, "state_pool_shared_memory_mode_count") else
            "mmap_file" if direct_metric_number(metric_payload, "state_pool_mmap_mode_count") else None
        )
    control_lane, is_t2 = control_lane_for_path(path)
    semantic_base_layer = (
        f"L{int(direct_metric_number(metric_payload, 'benchmark_layer'))}"
        if direct_metric_number(metric_payload, "benchmark_layer") is not None
        else first_text(payload, "layer", "selected_layer") or variant
    )
    row = {
        "run_group": run_group,
        "stage": stage,
        "variant": first_text(payload, "variant", "state_pool_mode_used") or variant,
        "transport": first_text(payload, "transport", "executor_transport"),
        "role_path_mode": first_text(payload, "role_path_mode") or first_text(metadata, "role_path_mode"),
        "embedding_mode": first_text(payload, "embedding_mode") or first_text(metadata, "embedding_mode"),
        "layer": "T2" if is_t2 else semantic_base_layer,
        "semantic_base_layer": semantic_base_layer,
        "control_lane": control_lane,
        "workspace_lane": workspace_lane(path),
        "family": first_text(payload, "task_family", "family") or first_text(supplement, "task_family", "family"),
        "case_id": case_id,
        "round": first_text(payload, "round", "round_id"),
        "repeat": repeat,
        "system_identity": (
            "external" if "external" in path.parts else first_text(payload, "mode", "lane", "system") or "statebus"
        ),
        "source_path": str(path),
        "quality_pass": as_bool(quality),
        "replay_class": first_text(payload, "replay_class"),
        "state_ref_count": state_count,
        "state_bytes": state_bytes,
        "agent_call_count": role_calls,
        "tool_call_count": direct_metric_number(metric_payload, "tool_call_count", "executor_tool_call_count"),
        "llm_total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_bytes": direct_metric_number(metric_payload, "prompt_bytes", "llm_prompt_bytes"),
        "prompt_visible_bytes": direct_metric_number(metric_payload, "prompt_visible_bytes", "prompt_visible_total_bytes"),
        "prompt_scaffolding_bytes_total": direct_metric_number(metric_payload, "prompt_scaffolding_bytes_total"),
        "external_evidence_bytes": direct_metric_number(metric_payload, "external_evidence_bytes"),
        "non_external_prompt_visible_bytes": direct_metric_number(metric_payload, "non_external_prompt_visible_bytes"),
        "raw_evidence_bytes_seen_by_llm": direct_metric_number(metric_payload, "raw_evidence_bytes_seen_by_llm"),
        "selected_evidence_bytes": direct_metric_number(metric_payload, "selected_evidence_bytes"),
        "full_corpus_bytes": direct_metric_number(metric_payload, "full_corpus_bytes"),
        "pruning_gain_bytes": direct_metric_number(metric_payload, "pruning_gain_bytes"),
        "control_bytes": direct_metric_number(metric_payload, "control_bytes"),
        "control_message_count": direct_metric_number(metric_payload, "control_message_count"),
        "rendered_role_request_count": direct_metric_number(metric_payload, "rendered_role_request_count"),
        "memory_match_count": direct_metric_number(metric_payload, "memory_match_count"),
        "memory_ref_count": direct_metric_number(metric_payload, "memory_ref_count"),
        "memory_candidate_count": direct_metric_number(metric_payload, "memory_candidate_count"),
        "exact_replay_count": direct_metric_number(metric_payload, "exact_replay_count"),
        "validated_replay_count": direct_metric_number(metric_payload, "validated_replay_count"),
        "answer_restoration_replay_count": direct_metric_number(metric_payload, "answer_restoration_replay_count"),
        "artifact_reuse_count": direct_metric_number(metric_payload, "artifact_reuse_count"),
        "history_artifact_reuse_count": direct_metric_number(metric_payload, "history_artifact_reuse_count"),
        "history_strategy_reuse_count": direct_metric_number(metric_payload, "history_strategy_reuse_count"),
        "skipped_step_count": direct_metric_number(metric_payload, "skipped_step_count"),
        "reuse_gain": direct_metric_number(metric_payload, "reuse_gain"),
        "history_reuse_gain": direct_metric_number(metric_payload, "history_reuse_gain"),
        "memfd_bytes_transferred": direct_metric_number(metric_payload, "memfd_bytes_transferred"),
        "logit_state_transfer_count": direct_metric_number(metric_payload, "logit_state_transfer_count"),
        "logit_state_bytes": direct_metric_number(metric_payload, "logit_state_bytes"),
        "wall_time_ms": direct_metric_number(metric_payload, "task_ms", "wall_time_ms", "total_time_ms", "llm_wall_ms"),
        "state_pool_mode": state_pool_mode,
        "fallback_count": direct_metric_number(metric_payload, "fallback_count", "runtime_fallback_count"),
        "state_pool_fallback_count": direct_metric_number(metric_payload, "state_pool_fallback_count"),
        "prefix_queries": prefix_queries,
        "prefix_hits": prefix_hits,
        "prefix_hit_rate": (prefix_hits / prefix_queries if prefix_hits is not None and prefix_queries else None),
        "output_hash": first_text(payload, "output_hash", "output_artifact_hash") or first_text(supplement, "output_artifact_hash"),
        "notes": "llm_wall_ms used when task_ms is not persisted" if direct_metric_number(metric_payload, "task_ms") is None and direct_metric_number(metric_payload, "llm_wall_ms") is not None else None,
    }
    row.update(metric_field_provenance(row, path, payload, metric_payload, supplement))
    return row


def workspace_root(path: Path) -> Path | None:
    for parent in (path.parent, *path.parents):
        if parent.name in {"logs", "outputs", "inputs", "manifest", "tmp"}:
            return parent.parent
    return None


def workspace_supplements(parsed: dict[Path, Any]) -> dict[Path, dict[str, Any]]:
    supplements: dict[Path, dict[str, Any]] = defaultdict(dict)

    def record_paths(target: dict[str, Any], source: Path, payload: dict[str, Any], *names: str) -> None:
        field_paths = target.setdefault("_field_paths", {})
        for name in names:
            paths = [
                qualified_field_path(source, json_path)
                for json_path, value in find_all_values(payload, (name,))
                if value is not None
            ]
            if paths:
                field_paths.setdefault(name, []).extend(paths)

    for path, payload in parsed.items():
        if not isinstance(payload, dict):
            continue
        root = workspace_root(path)
        if root is None:
            continue
        if path.name == "result.json" and path.parent.name == "outputs":
            supplements[root]["result"] = payload
            supplements[root].update({key: payload[key] for key in ("task_id", "task_family") if key in payload})
            record_paths(supplements[root], path, payload, "task_id", "task_family", "output_hash", "output_artifact_hash")
        elif path.name == "canonical_task_spec.json":
            supplements[root]["spec"] = payload
            supplements[root].update({key: payload[key] for key in ("task_id", "task_family") if key in payload})
            record_paths(supplements[root], path, payload, "task_id", "task_family")
        elif path.name == "artifact_audit.json":
            supplements[root]["artifact_audit"] = payload
            output_hash = find_value(payload, ("output_artifact_hash",))
            if output_hash:
                supplements[root]["output_artifact_hash"] = output_hash
            record_paths(supplements[root], path, payload, "output_hash", "output_artifact_hash")
        elif path.name == "replay_audit.json":
            supplements[root]["replay_audit"] = payload
    return supplements


def extract_case_ledger(
    root_sets: list[tuple[str, Path, dict[Path, Any]]],
    *,
    include_pytest_repair_partial: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_group, root, parsed in root_sets:
        # The repair root is fully inventoried, but its launcher was stopped at
        # Stage 02. It can prove the later pytest result only. Old/copied
        # workspace artifacts in that tree are never primary P0/P1 evidence.
        if run_group == "pytest_repair_partial" and not include_pytest_repair_partial:
            continue
        supplements = workspace_supplements(parsed)
        for path, payload in parsed.items():
            if not isinstance(payload, dict):
                continue
            lower = path.as_posix().lower()
            if path.name == "task_metrics.json":
                supplement = supplements.get(workspace_root(path) or path, {})
                row = metric_row(run_group, root, path, payload, supplement)
                replay = supplement.get("replay_audit")
                if isinstance(replay, dict):
                    row["replay_class"] = first_text(replay, "replay_class") or row["replay_class"]
                rows.append(row)
            elif path.name == "result.json" and "/outputs/" in lower:
                candidate = metric_row(run_group, root, path, payload, supplements.get(workspace_root(path) or path, {}))
                candidate["notes"] = "result artifact; metrics may be absent"
                rows.append(candidate)
            elif "/external/benchmark_reports/" in lower and isinstance(payload.get("cases"), list):
                # External baseline cases do not have StateBus workspace task_metrics.
                # Keep their report rows so the long ledger retains both systems.
                for case in payload["cases"]:
                    if isinstance(case, dict):
                        candidate = metric_row(run_group, root, path, case)
                        candidate["system_identity"] = "external"
                        candidate["notes"] = "external baseline benchmark report case"
                        rows.append(candidate)
    # Results are retained only when no task_metrics row shares the exact workspace.
    metrics_workspace = {
        str(Path(row["source_path"]).parent.parent)
        for row in rows
        if Path(row["source_path"]).name == "task_metrics.json"
    }
    return [
        row
        for row in rows
        if Path(row["source_path"]).name == "task_metrics.json"
        or str(Path(row["source_path"]).parent.parent) not in metrics_workspace
    ]


TAINT_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("answer_or_gold", re.compile(r"\b(expected[ _-]?(answer|fact|value)|gold|ground[ _-]?truth|oracle[ _-]?answer)\b", re.I), "critical"),
    ("scorer_or_validator", re.compile(r"\b(score|scorer|validator|quality[ _-]?check|quality[ _-]?floor)\b", re.I), "high"),
    ("route_tool_candidate", re.compile(r"\b(preferred[ _-]?candidate|candidate[ _-]?key|route[ _-]?hint|tool[ _-]?hint)\b", re.I), "high"),
    ("task_contract_identity", re.compile(r"\b(case|sample|task)[ _-]?id\b|canonicaltaskspec", re.I), "review"),
    ("state_or_evidence_contract", re.compile(r"\b(hydrate[ _-]?manifest|evidence[ _-]?(pack|manifest)|semantic[ _-]?task[ _-]?plan)\b", re.I), "review"),
]


def flatten_strings(value: Any, path: str = "$") -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield f"{path}.{key}", str(key)
            yield from flatten_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from flatten_strings(child, f"{path}[{index}]")
    elif isinstance(value, str):
        yield path, value


def rendered_request_rows(
    root_sets: list[tuple[str, Path, dict[Path, Any]]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    source_count = 0
    request_count = 0
    source_count_by_run_group: Counter[str] = Counter()
    request_count_by_run_group: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    rule_counts_by_run_group: dict[str, Counter[str]] = defaultdict(Counter)
    unique_signatures: set[tuple[str, str, str]] = set()
    for run_group, root, parsed in root_sets:
        for path, payload in parsed.items():
            if "rendered_llm_requests" not in path.as_posix() or not isinstance(payload, dict):
                continue
            source_count += 1
            source_count_by_run_group[run_group] += 1
            stage, _, case_id, _ = relative_stage(path)
            file_role = str(payload.get("role") or path.name.split(".", maxsplit=1)[0]).lower()
            requests = payload.get("requests")
            # Keep malformed/legacy artifacts visible without pretending that
            # their whole file is one actual LLM request.
            request_items = requests if isinstance(requests, list) else []
            if not request_items:
                request_items = [{"_missing_requests_array": True}]
            for request_index, request in enumerate(request_items):
                request_count += 1
                request_count_by_run_group[run_group] += 1
                request_payload = request if isinstance(request, dict) else {"_non_object_request": request}
                role = str(request_payload.get("role") or file_role).lower()
                request_case_id = first_text(request_payload, "task_id", "case_id") or case_id
                matches: list[tuple[str, str, str, str]] = []
                for field_path, text_value in flatten_strings(request_payload):
                    for rule_name, pattern, severity in TAINT_RULES:
                        if pattern.search(text_value):
                            matches.append((rule_name, severity, field_path, text_value))
                common = {
                    "run_group": run_group, "stage": stage, "case_id": request_case_id, "role": role,
                    "request_index": request_index, "source_path": str(path),
                    "upstream_source": f"rendered request requests[{request_index}]",
                    "code_path": "v2/runtime/smoke.py:578-590",
                }
                if not matches:
                    rows.append({
                        **common, "fragment_hash": None, "match_rule": "no_match", "match_count": 0,
                        "unique_type": "none", "field_path": None, "excerpt": None,
                        "role_contract_judgment": "no flagged field-name/value pattern",
                        "severity": "none", "classification": "no_lexical_signal",
                        "conclusion": "no automated taint hit",
                    })
                    continue
                for rule_name, severity, field_path, text_value in matches:
                    excerpt = text_value.replace("\n", " ")[:240]
                    signature = (rule_name, field_path, sha256_text(excerpt))
                    unique_signatures.add(signature)
                    rule_counts[rule_name] += 1
                    rule_counts_by_run_group[run_group][rule_name] += 1
                    route_to_executor = rule_name == "route_tool_candidate" and role == "executor"
                    role_judgment = (
                        "Executor route/tool fields can be a lawful verified execution contract; inspect upstream provenance"
                        if route_to_executor else
                        "lexical signal requires role, provenance, scorer-visibility and downstream data-flow review"
                    )
                    rows.append({
                        **common, "fragment_hash": sha256_text(excerpt), "match_rule": rule_name,
                        "match_count": 1, "unique_type": rule_name, "field_path": field_path,
                        "excerpt": excerpt, "role_contract_judgment": role_judgment,
                        "severity": severity, "classification": "automated_lexical_triage_only",
                        "conclusion": "lexical hit only; not evidence of cheating without provenance/data-flow confirmation",
                    })
    return rows, {
        "rendered_request_file_count": source_count,
        "rendered_request_count": request_count,
        "raw_match_count": sum(rule_counts.values()),
        "unique_match_type_count": len({name for name, count in rule_counts.items() if count}),
        "unique_signature_count": len(unique_signatures),
        "matches_by_rule": dict(sorted(rule_counts.items())),
        "rendered_request_file_count_by_run_group": dict(sorted(source_count_by_run_group.items())),
        "rendered_request_count_by_run_group": dict(sorted(request_count_by_run_group.items())),
        "matches_by_run_group": {
            run_group: dict(sorted(counts.items()))
            for run_group, counts in sorted(rule_counts_by_run_group.items())
        },
    }


def read_stage_statuses(root: Path, summary: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(summary, dict):
        return []
    stages = summary.get("stages")
    return [item for item in stages if isinstance(item, dict)] if isinstance(stages, list) else []


def stage_artifact_coverage(entries: list[dict[str, Any]], statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage_files: Counter[str] = Counter()
    stage_parse_errors: Counter[str] = Counter()
    for entry in entries:
        parts = Path(entry["relative_path"]).parts
        if "stages" in parts:
            index = parts.index("stages")
            if index + 1 < len(parts):
                stage_files[parts[index + 1]] += 1
                if entry["parse_status"] in {"error", "partial_error"}:
                    stage_parse_errors[parts[index + 1]] += 1
    rows = []
    for status in statuses:
        stage = str(status.get("stage"))
        rows.append({
            "stage": stage,
            "historical_status": status.get("status"),
            "artifact": status.get("artifact"),
            "artifact_file_count": stage_files.get(stage, 0),
            "parse_error_count": stage_parse_errors.get(stage, 0),
            "artifact_present": stage_files.get(stage, 0) > 0 or bool(status.get("artifact")),
        })
    return rows


def numeric_summary(values: Iterable[float | None]) -> dict[str, Any]:
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not usable:
        return {"count": 0, "sum": None, "mean": None, "median": None, "min": None, "max": None}
    ordered = sorted(usable)
    return {
        "count": len(ordered), "sum": sum(ordered), "mean": sum(ordered) / len(ordered),
        "median": median(ordered), "min": ordered[0], "max": ordered[-1],
    }


def aggregate_case_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["run_group"], row["stage"], row["layer"], row["family"], row["system_identity"])].append(row)
    result: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
        qualities = [row["quality_pass"] for row in group if row["quality_pass"] is not None]
        prefix_hits = sum(row["prefix_hits"] or 0.0 for row in group)
        prefix_queries = sum(row["prefix_queries"] or 0.0 for row in group)
        result.append({
            "run_group": key[0], "stage": key[1], "layer": key[2], "family": key[3],
            "system_identity": key[4], "case_records": len(group),
            "source_path_count": len({row["source_path"] for row in group}),
            "quality_numerator": sum(1 for value in qualities if value), "quality_denominator": len(qualities),
            "quality_rate": (sum(1 for value in qualities if value) / len(qualities)) if qualities else None,
            "prompt_tokens": numeric_summary(row["prompt_tokens"] for row in group),
            "total_tokens": numeric_summary(row["llm_total_tokens"] for row in group),
            "prompt_visible_bytes": numeric_summary(row["prompt_visible_bytes"] for row in group),
            "prompt_scaffolding_bytes_total": numeric_summary(row["prompt_scaffolding_bytes_total"] for row in group),
            "external_evidence_bytes": numeric_summary(row["external_evidence_bytes"] for row in group),
            "non_external_prompt_visible_bytes": numeric_summary(row["non_external_prompt_visible_bytes"] for row in group),
            "raw_evidence_bytes_seen_by_llm": numeric_summary(row["raw_evidence_bytes_seen_by_llm"] for row in group),
            "selected_evidence_bytes": numeric_summary(row["selected_evidence_bytes"] for row in group),
            "full_corpus_bytes": numeric_summary(row["full_corpus_bytes"] for row in group),
            "wall_time_ms": numeric_summary(row["wall_time_ms"] for row in group),
            "state_ref_count": numeric_summary(row["state_ref_count"] for row in group),
            "memory_match_count": numeric_summary(row["memory_match_count"] for row in group),
            "exact_replay_count": numeric_summary(row["exact_replay_count"] for row in group),
            "validated_replay_count": numeric_summary(row["validated_replay_count"] for row in group),
            "skipped_step_count": numeric_summary(row["skipped_step_count"] for row in group),
            "reuse_gain": numeric_summary(row["reuse_gain"] for row in group),
            "prefix_hits": prefix_hits if prefix_queries else None,
            "prefix_queries": prefix_queries if prefix_queries else None,
            "prefix_hit_rate": prefix_hits / prefix_queries if prefix_queries else None,
        })
    return result


def ratio_delta(baseline: float | None, treatment: float | None) -> tuple[float | None, float | None]:
    if baseline is None or treatment is None:
        return None, None
    delta = treatment - baseline
    return delta, (-delta / baseline) if baseline else None


def comparison_row(
    comparison_id: str,
    comparison_scope: str,
    baseline: dict[str, Any],
    treatment: dict[str, Any],
    claim_boundary: str,
) -> dict[str, Any]:
    quality_values = [baseline.get("quality_pass"), treatment.get("quality_pass")]
    comparable = all(value is not None for value in quality_values)
    visible_delta, visible_reduction = ratio_delta(
        number(baseline.get("prompt_visible_bytes")), number(treatment.get("prompt_visible_bytes"))
    )
    prompt_delta, prompt_reduction = ratio_delta(
        number(baseline.get("prompt_tokens")), number(treatment.get("prompt_tokens"))
    )
    total_delta, total_reduction = ratio_delta(
        number(baseline.get("llm_total_tokens")), number(treatment.get("llm_total_tokens"))
    )
    wall_delta, _ = ratio_delta(number(baseline.get("wall_time_ms")), number(treatment.get("wall_time_ms")))
    return {
        "comparison_id": comparison_id,
        "comparison_scope": comparison_scope,
        "run_group": baseline.get("run_group"), "stage": baseline.get("stage"),
        "family": baseline.get("family"), "case_id": baseline.get("case_id"),
        "baseline_layer": baseline.get("layer"), "treatment_layer": treatment.get("layer"),
        "baseline_source_path": baseline.get("source_path"), "treatment_source_path": treatment.get("source_path"),
        "match_status": "matched_case_family" if comparable else "matched_case_family_missing_quality",
        "quality_comparable_numerator": int(comparable and bool(baseline.get("quality_pass")) and bool(treatment.get("quality_pass"))),
        "quality_comparable_denominator": int(comparable),
        "baseline_quality_pass": baseline.get("quality_pass"), "treatment_quality_pass": treatment.get("quality_pass"),
        "baseline_prompt_visible_bytes": baseline.get("prompt_visible_bytes"),
        "treatment_prompt_visible_bytes": treatment.get("prompt_visible_bytes"),
        "prompt_visible_bytes_delta": visible_delta,
        "prompt_visible_bytes_reduction_ratio": visible_reduction,
        "baseline_prompt_tokens": baseline.get("prompt_tokens"), "treatment_prompt_tokens": treatment.get("prompt_tokens"),
        "prompt_tokens_delta": prompt_delta, "prompt_tokens_reduction_ratio": prompt_reduction,
        "baseline_total_tokens": baseline.get("llm_total_tokens"), "treatment_total_tokens": treatment.get("llm_total_tokens"),
        "total_tokens_delta": total_delta, "total_tokens_reduction_ratio": total_reduction,
        "baseline_wall_time_ms": baseline.get("wall_time_ms"), "treatment_wall_time_ms": treatment.get("wall_time_ms"),
        "wall_time_ms_delta": wall_delta,
        "baseline_state_ref_count": baseline.get("state_ref_count"),
        "treatment_state_ref_count": treatment.get("state_ref_count"),
        "claim_boundary": claim_boundary,
    }


def comparison_recomputation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Emit only explicit same-case comparisons; no unmatched aggregate is promoted to A/B evidence."""
    result: list[dict[str, Any]] = []
    by_key: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("system_identity") != "statebus":
            continue
        key = (row.get("run_group"), row.get("stage"), row.get("family"), row.get("case_id"))
        by_key[key].append(row)
    for key, group in sorted(by_key.items(), key=lambda item: tuple(str(value) for value in item[0])):
        run_group, stage, _, _ = key
        if run_group == "p0_full" and stage == "06_formal_full":
            layers = {str(row.get("layer")): row for row in group if str(row.get("layer")) in {"L0", "L1", "L2", "L3"}}
            if "L0" in layers:
                for target in ("L1", "L2", "L3"):
                    if target in layers:
                        result.append(comparison_row(
                            f"p0_formal_{layers['L0']['case_id']}_L0_to_{target}", "P0 formal ladder", layers["L0"], layers[target],
                            "same recorded case/layer rows; semantic selection, prompt layout and runtime behavior may still vary, so this is not carrier-only causality",
                        ))
        if run_group == "p1_extension" and stage == "17_flagship_refresh":
            ladder = {
                str(row.get("layer")): row for row in group
                if row.get("control_lane") == "ladder" and str(row.get("layer")) in {"L0", "L1", "L2", "L3"}
            }
            if "L0" in ladder:
                for target in ("L1", "L2", "L3"):
                    if target in ladder:
                        result.append(comparison_row(
                            f"p1_flagship_{ladder['L0']['case_id']}_L0_to_{target}", "P1 flagship ladder", ladder["L0"], ladder[target],
                            "same recorded case/layer rows; no single-variable carrier causal conclusion",
                        ))
            t2_rows = [row for row in group if row.get("layer") == "T2" and row.get("control_lane") == "text_same_semantic_selection"]
            if len(t2_rows) == 1 and "L2" in ladder:
                result.append(comparison_row(
                    f"p1_flagship_{ladder['L2']['case_id']}_L2_to_T2", "P1 L2 versus text-same-semantic-selection", ladder["L2"], t2_rows[0],
                    "T2 retains the semantic base layer but switches the Stage 17 control lane to text; this is the closest recorded non-text StateRef comparison and remains lane-specific",
                ))
    return result


def prefix_pair_validation(
    repeat_payload: dict[str, Any] | None,
    p1_root: Path,
    parsed: dict[Path, Any],
) -> list[dict[str, Any]]:
    if not isinstance(repeat_payload, dict):
        return []
    rows: list[dict[str, Any]] = []
    for pair in repeat_payload.get("pairs", []):
        if not isinstance(pair, dict):
            continue
        repeat_index = pair.get("repeat_index")
        analysis_path = str(pair.get("analysis_path") or "")
        local_path = p1_root / "stages/18_prefix_parity_clean_repeats" / f"repeat{int(repeat_index or 0):02d}" / "pair_summary.json"
        pair_payload = parsed.get(local_path)
        parse_ok = isinstance(pair_payload, dict)
        # The parent repeat summary owns repeat/order/evidence metadata. The
        # referenced pair file intentionally owns only the compatibility and
        # observed pair result, so verify the reference path rather than
        # falsely requiring duplicated metadata fields.
        analysis_parts = Path(analysis_path).parts
        reference_matches = (
            Path(analysis_path).name == "pair_summary.json"
            and f"repeat{int(repeat_index or 0):02d}" in analysis_parts
        )
        pair_ok = pair_payload.get("ok") if parse_ok else None
        compatibility = pair_payload.get("compatibility") if parse_ok and isinstance(pair_payload.get("compatibility"), dict) else {}
        all_contracts = compatibility.get("all_completion_contracts_valid") if compatibility else None
        latency = pair_payload.get("latency_observation") if parse_ok and isinstance(pair_payload.get("latency_observation"), dict) else {}
        rows.append({
            "repeat_index": repeat_index, "order": pair.get("order"), "evidence_file": pair.get("evidence_file"),
            "pair_summary_path": str(local_path), "pair_summary_parse_status": "ok" if parse_ok else "missing_or_unparsed",
            "pair_ok": pair_ok, "counter_claim_allowed": pair_payload.get("counter_claim_allowed") if parse_ok else None,
            "all_completion_contracts_valid": all_contracts,
            "shared_queries": None, "shared_hits": None, "shared_hit_rate": None,
            "shared_warm_ttft_mean_ms": latency.get("shared_warm_mean_ttft_ms") if latency else None,
            "independent_queries": None, "independent_hits": None, "independent_hit_rate": None,
            "independent_warm_ttft_mean_ms": latency.get("independent_warm_mean_ttft_ms") if latency else None,
            "shared_minus_independent_warm_ttft_ms": latency.get("shared_minus_independent_warm_ttft_ms") if latency else None,
            "pair_validation_status": "validated" if reference_matches and pair_ok is True and all_contracts is True else "requires_reconciliation",
            "failure_or_anomaly": (
                "metadata (repeat/order/evidence) is stored only in repeat_summary; pair_summary provides compatibility/latency"
                if reference_matches else f"repeat_summary_analysis_path={analysis_path} does not reconcile with repeat index"
            ),
        })
    return rows


def prefix_counter_recomputation(
    full_root: Path,
    full_parsed: dict[Path, Any],
    p1_root: Path,
    p1_parsed: dict[Path, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for stage, mode in (("09_prefix_shared", "shared"), ("10_prefix_independent", "independent")):
        path = full_root / f"stages/{stage}/stdout.json"
        payload = full_parsed.get(path)
        summary = payload.get("summary") if isinstance(payload, dict) and isinstance(payload.get("summary"), dict) else {}
        queries = number(summary.get("counter_delta_queries"))
        hits = number(summary.get("counter_delta_hits"))
        reported = number(summary.get("counter_delta_hit_rate"))
        recomputed = hits / queries if hits is not None and queries else None
        result.append({
            "source": "p0", "scope": stage, "source_path": str(path), "mode": mode,
            "request_count": summary.get("request_count"), "counter_queries": queries, "counter_hits": hits,
            "reported_hit_rate": reported, "recomputed_hit_rate": recomputed,
            "hit_rate_matches_report": None if reported is None or recomputed is None else math.isclose(reported, recomputed, rel_tol=1e-12, abs_tol=1e-12),
            "warm_ttft_mean_ms": summary.get("warm_candidate_mean_ttft_ms"), "warm_ttft_median_ms": None,
            "warm_ttft_p95_ms": None, "claim_boundary": summary.get("latency_claim_boundary"),
        })
    path = p1_root / "stages/18_prefix_parity_clean_repeats/repeat_summary.json"
    payload = p1_parsed.get(path)
    if isinstance(payload, dict):
        for mode in ("shared", "independent"):
            summary = payload.get(mode) if isinstance(payload.get(mode), dict) else {}
            queries = number(summary.get("queries"))
            hits = number(summary.get("hits"))
            reported = number(summary.get("hit_rate"))
            recomputed = hits / queries if hits is not None and queries else None
            result.append({
                "source": "p1", "scope": "18_prefix_parity_clean_repeats", "source_path": str(path), "mode": mode,
                "request_count": None, "counter_queries": queries, "counter_hits": hits,
                "reported_hit_rate": reported, "recomputed_hit_rate": recomputed,
                "hit_rate_matches_report": None if reported is None or recomputed is None else math.isclose(reported, recomputed, rel_tol=1e-12, abs_tol=1e-12),
                "warm_ttft_mean_ms": summary.get("warm_ttft_mean_ms"), "warm_ttft_median_ms": summary.get("warm_ttft_median_ms"),
                "warm_ttft_p95_ms": summary.get("warm_ttft_p95_ms"), "claim_boundary": payload.get("claim_boundary"),
            })
    return result


def linear_percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_repeat_recomputation(full_root: Path, full_parsed: dict[Path, Any]) -> list[dict[str, Any]]:
    path = full_root / "latency_repeat_summary.json"
    payload = full_parsed.get(path)
    if not isinstance(payload, dict):
        return []
    metric_to_report = {
        "task_ms_delta": "median_task_ms_delta",
        "llm_ms_delta": "median_llm_ms_delta",
        "total_tokens_delta": "median_total_tokens_delta",
        "prompt_tokens_delta": None,
    }
    raw_rows = [row for row in payload.get("rows", []) if isinstance(row, dict)]
    result: list[dict[str, Any]] = []
    for row in raw_rows:
        for metric in metric_to_report:
            value = number(row.get(metric))
            if value is None:
                continue
            result.append({
                "row_type": "repeat", "metric": metric, "repeat_index": row.get("repeat_index"),
                "source_path": row.get("source_path"), "comparison_valid": row.get("comparison_valid"),
                "value": value, "count": None, "sum": None, "median": None, "p90_linear": None,
                "p95_linear": None, "reported_value": None, "matches_report": None,
                "claim_boundary": "serialized three-repeat aggregate; no p90/p95 stability claim from n=3",
            })
    for metric, report_key in metric_to_report.items():
        values = [number(row.get(metric)) for row in raw_rows]
        usable = [value for value in values if value is not None]
        if not usable:
            continue
        reported = number(payload.get(report_key)) if report_key else None
        recomputed_median = median(usable)
        result.append({
            "row_type": "aggregate", "metric": metric, "repeat_index": None, "source_path": str(path),
            "comparison_valid": all(row.get("comparison_valid") is True for row in raw_rows), "value": None,
            "count": len(usable), "sum": sum(usable), "median": recomputed_median,
            "p90_linear": linear_percentile(usable, 0.90), "p95_linear": linear_percentile(usable, 0.95),
            "reported_value": reported,
            "matches_report": None if reported is None else math.isclose(recomputed_median, reported, rel_tol=1e-12, abs_tol=1e-12),
            "claim_boundary": "serialized three-repeat aggregate; p90/p95 are descriptive linear interpolation only and do not establish tail-latency stability",
        })
    return result


STAGE_PURPOSES = {
    "00_preflight": "environment/configuration precondition",
    "01_pytest_v2": "v2 regression suite",
    "02_compare_full": "StateBus/external-text comparison",
    "03_replay_full": "replay classification and reuse",
    "04_continuous_csv_full": "CSV continuous-task reuse",
    "05_continuous_cross_full": "cross-period continuous-task reuse",
    "06_formal_full": "formal L0-L3 matrix",
    "07_formal_subprocess_uds_full": "subprocess UDS execution",
    "08_genericity_holdout": "genericity, paraphrase and taint holdout",
    "09_prefix_shared": "shared-prefix measurement",
    "10_prefix_independent": "independent-prefix measurement",
    "11_carrier_compare_full": "carrier comparison",
    "12_compare_repeat_2": "serialized comparison repeat 2",
    "13_compare_repeat_3": "serialized comparison repeat 3",
    "14_latency_repeat_aggregate": "serialized latency aggregation",
    "15_tag_baseline_audit": "historical tag-baseline audit",
    "16_backend_matrix": "mmap/shared-memory/memfd matrix",
    "17_flagship_refresh": "flagship refresh and StateRef stress",
    "18_prefix_parity_clean_repeats": "paired prefix parity repeats",
}


def read_status_tsv(root: Path) -> dict[str, str]:
    """Read the launcher TSV without assuming one particular header spelling."""
    path = root / "status.tsv"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    result: dict[str, str] = {}
    for row in rows:
        normalized = {str(key).strip().lower(): value for key, value in row.items() if key}
        stage = normalized.get("stage") or normalized.get("stage_name") or normalized.get("name")
        status = normalized.get("status") or normalized.get("result")
        if stage and status:
            result[str(stage)] = str(status)
    return result


def stage_integrity_matrix(
    run_group: str,
    root: Path,
    entries: list[dict[str, Any]],
    parsed: dict[Path, Any],
    statuses: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    status_tsv = read_status_tsv(root)
    run_log = (root / "run.log").read_text(encoding="utf-8", errors="replace") if (root / "run.log").exists() else ""
    rows: list[dict[str, Any]] = []
    for status in statuses:
        stage = str(status.get("stage"))
        stage_entries = [
            entry for entry in entries
            if Path(entry["relative_path"]).parts[:2] == ("stages", stage)
        ]
        parse_errors = sum(entry["parse_status"] in {"error", "partial_error"} for entry in stage_entries)
        empty_files = sum(entry["parse_error"] == "empty file" for entry in stage_entries)
        stdout_path = root / "stages" / stage / "stdout.json"
        stderr_entries = [
            entry for entry in stage_entries
            if "stderr" in Path(entry["relative_path"]).name.lower()
        ]
        workspace_entries = [entry for entry in stage_entries if "workspaces" in Path(entry["relative_path"]).parts]
        subreport_entries = [
            entry for entry in stage_entries
            if entry["category"] == "benchmark_report" or Path(entry["relative_path"]).name in {"repeat_summary.json", "pair_summary.json"}
        ]
        workspace_parse_errors = sum(entry["parse_status"] in {"error", "partial_error"} for entry in workspace_entries)
        stdout = parsed.get(stdout_path)
        stdout_signal = None
        if isinstance(stdout, dict):
            if stdout.get("ok") is True:
                stdout_signal = "pass"
            elif stdout.get("ok") is False:
                stdout_signal = "fail"
            elif isinstance(stdout.get("status"), str):
                stdout_signal = str(stdout["status"])
        summary_status = str(status.get("status")) if status.get("status") is not None else None
        tsv_status = status_tsv.get(stage)
        status_agree = tsv_status in {None, "", summary_status}
        stdout_agree = stdout_signal in {None, "", summary_status}
        consistency = "consistent" if status_agree and stdout_agree else "requires_manual_reconciliation"
        stage_cases = [row for row in case_rows if row["stage"] == stage]
        statebus = [row for row in stage_cases if row["system_identity"] != "external"]
        external = [row for row in stage_cases if row["system_identity"] == "external"]
        quality = [row["quality_pass"] for row in stage_cases if row["quality_pass"] is not None]
        metrics = {
            "prompt_tokens": numeric_summary(row["prompt_tokens"] for row in stage_cases)["sum"],
            "total_tokens": numeric_summary(row["llm_total_tokens"] for row in stage_cases)["sum"],
            "prompt_visible_bytes": numeric_summary(row["prompt_visible_bytes"] for row in stage_cases)["sum"],
            "raw_evidence_bytes_seen_by_llm": numeric_summary(row["raw_evidence_bytes_seen_by_llm"] for row in stage_cases)["sum"],
            "state_ref_count": numeric_summary(row["state_ref_count"] for row in statebus)["sum"],
            "fallback_count": numeric_summary(row["fallback_count"] for row in statebus)["sum"],
        }
        anomalies: list[str] = []
        if summary_status != "pass":
            anomalies.append(f"historical_status={summary_status}")
        if parse_errors:
            anomalies.append(f"parse_errors={parse_errors}")
        if not stage_entries and not status.get("artifact"):
            anomalies.append("no_stage_artifact")
        if not status_agree:
            anomalies.append("summary_vs_status_tsv_mismatch")
        if not stdout_agree:
            anomalies.append("summary_vs_stdout_signal_mismatch")
        supported, unsupported = stage_claim_boundary(stage, summary_status, stdout_signal)
        paths = [entry["relative_path"] for entry in stage_entries if entry["relative_path"].endswith(("stdout.json", "stderr.log", "stderr.txt"))]
        if status.get("artifact"):
            paths.append(str(status["artifact"]))
        artifact_status = (
            "parse_errors_present" if parse_errors else
            "stage_artifacts_present" if stage_entries or status.get("artifact") else
            "artifact_not_found"
        )
        stdout_artifact_status = "parsed" if isinstance(stdout, dict) else "missing_or_unparsed"
        stderr_artifact_status = (
            "not_present" if not stderr_entries else
            "parse_or_content_present" if any(entry["size_bytes"] for entry in stderr_entries) else "zero_byte_only"
        )
        coverage_status = (
            "complete_with_parse_errors" if parse_errors else
            "stdout_and_workspace_or_subreport_present" if isinstance(stdout, dict) and (workspace_entries or subreport_entries) else
            "partial_artifact_coverage"
        )
        integrity_detail = {
            "stdout_path": str(stdout_path) if stdout_path.exists() else None,
            "stderr_paths": [entry["relative_path"] for entry in stderr_entries[:8]],
            "subreport_paths": [entry["relative_path"] for entry in subreport_entries[:8]],
            "workspace_paths_present": len(workspace_entries),
            "workspace_parse_errors": workspace_parse_errors,
        }
        rows.append({
            "run_group": run_group,
            "stage": stage,
            "purpose": STAGE_PURPOSES.get(stage, "unclassified"),
            "historical_status": summary_status,
            "status_tsv_status": tsv_status,
            "stdout_status_signal": stdout_signal,
            "stdout_artifact_status": stdout_artifact_status,
            "stderr_artifact_status": stderr_artifact_status,
            "run_log_mentions_stage": stage in run_log,
            "subreport_file_count": len(subreport_entries),
            "workspace_file_count": len(workspace_entries),
            "workspace_parse_error_count": workspace_parse_errors,
            "artifact_status": artifact_status,
            "consistency_status": consistency,
            "coverage_status": coverage_status,
            "artifact_file_count": len(stage_entries),
            "parse_error_count": parse_errors,
            "empty_file_count": empty_files,
            "statebus_case_records": len(statebus),
            "external_case_records": len(external),
            "quality_numerator": sum(1 for item in quality if item),
            "quality_denominator": len(quality),
            "key_metrics": stable_json(metrics),
            "failure_or_anomaly": "; ".join(anomalies) if anomalies else "none recorded",
            "integrity_detail": stable_json(integrity_detail),
            "supported_claim": supported,
            "unsupported_claim": unsupported,
            "artifact_paths": "; ".join(sorted(dict.fromkeys(paths))[:8]),
        })
    return rows


def stage_claim_boundary(stage: str, status: str | None, stdout_signal: str | None) -> tuple[str, str]:
    if status != "pass":
        if stage == "18_prefix_parity_clean_repeats":
            return (
                "existing repeat artifact may support a separately-labelled repaired-verifier result",
                "historical Stage 18 pass or a new model rerun",
            )
        return ("historical failure is preserved", "an all-green matrix conclusion")
    if stage == "16_backend_matrix":
        return ("functional backend realization under the recorded variant contracts", "cross-backend speed superiority or loopback IPC")
    if stage in {"09_prefix_shared", "10_prefix_independent", "18_prefix_parity_clean_repeats"}:
        return ("recorded prefix-counter behavior", "agent-to-agent KV/hidden-state handoff or general latency superiority")
    if stage == "08_genericity_holdout":
        return ("bounded precompiled-contract holdout evidence", "free-text task-contract compilation generalization")
    if stage in {"02_compare_full", "11_carrier_compare_full", "12_compare_repeat_2", "13_compare_repeat_3", "14_latency_repeat_aggregate"}:
        return ("the recorded system-level comparison", "single-variable typed-carrier causality without matched controls")
    return ("the recorded stage contract and artifacts", "claims outside the stage contract or absent fairness controls")


def role_case_metrics(
    root_sets: list[tuple[str, Path, dict[Path, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for run_group, root, parsed in root_sets:
        if run_group == "pytest_repair_partial":
            continue
        supplements = workspace_supplements(parsed)
        for path, payload in parsed.items():
            if path.name != "task_metrics.json" or not isinstance(payload, dict):
                continue
            supplement = supplements.get(workspace_root(path) or path, {})
            base = metric_row(run_group, root, path, payload, supplement)
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
            for role in ROLE_NAMES:
                rows.append({
                    "run_group": run_group,
                    "stage": base["stage"],
                    "layer": base["layer"],
                    "family": base["family"],
                    "case_id": base["case_id"],
                    "role": role,
                    "source_path": str(path),
                    "role_call_count": first_number(metrics, f"{role}_call_count"),
                    "hydrated_bytes": first_number(metrics, f"{role}_hydrated_bytes"),
                    "hydrated_item_count": first_number(metrics, f"{role}_hydrated_item_count"),
                    "memory_bytes": first_number(metrics, f"{role}_memory_bytes"),
                    "memory_item_count": first_number(metrics, f"{role}_memory_item_count"),
                    "artifact_bytes": first_number(metrics, f"{role}_artifact_bytes"),
                    "artifact_item_count": first_number(metrics, f"{role}_artifact_item_count"),
                    "text_bytes": first_number(metrics, f"{role}_text_bytes"),
                    "text_item_count": first_number(metrics, f"{role}_text_item_count"),
                    "table_bytes": first_number(metrics, f"{role}_table_bytes"),
                    "table_item_count": first_number(metrics, f"{role}_table_item_count"),
                    "state_ref_count": base["state_ref_count"],
                    "prompt_bytes": direct_metric_number(metrics, f"{role}_prompt_bytes"),
                    "prompt_visible_bytes": direct_metric_number(metrics, f"{role}_prompt_visible_bytes"),
                    "prompt_scaffolding_bytes": direct_metric_number(metrics, f"{role}_prompt_scaffolding_bytes"),
                    "non_external_prompt_visible_bytes": direct_metric_number(metrics, f"{role}_non_external_prompt_visible_bytes"),
                    "completion_tokens": direct_metric_number(metrics, f"{role}_completion_tokens"),
                    "replay_class": base["replay_class"],
                    "quality_pass": base["quality_pass"],
                })
    return rows


def taint_rollup(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str | None, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["run_group"], row["stage"], row["case_id"], row["role"], row["match_rule"], row["severity"])].append(row)
    result = []
    for key, group in sorted(grouped.items(), key=lambda item: tuple(str(value) for value in item[0])):
        result.append({
            "run_group": key[0], "stage": key[1], "case_id": key[2], "role": key[3],
            "match_rule": key[4], "severity": key[5], "raw_occurrence_count": len(group),
            "unique_fragment_count": len({row["fragment_hash"] for row in group if row["fragment_hash"]}),
            "unique_source_count": len({row["source_path"] for row in group}),
            "conclusion": "no automated hit" if key[4] == "no_match" else "triage only; requires provenance review",
        })
    return result


def get_json(parsed: dict[Path, Any], name: str) -> dict[str, Any] | None:
    for path, payload in parsed.items():
        if path.name == name and isinstance(payload, dict):
            return payload
    return None


def p1_prefix_verification(payload: dict[str, Any] | None, stderr_path: Path) -> dict[str, Any]:
    requirements: list[tuple[str, bool]] = []
    if not isinstance(payload, dict):
        return {"available": False, "requirements": [], "all_required_pass": False}
    shared = payload.get("shared") if isinstance(payload.get("shared"), dict) else {}
    independent = payload.get("independent") if isinstance(payload.get("independent"), dict) else {}
    def recompute_hit_rate(summary: dict[str, Any]) -> tuple[float | None, bool | None]:
        hits = number(summary.get("hits"))
        queries = number(summary.get("queries"))
        reported = number(summary.get("hit_rate"))
        recomputed = hits / queries if hits is not None and queries else None
        matches = None if recomputed is None or reported is None else math.isclose(recomputed, reported, rel_tol=1e-12, abs_tol=1e-12)
        return recomputed, matches
    shared_rate, shared_matches = recompute_hit_rate(shared)
    independent_rate, independent_matches = recompute_hit_rate(independent)
    requirements.extend([
        ("pair_parity", payload.get("ok") is True),
        ("repeat_coverage_ge_4", int(payload.get("repeat_count", 0) or 0) >= 4),
        ("AB_BA_coverage", payload.get("both_orders_present") is True),
        ("completion_contract_parity", payload.get("all_completion_contracts_valid") is True),
        ("two_corpus_coverage", int(payload.get("evidence_file_count", 0) or 0) >= 2),
        ("clean_service_readiness", payload.get("clean_service_all_ready") is True),
        ("aggregate_counter_rate_recomputation", shared_matches is True and independent_matches is True),
    ])
    historical_error = None
    historical_error_evidence = "not_checked"
    if stderr_path.exists():
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        if "NameError" in stderr and "os" in stderr:
            historical_error = "NameError involving os in post-run verifier"
            historical_error_evidence = "preserved stderr"
        elif not stderr:
            historical_error = "unrecoverable from preserved artifacts: Stage 18 stderr is zero bytes"
            historical_error_evidence = "zero-byte stderr; run.log records only generic stage failure"
        else:
            historical_error = "not identified in preserved Stage 18 stderr"
            historical_error_evidence = "stderr inspected but does not contain a recognizable verifier exception"
    return {
        "available": True,
        "requirements": [{"gate": gate, "pass": verdict} for gate, verdict in requirements],
        "all_required_pass": all(verdict for _, verdict in requirements),
        "clean_service_requested": payload.get("clean_service_requested"),
        "service_window": payload.get("service_window"),
        "aggregate_recomputation": {
            "shared": {"hits": shared.get("hits"), "queries": shared.get("queries"), "reported_hit_rate": shared.get("hit_rate"), "recomputed_hit_rate": shared_rate, "matches_report": shared_matches},
            "independent": {"hits": independent.get("hits"), "queries": independent.get("queries"), "reported_hit_rate": independent.get("hit_rate"), "recomputed_hit_rate": independent_rate, "matches_report": independent_matches},
        },
        "historical_post_processing_error": historical_error,
        "historical_error_evidence": historical_error_evidence,
        "historical_status": "fail",
        "artifact_status": "complete_requests_and_summary_present",
        "current_verifier_status": "post_run_validator_repair_pass" if all(verdict for _, verdict in requirements) else "not_verified",
        "claim_status": (
            "engine_local_prefix_repeat artifact satisfies repaired default verifier; historical summary remains fail"
            if all(verdict for _, verdict in requirements) else "no repaired-verifier claim"
        ),
    }


def stage_diagnostics(
    full_root: Path,
    full_parsed: dict[Path, Any],
    p1_root: Path,
    p1_parsed: dict[Path, Any],
    repair_log: Path,
) -> dict[str, Any]:
    def payload(parsed: dict[Path, Any], path: Path) -> dict[str, Any]:
        value = parsed.get(path)
        return value if isinstance(value, dict) else {}

    p0_stage = lambda stage: payload(full_parsed, full_root / f"stages/{stage}/stdout.json")
    p1_stage = lambda stage: payload(p1_parsed, p1_root / f"stages/{stage}/stdout.json")
    p0_pytest = (full_root / "logs/01_pytest_v2.log").read_text(encoding="utf-8", errors="replace")
    repair_text = repair_log.read_text(encoding="utf-8", errors="replace")
    backend = p1_stage("16_backend_matrix")
    flagship = p1_stage("17_flagship_refresh")
    stage03 = p0_stage("03_replay_full")
    stage08 = p0_stage("08_genericity_holdout")
    stage09 = p0_stage("09_prefix_shared")
    stage10 = p0_stage("10_prefix_independent")
    p0_failure_names = sorted(set(re.findall(r"^FAILED\s+([^\s]+)", p0_pytest, flags=re.M)))
    if not p0_failure_names:
        p0_failure_names = sorted(set(re.findall(r"(tests/v2/[^\s:]+\.py::[^\s]+)", p0_pytest)))
    repair_pass_counts = [int(item) for item in re.findall(r"(\d+)\s+passed", repair_text)]
    repair_mtime = repair_log.stat().st_mtime_ns
    p0_pytest_path = full_root / "logs/01_pytest_v2.log"
    return {
        "p0_pytest": {
            "reported_pass_counts": [int(item) for item in re.findall(r"(\d+)\s+passed", p0_pytest)],
            "reported_failure_count": len(re.findall(r"^FAILED\s", p0_pytest, flags=re.M)),
            "failure_names": p0_failure_names,
            "repair_pass_counts": repair_pass_counts,
            "repair_log_sha256": sha256_file(repair_log),
            "p0_pytest_log_mtime_ns": p0_pytest_path.stat().st_mtime_ns if p0_pytest_path.exists() else None,
            "repair_log_mtime_ns": repair_mtime,
            "repair_log_is_later_than_p0_pytest": p0_pytest_path.exists() and repair_mtime > p0_pytest_path.stat().st_mtime_ns,
            "repair_log_reports_failures": bool(re.search(r"^FAILED\s", repair_text, flags=re.M)),
            "failed_name_coverage": "repair log reports suite-level pass only; individual historical test names are not reprinted",
        },
        "p0_replay": {
            "selected_case_count": stage03.get("selected_case_count"),
            "quality_floor_breakdown": stage03.get("quality_floor_breakdown"),
            "replay_class_distribution": stage03.get("replay_class_distribution"),
            "telemetry_summary": {
                key: (stage03.get("telemetry_summary") or {}).get(key)
                for key in (
                    "planner_call_count", "retriever_call_count", "executor_call_count", "summarizer_call_count",
                    "llm_call_count", "exact_replay_count", "validated_replay_count", "answer_restoration_replay_count",
                    "artifact_reuse_count", "skipped_step_count", "reuse_gain",
                )
            },
        },
        "p0_genericity": {
            "ok": stage08.get("ok"), "selected_case_count": stage08.get("selected_case_count"),
            "selected_family_count": stage08.get("selected_family_count"),
            "paraphrase_semantic_equivalence": stage08.get("paraphrase_semantic_equivalence"),
            "route_hint_policy": stage08.get("route_hint_policy"), "claim_boundary": stage08.get("claim_boundary"),
            "prompt_taint_audit": {
                key: (stage08.get("prompt_taint_audit") or {}).get(key)
                for key in ("pass", "violation_count", "scanned_request_count")
            },
        },
        "p0_prefix_shared": stage09.get("summary"),
        "p0_prefix_independent": stage10.get("summary"),
        "p0_latency_repeat": payload(full_parsed, full_root / "latency_repeat_summary.json"),
        "p1_backend": [
            {
                "variant": entry.get("variant"), "validation": entry.get("validation"),
            }
            for entry in backend.get("entries", []) if isinstance(entry, dict)
        ],
        "p1_flagship": {
            "claim_level": flagship.get("claim_level"),
            "non_text_state_stress_summary": flagship.get("non_text_state_stress_summary"),
            "fixed_answer_external_claim": ((flagship.get("fixed_answer_evidence") or {}).get("external_pure_text") or {}).get("claim_restriction"),
        },
    }


def git_state(repo: Path) -> dict[str, Any]:
    def run(*command: str) -> str:
        try:
            return subprocess.run(command, cwd=repo, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()
        except OSError as exc:
            return f"unavailable: {exc}"
    smoke_diff = run("git", "diff", "--unified=0", "2a8b402", "--", "v2/runtime/smoke.py")
    store_diff = run("git", "diff", "--unified=0", "2a8b402", "--", "v2/state/store.py")
    return {
        "p1_anchor_revision": "2a8b402aecf2b89f9b64f94ebfb1900cea865641",
        "head": run("git", "rev-parse", "HEAD"),
        "branch": run("git", "branch", "--show-current"),
        "status_short": run("git", "status", "--short"),
        "diff_names_vs_p0_anchor": run("git", "diff", "--name-status", "2a8b402", "--"),
        "untracked": run("git", "ls-files", "--others", "--exclude-standard"),
        "anchor_diff_observations": {
            "smoke_role_call_accounting_changed": "execution_role_call_counts" in smoke_diff,
            "smoke_rendered_request_metric_changed": "rendered_role_request_count" in smoke_diff,
            "smoke_mmap_cli_option_changed": '"mmap"' in smoke_diff,
            "state_store_changed": bool(store_diff),
            "interpretation": (
                "The smoke diff can affect later role-call metric semantics and CLI backend selection. "
                "Other changed files may affect later runs, but the diff alone cannot recover the exact historical dirty tree "
                "or establish that a given model request changed during P0/P1."
            ),
        },
        "historical_dirty_worktree_recoverable": False,
        "drift_boundary": (
            "The P1 manifest records an anchor revision, but no immutable snapshot of the historical dirty "
            "worktree exists. Current diff is evidence of later drift, not proof of the exact run-time tree."
        ),
    }


STATIC_REVIEW_TARGETS: dict[str, dict[str, tuple[str, ...]]] = {
    "state_ref_hydration": {
        "v2/runtime/smoke.py": ("state_ref", "hydrate", "semantic_state"),
        "v2/state/store.py": ("materialize", "read", "shared_memory", "memfd"),
    },
    "memory_replay": {
        "v2/runtime/smoke.py": ("replay", "memory_match", "artifact_reuse"),
        "v2/benchmark/continuous_runner.py": ("history", "reuse", "replay"),
    },
    "typed_uds": {
        "v2/control/transport.py": ("AF_UNIX", "protobuf", "socket"),
        "v2/control/subprocess_worker.py": ("Popen", "socket", "worker"),
        "v2/control/statebus_v2.proto": ("message", "service"),
    },
    "statepool_backends": {
        "v2/state/store.py": ("mmap", "shared_memory", "memfd", "fallback"),
    },
    "prefix": {
        "v2/runtime/vllm_metrics.py": ("prefix", "hit", "query"),
        "scripts/run_vllm_prefix_alignment_repeats.py": ("AB", "BA", "prefix"),
    },
    "logit_state": {
        "v2/runtime/logit_state.py": ("logit", "top_logprob", "state"),
        "v2/runtime/role_path.py": ("serialize_logit_state", "logit_state_bytes", "top_logprobs"),
        "v2/runtime/smoke.py": ("logit_state_transfer_count", "logit_confidence_gate_trigger_count"),
        "v2/refs/models.py": ("LogitState", "logit"),
    },
    "codeact_sandbox": {
        "v2/runtime/codeact.py": ("plan", "execute", "fallback"),
        "v2/runtime/codeact_sandbox.py": ("bwrap", "resource", "fallback"),
    },
    "specialization_oracle_fallback": {
        "v2/runtime/compiler.py": ("CanonicalTaskSpec", "precompiled", "fallback"),
        "v2/runtime/semantic_plan.py": ("candidate", "route", "fallback"),
        "v2/benchmark/live_runner.py": ("case_id", "seed_replay_memory", "select_cases"),
        "v2/benchmark/scoring.py": ("quality_floor", "contamination"),
    },
}

GLOBAL_LEXICAL_RISK_RULES: dict[str, re.Pattern[str]] = {
    "expected_answer_gold_oracle": re.compile(
        r"expected[ _-]?(answer|fact|value)|ground[ _-]?truth|\bgold\b|oracle[ _-]?(answer|route|tool)", re.I
    ),
    "candidate_order_route_tool_hint": re.compile(
        r"preferred[ _-]?candidate|candidate[ _-]?(key|order)|route[ _-]?hint|tool[ _-]?hint", re.I
    ),
    "case_or_sample_specialization": re.compile(r"\b(case|sample)[ _-]?id\b", re.I),
    "canonical_contract_or_precompile": re.compile(r"canonical[ _-]?task[ _-]?spec|precompiled", re.I),
    "fallback_or_quality_gate": re.compile(r"deterministic[ _-]?fallback|runtime[ _-]?fallback|quality[ _-]?floor", re.I),
}


def global_lexical_risk_scan(
    repo: Path,
    anchor: str,
    roots: tuple[str, ...] = ("v2", "scripts", "tests"),
    sample_limit: int = 96,
) -> dict[str, Any]:
    """Scan the complete in-scope text tree; lexical hits are review leads only."""
    source_paths = sorted(
        path for root_name in roots for path in (repo / root_name).rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".sh", ".yaml", ".yml"}
    )
    current: dict[str, dict[str, Any]] = {}
    for name, pattern in GLOBAL_LEXICAL_RISK_RULES.items():
        hits = 0
        files: set[str] = set()
        samples: list[str] = []
        for path in source_paths:
            relative = str(path.relative_to(repo))
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                if pattern.search(line):
                    hits += 1
                    files.add(relative)
                    if len(samples) < sample_limit:
                        samples.append(f"{relative}:{line_no}")
        current[name] = {
            "line_hit_count": hits,
            "source_file_count": len(files),
            "source_files": sorted(files),
            "sample_line_references": samples,
        }

    anchor_results: dict[str, dict[str, Any]] = {}
    for name, pattern in GLOBAL_LEXICAL_RISK_RULES.items():
        shown = subprocess.run(
            ["git", "grep", "-n", "-i", "-E", pattern.pattern, anchor, "--", *roots],
            cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
        )
        lines = shown.stdout.splitlines() if shown.returncode in {0, 1} else []
        files: set[str] = set()
        samples: list[str] = []
        for line in lines:
            parts = line.split(":", 3)
            if len(parts) >= 3:
                files.add(parts[1])
                if len(samples) < sample_limit:
                    samples.append(f"{parts[1]}:{parts[2]}")
        anchor_results[name] = {
            "line_hit_count": len(lines),
            "source_file_count": len(files),
            "source_files": sorted(files),
            "sample_line_references": samples,
        }
    return {
        "method": (
            "complete lexical line scan of current v2/, scripts/, tests/ text sources plus git-grep at the P1 anchor; "
            "capped references are navigation evidence, not data-flow or cheating proof"
        ),
        "roots": list(roots),
        "current_scanned_file_count": len(source_paths),
        "current": current,
        "anchor": anchor_results,
    }


def source_line_matches(text: str, path_label: str, patterns: tuple[str, ...], limit: int = 24) -> list[str]:
    matches: list[str] = []
    wanted = tuple(pattern.lower() for pattern in patterns)
    for line_no, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        if any(pattern in lower for pattern in wanted):
            matches.append(f"{path_label}:{line_no}")
        if len(matches) >= limit:
            break
    return matches


def static_specialization_scan(repo: Path, anchor: str = "2a8b402aecf2b89f9b64f94ebfb1900cea865641") -> dict[str, Any]:
    """Lexical source review only; it deliberately does not claim data-flow proof."""
    result: dict[str, Any] = {
        "method": "targeted lexical line scan plus complete in-scope risk index; neither is a data-flow proof",
        "anchor_revision": anchor,
        "mechanisms": {},
    }
    for mechanism, paths in STATIC_REVIEW_TARGETS.items():
        current: list[str] = []
        anchor_matches: list[str] = []
        missing_current: list[str] = []
        missing_anchor: list[str] = []
        for relative_path, patterns in paths.items():
            current_path = repo / relative_path
            if current_path.exists():
                current.extend(source_line_matches(current_path.read_text(encoding="utf-8", errors="replace"), relative_path, patterns))
            else:
                missing_current.append(relative_path)
            shown = subprocess.run(
                ["git", "show", f"{anchor}:{relative_path}"], cwd=repo, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False,
            )
            if shown.returncode == 0:
                anchor_matches.extend(source_line_matches(shown.stdout, relative_path, patterns))
            else:
                missing_anchor.append(relative_path)
        result["mechanisms"][mechanism] = {
            "current_matches": current,
            "anchor_matches": anchor_matches,
            "missing_current": missing_current,
            "missing_anchor": missing_anchor,
        }
    result["global_lexical_risk_scan"] = global_lexical_risk_scan(repo, anchor)
    return result


def static_code_evidence(repo: Path, scan: dict[str, Any] | None = None) -> dict[str, str]:
    scan = scan or static_specialization_scan(repo)
    return {
        mechanism: ", ".join(value["current_matches"][:8])
        for mechanism, value in scan["mechanisms"].items()
        if value["current_matches"]
    }


def runtime_event_evidence(
    root_sets: list[tuple[str, Path, dict[Path, Any]]], case_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    event_counts: Counter[str] = Counter()
    event_paths: dict[str, list[str]] = defaultdict(list)
    channels: Counter[str] = Counter()
    for run_group, root, parsed in root_sets:
        if run_group == "pytest_repair_partial":
            continue
        for path, payload in parsed.items():
            if "telemetry" not in path.as_posix().lower() or not isinstance(payload, list):
                continue
            for event in payload:
                if not isinstance(event, dict) or not isinstance(event.get("event_type"), str):
                    continue
                event_type = str(event["event_type"])
                event_counts[event_type] += 1
                if len(event_paths[event_type]) < 8:
                    event_paths[event_type].append(str(path))
                if event.get("channel"):
                    channels[str(event["channel"])] += 1
    def count_named(*fragments: str) -> int:
        return sum(count for name, count in event_counts.items() if all(fragment in name.upper() for fragment in fragments))
    state_modes = Counter(
        str(row["state_pool_mode"]) for row in case_rows
        if row["system_identity"] != "external" and row["state_pool_mode"]
    )
    return {
        "event_type_counts": dict(sorted(event_counts.items())),
        "event_paths": {key: value for key, value in sorted(event_paths.items())},
        "channel_counts": dict(sorted(channels.items())),
        "state_publish_event_count": count_named("STATE", "PUBLISH"),
        "state_hydrate_event_count": count_named("HYDRAT"),
        "state_consume_event_count": count_named("CONSUM"),
        "logit_event_count": count_named("LOGIT"),
        "state_pool_modes_from_metric_rows": dict(sorted(state_modes.items())),
    }


LOGIT_METRIC_FIELD_NAMES = (
    "logit_state_transfer_count",
    "logit_state_bytes",
    "logit_state_mean_entropy",
    "logit_confidence_gate_trigger_count",
    "logit_varentropy",
    "logit_top_gap",
    "logit_peak_position",
    "logit_sequence_length",
    "logit_decision_entropy",
)


def matching_key_values(
    payload: Any,
    predicate: callable,
    path: str = "$",
) -> list[tuple[str, str, Any]]:
    """Return every JSON field whose key satisfies ``predicate``."""
    matches: list[tuple[str, str, Any]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            child = f"{path}.{key_text}"
            if predicate(key_text):
                matches.append((child, key_text, value))
            matches.extend(matching_key_values(value, predicate, child))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            matches.extend(matching_key_values(value, predicate, f"{path}[{index}]"))
    return matches


def numeric_value_summary(values: Iterable[Any]) -> dict[str, float | int | None]:
    numbers = [float(value) for value in values if number(value) is not None]
    if not numbers:
        return {"value_count": 0, "sum": None, "min": None, "max": None, "mean": None}
    return {
        "value_count": len(numbers),
        "sum": sum(numbers),
        "min": min(numbers),
        "max": max(numbers),
        "mean": sum(numbers) / len(numbers),
    }


def logit_participation_matrix(
    root_sets: list[tuple[str, Path, dict[Path, Any]]],
    case_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Audit observed LogitState participation without treating a metric as a handoff.

    Every parsed P0/P1 JSON object is searched for logit/logprob field names to
    retain raw navigation evidence. Numeric aggregation then uses only the
    primary task-metric rows, avoiding duplicate totals from stage summaries and
    benchmark reports that copy the same values.
    """
    parsed_by_group = {
        run_group: parsed
        for run_group, _root, parsed in root_sets
        if run_group in {"p0_full", "p1_extension"}
    }
    keyword_fields_by_group: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    keyword_artifacts_by_group: dict[str, set[str]] = defaultdict(set)
    keyword_occurrences_by_group: Counter[str] = Counter()
    configuration_paths_by_group: dict[str, list[str]] = defaultdict(list)
    registry_paths_by_group: dict[str, list[str]] = defaultdict(list)
    receiver_paths_by_group: dict[str, list[str]] = defaultdict(list)

    def is_logit_keyword(key: str) -> bool:
        lowered = key.lower()
        return "logit" in lowered or "logprob" in lowered

    def visit_records(value: Any, artifact_path: Path, json_path: str = "$") -> None:
        if isinstance(value, dict):
            ref_kind = str(value.get("ref_kind", "")).lower()
            channel = str(value.get("channel", "")).lower()
            if ref_kind == "logit_state" or channel == "logit_state":
                registry_paths_by_group[current_group].append(qualified_field_path(artifact_path, json_path))
            consumer = value.get("consumer_role")
            if consumer is not None and (ref_kind == "logit_state" or channel == "logit_state"):
                receiver_paths_by_group[current_group].append(
                    qualified_field_path(artifact_path, f"{json_path}.consumer_role")
                )
            for key, child in value.items():
                visit_records(child, artifact_path, f"{json_path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit_records(child, artifact_path, f"{json_path}[{index}]")

    for current_group, parsed in parsed_by_group.items():
        for artifact_path, payload in parsed.items():
            for json_path, field_name, _value in matching_key_values(payload, is_logit_keyword):
                qualified = qualified_field_path(artifact_path, json_path)
                keyword_fields_by_group[current_group][field_name].append(qualified)
                keyword_artifacts_by_group[current_group].add(str(artifact_path))
                keyword_occurrences_by_group[current_group] += 1
                lower_path = artifact_path.as_posix().lower()
                if "config" in lower_path or "request" in lower_path:
                    configuration_paths_by_group[current_group].append(qualified)
            visit_records(payload, artifact_path)

    primary_paths_by_group: dict[str, set[str]] = defaultdict(set)
    for row in case_rows:
        run_group = str(row.get("run_group"))
        source_path = str(row.get("source_path") or "")
        if run_group in parsed_by_group and row.get("system_identity") == "statebus" and source_path:
            primary_paths_by_group[run_group].add(source_path)

    def raw_field_summaries(run_group: str) -> tuple[dict[str, dict[str, float | int | None]], dict[str, list[str]]]:
        values_by_field: dict[str, list[Any]] = defaultdict(list)
        paths_by_field: dict[str, list[str]] = defaultdict(list)
        parsed = parsed_by_group[run_group]
        for source_path in sorted(primary_paths_by_group[run_group]):
            payload = parsed.get(Path(source_path))
            if payload is None:
                continue
            for field_name in LOGIT_METRIC_FIELD_NAMES:
                for json_path, value in find_all_values(payload, (field_name,)):
                    values_by_field[field_name].append(value)
                    paths_by_field[field_name].append(qualified_field_path(Path(source_path), json_path))
        return (
            {field: numeric_value_summary(values_by_field[field]) for field in LOGIT_METRIC_FIELD_NAMES},
            {field: paths[:12] for field, paths in sorted(paths_by_field.items())},
        )

    per_group_summaries: dict[str, dict[str, Any]] = {}
    for run_group in ("p0_full", "p1_extension"):
        field_summary, primary_field_paths = raw_field_summaries(run_group)
        transfer = field_summary["logit_state_transfer_count"]
        positive_transfer_rows = sum(
            1
            for source_path in primary_paths_by_group[run_group]
            for json_path, value in find_all_values(
                parsed_by_group[run_group].get(Path(source_path)), ("logit_state_transfer_count",)
            )
            if number(value) is not None and float(value) > 0
        )
        config_paths = configuration_paths_by_group[run_group][:12]
        per_group_summaries[run_group] = {
            "primary_metric_row_count": len(primary_paths_by_group[run_group]),
            "all_parsed_artifact_count": len(keyword_artifacts_by_group[run_group]),
            "all_parsed_logit_field_occurrence_count": keyword_occurrences_by_group[run_group],
            "positive_transfer_metric_row_count": positive_transfer_rows,
            "transfer_count_sum": transfer["sum"],
            "logit_byte_measurement_row_count": field_summary["logit_state_bytes"]["value_count"],
            "logit_byte_sum": field_summary["logit_state_bytes"]["sum"],
            "entropy_measurement_row_count": field_summary["logit_state_mean_entropy"]["value_count"],
            "confidence_gate_trigger_sum": field_summary["logit_confidence_gate_trigger_count"]["sum"],
            "configuration_paths": config_paths,
            "raw_value_evidence": field_summary,
            "raw_field_paths": primary_field_paths,
            "raw_artifact_paths": sorted(primary_paths_by_group[run_group])[:12],
            "registry_paths": registry_paths_by_group[run_group][:12],
            "receiver_paths": receiver_paths_by_group[run_group][:12],
        }

    combined_primary_paths = set().union(*primary_paths_by_group.values())
    combined_field_summary: dict[str, dict[str, float | int | None]] = {}
    combined_field_paths: dict[str, list[str]] = {}
    for field_name in LOGIT_METRIC_FIELD_NAMES:
        values: list[float | int] = []
        paths: list[str] = []
        for run_group in ("p0_full", "p1_extension"):
            values.extend(
                value
                for source_path in primary_paths_by_group[run_group]
                for _json_path, value in find_all_values(
                    parsed_by_group[run_group].get(Path(source_path)), (field_name,)
                )
            )
            paths.extend(per_group_summaries[run_group]["raw_field_paths"].get(field_name, []))
        combined_field_summary[field_name] = numeric_value_summary(values)
        combined_field_paths[field_name] = paths[:12]
    combined = {
        "primary_metric_row_count": len(combined_primary_paths),
        "all_parsed_artifact_count": sum(
            len(keyword_artifacts_by_group[run_group]) for run_group in ("p0_full", "p1_extension")
        ),
        "all_parsed_logit_field_occurrence_count": sum(keyword_occurrences_by_group.values()),
        "positive_transfer_metric_row_count": sum(
            per_group_summaries[run_group]["positive_transfer_metric_row_count"]
            for run_group in ("p0_full", "p1_extension")
        ),
        "transfer_count_sum": combined_field_summary["logit_state_transfer_count"]["sum"],
        "logit_byte_measurement_row_count": combined_field_summary["logit_state_bytes"]["value_count"],
        "logit_byte_sum": combined_field_summary["logit_state_bytes"]["sum"],
        "entropy_measurement_row_count": combined_field_summary["logit_state_mean_entropy"]["value_count"],
        "confidence_gate_trigger_sum": combined_field_summary["logit_confidence_gate_trigger_count"]["sum"],
        "configuration_paths": [
            path
            for run_group in ("p0_full", "p1_extension")
            for path in per_group_summaries[run_group]["configuration_paths"]
        ][:12],
        "raw_value_evidence": combined_field_summary,
        "raw_field_paths": combined_field_paths,
        "raw_artifact_paths": sorted(combined_primary_paths)[:12],
        "registry_paths": [
            path
            for run_group in ("p0_full", "p1_extension")
            for path in per_group_summaries[run_group]["registry_paths"]
        ][:12],
        "receiver_paths": [
            path
            for run_group in ("p0_full", "p1_extension")
            for path in per_group_summaries[run_group]["receiver_paths"]
        ][:12],
    }
    per_group_summaries["p0_p1_combined"] = combined

    rows: list[dict[str, Any]] = []
    for scope in ("p0_full", "p1_extension", "p0_p1_combined"):
        values = per_group_summaries[scope]
        config_paths = values["configuration_paths"]
        registry_paths = values["registry_paths"]
        receiver_paths = values["receiver_paths"]
        transfer_sum = values["transfer_count_sum"]
        byte_rows = values["logit_byte_measurement_row_count"]
        confidence_gate_sum = values["confidence_gate_trigger_sum"]
        rows.append({
            "scope": scope,
            "primary_metric_row_count": values["primary_metric_row_count"],
            "all_parsed_artifact_count": values["all_parsed_artifact_count"],
            "all_parsed_logit_field_occurrence_count": values["all_parsed_logit_field_occurrence_count"],
            "positive_transfer_metric_row_count": values["positive_transfer_metric_row_count"],
            "transfer_count_sum": transfer_sum,
            "logit_byte_measurement_row_count": byte_rows,
            "logit_byte_sum": values["logit_byte_sum"],
            "entropy_measurement_row_count": values["entropy_measurement_row_count"],
            "confidence_gate_trigger_sum": confidence_gate_sum,
            "configuration_evidence": (
                f"{len(config_paths)} parsed configuration/request field paths contain logit/logprob keywords"
                if config_paths else
                "no immutable parsed P0/P1 configuration or rendered-request field records a logprobs/top-k option"
            ),
            "actual_generation_evidence": (
                f"primary task metrics persist {values['positive_transfer_metric_row_count']} positive "
                f"logit_state_transfer_count rows (sum={transfer_sum}); this is a metric projection, not a persisted payload"
            ),
            "raw_value_evidence": values["raw_value_evidence"],
            "raw_artifact_paths": values["raw_artifact_paths"],
            "raw_field_paths": values["raw_field_paths"],
            "state_ref_registration_evidence": (
                f"parsed registry/channel evidence at {registry_paths}"
                if registry_paths else
                "no parsed P0/P1 artifact has ref_kind/channel=logit_state; current v2/refs/models.py defines LogitStateRef.registry_entry(), but definition is not run evidence"
            ),
            "receiver_evidence": (
                f"parsed LogitState receiver evidence at {receiver_paths}"
                if receiver_paths else
                "no parsed P0/P1 artifact records a LogitStateRef consumer_role or receiving-role hydration"
            ),
            "downstream_consumption_evidence": (
                "no separately recorded LogitState consumption event or behavior-changing consumer was found in the audited artifacts"
            ),
            "route_tool_retry_fallback_effect_evidence": (
                f"logit_confidence_gate_trigger_count sum={confidence_gate_sum}; no artifact maps a LogitState value to a route/tool/retry/fallback outcome"
            ),
            "fair_ab_evidence": "no LogitState enabled/disabled or receiver-consumption A/B is present",
            "claim_status": "telemetry_projection_only",
            "claim_boundary": (
                "top-logprob/entropy metrics show an executor-side projection may have been generated; absent payload bytes, ref registration, receiver, "
                "behavior effect and A/B evidence, this is not hidden-state/KV transfer or a demonstrated benefit"
            ),
        })
    return rows, {"scopes": per_group_summaries, "method": (
        "all parsed P0/P1 JSON/JSONL artifacts are scanned for logit/logprob field names; numeric totals use unique primary StateBus task-metric artifacts only"
    )}


def runtime_provenance(
    repo: Path,
    full_root: Path,
    full_entries: list[dict[str, Any]],
    full_parsed: dict[Path, Any],
    p1_root: Path,
    p1_entries: list[dict[str, Any]],
    p1_parsed: dict[Path, Any],
    case_rows: list[dict[str, Any]],
    prefix_check: dict[str, Any],
) -> dict[str, Any]:
    def role_contracts(content: str) -> dict[str, dict[str, str]]:
        contracts: dict[str, dict[str, str]] = {}
        for role in ROLE_NAMES:
            block = re.search(
                rf"(?ms)^  {re.escape(role)}:\n(?P<body>.*?)(?=^  [A-Za-z_][A-Za-z0-9_-]*:\n|\Z)",
                content,
            )
            if not block:
                continue
            contracts[role] = {
                key: match.group(1)
                for key in ("model", "temperature", "max_tokens", "max_context_tokens", "max_context_safety_margin_tokens")
                if (match := re.search(rf"(?m)^    {key}:\s*([^#\s]+)", block.group("body")))
            }
        return contracts

    def config_records(root: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = []
        for entry in entries:
            relative = str(entry["relative_path"])
            if entry["category"] != "configuration":
                continue
            content = (root / relative).read_text(encoding="utf-8", errors="replace")
            endpoint = sorted(set(re.findall(r"https?://[^\s'\"]+", content)))
            models = sorted(set(re.findall(r"(?i)\bqwen[\w.\-/]+", content)))
            temperatures = sorted(set(re.findall(r"(?im)^\s*temperature\s*:\s*([^#\s]+)", content)))
            records.append({
                "path": relative, "sha256": entry["sha256"], "size_bytes": entry["size_bytes"],
                "endpoints": endpoint, "models": models, "temperatures": temperatures,
                "role_contracts": role_contracts(content),
            })
        return records

    def named_payloads(parsed: dict[Path, Any], needle: str) -> list[str]:
        return [str(path) for path in parsed if needle.lower() in path.name.lower()][:20]

    manifest_path = p1_root / "manifest.txt"
    manifest = manifest_path.read_text(encoding="utf-8", errors="replace") if manifest_path.exists() else ""
    revision_match = re.search(r"(?m)^git_revision=([0-9a-f]+)$", manifest)
    p1_config_reference_match = re.search(r"(?m)^source_llm_config=(.+)$", manifest)
    source_eligibility = p1_parsed.get(p1_root / "source_eligibility.json")
    preflight_path = full_root / "stages/00_preflight/stdout.json"
    preflight = full_parsed.get(preflight_path)
    preflight_projection = None
    if isinstance(preflight, dict):
        metadata = preflight.get("metadata") if isinstance(preflight.get("metadata"), dict) else {}
        checks = preflight.get("checks") if isinstance(preflight.get("checks"), list) else []
        preflight_projection = {
            "path": str(preflight_path), "ok": preflight.get("ok"),
            "role_path_mode": preflight.get("role_path_mode"), "embedding_mode": preflight.get("embedding_mode"),
            "llm_config_source": metadata.get("llm_config_source"),
            "embedding_model_path": metadata.get("embedding_model_path"),
            "embedding_device": metadata.get("embedding_device"), "cuda_available": metadata.get("cuda_available"),
            "checks": [
                {key: item.get(key) for key in ("name", "ok", "detail")}
                for item in checks if isinstance(item, dict)
            ],
        }
    p0_config = config_records(full_root, full_entries)
    p1_config = config_records(p1_root, p1_entries)
    p1_config_reference = p1_config_reference_match.group(1).strip() if p1_config_reference_match else None
    p1_config_host_path = (
        Path("/home/qcrs/statebus") / p1_config_reference.removeprefix("/statebus/")
        if p1_config_reference and p1_config_reference.startswith("/statebus/") else None
    )
    p1_referenced_config = None
    if p1_config_host_path and p1_config_host_path.is_file():
        content = p1_config_host_path.read_text(encoding="utf-8", errors="replace")
        p1_referenced_config = {
            "container_path": p1_config_reference,
            "host_path": str(p1_config_host_path),
            "sha256": sha256_file(p1_config_host_path),
            "endpoints": sorted(set(re.findall(r"https?://[^\s'\"]+", content))),
            "models": sorted(set(re.findall(r"(?i)\bqwen[\w.\-/]+", content))),
            "role_contracts": role_contracts(content),
        }

    def immutable_environment_evidence(root: Path, entries: list[dict[str, Any]], manifest_text: str = "") -> dict[str, Any]:
        candidates = [
            str(root / entry["relative_path"])
            for entry in entries
            if Path(entry["relative_path"]).name.lower().endswith(".env")
            or Path(entry["relative_path"]).name.lower() in {"manifest.txt", "environment.txt", "env.txt"}
        ]
        variable_names = sorted(set(re.findall(r"(?m)^(?:export\s+)?([A-Z][A-Z0-9_]{2,})=", manifest_text)))
        return {
            "artifact_paths_checked": candidates,
            "preserved_variable_names": variable_names,
            "status": (
                "not_preserved_in_immutable_run_artifacts"
                if not variable_names else "manifest_preserves_variable_names_only"
            ),
            "boundary": (
                "No immutable shell environment snapshot was retained; configuration/preflight artifacts may show "
                "selected model settings but cannot reconstruct exported environment values."
            ),
        }

    def declared_stage_order(root: Path, parsed: dict[Path, Any]) -> dict[str, Any]:
        status_order = [
            {"stage": stage, "status": status}
            for stage, status in read_status_tsv(root).items()
        ]
        summary_payload = parsed.get(root / "summary.json")
        summary_order = [
            {"stage": item.get("stage"), "status": item.get("status")}
            for item in (summary_payload.get("stages") if isinstance(summary_payload, dict) else [])
            if isinstance(item, dict)
        ]
        return {
            "status_tsv_path": str(root / "status.tsv") if (root / "status.tsv").exists() else None,
            "status_tsv_order": status_order,
            "summary_path": str(root / "summary.json") if (root / "summary.json").exists() else None,
            "summary_order": summary_order,
            "boundary": "launcher/status order is an observed declared sequence, not a per-stage wall-clock start-time reconstruction",
        }

    statepool_modes: dict[str, dict[str, int]] = {}
    for run_group in ("p0_full", "p1_extension"):
        modes = Counter(
            str(row["state_pool_mode"])
            for row in case_rows
            if row["run_group"] == run_group and row["system_identity"] != "external" and row["state_pool_mode"]
        )
        statepool_modes[run_group] = dict(sorted(modes.items()))
    return {
        "p0": {
            "manifest_present": (full_root / "manifest.txt").exists(),
            "manifest_boundary": "P0 root has no manifest.txt; do not invent an immutable revision.",
            "configuration": p0_config,
            "preflight": preflight_projection,
            "preflight_payload_paths": named_payloads(full_parsed, "preflight"),
        },
        "p1": {
            "manifest_path": str(manifest_path) if manifest_path.exists() else None,
            "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
            "manifest_git_revision": revision_match.group(1) if revision_match else None,
            "configuration": p1_config,
            "referenced_source_llm_config": p1_referenced_config,
            "source_eligibility_path": str(p1_root / "source_eligibility.json") if isinstance(source_eligibility, dict) else None,
            "source_eligibility": source_eligibility if isinstance(source_eligibility, dict) else None,
        },
        "run_environment_and_order": {
            "model_and_role_configuration": {
                "p0_configuration_artifacts": p0_config,
                "p1_configuration_artifacts": p1_config,
                "p1_manifest_referenced_source_config": p1_referenced_config,
            },
            "environment_variable_evidence": {
                "p0": immutable_environment_evidence(full_root, full_entries),
                "p1": immutable_environment_evidence(p1_root, p1_entries, manifest),
            },
            "declared_stage_execution_order": {
                "p0": declared_stage_order(full_root, full_parsed),
                "p1": declared_stage_order(p1_root, p1_parsed),
            },
            "statepool_modes_from_primary_metric_rows": statepool_modes,
            "stage18_cache_service_window": {
                "clean_service_requested": prefix_check.get("clean_service_requested"),
                "service_window": prefix_check.get("service_window"),
                "boundary": "Stage 18 is a continuous-service window, not a per-repeat clean-service restart cohort.",
            },
        },
        "current_vs_anchor": git_state(repo),
    }


def scan_refs(static_scan: dict[str, Any], mechanism: str, *, anchor: bool = False) -> str:
    value = ((static_scan.get("mechanisms") or {}).get(mechanism) or {})
    key = "anchor_matches" if anchor else "current_matches"
    matches = value.get(key) or []
    return ", ".join(matches[:12]) if matches else "no lexical matches retained"


def mechanism_evidence_matrix(
    static_scan: dict[str, Any],
    diagnostics: dict[str, Any],
    event_evidence: dict[str, Any],
    prefix_check: dict[str, Any],
    logit_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    backend = diagnostics.get("p1_backend") or []
    backend_summary = "; ".join(
        f"{(item.get('variant') or {}).get('id')}:{(item.get('validation') or {}).get('actual_state_pool_mode')}"
        for item in backend
    )
    state_events = (
        f"publish={event_evidence.get('state_publish_event_count')}, "
        f"hydrate={event_evidence.get('state_hydrate_event_count')}, "
        f"consume={event_evidence.get('state_consume_event_count')}"
    )
    combined_logit = ((logit_summary.get("scopes") or {}).get("p0_p1_combined") or {})
    logit_events = (
        f"positive transfer-count rows={combined_logit.get('positive_transfer_metric_row_count')}, "
        f"transfer-count sum={combined_logit.get('transfer_count_sum')}, "
        f"persisted byte-value rows={combined_logit.get('logit_byte_measurement_row_count')}, "
        f"confidence-gate sum={combined_logit.get('confidence_gate_trigger_sum')}, "
        f"telemetry event names containing LOGIT={event_evidence.get('logit_event_count')}"
    )
    return [
        {
            "mechanism": "StateRef publication and hydration",
            "static_review_evidence": scan_refs(static_scan, "state_ref_hydration"),
            "anchor_static_review_evidence": scan_refs(static_scan, "state_ref_hydration", anchor=True),
            "executed_path_evidence": "P0 formal/UDS workspaces and P1 Stage 16/17 task artifacts",
            "artifact_data_evidence": state_events,
            "downstream_consumption_evidence": "publication and receiver hydration are recorded, but no distinct STATE_CONSUME event or behavior-changing consumption record is retained",
            "fair_ab_evidence": "no carrier-only repeated A/B is established",
            "evidence_level": 3,
            "claim_status": "supported_through_receiver_hydration_only",
            "claim_boundary": "publication, transfer and receiver hydration are recorded; downstream consumption is not separately instrumented or proven. StateRef is not a hidden-state or KV tensor handoff",
        },
        {
            "mechanism": "Memory and replay",
            "static_review_evidence": scan_refs(static_scan, "memory_replay"),
            "anchor_static_review_evidence": scan_refs(static_scan, "memory_replay", anchor=True),
            "executed_path_evidence": "P0 Stages 03-05 and P1 Stage 17",
            "artifact_data_evidence": stable_json(diagnostics.get("p0_replay", {})),
            "downstream_consumption_evidence": "exact/validated replay, restoration, artifact reuse, skipped steps and calls are retained as separate metrics",
            "fair_ab_evidence": "a memory match alone is not a matched saving claim",
            "evidence_level": 4,
            "claim_status": "supported_with_replay_class_boundary",
            "claim_boundary": "do not equate memory match or validated replay with skipped execution, LLM calls, tools, or reuse_gain",
        },
        {
            "mechanism": "StatePool modes and fallback",
            "static_review_evidence": scan_refs(static_scan, "statepool_backends"),
            "anchor_static_review_evidence": scan_refs(static_scan, "statepool_backends", anchor=True),
            "executed_path_evidence": "P1 Stage 16 backend matrix",
            "artifact_data_evidence": backend_summary,
            "downstream_consumption_evidence": "P1 validation records requested/actual mode, transport, case coverage and fallback",
            "fair_ab_evidence": "no matched repeated timing contract in this matrix",
            "evidence_level": 3,
            "claim_status": "supported_functionally",
            "claim_boundary": "mmap/shared_memory loopback is not cross-process IPC; only memfd_subprocess supports the narrower external-boundary claim",
        },
        {
            "mechanism": "UDS typed control plane",
            "static_review_evidence": scan_refs(static_scan, "typed_uds"),
            "anchor_static_review_evidence": scan_refs(static_scan, "typed_uds", anchor=True),
            "executed_path_evidence": "P0 Stage 07 formal_subprocess_uds_full and P1 memfd_subprocess",
            "artifact_data_evidence": "Stage 16 validates memfd_subprocess separately from loopbacks",
            "downstream_consumption_evidence": "subprocess transport is a concrete execution boundary; lifecycle evidence remains stage-specific",
            "fair_ab_evidence": "not an IPC performance comparison",
            "evidence_level": 3,
            "claim_status": "supported_as_narrow_transport_path",
            "claim_boundary": "do not extend this to all agents, all StatePool modes, or a measured latency advantage",
        },
        {
            "mechanism": "Engine-local prefix reuse",
            "static_review_evidence": scan_refs(static_scan, "prefix"),
            "anchor_static_review_evidence": scan_refs(static_scan, "prefix", anchor=True),
            "executed_path_evidence": "P0 Stages 09/10 and P1 Stage 18 repeat artifact",
            "artifact_data_evidence": stable_json(prefix_check),
            "downstream_consumption_evidence": "vLLM counter observation is engine-local; no StateRef consumer is shown",
            "fair_ab_evidence": "four AB/BA pairs and two corpora pass the repaired verifier, under continuous service",
            "evidence_level": 4 if prefix_check.get("all_required_pass") else 3,
            "claim_status": "supported_only_as_engine_local_prefix_observation",
            "claim_boundary": "not agent-to-agent KV, hidden-state transfer, cross-engine reuse, or a clean-service general latency claim",
        },
        {
            "mechanism": "LogitState / logprobs",
            "static_review_evidence": scan_refs(static_scan, "logit_state"),
            "anchor_static_review_evidence": scan_refs(static_scan, "logit_state", anchor=True),
            "executed_path_evidence": "P0/P1 primary task metrics record transfer-count and entropy projections; see 03_logitstate_participation_matrix.csv",
            "artifact_data_evidence": logit_events,
            "downstream_consumption_evidence": "no persisted LogitState bytes, ref registration, receiver, separately recorded consumption, or behavior-changing route/tool/retry/fallback record was found",
            "fair_ab_evidence": "absent",
            "evidence_level": 3,
            "claim_status": "telemetry_projection_only",
            "claim_boundary": "top-logprob summaries are not hidden-state tensors or KV cache transfer; the observed metrics do not support a receiver, efficiency, or quality causal claim",
        },
        {
            "mechanism": "CodeAct and sandbox boundary",
            "static_review_evidence": scan_refs(static_scan, "codeact_sandbox"),
            "anchor_static_review_evidence": scan_refs(static_scan, "codeact_sandbox", anchor=True),
            "executed_path_evidence": "task telemetry records CodeAct/sandbox counters where used",
            "artifact_data_evidence": "per-role task metric rows retain CodeAct and fallback counters when persisted",
            "downstream_consumption_evidence": "execution path is present; static review shows fallback-capable sandbox implementation",
            "fair_ab_evidence": "no independent security effectiveness or CodeAct benefit A/B",
            "evidence_level": 3,
            "claim_status": "implemented_with_safety_boundary",
            "claim_boundary": "not a claim of production-grade isolation, nsjail validation, or a benchmarked CodeAct causal benefit",
        },
        {
            "mechanism": "CanonicalTaskSpec, route selection and fallback",
            "static_review_evidence": scan_refs(static_scan, "specialization_oracle_fallback"),
            "anchor_static_review_evidence": scan_refs(static_scan, "specialization_oracle_fallback", anchor=True),
            "executed_path_evidence": "P0 Stage 08 genericity/taint holdout and P1 fixed-answer ablations",
            "artifact_data_evidence": stable_json(diagnostics.get("p0_genericity", {})),
            "downstream_consumption_evidence": "precompiled contracts are consumed by planning; rendered-request taint findings require role/provenance review",
            "fair_ab_evidence": "ablation evidence does not remove the precompiled-contract prior",
            "evidence_level": 3,
            "claim_status": "limitation_identified",
            "claim_boundary": "lexical code review identifies specialization/fallback surfaces only; it neither proves cheating nor free-text generalization",
        },
    ]


def contest_coverage_matrix(static_scan: dict[str, Any], diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
    def code(*mechanisms: str) -> str:
        return "; ".join(scan_refs(static_scan, mechanism) for mechanism in mechanisms)
    return [
        {
            "contest_requirement": "At least three agents / roles",
            "code_mechanism": code("state_ref_hydration"),
            "raw_experiment_evidence": "P0/P1 task metrics and rendered requests contain planner, retriever, executor and summarizer role fields",
            "proven_content": "four named roles are represented in the audited runtime artifacts",
            "fairness_or_quality_evidence": "role-level quality attribution is limited; see 02_role_case_metrics.csv",
            "risk_or_gap": "role call accounting changed after the anchor, so historical P0 remains failed",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "Structured protocol and capability/handshake",
            "code_mechanism": code("typed_uds"),
            "raw_experiment_evidence": "P0 Stage 07 and P1 memfd_subprocess artifacts",
            "proven_content": "typed UDS/subprocess path is exercised",
            "fairness_or_quality_evidence": "functional transport evidence, not comparative performance evidence",
            "risk_or_gap": "not all roles or all variants cross a process boundary",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "Same-task text and structured comparison",
            "code_mechanism": code("specialization_oracle_fallback", "state_ref_hydration"),
            "raw_experiment_evidence": "P0 Stages 02, 06, 11-14 and P1 fixed-answer controls",
            "proven_content": "system-level text/structured comparison records exist",
            "fairness_or_quality_evidence": "serialized repeat is recorded; latency superiority gate is false",
            "risk_or_gap": "semantic selection, prompts, helpers and carrier vary together in several comparisons",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "Non-text state production, transfer, receipt and consumption",
            "code_mechanism": code("state_ref_hydration", "statepool_backends"),
            "raw_experiment_evidence": "P0 formal/UDS and P1 Stage 16/17 workspace/telemetry artifacts",
            "proven_content": "StateRef publication, transfer and receiver hydration plus backend variants are recorded",
            "fairness_or_quality_evidence": "functional hydration evidence, not a carrier-only gain proof",
            "risk_or_gap": "downstream consumption is not separately instrumented; not an LLM hidden-state or KV cache handoff",
            "claim_level": 3, "claim_status": "supported_through_receiver_hydration_only",
        },
        {
            "contest_requirement": "Shared memory storage, retrieval and reuse",
            "code_mechanism": code("memory_replay", "statepool_backends"),
            "raw_experiment_evidence": "P0 Stages 03-05 and P1 Stage 17",
            "proven_content": "memory/replay classes and some reuse signals are persisted",
            "fairness_or_quality_evidence": "quality and reuse fields are separated in the ledger",
            "risk_or_gap": "memory match is not automatically a skipped call/tool or reuse_gain",
            "claim_level": 4, "claim_status": "supported_with_reuse_class_boundary",
        },
        {
            "contest_requirement": "Two related continuous tasks and at least ten rounds",
            "code_mechanism": code("memory_replay"),
            "raw_experiment_evidence": "P0 Stages 04/05 continuous-task artifacts",
            "proven_content": "continuous families and round metrics are inventoried",
            "fairness_or_quality_evidence": "quality/reuse require family-level reading",
            "risk_or_gap": "do not generalize a family-specific reuse result to all tasks",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "Communication/token/byte/latency/state/reuse telemetry",
            "code_mechanism": code("prefix", "state_ref_hydration"),
            "raw_experiment_evidence": "normalized case, role and stage ledgers",
            "proven_content": "metrics are retained and ratios are recomputed from additive fields",
            "fairness_or_quality_evidence": "P0 latency repeat preserves an explicit non-superiority decision",
            "risk_or_gap": "missing values remain null; timing claims require serialized matched reruns",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "Runtime/protocol/statepool/memory/eval system completeness",
            "code_mechanism": code("typed_uds", "statepool_backends", "memory_replay"),
            "raw_experiment_evidence": "P0/P1 stage inventory and artifact-ledger coverage",
            "proven_content": "multiple implemented subsystems have recorded execution paths",
            "fairness_or_quality_evidence": "not applicable as one aggregate causal comparison",
            "risk_or_gap": "P0 pytest and P1 Stage 18 historical statuses are not all-pass",
            "claim_level": 3, "claim_status": "partially_proven",
        },
        {
            "contest_requirement": "CodeAct and safety boundary",
            "code_mechanism": code("codeact_sandbox"),
            "raw_experiment_evidence": "task telemetry where CodeAct counters are persisted",
            "proven_content": "fallback-aware CodeAct/sandbox path exists",
            "fairness_or_quality_evidence": "no independent security or benefit experiment",
            "risk_or_gap": "no nsjail/openEuler final isolation validation in this evidence",
            "claim_level": 3, "claim_status": "prototype_or_proxy",
        },
        {
            "contest_requirement": "openEuler delivery reproducibility",
            "code_mechanism": "docker/deploy paths only; no VM result is in the audited roots",
            "raw_experiment_evidence": "P1 manifest/configuration provenance only",
            "proven_content": "container-oriented source/provenance exists",
            "fairness_or_quality_evidence": "not applicable",
            "risk_or_gap": "no audited openEuler VM final-delivery validation",
            "claim_level": 2, "claim_status": "not_supported",
        },
    ]


def issue_ledger(prefix_check: dict[str, Any], static_scan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "priority": "P0", "phenomenon": "Historical P0 pytest failure",
            "root_cause_or_hypothesis": "post-anchor role-call accounting change is consistent with the reported lightweight-stub issue, but does not rewrite history",
            "artifact_evidence": "P0 summary.json/status.tsv/logs/01_pytest_v2.log; later repair log",
            "code_location": scan_refs(static_scan, "state_ref_hydration"),
            "conclusion_impact": "P0 cannot be represented as a 16/16 all-pass matrix",
            "severity": "high", "minimum_repair": "retain immutable historical status and separately version the metric repair",
            "regression_risk": "future call totals can again depend on optional rendered-request artifacts",
            "minimum_validation": "target exact failures plus a clearly-labelled tests/v2-only rerun",
        },
        {
            "priority": "P0", "phenomenon": "Stage 18 post-processing failure lacks preserved exception text",
            "root_cause_or_hypothesis": "documented NameError cannot be independently established because preserved stderr is zero bytes",
            "artifact_evidence": "P1 run.log, Stage 18 stderr, repeat_summary.json",
            "code_location": "scripts/run_v2_post_full_p1_qwen3_container.sh verifier; current source is post-run code",
            "conclusion_impact": "historical fail stays fail; only a separately-labelled repaired-verifier result is supported",
            "severity": "high", "minimum_repair": "preserve summary and version the static verifier separately",
            "regression_risk": "post-processing errors can be misreported as model-execution failures",
            "minimum_validation": "static verify immutable repeat_summary; recover original stderr before asserting a specific historical exception",
        },
        {
            "priority": "P1", "phenomenon": "Carrier comparison changes multiple variables",
            "root_cause_or_hypothesis": "semantic selection/pruning, prompt layout, tools and carrier are not all frozen",
            "artifact_evidence": "P0 Stages 02/11-14; P1 fixed-answer controls",
            "code_location": scan_refs(static_scan, "specialization_oracle_fallback"),
            "conclusion_impact": "typed-carrier-only causal and latency claims are not identified",
            "severity": "high", "minimum_repair": "freeze visibility, selection, tool and scorer contracts",
            "regression_risk": "a comparator can regain implicit StateBus-only helper advantages",
            "minimum_validation": "serialized AB/BA repeated matched-control comparison with medians and tail percentiles",
        },
        {
            "priority": "P1", "phenomenon": "Prefix service window is continuous",
            "root_cause_or_hypothesis": "clean_service_requested is false and cache/order effects can confound a small sample",
            "artifact_evidence": stable_json(prefix_check),
            "code_location": scan_refs(static_scan, "prefix"),
            "conclusion_impact": "no clean-service general latency or agent KV-transfer conclusion",
            "severity": "medium", "minimum_repair": "report clean and continuous service cohorts separately with counters",
            "regression_risk": "warm cache and ordering can be mistaken for protocol benefit",
            "minimum_validation": "four AB/BA pairs per corpus in both cohorts with before/after counters",
        },
        {
            "priority": "P1", "phenomenon": "StateRef downstream consumption is not separately recorded",
            "root_cause_or_hypothesis": "telemetry has STATE_PUBLISHED and STATE_HYDRATED events but no distinct STATE_CONSUME event or behavior-effect field",
            "artifact_evidence": "runtime_event_evidence: STATE_PUBLISHED=1380, STATE_HYDRATED=4140, STATE_CONSUME=0",
            "code_location": scan_refs(static_scan, "state_ref_hydration"),
            "conclusion_impact": "the audit can support StateRef publication/transfer/receiver hydration, not full behavior-changing consumption",
            "severity": "medium", "minimum_repair": "emit a role-attributed consume event plus the consumed field/ref and downstream decision linkage",
            "regression_risk": "hydration can be mistaken for effective use when a downstream role ignores the hydrated state",
            "minimum_validation": "per-role StateRef on/off or consumed-field perturbation with route/tool/output checks",
        },
        {
            "priority": "P1", "phenomenon": "LogitState participation is only a metric projection",
            "root_cause_or_hypothesis": "task metrics retain transfer-count/entropy projections but not payload bytes, LogitStateRef registration, receiver, or behavior linkage",
            "artifact_evidence": "03_logitstate_participation_matrix.csv; 848 positive primary transfer-count rows and zero persisted logit_state_bytes measurements",
            "code_location": scan_refs(static_scan, "logit_state"),
            "conclusion_impact": "no hidden-state/KV-transfer, receiving-agent, route/tool/retry/fallback-effect, quality, or efficiency claim is supported",
            "severity": "medium", "minimum_repair": "persist ref registration, byte length/hash, receiver hydration/consume and decision provenance with explicit enabled/disabled mode",
            "regression_risk": "a telemetry field can be misread as a transferred, consumed neural state",
            "minimum_validation": "matched LogitState on/off experiment with payload/ref/receiver traces and quality/cost outcomes",
        },
        {
            "priority": "P2", "phenomenon": "Precompiled CanonicalTaskSpec is a strong task prior",
            "root_cause_or_hypothesis": "bounded holdout does not eliminate static task-contract/route surfaces",
            "artifact_evidence": "P0 Stage 08 prompt taint and paraphrase artifacts",
            "code_location": scan_refs(static_scan, "specialization_oracle_fallback"),
            "conclusion_impact": "no free-text task-contract compilation headline",
            "severity": "medium", "minimum_repair": "separate raw request from a safe semantic-plan suite",
            "regression_risk": "case-specific metadata or fallback can leak into role prompts",
            "minimum_validation": "holdout/paraphrase/taint suite with no task-contract oracle and role-aware review",
        },
    ]


def claim_ledger(
    prefix_check: dict[str, Any],
    p0_summary: dict[str, Any],
    p1_summary: dict[str, Any],
    logit_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    p0_passes = sum(1 for item in p0_summary.get("stages", []) if item.get("status") == "pass") if isinstance(p0_summary, dict) else 0
    combined_logit = ((logit_summary.get("scopes") or {}).get("p0_p1_combined") or {})
    return [
        {
            "mechanism": "P0 matrix", "claim": "P0 was a complete all-pass 16-stage matrix",
            "code_evidence": "launcher/status artifacts", "run_evidence": "P0 summary/status.tsv",
            "data_evidence": f"{p0_passes}/16 stages marked pass; 01_pytest_v2 marked fail",
            "executed": "yes", "artifact_data": "yes", "downstream_consumption": "n/a",
            "fair_ab_evidence": "n/a", "claim_level": 3, "claim_status": "contradicted",
            "boundary": "matrix_complete is not all_stages_passed; do not describe P0 as 16/16 green",
        },
        {
            "mechanism": "pytest repair", "claim": "later pytest evidence repairs only the historical P0 pytest conclusion",
            "code_evidence": "v2/runtime/smoke.py current post-run diff", "run_evidence": "partial repair log",
            "data_evidence": "repair log pass count and later timestamp are inventoried separately",
            "executed": "yes, pytest-only", "artifact_data": "yes", "downstream_consumption": "n/a",
            "fair_ab_evidence": "n/a", "claim_level": 3, "claim_status": "supported_with_boundary",
            "boundary": "partial repair was interrupted at Stage 02 and is not a second full matrix",
        },
        {
            "mechanism": "Semantic StateRef", "claim": "non-text state is published, transferred and receiver-hydrated",
            "code_evidence": "v2/runtime/smoke.py; v2/state/store.py", "run_evidence": "P0 formal/UDS and P1 backend artifacts",
            "data_evidence": "case ledger retains transfer counts/bytes where persisted",
            "executed": "yes", "artifact_data": "yes", "downstream_consumption": "publication and hydration telemetry exists; no distinct consume event or behavior-effect record",
            "fair_ab_evidence": "not implied by backend functional pass", "claim_level": 3,
            "claim_status": "supported_through_receiver_hydration_only", "boundary": "downstream consumption remains uninstrumented and unproven; not hidden state or KV tensor transfer",
        },
        {
            "mechanism": "P1 backend matrix", "claim": "three storage variants have equal performance benefit",
            "code_evidence": "v2/benchmark/backend_matrix.py", "run_evidence": "P1 Stage 16",
            "data_evidence": "three validation entries", "executed": "yes", "artifact_data": "yes",
            "downstream_consumption": "backend-specific", "fair_ab_evidence": "no matched repeated timing proven",
            "claim_level": 3, "claim_status": "not_supported", "boundary": "loopback is not cross-process IPC; only memfd subprocess can support that narrower path claim",
        },
        {
            "mechanism": "Memory/replay", "claim": "a memory match necessarily skips execution",
            "code_evidence": "v2/runtime/replay.py", "run_evidence": "P0 Stage 03/04/05 and P1 Stage 17",
            "data_evidence": "replay class and call metrics remain separate ledger fields", "executed": "yes",
            "artifact_data": "yes", "downstream_consumption": "must be verified per replay class",
            "fair_ab_evidence": "only a matched call/token reduction supports gain", "claim_level": 4,
            "claim_status": "not_supported_as_general_rule", "boundary": "distinguish assist, validated replay, exact replay, restored output and skipped calls",
        },
        {
            "mechanism": "Prefix", "claim": "P1 proves agent-to-agent KV/hidden-state handoff",
            "code_evidence": "scripts/run_vllm_prefix_alignment_repeats.py", "run_evidence": "P1 Stage 18",
            "data_evidence": stable_json(prefix_check), "executed": "yes", "artifact_data": "yes",
            "downstream_consumption": "vLLM engine-local cache only", "fair_ab_evidence": "four paired AB/BA repeats where verifier checks pass",
            "claim_level": 4 if prefix_check.get("all_required_pass") else 3, "claim_status": "contradicted",
            "boundary": "may support engine-local vLLM prefix reuse only; continuous service window is not clean-service restart per repeat",
        },
        {
            "mechanism": "LogitState", "claim": "LogitState is hidden state and caused a quality/efficiency improvement",
            "code_evidence": "v2/runtime/logit_state.py; v2/refs/models.py", "run_evidence": "P0 task telemetry",
            "data_evidence": (
                f"positive transfer-count rows={combined_logit.get('positive_transfer_metric_row_count')}; "
                f"persisted logit_state_bytes rows={combined_logit.get('logit_byte_measurement_row_count')}"
            ),
            "executed": "executor-side metric projection recorded", "artifact_data": "transfer-count and entropy fields; payload bytes absent",
            "downstream_consumption": "no ref registration, receiver, separately recorded consume event, or behavior-changing A/B established",
            "fair_ab_evidence": "absent", "claim_level": 3,
            "claim_status": "not_supported", "boundary": "top-logprob compact summary is not a hidden-state tensor or KV cache; do not infer transfer, consumption, or benefit",
        },
        {
            "mechanism": "External compare", "claim": "all token/time difference is caused by a typed carrier",
            "code_evidence": "v2/benchmark/external_text_baseline.py", "run_evidence": "P0 Stage 02/12/13/14",
            "data_evidence": "case and aggregate ledger", "executed": "yes", "artifact_data": "yes",
            "downstream_consumption": "yes", "fair_ab_evidence": "system-level, not single-variable carrier proof", "claim_level": 5,
            "claim_status": "limited", "boundary": "separate semantic selection/pruning, prompt layout, tools and carrier differences",
        },
        {
            "mechanism": "Genericity", "claim": "precompiled CanonicalTaskSpec holdout proves free-text task compilation",
            "code_evidence": "scripts/run_v2_genericity_holdout.py", "run_evidence": "P0 Stage 08", "data_evidence": "taint/paraphrase artifacts",
            "executed": "yes", "artifact_data": "yes", "downstream_consumption": "bounded plan path", "fair_ab_evidence": "ablation evidence only", "claim_level": 4,
            "claim_status": "not_supported", "boundary": "precompiled task contract remains a strong prior",
        },
        {
            "mechanism": "openEuler delivery", "claim": "current experiment proves final openEuler reproducibility",
            "code_evidence": "docker/", "run_evidence": "container run paths", "data_evidence": "container manifest only",
            "executed": "container only", "artifact_data": "partial", "downstream_consumption": "n/a", "fair_ab_evidence": "n/a", "claim_level": 2,
            "claim_status": "not_supported", "boundary": "VM/final delivery validation is not in the audited evidence",
        },
    ]


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, columns: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: stable_json(value) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def markdown_inventory(summary: dict[str, Any], coverage: list[dict[str, Any]]) -> str:
    lines = [
        "# Artifact Inventory",
        "",
        f"Generated by `{SCRIPT_VERSION}` using static reads only.",
        "",
        "## Parse Coverage",
        "",
        "| Root | Files | JSON/JSONL | Parsed cleanly | Parse errors | Empty files | Missing schema | Missing required shape | Duplicate objects | JSON records |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for label, item in summary["roots"].items():
        lines.append(
            f"| {label} | {item['file_count']} | {item['json_or_jsonl_count']} | {item['parsed_ok_count']} | "
            f"{item['parse_error_count']} | {item['empty_file_count']} | {item['missing_schema_file_count']} | "
            f"{item['missing_required_shape_file_count']} | {item['duplicate_object_file_count']} | {item['json_record_count']} |"
        )
    lines += ["", "## Stage Artifact Coverage", "", "| Stage | Historical status | Artifact files | Parse errors | Artifact present |", "| --- | --- | ---: | ---: | --- |"]
    for item in coverage:
        lines.append(f"| {item['stage']} | {item['historical_status']} | {item['artifact_file_count']} | {item['parse_error_count']} | {item['artifact_present']} |")
    excluded = summary.get("excluded_partial_case_artifacts", {})
    lines += [
        "",
        "## Analytical Exclusion",
        "",
        "Every repair-root file is hashed and parsed above. Its experiment-like case records are excluded from "
        "P0/P1 metric aggregation because the repair launcher stopped at Stage 02; they cannot establish a new matrix.",
        f"Excluded normalized candidate rows: `{excluded.get('normalized_candidate_row_count')}` "
        f"across stages `{stable_json(excluded.get('rows_by_stage', {}))}`.",
        "",
        "Input hashes, individual parse failures, schema/shape diagnostics, duplicate-object diagnostics, file categories, size and mtime are in `01_artifact_inventory.json`.",
    ]
    return "\n".join(lines) + "\n"


def scope_markdown(summary: dict[str, Any], p0_statuses: list[dict[str, Any]], p1_statuses: list[dict[str, Any]]) -> str:
    p0_fail = [item["stage"] for item in p0_statuses if item.get("status") != "pass"]
    p1_fail = [item["stage"] for item in p1_statuses if item.get("status") != "pass"]
    return f"""# Scope And Run Index

This is a static evidence audit. It does not import Runtime, call a model, modify an existing run artifact, or change tests.

## Inputs

| Group | Host root | Container mapping | Role |
| --- | --- | --- | --- |
| P0 full matrix | `{summary['inputs']['full_root']}` | `/statebus/runs/{Path(summary['inputs']['full_root']).name}` | Historical stages 00-15 |
| pytest repair | `{summary['inputs']['pytest_repair_log']}` | n/a | Later pytest-only evidence |
| P1 extension | `{summary['inputs']['p1_root']}` | `/statebus/runs/{Path(summary['inputs']['p1_root']).name}` | Additive stages 16-18 |

## Counting

- Stage labels: 19 (`00` through `18`).
- User-level independent experimental units: 18 (`01` through `18`). `00_preflight` is a configuration/precondition label, so it belongs in the 19-label stage index but not in the user's 18-experiment convention. The later pytest repair remains separate.
- Primary normalized execution records: `{summary['normalized_evidence_counts']['primary_case_row_count']}` total: `{summary['normalized_evidence_counts']['statebus_case_row_count']}` StateBus task-metric rows and `{summary['normalized_evidence_counts']['external_case_row_count']}` external-comparator rows. These records preserve layer, family, variant, repeat and case expansion; they are intentionally not cross-stage deduplicated.
- Excluded partial-repair candidates: `{summary['excluded_partial_case_artifacts']['normalized_candidate_row_count']}`. They remain fully inventoried but cannot be used as experiment evidence because the repair run was interrupted at Stage 02.
- `16_backend_matrix` contains three backend variants. Stage 18 has four paired repeats, two request conditions per pair and two evidence corpora; its request-level observations are held in its own repeat artifact rather than fabricated as task-metric rows.

## Historical Status Boundary

- P0 has {len(p0_statuses)} recorded labels and historical non-pass label(s): {', '.join(p0_fail) or 'none'}.
- P1 has {len(p1_statuses)} recorded labels and historical non-pass label(s): {', '.join(p1_fail) or 'none'}.
- P0 `matrix_complete` describes recorded coverage, not a 16/16 pass. The repair log may support the exact pytest conclusion only; it does not replace the historical P0 summary.

## Reproduction

```bash
python3 scripts/analyze_qwen3_p0_p1_experiment_evidence_20260715.py \\
  --full-root "{summary['inputs']['full_root']}" \\
  --pytest-repair-log "{summary['inputs']['pytest_repair_log']}" \\
  --p1-root "{summary['inputs']['p1_root']}" \\
  --output-root "{summary['inputs']['output_root']}"
```

The script validates its output JSON, CSV header/row shape, unique ledger keys and non-zero denominators before exit.
"""


def working_findings(summary: dict[str, Any], prefix_check: dict[str, Any], taint_summary: dict[str, Any]) -> str:
    return f"""# Working Findings

Updated by audit script version `{SCRIPT_VERSION}` at `{summary['generated_at']}`.

1. Full enumeration completed for all three input roots. The inventory records every file hash and every JSON/JSONL parse outcome; no conclusion here relies on a summary field alone.
2. P0 must remain historically failed: its own stage list marks `01_pytest_v2` failed even though all other recorded stages completed. The later `320 passed` repair log is isolated evidence and not a replacement 16-stage run.
3. P1 Stage 18 has four pair directories and a completed `repeat_summary.json`; its historical runner failure is treated separately from its artifact-level verifier result. Repaired default-verifier gates all pass: `{prefix_check.get('all_required_pass')}`. The preserved stderr root-cause evidence is `{prefix_check.get('historical_error_evidence')}`. The summary remains immutable and historically failed.
4. The primary metric ledger contains `{summary['normalized_evidence_counts']['primary_case_row_count']}` rows: `{summary['normalized_evidence_counts']['statebus_case_row_count']}` StateBus and `{summary['normalized_evidence_counts']['external_case_row_count']}` external. `{summary['excluded_partial_case_artifacts']['normalized_candidate_row_count']}` repair-root candidates are transparently excluded from experimental aggregation, while all repair files remain in the inventory.
5. Rendered-request inventory found `{taint_summary['rendered_request_file_count']}` request artifacts containing `{taint_summary['rendered_request_count']}` actual request elements across all three roots: `{stable_json(taint_summary['rendered_request_count_by_run_group'])}`. Automated hits are triage signals, not leakage verdicts: `{stable_json(taint_summary['matches_by_rule'])}`. Every actual request element, including no-match requests, is present in `02_rendered_request_taint_ledger.csv`.
6. StateRef evidence is bounded at publication, transfer and receiver hydration: `{summary['runtime_event_evidence']['state_publish_event_count']}` publish events and `{summary['runtime_event_evidence']['state_hydrate_event_count']}` hydrate events are recorded, but separately named consume events are `{summary['runtime_event_evidence']['state_consume_event_count']}`. Hydration is not treated as proof of behavior-changing consumption.
7. Prefix and LogitState claims stay bounded. Prefix evidence may concern engine-local vLLM reuse only. `03_logitstate_participation_matrix.csv` records task-metric logit projections, but payload-byte persistence, ref registration, receiver evidence, consumption and a behavior-effect A/B are absent; this is not hidden-state/KV transfer or a benefit claim.
"""


def full_report(
    summary: dict[str, Any],
    p0_statuses: list[dict[str, Any]],
    p1_statuses: list[dict[str, Any]],
    case_rows: list[dict[str, Any]],
    aggregates: list[dict[str, Any]],
    prefix_check: dict[str, Any],
    taint_summary: dict[str, Any],
    claims: list[dict[str, Any]],
    integrity_rows: list[dict[str, Any]],
    role_rows: list[dict[str, Any]],
    mechanism_rows: list[dict[str, Any]],
    contest_rows: list[dict[str, Any]],
    provenance: dict[str, Any],
    issues: list[dict[str, Any]],
    comparison_rows: list[dict[str, Any]],
    prefix_counter_rows: list[dict[str, Any]],
    prefix_pair_rows: list[dict[str, Any]],
    latency_repeat_rows: list[dict[str, Any]],
    logit_participation_rows: list[dict[str, Any]],
) -> str:
    stage_rows = []
    units_by_stage_and_system: Counter[tuple[str, str]] = Counter()
    for row in case_rows:
        if row["stage"]:
            units_by_stage_and_system[(str(row["stage"]), str(row["system_identity"]))] += 1
    for item in p0_statuses + p1_statuses:
        stage = str(item.get("stage"))
        status = str(item.get("status"))
        support = "artifact-level review required" if status == "pass" else "not a historical pass"
        statebus_records = units_by_stage_and_system[(stage, "statebus")]
        external_records = units_by_stage_and_system[(stage, "external")]
        stage_rows.append(
            f"| {stage} | {STAGE_PURPOSES.get(stage, 'unknown')} | {status} | {statebus_records} | "
            f"{external_records} | {statebus_records + external_records} | {support} | `{item.get('artifact')}` |"
        )
    statebus_aggregate_rows = []
    external_aggregate_rows = []
    for item in aggregates:
        if item["quality_denominator"]:
            rendered = (
                f"| {item['run_group']} | {item['stage']} | {item['layer']} | {item['family']} | "
                f"{item['quality_numerator']}/{item['quality_denominator']} | {item['prompt_tokens']['sum']} | "
                f"{item['total_tokens']['sum']} | {item['prefix_hits']}/{item['prefix_queries']} | {item['source_path_count']} |"
            )
            (external_aggregate_rows if item["system_identity"] == "external" else statebus_aggregate_rows).append(rendered)
    claim_rows = []
    for claim in claims:
        claim_rows.append(f"| {claim['mechanism']} | {claim['claim_status']} | {claim['claim_level']} | {claim['boundary']} |")
    prefix_rows = "\n".join(f"| {item['gate']} | {item['pass']} |" for item in prefix_check.get("requirements", []))
    diagnostics = summary.get("stage_diagnostics", {})
    replay = diagnostics.get("p0_replay", {})
    genericity = diagnostics.get("p0_genericity", {})
    latency = diagnostics.get("p0_latency_repeat", {})
    p0_pytest = diagnostics.get("p0_pytest", {})
    backend = diagnostics.get("p1_backend", [])
    flagship = diagnostics.get("p1_flagship", {})
    backend_rows = "\n".join(
        f"| {(item.get('variant') or {}).get('id')} | {(item.get('validation') or {}).get('requested_state_pool_mode')} | "
        f"{(item.get('validation') or {}).get('actual_state_pool_mode')} | {(item.get('validation') or {}).get('executor_transport')} | "
        f"{(item.get('validation') or {}).get('observed_quality_pass_count')}/{(item.get('validation') or {}).get('observed_case_count')} | "
        f"{(item.get('validation') or {}).get('fallback_count')} |"
        for item in backend
    )
    stress = flagship.get("non_text_state_stress_summary") or {}
    comparison_rendered = "\n".join(
        f"| {row['comparison_scope']} | {row['family']} | {row['case_id']} | {row['baseline_layer']} | "
        f"{row['treatment_layer']} | {row['quality_comparable_numerator']}/{row['quality_comparable_denominator']} | "
        f"{row['prompt_visible_bytes_delta']} | {row['prompt_tokens_delta']} | {row['total_tokens_delta']} | "
        f"{row['wall_time_ms_delta']} |"
        for row in comparison_rows[:80]
    )
    prefix_counter_rendered = "\n".join(
        f"| {row['source']} | {row['scope']} | {row['mode']} | {row['counter_hits']}/{row['counter_queries']} | "
        f"{row['recomputed_hit_rate']} | {row['warm_ttft_mean_ms']} | {row['warm_ttft_median_ms']} | {row['hit_rate_matches_report']} |"
        for row in prefix_counter_rows
    )
    prefix_pair_rendered = "\n".join(
        f"| {row['repeat_index']} | {row['order']} | {row['evidence_file']} | {row['pair_ok']} | "
        f"{row['all_completion_contracts_valid']} | {row['pair_validation_status']} |"
        for row in prefix_pair_rows
    )
    latency_repeat_rendered = "\n".join(
        f"| {row['metric']} | {row['repeat_index']} | `{row['source_path']}` | "
        f"{row['comparison_valid']} | {row['value']} |"
        for row in latency_repeat_rows if row["row_type"] == "repeat"
    )
    latency_aggregate_rendered = "\n".join(
        f"| {row['metric']} | {row['count']} | {row['sum']} | {row['median']} | "
        f"{row['p90_linear']} | {row['p95_linear']} | {row['reported_value']} | {row['matches_report']} |"
        for row in latency_repeat_rows if row["row_type"] == "aggregate"
    )
    logit_participation_rendered = "\n".join(
        f"| {row['scope']} | {row['primary_metric_row_count']} | "
        f"{row['positive_transfer_metric_row_count']} (sum={row['transfer_count_sum']}) | "
        f"{row['logit_byte_measurement_row_count']} (sum={row['logit_byte_sum']}) | "
        f"{row['entropy_measurement_row_count']} | {row['confidence_gate_trigger_sum']} | "
        f"{row['state_ref_registration_evidence']} | {row['receiver_evidence']} | "
        f"{row['route_tool_retry_fallback_effect_evidence']} | {row['fair_ab_evidence']} |"
        for row in logit_participation_rows
    )
    integrity_rendered = "\n".join(
        f"| {row['stage']} | {row['purpose']} | {row['historical_status']} | {row['consistency_status']} | "
        f"{row['artifact_status']} | {row['statebus_case_records']}/{row['external_case_records']} | "
        f"{row['quality_numerator']}/{row['quality_denominator']} | {row['failure_or_anomaly']} | "
        f"{row['supported_claim']} | {row['unsupported_claim']} |"
        for row in integrity_rows
    )
    role_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in role_rows:
        role_groups[str(row["role"])].append(row)
    role_rendered = "\n".join(
        f"| {role} | {len(group)} | {numeric_summary(item['role_call_count'] for item in group)['sum']} | "
        f"{numeric_summary(item['hydrated_bytes'] for item in group)['sum']} | "
        f"{numeric_summary(item['memory_bytes'] for item in group)['sum']} | "
        f"{numeric_summary(item['artifact_bytes'] for item in group)['sum']} |"
        for role, group in sorted(role_groups.items())
    )
    mechanism_rendered = "\n".join(
        f"| {row['mechanism']} | {row['evidence_level']} | {row['claim_status']} | "
        f"{row['artifact_data_evidence']} | {row['downstream_consumption_evidence']} | {row['claim_boundary']} |"
        for row in mechanism_rows
    )
    contest_rendered = "\n".join(
        f"| {row['contest_requirement']} | {row['claim_level']} | {row['claim_status']} | "
        f"{row['proven_content']} | {row['risk_or_gap']} |"
        for row in contest_rows
    )
    issue_rendered = "\n".join(
        f"| {row['priority']} | {row['phenomenon']} | {row['root_cause_or_hypothesis']} | "
        f"{row['artifact_evidence']} | {row['code_location']} | {row['conclusion_impact']} | "
        f"{row['minimum_repair']} | {row['minimum_validation']} |"
        for row in issues
    )
    p0_config_rendered = "\n".join(
        f"| {item['path']} | {item['sha256']} | {stable_json(item['models'])} | {stable_json(item['endpoints'])} |"
        for item in provenance.get("p0", {}).get("configuration", [])
    ) or "| no configuration artifact classified | | | |"
    p0_preflight = provenance.get("p0", {}).get("preflight")
    p1_manifest = provenance.get("p1", {})
    p1_eligibility = p1_manifest.get("source_eligibility") or {}
    p1_source_statuses = p1_eligibility.get("source_stage_statuses") or {}
    p1_source_pass_count = sum(status == "pass" for status in p1_source_statuses.values())
    drift = provenance.get("current_vs_anchor", {})
    environment_and_order = provenance.get("run_environment_and_order", {})
    model_contracts = environment_and_order.get("model_and_role_configuration", {})
    environment_evidence = environment_and_order.get("environment_variable_evidence", {})
    stage_orders = environment_and_order.get("declared_stage_execution_order", {})
    statepool_modes = environment_and_order.get("statepool_modes_from_primary_metric_rows", {})
    stage18_service_window = environment_and_order.get("stage18_cache_service_window", {})
    role_contract_rows: list[str] = []
    for label, records in (
        ("P0 configuration artifact", model_contracts.get("p0_configuration_artifacts") or []),
        ("P1 configuration artifact", model_contracts.get("p1_configuration_artifacts") or []),
    ):
        for record in records:
            for role, contract in (record.get("role_contracts") or {}).items():
                role_contract_rows.append(
                    f"| {label} | {role} | {contract.get('model')} | {contract.get('temperature')} | "
                    f"{contract.get('max_tokens')} | {contract.get('max_context_tokens')} |"
                )
    referenced_contract = model_contracts.get("p1_manifest_referenced_source_config") or {}
    for role, contract in (referenced_contract.get("role_contracts") or {}).items():
        role_contract_rows.append(
            f"| P1 manifest referenced source config | {role} | {contract.get('model')} | {contract.get('temperature')} | "
            f"{contract.get('max_tokens')} | {contract.get('max_context_tokens')} |"
        )
    environment_rows = "\n".join(
        f"| {run} | {value.get('status')} | {stable_json(value.get('preserved_variable_names', []))} | "
        f"{stable_json(value.get('artifact_paths_checked', []))} |"
        for run, value in sorted(environment_evidence.items())
    ) or "| no environment evidence record | | | |"
    def render_declared_order(items: list[dict[str, Any]]) -> str:
        return ", ".join(f"{item.get('stage')}:{item.get('status')}" for item in items)

    stage_order_rows = "\n".join(
        f"| {run} | {render_declared_order(value.get('status_tsv_order', []))} | "
        f"{render_declared_order(value.get('summary_order', []))} |"
        for run, value in sorted(stage_orders.items())
    ) or "| no declared order record | | |"
    statepool_mode_rows = "\n".join(
        f"| {run} | {stable_json(modes)} |" for run, modes in sorted(statepool_modes.items())
    ) or "| no StatePool mode persisted | |"
    global_risk_scan = (summary.get("static_specialization_review") or {}).get("global_lexical_risk_scan") or {}
    global_risk_current = global_risk_scan.get("current") or {}
    global_risk_anchor = global_risk_scan.get("anchor") or {}
    global_risk_rows = "\n".join(
        f"| {name} | {value.get('line_hit_count')} | {value.get('source_file_count')} | "
        f"{(global_risk_anchor.get(name) or {}).get('line_hit_count')} | "
        f"{(global_risk_anchor.get(name) or {}).get('source_file_count')} |"
        for name, value in sorted(global_risk_current.items())
    ) or "| no global risk scan record | | | | |"
    return f"""# Full Experiment Truth Audit

## Executive Summary

This audit indexes every file under the P0 full run, the partial pytest repair run, and the P1 additive extension. It preserves historical statuses. P0 has a complete 16-label record but is not an all-green matrix because `01_pytest_v2` failed. The later repair log can support only the tests/v2 repair conclusion. P1 Stage 18 remains historical `fail`; the completed request artifact independently satisfies the repaired default verifier, so it is recorded as `post_run_validator_repair`, not as a rerun or a summary rewrite. The primary metric ledger has `{summary['normalized_evidence_counts']['primary_case_row_count']}` records; `{summary['excluded_partial_case_artifacts']['normalized_candidate_row_count']}` repair-root candidates are excluded from it.

## Reproducibility And Coverage

Inputs, hashes, file sizes, mtimes, JSON/JSONL parse coverage, errors, empty files and exclusion rationale are in `01_artifact_inventory.json`. The analysis command and current worktree state are in `04_full_experiment_truth_audit.json`. All averages and rates below are built from additive numerator/denominator fields when those fields were present; missing values remain null rather than zero. In `02_stage_layer_family_case.csv`, `metric_field_paths` is a deterministic JSON mapping from every populated normalized metric to one or more `artifact-path#JSONPath` locations; `missing_metric_fields` and `missing_metric_reason` retain field-level null causes rather than silently zero-filling them.

P0 configuration/provenance artifacts are below. P0 has no root `manifest.txt`, so the audit intentionally does not invent a source revision. P1 `manifest.txt` records revision `{p1_manifest.get('manifest_git_revision')}`. Current-vs-anchor drift is recorded from `git diff` in the JSON; it cannot reconstruct the historical dirty worktree: `{drift.get('drift_boundary')}`.

| P0 configuration artifact | SHA256 | Model labels found | Endpoint values found |
| --- | --- | --- | --- |
{p0_config_rendered}

P0 preflight projection: `{stable_json(p0_preflight)}`.

## Immutable Runtime Environment And Declared Order

The P0 local-vLLM configuration and the P1 manifest-referenced copy both record the model endpoint/configuration contract. The retained immutable run artifacts do not contain a shell environment snapshot, so this audit records that absence rather than inferring environment variables from the current host. P1's referenced configuration is a provenance link to the P0 run artifact; it is not an independent P1 configuration capture.

| Configuration source | Role | Model | Temperature | Max tokens | Max context tokens |
| --- | --- | --- | ---: | ---: | ---: |
{chr(10).join(role_contract_rows) or '| no role configuration was retained | | | | | |'}

| Run | Environment-variable evidence | Preserved variable names | Immutable artifacts checked |
| --- | --- | --- | --- |
{environment_rows}

| Run | `status.tsv` declared order | `summary.json` order |
| --- | --- | --- |
{stage_order_rows}

| Run | StatePool modes from primary normalized metric rows |
| --- | --- |
{statepool_mode_rows}

Stage 18 cache-service evidence: `clean_service_requested={stage18_service_window.get('clean_service_requested')}`, `service_window={stage18_service_window.get('service_window')}`. {stage18_service_window.get('boundary')}

## P0/P1 Timeline And Stage Status

| Stage | Purpose | Historical status | StateBus metric records | External records | Total normalized records | Strongest immediate interpretation | Artifact |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
{chr(10).join(stage_rows)}

The pytest repair is deliberately outside this stage table: it was a partial rerun stopped after Stage 02 and therefore cannot be counted as a fresh P0 matrix.

P1's own `source_eligibility.json` records mode `{p1_eligibility.get('mode')}`, `{p1_source_pass_count}` source pass stages, and source `01_pytest_v2={p1_source_statuses.get('01_pytest_v2')}`. It admits P1 only through the later repair log reporting `{p1_eligibility.get('repaired_pytest_pass_count')}` passes (SHA256 `{p1_eligibility.get('repaired_pytest_log_sha256')}`); it explicitly preserves the historical P0 failure and does not create a replacement full matrix.

## Per-Stage Integrity Matrix

`03_stage_integrity_matrix.csv` is the complete machine-readable reconciliation of `summary.json`, `status.tsv`, stage stdout, run log mentions, artifact coverage and parse errors. Case counts and quality values are recomputed from the normalized ledger; an empty denominator is kept as `0/0`, never promoted to a pass.

| Stage | Purpose | Historical | Status consistency | Artifact completeness | StateBus/external units | Quality | Failure or anomaly | Supported | Unsupported |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
{integrity_rendered}

## StateBus Normalized Metrics

| Run | Stage | Layer | Family | Quality | Prompt tokens | Total tokens | Observed prefix hits/queries | Source paths |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(statebus_aggregate_rows) or '| no persisted StateBus task-metric rows found | | | | | | | | |'}

## External Comparator Metrics

| Run | Stage | Layer | Family | Quality | Prompt tokens | Total tokens | Observed prefix hits/queries | Source paths |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
{chr(10).join(external_aggregate_rows) or '| no persisted external comparator rows found | | | | | | | | |'}

`02_stage_layer_family_case.csv` retains every primary source artifact. The tables keep StateBus and external rows separate; `Source paths` is the number of retained source artifacts in each aggregate. Missing fields are empty/null rather than inferred as zero. The repair root is fully present in the inventory but excluded from these normalized experimental metrics because its only admissible conclusion is the later pytest result.

## Matched Comparison Recomputation

`03_comparison_recomputation.csv` retains only same-case/family pairs that can be identified directly from the task-metric ledger. It recomputes deltas as treatment minus baseline and reductions as `(baseline - treatment) / baseline`, retaining null when either input is absent. `T2` is explicitly the Stage 17 `text_same_semantic_selection` lane while `semantic_base_layer` retains its raw L2 value; it is not folded into L2.

| Scope | Family | Case | Baseline | Treatment | Equal-quality | Visible-byte delta | Prompt-token delta | Total-token delta | Wall-ms delta |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
{comparison_rendered}

## Role-Level Case Metrics

`02_role_case_metrics.csv` has one row per persisted task-metric source and role, retaining layer/family/case/source path and role-scoped hydrated, memory, artifact, text and table metrics. This summary is additive across retained primary task metrics; it is not a quality attribution to an individual role.

| Role | Task-metric role rows | Call-count sum | Hydrated bytes sum | Memory bytes sum | Artifact bytes sum |
| --- | ---: | ---: | ---: | ---: | ---: |
{role_rendered}

## P0 Pytest Failure And Repair Boundary

The historical P0 pytest log names `{stable_json(p0_pytest.get('failure_names'))}`. It records `{p0_pytest.get('reported_failure_count')}` failure lines. The repair log reports `{stable_json(p0_pytest.get('repair_pass_counts'))}` passes, SHA256 `{p0_pytest.get('repair_log_sha256')}`, and `repair_log_is_later_than_p0_pytest={p0_pytest.get('repair_log_is_later_than_p0_pytest')}`; it does not reproduce individual test names, so it supports the suite-level repair conclusion only.

The current worktree diff records a post-run change in `v2/runtime/smoke.py` that separates execution role calls from optional rendered-request artifacts. This is consistent with the stated P0 lightweight-stub failure mode, but the audit does not use current code to relabel historical P0. The proper conclusion is: historical P0 pytest failed; later pytest-only evidence may repair the tests/v2 conclusion; neither establishes a new 16-stage all-pass matrix.

## P1 Stage 18 Validator Failure

| Repaired default verifier gate | Existing repeat artifact |
| --- | --- |
{prefix_rows}

Historical post-processing signal: `{prefix_check.get('historical_post_processing_error')}`. Evidence quality: `{prefix_check.get('historical_error_evidence')}`. The current verifier source at `scripts/run_v2_post_full_p1_qwen3_container.sh:211-251` imports `os`; that is post-run validation code, not evidence of the historical exception. Since the original stderr is zero-byte, the documented `NameError` remains an uncorroborated explanation rather than an audit fact. `clean_service_requested={prefix_check.get('clean_service_requested')}` and `service_window={prefix_check.get('service_window')}` mean this is not a per-repeat clean-service-restart experiment. Its valid claim boundary is paired engine-local vLLM prefix reuse under the recorded continuous service window, not Agent KV transfer or a clean-service general latency result.

The aggregate counters and TTFT rows below are recomputed directly from P0 Stage 09/10 summaries and the P1 Stage 18 repeat summary. `03_prefix_pair_validation.csv` independently reconciles all four repeat-summary pair references to their per-repeat `pair_summary.json`; pair-level counters are not persisted in those pair summaries and therefore remain null instead of being fabricated.

| Source | Scope | Mode | Hits/queries | Recomputed hit rate | Warm TTFT mean ms | Warm TTFT median ms | Rate matches raw report |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
{prefix_counter_rendered}

| Repeat | Order | Evidence file | Pair ok | Completion contracts | Direct pair-summary validation |
| ---: | --- | --- | --- | --- | --- |
{prefix_pair_rendered}

## Replay, Genericity And Latency

P0 Stage 03 has `{replay.get('selected_case_count')}` cases, quality `{stable_json(replay.get('quality_floor_breakdown'))}`, and replay distribution `{stable_json(replay.get('replay_class_distribution'))}`. Its aggregated role/call and reuse fields are `{stable_json(replay.get('telemetry_summary'))}`. Exact replay, restored answer, artifact reuse, skipped steps and reduced calls are separate values; the report does not infer one from another.

P0 Stage 08 records `{genericity.get('selected_case_count')}` cases across `{genericity.get('selected_family_count')}` families, route hints `{genericity.get('route_hint_policy')}`, and paraphrase equivalence `{stable_json(genericity.get('paraphrase_semantic_equivalence'))}`. Its own taint audit is `{stable_json(genericity.get('prompt_taint_audit'))}`. This supports a bounded precompiled-contract audit only, as stated by its source boundary: `{genericity.get('claim_boundary')}`.

The P0 serialized compare aggregate reports `{latency.get('repeat_count')}` repeats, all equal-quality validity `{latency.get('all_equal_quality_comparisons_valid')}`, favorable task-ms repeats `{latency.get('favorable_task_ms_repeat_count')}`, median task delta `{latency.get('median_task_ms_delta')}`, and `latency_superiority_claim_allowed={latency.get('latency_superiority_claim_allowed')}`. `03_latency_repeat_recomputation.csv` preserves every raw repeat metric and recomputes each aggregate below. Do not replace that explicit non-superiority gate with token results.

| Metric | Repeat | Source artifact | Equal-quality comparison | Raw delta |
| --- | ---: | --- | --- | ---: |
{latency_repeat_rendered}

| Metric | n | Sum | Recomputed median | Descriptive p90 (linear) | Descriptive p95 (linear) | Reported median | Matches report |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
{latency_aggregate_rendered}

The p90/p95 values are descriptive linear interpolation across only three serialized repeats. They do not establish tail-latency stability, and the raw source explicitly disallows a latency-superiority claim.

## P1 Backend And Flagship

| Variant | Requested mode | Actual mode | Transport | Quality | Fallback |
| --- | --- | --- | --- | ---: | ---: |
{backend_rows}

This supports functional realization of three modes. `mmap_loopback` and `shared_memory_loopback` are loopbacks, not cross-process IPC. `memfd_subprocess` is the only variant with a subprocess transport. The Stage 16 claim boundary itself withholds cross-backend timing superiority.

Stage 17 declares `{flagship.get('claim_level')}` and its external comparator restriction is `{flagship.get('fixed_answer_external_claim')}`. StateRef stress has `{stress.get('stress_pass_family_count')}/{stress.get('stress_family_count')}` passing families and `{stress.get('diagnostic_only_family_count')}` diagnostic-only family; its accumulated claimed prompt-visible saving is `{stress.get('total_prompt_visible_saved_by_state_ref_bytes')}` bytes. This evidence must retain the family eligibility and T2 scope present in the raw artifact.

## LogitState / Logits Participation Audit

`03_logitstate_participation_matrix.csv` searches every parsed P0/P1 JSON/JSONL artifact for logit/logprob fields, preserving raw artifact and JSON-field paths. Its numeric totals deliberately use only unique primary StateBus task-metric artifacts, so copied benchmark-report values cannot inflate the count. The task metrics show positive `logit_state_transfer_count` projections, but no primary artifact persists `logit_state_bytes`; missing bytes stay null rather than becoming zero. The normalised `state_ref_count` excludes this separate LogitState projection because no LogitStateRef registration or receiver was retained. Current source can serialize executor top-logprob data, yet the audited run artifacts do not record a LogitStateRef registry entry, a receiving role, a distinct consumption event, or a behavior-changing route/tool/retry/fallback effect.

| Scope | Primary metric rows | Positive transfer-count rows | Persisted logit-byte measurements | Entropy measurements | Confidence-gate sum | StateRef registration | Receiver | Route/tool/retry/fallback effect | A/B evidence |
| --- | ---: | --- | --- | ---: | ---: | --- | --- | --- | --- |
{logit_participation_rendered}

The only defensible conclusion is executor-side telemetry/metric projection. It is not evidence of a persisted hidden-state tensor, KV cache, agent-to-agent transfer, receiving-role consumption, or quality/efficiency benefit.

## Mechanisms, Fairness And Boundaries

| Mechanism | Claim status | Evidence level | Boundary |
| --- | --- | ---: | --- |
{chr(10).join(claim_rows)}

L0-L3 and T2 comparisons must not collapse semantic selection/pruning, prompt layout, carrier, memory/replay and state transport into one causal attribution. A backend loopback pass proves a functional path, not cross-process IPC or performance superiority. For UDS, only explicit subprocess/AF_UNIX/Protobuf lifecycle evidence can support the narrower external executor claim.

## Mechanism Evidence Matrix

The following matrix combines static source review with executed-artifact evidence. Static rows are bounded lexical line references in current code and the P1 anchor only; they identify paths for review and are explicitly not a data-flow proof. The full columns, including current/anchor references and fairness evidence, are in `03_mechanism_evidence_matrix.csv`.

| Mechanism | Level | Claim status | Artifact evidence | Consumption evidence | Boundary |
| --- | ---: | --- | --- | --- | --- |
{mechanism_rendered}

## Taint, Oracle, Fallback And Cache Audit

All available rendered requests were enumerated. The automated scanner reports `{taint_summary['raw_match_count']}` raw matches across `{taint_summary['unique_signature_count']}` unique rule/path/fragment signatures. That scanner intentionally does not call a field-name match a confirmed leak: role contract, upstream provenance, value semantics, scorer visibility and whether a verified route/tool was handed to Executor must be judged from the retained ledger. Existing genericity artifacts and precompiled `CanonicalTaskSpec` remain a limitation for free-text generalization claims.

`02_rendered_request_taint_rollup.csv` groups repeat hits by run/stage/case/role/rule, preserving raw occurrence and unique-fragment counts. The lexical static scan includes a complete `v2/`, `scripts/`, `tests/` index for expected-answer/gold/oracle, candidate/order/route/tool hints, case/sample specialization, CanonicalTaskSpec/precompile, and fallback/quality-gate surfaces in both current code and the P1 anchor. Counts below are line hits, not vulnerabilities; capped file/line references are retained in `04_full_experiment_truth_audit.json` as navigation evidence and do not establish answer leakage or cheating without role-aware provenance/data-flow review.

| Static lexical category | Current line hits | Current files | Anchor line hits | Anchor files |
| --- | ---: | ---: | ---: | ---: |
{global_risk_rows}

Cache and history remain a confounder unless artifacts demonstrate isolated history roots and case-level replay identity. Memory match, assist reuse, validated replay, exact replay, output restoration and skipped calls/tokens are separate columns in the ledger and must not be conflated.

## Contest Coverage And Claim Level

Evidence level is cumulative: `1` code definition, `2` executed path, `3` raw artifact data, `4` downstream behavior consumption, `5` repeated fair A/B benefit. `03_contest_coverage_matrix.csv` contains the code, run and fairness columns for each requirement derived from `docs/reference/题目.md`.

| Contest requirement | Level | Claim status | Proven content | Risk/gap |
| --- | ---: | --- | --- | --- |
{contest_rendered}

## P0/P1/P2 Issue Ledger

`05_issue_ledger.csv` retains phenomenon, root-cause/hypothesis, evidence, code location, impact, severity, repair, regression risk and minimal validation.

| Priority | Phenomenon | Root cause/hypothesis | Artifact evidence | Code location | Conclusion impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- | --- | --- | --- |
{issue_rendered}

## Conclusion Classes

- **Supported:** P0 has a complete recorded 16-label matrix with a historical pytest failure; P1 is additive; Stage 18 has completed repeat artifacts that satisfy the repaired default verifier.
- **Proxy/diagnostic only:** LogitState metric projection without persisted bytes/ref registration/receiver/behavior evidence; loopback backend functionality; single-run timing.
- **Not claimable:** Agent-to-Agent KV/hidden-state transfer, a new all-green P0 matrix, universal backend performance gain, free-text CanonicalTaskSpec compilation, and openEuler final-delivery validation.
"""


def issue_plan(prefix_check: dict[str, Any], issues: list[dict[str, Any]]) -> str:
    detailed = "\n".join(
        f"| {row['priority']} | {row['phenomenon']} | {row['severity']} | {row['regression_risk']} | {row['minimum_validation']} |"
        for row in issues
    )
    return f"""# Issues And Minimum Validation Plan

## High Priority

| Issue | Evidence | Impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- |
| P0 pytest status was historical fail | P0 `summary.json`, `status.tsv`, pytest log, later repair log | P0 cannot be called a complete all-pass matrix | Do not rewrite history; retain separate repair provenance | Targeted failing regression plus a separately labelled pytest-only rerun |
| Stage 18 runner post-processing failed | P1 `run.log` plus existing `repeat_summary.json`; preserved stderr is zero-byte | Run status is fail even though requests/artifact completed; exact historical exception is not independently recoverable | Keep original summary; retain the current validator repair only as post-run validation code | Re-run static verifier against immutable artifact; recover original stderr before asserting a specific NameError; rerun model requests only for a new experimental claim |
| Prefix cleanliness is limited | `clean_service_requested={prefix_check.get('clean_service_requested')}`, service window `{prefix_check.get('service_window')}` | TTFT sample can have service/warm-order confounding | Explicitly report clean and continuous-service cohorts | Four AB/BA pairs per corpus in both cohorts with before/after counters |

## Medium Priority

| Issue | Evidence | Impact | Minimum repair | Minimum validation |
| --- | --- | --- | --- | --- |
| Backend matrix variants have different process boundaries | Stage 16 variant contracts | Loopback cannot substantiate cross-process IPC or timing superiority | Split functional and timing claims by variant | Matched repeated timing and lifecycle evidence; subprocess-only IPC assertion |
| Memory/replay labels can overstate savings | replay class/call metrics are distinct | Match/validated replay may not skip work | Require per-case output/artifact/call/token deltas | Exact/validated/assist cases with independent checks |
| Compare changes more than carrier | L0-L3/T2/external implementations | Carrier-only attribution is not identified | Freeze semantic selection/tool/scorer/prompt visibility | Serialized AB/BA compare with medians and tail percentiles |
| StateRef consumption is not separately recorded | `STATE_PUBLISHED`/`STATE_HYDRATED` exist but `STATE_CONSUME=0` | Hydration cannot prove a behavior change | Emit role/ref/field consumption plus decision provenance | StateRef on/off or consumed-field perturbation with route/tool/output checks |
| LogitState has no handoff provenance | transfer-count/entropy metrics lack bytes/ref/receiver/consume evidence | No neural-state transfer or benefit claim | Persist payload/ref/receiver/decision linkage and an enabled flag | Matched LogitState on/off with quality/cost outcomes |

## Required Tests Versus Experiments

- Unit or targeted regression: role-call accounting, Stage 18 verifier import, metric denominator aggregation, taint role allowlist, replay call/token consistency.
- Targeted stage: backend variant lifecycle, one UDS subprocess trace, genericity safe-plan/taint gate.
- Clean repeat: prefix counter and TTFT parity under both clean and continuous service policies.
- Full matrix: only after targeted checks retain their contracts; it is required for a new all-stages claim, not to relabel P0.

## Regression Risks

The complete issue fields are in `05_issue_ledger.csv`.

| Priority | Phenomenon | Severity | Regression risk | Minimum validation |
| --- | --- | --- | --- | --- |
{detailed}
"""


def validate_outputs(output_root: Path) -> None:
    json_paths = [
        output_root / "01_artifact_inventory.json", output_root / "02_normalized_evidence_ledger.json",
        output_root / "04_full_experiment_truth_audit.json",
    ]
    parsed_json = {
        path.name: json.loads(path.read_text(encoding="utf-8")) for path in json_paths
    }
    for path, columns in [
        (output_root / "02_stage_layer_family_case.csv", CSV_COLUMNS),
        (output_root / "02_role_case_metrics.csv", ROLE_CASE_COLUMNS),
        (output_root / "03_comparison_recomputation.csv", COMPARISON_COLUMNS),
        (output_root / "03_prefix_counter_recomputation.csv", PREFIX_COUNTER_COLUMNS),
        (output_root / "03_prefix_pair_validation.csv", PREFIX_PAIR_COLUMNS),
        (output_root / "03_latency_repeat_recomputation.csv", LATENCY_REPEAT_COLUMNS),
        (output_root / "03_logitstate_participation_matrix.csv", LOGIT_PARTICIPATION_COLUMNS),
        (output_root / "02_rendered_request_taint_ledger.csv", TAINT_COLUMNS),
        (output_root / "02_rendered_request_taint_rollup.csv", TAINT_ROLLUP_COLUMNS),
        (output_root / "02_claim_and_boundary_ledger.csv", CLAIM_COLUMNS),
        (output_root / "03_stage_integrity_matrix.csv", STAGE_INTEGRITY_COLUMNS),
        (output_root / "03_mechanism_evidence_matrix.csv", MECHANISM_COLUMNS),
        (output_root / "03_contest_coverage_matrix.csv", CONTEST_COLUMNS),
        (output_root / "05_issue_ledger.csv", ISSUE_COLUMNS),
    ]:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != columns:
                raise ValueError(f"unexpected CSV header: {path}")
            seen: set[tuple[str | None, ...]] = set()
            for row in reader:
                key = tuple(row.get(column) for column in reader.fieldnames[:6])
                if path.name == "02_stage_layer_family_case.csv" and key in seen:
                    # Duplicate source records are valid only when their source path differs.
                    key += (row.get("source_path"),)
                seen.add(key)
    ledger = json.loads((output_root / "02_normalized_evidence_ledger.json").read_text(encoding="utf-8"))
    denominators = [item["quality_denominator"] for item in ledger["aggregates"] if item["quality_denominator"]]
    if not denominators:
        raise ValueError("no non-zero quality denominator was extracted")
    truth_summary = parsed_json["04_full_experiment_truth_audit.json"].get("summary", {})
    p1_eligibility = (
        (truth_summary.get("runtime_provenance", {}).get("p1", {}) or {}).get("source_eligibility") or {}
    )
    p1_source_statuses = p1_eligibility.get("source_stage_statuses") or {}
    if (
        p1_eligibility.get("mode") != "repaired_pytest_only"
        or p1_source_statuses.get("01_pytest_v2") != "fail"
        or sum(status == "pass" for status in p1_source_statuses.values()) != 15
        or p1_eligibility.get("repaired_pytest_pass_count") != 320
        or p1_eligibility.get("repaired_pytest_log_sha256") != truth_summary.get("pytest_repair", {}).get("sha256")
    ):
        raise ValueError("P1 source eligibility does not preserve the P0 pytest boundary")
    comparison_rows = list(csv.DictReader((output_root / "03_comparison_recomputation.csv").open("r", encoding="utf-8", newline="")))
    if not comparison_rows:
        raise ValueError("no matched comparison rows were extracted")
    if not any(row["treatment_layer"] == "T2" for row in comparison_rows):
        raise ValueError("T2 text-same-semantic-selection was not normalized into comparisons")
    latency_repeat_rows = list(csv.DictReader(
        (output_root / "03_latency_repeat_recomputation.csv").open("r", encoding="utf-8", newline="")
    ))
    required_latency_metrics = {
        "task_ms_delta", "llm_ms_delta", "total_tokens_delta", "prompt_tokens_delta",
    }
    raw_latency_rows = [row for row in latency_repeat_rows if row["row_type"] == "repeat"]
    raw_latency_by_metric: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in raw_latency_rows:
        raw_latency_by_metric[row["metric"]].append(row)
    if set(raw_latency_by_metric) != required_latency_metrics or any(
        {row["repeat_index"] for row in rows} != {"1", "2", "3"}
        or not all(row["comparison_valid"] == "True" and row["source_path"] for row in rows)
        for rows in raw_latency_by_metric.values()
    ):
        raise ValueError("P0 raw serialized latency repeat rows are incomplete")
    aggregate_latency_rows = {
        row["metric"]: row for row in latency_repeat_rows if row["row_type"] == "aggregate"
    }
    if set(aggregate_latency_rows) != required_latency_metrics:
        raise ValueError("P0 serialized latency aggregates are incomplete")
    for metric, raw_rows in raw_latency_by_metric.items():
        recomputed = median([float(row["value"]) for row in raw_rows])
        aggregate = aggregate_latency_rows[metric]
        if not math.isclose(float(aggregate["median"]), recomputed, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"P0 latency median does not match raw repeats: {metric}")
        if metric != "prompt_tokens_delta" and aggregate["matches_report"] != "True":
            raise ValueError(f"P0 latency reported median does not match recomputation: {metric}")
    logit_rows = list(csv.DictReader(
        (output_root / "03_logitstate_participation_matrix.csv").open("r", encoding="utf-8", newline="")
    ))
    expected_logit_scopes = {"p0_full", "p1_extension", "p0_p1_combined"}
    if {row["scope"] for row in logit_rows} != expected_logit_scopes:
        raise ValueError("LogitState participation scopes are incomplete")
    combined_logit_row = next(row for row in logit_rows if row["scope"] == "p0_p1_combined")
    if (
        combined_logit_row["positive_transfer_metric_row_count"] != "848"
        or combined_logit_row["transfer_count_sum"] != "848.0"
        or combined_logit_row["logit_byte_measurement_row_count"] != "0"
        or combined_logit_row["logit_byte_sum"] != ""
    ):
        raise ValueError("LogitState participation evidence was altered or zero-filled")
    prefix_pair_rows = list(csv.DictReader((output_root / "03_prefix_pair_validation.csv").open("r", encoding="utf-8", newline="")))
    if len(prefix_pair_rows) != 4 or not all(row["pair_validation_status"] == "validated" for row in prefix_pair_rows):
        raise ValueError("Stage 18 four-pair validation is incomplete")
    with (output_root / "03_stage_integrity_matrix.csv").open("r", encoding="utf-8", newline="") as handle:
        integrity_rows = list(csv.DictReader(handle))
    expected_stages = {f"{index:02d}" for index in range(19)}
    observed_numbers = {str(row["stage"])[:2] for row in integrity_rows}
    if observed_numbers != expected_stages:
        raise ValueError(f"stage integrity coverage mismatch: {sorted(observed_numbers)}")
    primary_csv = (output_root / "02_stage_layer_family_case.csv").read_text(encoding="utf-8")
    if "full_qwen3_full_p1_fix_20260715_001459" in primary_csv:
        raise ValueError("pytest repair rows leaked into the primary case CSV")
    primary_rows = list(csv.DictReader(primary_csv.splitlines()))
    if not primary_rows:
        raise ValueError("primary case ledger is empty")
    for row_index, row in enumerate(primary_rows, start=2):
        try:
            field_paths = json.loads(row["metric_field_paths"] or "{}")
            missing_fields = json.loads(row["missing_metric_fields"] or "[]")
            missing_reasons = json.loads(row["missing_metric_reason"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid metric provenance JSON at primary CSV row {row_index}: {exc}") from exc
        if not isinstance(field_paths, dict) or not isinstance(missing_fields, list) or not isinstance(missing_reasons, dict):
            raise ValueError(f"invalid metric provenance shape at primary CSV row {row_index}")
        if not set(missing_fields).issubset(TRACKED_METRIC_FIELD_ALIASES):
            raise ValueError(f"unknown missing metric field at primary CSV row {row_index}")
        if set(missing_fields) != set(missing_reasons):
            raise ValueError(f"missing metric reasons do not cover every null field at primary CSV row {row_index}")
        for field, paths in field_paths.items():
            if field not in TRACKED_METRIC_FIELD_ALIASES or not isinstance(paths, list) or not all("#$" in str(item) for item in paths):
                raise ValueError(f"invalid metric field path at primary CSV row {row_index}: {field}")
    required_markdown = [
        "00_scope_and_run_index.md", "01_artifact_inventory.md", "03_working_findings.md",
        "04_full_experiment_truth_audit.md", "05_issue_and_minimum_validation_plan.md",
    ]
    missing_markdown = [name for name in required_markdown if not (output_root / name).is_file()]
    if missing_markdown:
        raise ValueError(f"missing required Markdown output: {missing_markdown}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Static Qwen3 P0/P1 evidence audit")
    parser.add_argument("--full-root", type=Path, default=DEFAULT_FULL_ROOT)
    parser.add_argument("--pytest-repair-log", type=Path, default=DEFAULT_REPAIR_LOG)
    parser.add_argument("--p1-root", type=Path, default=DEFAULT_P1_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    args = parser.parse_args()
    for path in (args.full_root, args.p1_root, args.pytest_repair_log):
        if not path.exists():
            raise SystemExit(f"missing required input: {path}")
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    full_entries, full_inventory, full_parsed = inventory_root("p0_full", args.full_root)
    repair_root = args.pytest_repair_log.parent.parent
    repair_entries, repair_inventory, repair_parsed = inventory_root("pytest_repair_partial", repair_root)
    p1_entries, p1_inventory, p1_parsed = inventory_root("p1_extension", args.p1_root)
    p0_summary = full_parsed.get(args.full_root / "summary.json", {})
    p1_summary = p1_parsed.get(args.p1_root / "summary.json", {})
    p0_statuses = read_stage_statuses(args.full_root, p0_summary)
    p1_statuses = read_stage_statuses(args.p1_root, p1_summary)
    p0_coverage = stage_artifact_coverage(full_entries, p0_statuses)
    p1_coverage = stage_artifact_coverage(p1_entries, p1_statuses)
    root_sets = [
        ("p0_full", args.full_root, full_parsed),
        ("pytest_repair_partial", repair_root, repair_parsed),
        ("p1_extension", args.p1_root, p1_parsed),
    ]
    case_rows = extract_case_ledger(root_sets)
    partial_candidate_rows = extract_case_ledger(
        [("pytest_repair_partial", repair_root, repair_parsed)],
        include_pytest_repair_partial=True,
    )
    aggregates = aggregate_case_rows(case_rows)
    comparison_rows = comparison_recomputation(case_rows)
    taint_rows, taint_summary = rendered_request_rows(root_sets)
    repeat_path = args.p1_root / "stages/18_prefix_parity_clean_repeats/repeat_summary.json"
    prefix_check = p1_prefix_verification(
        p1_parsed.get(repeat_path),
        args.p1_root / "logs/18_prefix_parity_clean_repeats.stderr.log",
    )
    prefix_pair_rows = prefix_pair_validation(p1_parsed.get(repeat_path), args.p1_root, p1_parsed)
    prefix_counter_rows = prefix_counter_recomputation(
        args.full_root, full_parsed, args.p1_root, p1_parsed,
    )
    latency_repeat_rows = latency_repeat_recomputation(args.full_root, full_parsed)
    prefix_check["pair_validation"] = {
        "pair_count": len(prefix_pair_rows),
        "validated_pair_count": sum(row["pair_validation_status"] == "validated" for row in prefix_pair_rows),
        "rows": prefix_pair_rows,
    }
    repair_log_text = args.pytest_repair_log.read_text(encoding="utf-8", errors="replace")
    repair_passes = [int(value) for value in re.findall(r"(\d+)\s+passed", repair_log_text)]
    diagnostics = stage_diagnostics(
        args.full_root, full_parsed, args.p1_root, p1_parsed, args.pytest_repair_log
    )
    integrity_rows = stage_integrity_matrix(
        "p0_full", args.full_root, full_entries, full_parsed, p0_statuses, case_rows,
    ) + stage_integrity_matrix(
        "p1_extension", args.p1_root, p1_entries, p1_parsed, p1_statuses, case_rows,
    )
    role_rows = role_case_metrics(root_sets)
    taint_rollup_rows = taint_rollup(taint_rows)
    static_scan = static_specialization_scan(Path.cwd())
    event_evidence = runtime_event_evidence(root_sets, case_rows)
    logit_participation_rows, logit_participation_summary = logit_participation_matrix(root_sets, case_rows)
    provenance = runtime_provenance(
        Path.cwd(), args.full_root, full_entries, full_parsed,
        args.p1_root, p1_entries, p1_parsed,
        case_rows, prefix_check,
    )
    mechanism_rows = mechanism_evidence_matrix(
        static_scan, diagnostics, event_evidence, prefix_check, logit_participation_summary,
    )
    contest_rows = contest_coverage_matrix(static_scan, diagnostics)
    issues = issue_ledger(prefix_check, static_scan)
    primary_counts = Counter(row["system_identity"] for row in case_rows)
    partial_rows_by_stage = Counter(str(row["stage"]) for row in partial_candidate_rows if row["stage"])
    partial_rows_by_system = Counter(row["system_identity"] for row in partial_candidate_rows)
    partial_exclusion = {
        "run_group": "pytest_repair_partial",
        "reason": (
            "The partial repair launcher was interrupted at Stage 02. Its later pytest log is admissible "
            "only for the pytest repair conclusion; workspace and external-comparator artifacts cannot be "
            "treated as a new P0/P1 experiment matrix."
        ),
        "normalized_candidate_row_count": len(partial_candidate_rows),
        "rows_by_stage": dict(sorted(partial_rows_by_stage.items())),
        "rows_by_system_identity": dict(sorted(partial_rows_by_system.items())),
        "source_paths": sorted({row["source_path"] for row in partial_candidate_rows}),
    }
    summary = {
        "schema_version": "statebus.qwen3_p0_p1_evidence_audit.v1",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_command": " ".join([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]),
        "inputs": {
            "full_root": str(args.full_root), "pytest_repair_log": str(args.pytest_repair_log),
            "p1_root": str(args.p1_root), "output_root": str(output_root),
        },
        "roots": {"p0_full": full_inventory, "pytest_repair_partial": repair_inventory, "p1_extension": p1_inventory},
        "p0_summary": p0_summary,
        "p1_summary": p1_summary,
        "p0_stage_statuses": p0_statuses,
        "p1_stage_statuses": p1_statuses,
        "stage_artifact_coverage": p0_coverage + p1_coverage,
        "pytest_repair": {
            "log": str(args.pytest_repair_log), "sha256": sha256_file(args.pytest_repair_log),
            "mtime_ns": args.pytest_repair_log.stat().st_mtime_ns,
            "reported_pass_counts": repair_passes,
            "partial_run_root": str(repair_root),
            "claim_boundary": "pytest-only repair evidence; not a full matrix rerun",
        },
        "p1_stage18_verification": prefix_check,
        "comparison_recomputation": comparison_rows,
        "prefix_counter_recomputation": prefix_counter_rows,
        "latency_repeat_recomputation": latency_repeat_rows,
        "stage_diagnostics": diagnostics,
        "stage_integrity_matrix": integrity_rows,
        "runtime_event_evidence": event_evidence,
        "logitstate_participation_summary": logit_participation_summary,
        "runtime_provenance": provenance,
        "static_specialization_review": static_scan,
        "taint_summary": taint_summary,
        "experiment_count_interpretation": {
            "stage_label_count": len(p0_statuses) + len(p1_statuses),
            "user_level_experiment_count": len(p0_statuses) + len(p1_statuses) - 1,
            "precondition_label": "00_preflight",
            "backend_variant_count": len(diagnostics.get("p1_backend", [])),
            "primary_normalized_case_record_count": len(case_rows),
            "interpretation": (
                "Labels 00-18 produce 19 stages. The user-level count of 18 excludes 00_preflight as a "
                "precondition; backend variants and case/layer/family records are expanded units, not extra experiments."
            ),
        },
        "normalized_evidence_counts": {
            "primary_case_row_count": len(case_rows),
            "statebus_case_row_count": primary_counts["statebus"],
            "external_case_row_count": primary_counts["external"],
        },
        "excluded_partial_case_artifacts": partial_exclusion,
        "git_state": provenance["current_vs_anchor"],
        "code_evidence_index": static_code_evidence(Path.cwd(), static_scan),
        "excluded_files": [],
    }
    inventory_payload = {"summary": summary, "files": full_entries + repair_entries + p1_entries}
    normalized = {
        "schema_version": "statebus.qwen3_p0_p1_normalized_ledger.v1",
        "script_version": SCRIPT_VERSION,
        "case_rows": case_rows,
        "aggregates": aggregates,
        "comparison_recomputation": comparison_rows,
        "prefix_counter_recomputation": prefix_counter_rows,
        "latency_repeat_recomputation": latency_repeat_rows,
        "prefix_pair_validation": prefix_pair_rows,
        "role_case_rows": role_rows,
        "logitstate_participation_rows": logit_participation_rows,
        "logitstate_participation_summary": logit_participation_summary,
        "taint_rollup_rows": taint_rollup_rows,
        "stage_integrity_rows": integrity_rows,
        "excluded_partial_case_artifacts": partial_exclusion,
        "field_policy": (
            "every populated tracked metric records artifact#JSONPath source locations in metric_field_paths; "
            "missing_metric_fields and missing_metric_reason preserve field-level null causes; no missing metric is replaced with zero"
        ),
        "rate_policy": "rates are sum(numerator)/sum(denominator), never sums of per-case rates",
    }
    claims = claim_ledger(
        prefix_check,
        p0_summary if isinstance(p0_summary, dict) else {},
        p1_summary if isinstance(p1_summary, dict) else {},
        logit_participation_summary,
    )
    final_json = {
        "schema_version": "statebus.qwen3_p0_p1_truth_audit.v1",
        "summary": summary,
        "stage_table": p0_statuses + p1_statuses,
        "stage_integrity_matrix": integrity_rows,
        "aggregates": aggregates,
        "comparison_recomputation": comparison_rows,
        "prefix_counter_recomputation": prefix_counter_rows,
        "latency_repeat_recomputation": latency_repeat_rows,
        "prefix_pair_validation": prefix_pair_rows,
        "role_case_metrics": role_rows,
        "logitstate_participation_matrix": logit_participation_rows,
        "logitstate_participation_summary": logit_participation_summary,
        "taint_rollup": taint_rollup_rows,
        "mechanism_evidence_matrix": mechanism_rows,
        "contest_coverage_matrix": contest_rows,
        "issue_ledger": issues,
        "runtime_provenance": provenance,
        "static_specialization_review": static_scan,
        "runtime_event_evidence": event_evidence,
        "claims": claims,
        "minimum_validation_plan": [
            "targeted role-call metric and Stage 18 verifier regressions",
            "serialized AB/BA compare and clean/continuous prefix cohorts",
            "new full matrix only for a new all-stage claim",
        ],
    }
    write_json(output_root / "01_artifact_inventory.json", inventory_payload)
    (output_root / "01_artifact_inventory.md").write_text(markdown_inventory(summary, p0_coverage + p1_coverage), encoding="utf-8")
    write_json(output_root / "02_normalized_evidence_ledger.json", normalized)
    write_csv(output_root / "02_stage_layer_family_case.csv", CSV_COLUMNS, case_rows)
    write_csv(output_root / "02_role_case_metrics.csv", ROLE_CASE_COLUMNS, role_rows)
    write_csv(output_root / "03_comparison_recomputation.csv", COMPARISON_COLUMNS, comparison_rows)
    write_csv(output_root / "03_prefix_counter_recomputation.csv", PREFIX_COUNTER_COLUMNS, prefix_counter_rows)
    write_csv(output_root / "03_prefix_pair_validation.csv", PREFIX_PAIR_COLUMNS, prefix_pair_rows)
    write_csv(output_root / "03_latency_repeat_recomputation.csv", LATENCY_REPEAT_COLUMNS, latency_repeat_rows)
    write_csv(output_root / "03_logitstate_participation_matrix.csv", LOGIT_PARTICIPATION_COLUMNS, logit_participation_rows)
    write_csv(output_root / "02_rendered_request_taint_ledger.csv", TAINT_COLUMNS, taint_rows)
    write_csv(output_root / "02_rendered_request_taint_rollup.csv", TAINT_ROLLUP_COLUMNS, taint_rollup_rows)
    write_csv(output_root / "02_claim_and_boundary_ledger.csv", CLAIM_COLUMNS, claims)
    write_csv(output_root / "03_stage_integrity_matrix.csv", STAGE_INTEGRITY_COLUMNS, integrity_rows)
    write_csv(output_root / "03_mechanism_evidence_matrix.csv", MECHANISM_COLUMNS, mechanism_rows)
    write_csv(output_root / "03_contest_coverage_matrix.csv", CONTEST_COLUMNS, contest_rows)
    write_csv(output_root / "05_issue_ledger.csv", ISSUE_COLUMNS, issues)
    (output_root / "00_scope_and_run_index.md").write_text(scope_markdown(summary, p0_statuses, p1_statuses), encoding="utf-8")
    (output_root / "03_working_findings.md").write_text(working_findings(summary, prefix_check, taint_summary), encoding="utf-8")
    (output_root / "04_full_experiment_truth_audit.md").write_text(
        full_report(
            summary, p0_statuses, p1_statuses, case_rows, aggregates, prefix_check, taint_summary,
            claims, integrity_rows, role_rows, mechanism_rows, contest_rows, provenance, issues,
            comparison_rows, prefix_counter_rows, prefix_pair_rows, latency_repeat_rows,
            logit_participation_rows,
        ), encoding="utf-8",
    )
    write_json(output_root / "04_full_experiment_truth_audit.json", final_json)
    (output_root / "05_issue_and_minimum_validation_plan.md").write_text(issue_plan(prefix_check, issues), encoding="utf-8")
    validate_outputs(output_root)
    print(json.dumps({"output_root": str(output_root), "case_rows": len(case_rows), "taint_rows": len(taint_rows), "status": "validated"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
