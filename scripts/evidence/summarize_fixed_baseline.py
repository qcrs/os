#!/usr/bin/env python3
"""Derive decision-facing statistics from the canonical StateBus E0-E6 baseline.

This utility is deliberately read-only with respect to experiment artifacts. It
does not start tests, benchmarks, containers, model requests, or vLLM. It reads
only the canonical E1-E5 case/audit slices and writes one derived JSON report so
that presentation claims can be traced back to per-case evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import statistics
from typing import Any, Iterable


DEFAULT_ROOT = Path("/home/qcrs/statebus/runs/contest_evidence_closure_20260720")
RUNS = {
    "E0": "e0_focused_20260720_142422",
    "E1": "e1_causal_serial_20260720_150801",
    "E2": "e2_stress_serial_20260720_152924",
    "E3": "e3_adaptive_memory_final_20260720_160244",
    "E4": "e4_semantic_holdout_final4_20260720_175430",
    "E5": "e5_adaptive_final_20260720_190107",
    "E6": "e6_full_final_20260720_201043",
}

E1_E2_METRICS = (
    "message_count",
    "control_message_count",
    "control_bytes",
    "total_wire_bytes",
    "transport_request_wire_bytes",
    "transport_response_wire_bytes",
    "utf8_text_frame_count",
    "protobuf_frame_count",
    "ack_count",
    "llm_prompt_bytes",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "llm_call_count",
    "llm_wall_ms",
    "task_ms",
    "raw_evidence_bytes_seen_by_llm",
    "selected_evidence_bytes",
    "prompt_visible_total_bytes",
    "prompt_scaffolding_bytes_total",
    "semantic_state_ref_count",
    "semantic_state_transfer_count",
    "semantic_state_publish_count",
    "semantic_state_resolve_count",
    "semantic_state_consume_count",
    "semantic_state_release_count",
    "semantic_state_selected_count",
    "shared_memory_publish_count",
    "semantic_state_bytes",
    "semantic_state_released_bytes",
    "hybrid_memory_query_count",
    "memory_candidate_count",
    "memory_compatible_match_count",
    "memory_policy_approved_match_count",
    "memory_consumed_count",
    "memory_behavioral_effect_count",
    "memory_rejected_incompatible_count",
    "memory_commit_count",
    "memory_ref_count",
    "memory_assist_count",
    "validated_replay_count",
    "exact_replay_count",
    "skipped_step_count",
    "skipped_llm_call_count",
    "history_artifact_reuse_count",
    "history_reuse_gain",
    "history_step_reduction_count",
    "control_plane_exchange_stage_ms",
    "persist_and_reload_stage_ms",
    "runtime_driver_stage_ms",
    "codeact_execution_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "telemetry_emit_stage_ms",
    "runtime_signature_stage_ms",
    "retrieval_candidate_count",
    "retrieval_selected_count",
    "evidence_pruning_keep_count",
    "evidence_pruning_drop_count",
    "evidence_pruning_estimated_kv_tokens_saved",
    "verified_artifact_count",
    "verified_artifact_ref_count",
    "validator_report_count",
    "quality_floor_pass",
    "fact_coverage_validator_pass",
    "deterministic_validator_pass",
    "benchmark_gold_runtime_decision_input_count",
    "planner_semantic_plan_validation_error_count",
    "planner_objective_source_runtime_fallback",
    "runtime_fallback_count",
    "state_pool_fallback_count",
    "codeact_sandbox_fallback_count",
    "gc_issue_count",
)

DIAGNOSTIC_CASE_METRICS = (
    "planner_semantic_plan_validation_error_count",
    "planner_objective_source_runtime_fallback",
    "runtime_fallback_count",
    "state_pool_fallback_count",
    "codeact_sandbox_fallback_count",
    "skipped_step_count",
    "skipped_llm_call_count",
    "validated_replay_count",
)

DECISION_SUPPORT_METRICS = (
    # Typed-plan production and downstream use.
    "planner_behavioral_effect",
    "planner_semantic_plan_valid",
    "planner_generated_retrieval_objective_count",
    "planner_model_generated_field_count",
    "planner_model_downstream_consumed_field_count",
    "planner_downstream_consumed_field_count",
    "planner_retriever_consumed_hash_match_count",
    "planner_objective_source_hybrid",
    "planner_objective_source_runtime_fallback",
    "planner_semantic_plan_validation_error_count",
    # Verified artifact promotion and bounded execution.
    "workflow_step_count",
    "completed_workflow_step_count",
    "input_validator_report_count",
    "validator_report_count",
    "artifact_count",
    "verified_artifact_count",
    "verified_artifact_ref_count",
    "compiler_success_count",
    "codeact_sandbox_bwrap_count",
    "codeact_sandbox_fallback_count",
    # State/memory configuration must stay separate from actual use.
    "state_pool_shared_memory_mode_count",
    "shared_memory_publish_count",
    "semantic_state_transfer_count",
    "memory_ref_count",
    "memory_commit_count",
    "memory_keyword_candidate_count",
    "memory_tag_candidate_count",
    "memory_vector_candidate_count",
    "memory_consumed_count",
    "validated_downgraded_reuse_count",
    "validated_replay_count",
    "reuse_gain",
    "skipped_step_count",
    "skipped_llm_call_count",
    # Durable evidence and instrumentation footprint.
    "runtime_session_count",
    "replay_ledger_entry_count",
    "workspace_files",
    "workspace_input_bundle_reused_count",
    "workspace_input_bundle_write_count",
    "workspace_input_direct_write_count",
    "workspace_input_manifest_write_count",
    "workspace_output_bundle_reused_count",
    "workspace_output_bundle_write_count",
    "workspace_output_manifest_write_count",
    "telemetry_event_write_count",
    "telemetry_fact_write_count",
)

LATENCY_DIAGNOSTIC_METRICS = (
    "task_ms",
    "llm_wall_ms",
    "control_plane_exchange_stage_ms",
    "runtime_driver_stage_ms",
    "codeact_execution_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_bundle_write_stage_ms",
    "persist_core_reload_stage_ms",
    "persist_integrity_check_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "persist_semantic_manifest_reload_stage_ms",
    "persist_session_ledger_reload_stage_ms",
    "persist_validator_reload_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "runtime_signature_stage_ms",
    "runtime_data_plane_event_stage_ms",
    "runtime_replay_ledger_stage_ms",
    "runtime_commit_finalize_stage_ms",
    "telemetry_emit_stage_ms",
)

ROLE_METRIC_SUFFIXES = (
    "prompt_bytes",
    "prompt_scaffolding_bytes",
    "prompt_visible_bytes",
    "completion_tokens",
    "hydrated_bytes",
    "text_bytes",
    "table_bytes",
    "memory_bytes",
    "handoff_bytes",
    "call_count",
)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def json_files(path: Path) -> list[Path]:
    return sorted(path.glob("*.json"))


def percentile(values: Iterable[float], fraction: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def describe(values: Iterable[float]) -> dict[str, float | int | None]:
    collected = [float(value) for value in values]
    if not collected:
        return {
            "count": 0,
            "sum": 0.0,
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(collected),
        "sum": sum(collected),
        "min": min(collected),
        "p50": statistics.median(collected),
        "p95": percentile(collected, 0.95),
        "max": max(collected),
        "mean": statistics.fmean(collected),
    }


def numeric_metrics(record: dict[str, Any]) -> dict[str, float]:
    metrics = record.get("metrics", {})
    if not isinstance(metrics, dict):
        return {}
    return {
        key: float(value)
        for key, value in metrics.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def aggregate_metrics(
    records: Iterable[dict[str, Any]], metric_names: Iterable[str]
) -> dict[str, dict[str, float | int | None]]:
    rows = list(records)
    return {
        metric: describe(
            numeric_metrics(row)[metric]
            for row in rows
            if metric in numeric_metrics(row)
        )
        for metric in metric_names
    }


def metric_catalog(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    values: defaultdict[str, list[float]] = defaultdict(list)
    for record in records:
        for key, value in numeric_metrics(record).items():
            values[key].append(value)
    return {
        key: {
            **describe(items),
            "nonzero_count": sum(value != 0 for value in items),
        }
        for key, items in sorted(values.items())
    }


def load_case_reports(root: Path, stage: str) -> list[dict[str, Any]]:
    run_root = root / RUNS[stage]
    records = []
    for path in json_files(run_root / "case_reports"):
        record = load_json(path)
        record["_source_path"] = str(path)
        records.append(record)
    return records


def group_records(
    records: Iterable[dict[str, Any]], keys: tuple[str, ...]
) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        label = " / ".join(str(record.get(key, "")) for key in keys)
        grouped[label].append(record)
    return dict(sorted(grouped.items()))


def selected_metric_row(record: dict[str, Any]) -> dict[str, Any]:
    metrics = numeric_metrics(record)
    return {
        "task_id": record.get("task_id"),
        "task_family": record.get("task_family"),
        "lane": record.get("layer"),
        "round_number": metrics.get("round_number"),
        "replay_class": record.get("replay_class"),
        "quality_pass": (record.get("quality_floor") or {}).get("quality_floor_pass"),
        "metrics": {key: metrics.get(key, 0.0) for key in E1_E2_METRICS},
        "source_path": record["_source_path"],
    }


def diagnostic_case_rows(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        metrics = numeric_metrics(record)
        observed = {
            key: metrics[key]
            for key in DIAGNOSTIC_CASE_METRICS
            if metrics.get(key, 0.0) != 0.0
        }
        if observed:
            rows.append(
                {
                    "task_id": record.get("task_id"),
                    "task_family": record.get("task_family"),
                    "lane": record.get("layer"),
                    "metrics": observed,
                    "source_path": record["_source_path"],
                }
            )
    return rows


def workspace_memory_receipt_summary(
    run_root: Path, case_index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    files = sorted(run_root.glob("workspaces/**/logs/memory_consumption.json"))
    unique_records: dict[str, dict[str, Any]] = {}
    per_task: list[dict[str, Any]] = []
    for path in files:
        value = load_json(path)
        task_id = str(value.get("task_id", ""))
        records = value.get("records") or []
        record_ids = []
        for index, record in enumerate(records):
            record_id = str(
                record.get("consumption_id")
                or f"{task_id}:{index}:{record.get('memory_id', '')}"
            )
            unique_records.setdefault(record_id, record)
            record_ids.append(record_id)
        per_task.append(
            {
                "task_id": task_id,
                **case_index.get(task_id, {}),
                "record_count": len(records),
                "record_ids": record_ids,
                "source_path": str(path),
            }
        )

    records = list(unique_records.values())
    roles = Counter(str(record.get("consumer_role", "")) for record in records)
    effects = Counter(str(record.get("behavioral_effect", "")) for record in records)
    verdicts = Counter(
        str(record.get("compatibility_verdict", "")) for record in records
    )
    replay_classes = Counter(str(record.get("replay_class", "")) for record in records)
    memory_ids = {
        str(record.get("memory_id")) for record in records if record.get("memory_id")
    }
    return {
        "audit_file_count": len(files),
        "audit_file_with_records_count": sum(row["record_count"] > 0 for row in per_task),
        "unique_receipt_count": len(records),
        "unique_memory_id_count": len(memory_ids),
        "consumer_roles": dict(roles),
        "behavioral_effects": dict(effects),
        "compatibility_verdicts": dict(verdicts),
        "replay_classes": dict(replay_classes),
        "decision_surface_changed_count": sum(
            record.get("before_decision_surface_hash")
            != record.get("after_decision_surface_hash")
            for record in records
        ),
        "recipe_recomputed_count": sum(
            bool(record.get("recipe_recomputed")) for record in records
        ),
        "skipped_generation_step_count": sum(
            int(record.get("skipped_generation_step_count", 0)) for record in records
        ),
        "skipped_llm_call_count": sum(
            int(record.get("skipped_llm_call_count", 0)) for record in records
        ),
        "per_task": per_task,
    }


def workspace_artifact_promotion_summary(run_root: Path) -> dict[str, Any]:
    files = sorted(run_root.glob("workspaces/**/logs/artifact_audit.json"))
    records = []
    for path in files:
        value = load_json(path)
        value["_source_path"] = str(path)
        records.append(value)

    gate_reasons = Counter(str(record.get("commit_gate_reason", "")) for record in records)
    settlement_states = Counter(
        str(record.get("settlement_state", "")) for record in records
    )
    verification_states = Counter(
        str(record.get("verification_state", "")) for record in records
    )
    storage_kinds = Counter(str(record.get("state_storage_kind", "")) for record in records)
    return {
        "audit_file_count": len(files),
        "commit_gate_reasons": dict(gate_reasons),
        "settlement_states": dict(settlement_states),
        "verification_states": dict(verification_states),
        "replay_ready_count": sum(record.get("replay_ready") is True for record in records),
        "artifact_size_bytes": describe(
            float(record.get("size_bytes", 0)) for record in records
        ),
        "unique_blob_hash_count": len(
            {record.get("blob_hash") for record in records if record.get("blob_hash")}
        ),
        "input_validator_reference_count": sum(
            len(record.get("input_validator_hashes") or []) for record in records
        ),
        "validator_reference_count": sum(
            len(record.get("validator_report_hashes") or []) for record in records
        ),
        "memory_commit_path_count": sum(
            bool(record.get("memory_commit_path")) for record in records
        ),
        "state_storage_kinds": dict(storage_kinds),
        "lineage_complete_count": sum(
            all(
                record.get(field)
                for field in (
                    "artifact_id",
                    "artifact_manifest_hash",
                    "blob_hash",
                    "input_manifest_hash",
                    "output_artifact_hash",
                    "output_artifact_path",
                    "memory_commit_path",
                    "replay_ledger_path",
                    "runtime_signature_manifest_bundle_path",
                    "session_path",
                )
            )
            for record in records
        ),
        "source_paths": [record["_source_path"] for record in records],
    }


def build_e1(root: Path) -> dict[str, Any]:
    records = load_case_reports(root, "E1")
    by_lane = group_records(records, ("layer",))
    by_family_lane = group_records(records, ("task_family", "layer"))

    role_metrics = [
        f"{role}_{suffix}"
        for role in ("planner", "retriever", "executor", "summarizer")
        for suffix in ROLE_METRIC_SUFFIXES
    ]

    pair_metrics = (
        "task_ms",
        "llm_wall_ms",
        "llm_prompt_tokens",
        "llm_total_tokens",
        "control_bytes",
        "total_wire_bytes",
        "prompt_visible_total_bytes",
    )
    indexed = {
        (record.get("task_family"), record.get("task_id"), record.get("layer")): record
        for record in records
    }
    paired: list[dict[str, Any]] = []
    for family, task_id, lane in sorted(indexed):
        if lane != "L0":
            continue
        left = numeric_metrics(indexed[(family, task_id, "L0")])
        right = numeric_metrics(indexed[(family, task_id, "L3")])
        deltas = {}
        for metric in pair_metrics:
            lval = left.get(metric, 0.0)
            rval = right.get(metric, 0.0)
            deltas[metric] = {
                "L0": lval,
                "L3": rval,
                "absolute_delta": rval - lval,
                "relative_delta_pct": ((rval - lval) / lval * 100.0) if lval else None,
                "L3_lower": rval < lval,
            }
        paired.append({"task_family": family, "task_id": task_id, "deltas": deltas})

    pair_summary = {}
    for metric in pair_metrics:
        relative = [
            row["deltas"][metric]["relative_delta_pct"]
            for row in paired
            if row["deltas"][metric]["relative_delta_pct"] is not None
        ]
        pair_summary[metric] = {
            "L3_lower_count": sum(row["deltas"][metric]["L3_lower"] for row in paired),
            "L3_equal_count": sum(
                row["deltas"][metric]["L0"] == row["deltas"][metric]["L3"]
                for row in paired
            ),
            "L3_higher_count": sum(
                row["deltas"][metric]["L3"] > row["deltas"][metric]["L0"]
                for row in paired
            ),
            "paired_relative_delta_pct": describe(relative),
        }

    return {
        "case_count": len(records),
        "per_case": [selected_metric_row(record) for record in records],
        "lane_metrics": {
            group: aggregate_metrics(items, E1_E2_METRICS)
            for group, items in by_lane.items()
        },
        "family_lane_metrics": {
            group: aggregate_metrics(items, E1_E2_METRICS)
            for group, items in by_family_lane.items()
        },
        "role_metrics_by_lane": {
            group: aggregate_metrics(items, role_metrics) for group, items in by_lane.items()
        },
        "decision_support_by_lane": {
            group: aggregate_metrics(items, DECISION_SUPPORT_METRICS)
            for group, items in by_lane.items()
        },
        "latency_diagnostics_by_lane": {
            group: aggregate_metrics(items, LATENCY_DIAGNOSTIC_METRICS)
            for group, items in by_lane.items()
        },
        "memory": memory_slice_summary(root / RUNS["E1"], records),
        "artifact_promotion": workspace_artifact_promotion_summary(
            root / RUNS["E1"]
        ),
        "paired_L0_L3": paired,
        "paired_L0_L3_summary": pair_summary,
        "diagnostic_nonzero_cases": diagnostic_case_rows(records),
        "all_numeric_metric_catalog": metric_catalog(records),
    }


def memory_slice_summary(
    run_root: Path, case_records: Iterable[dict[str, Any]] = ()
) -> dict[str, Any]:
    case_index = {
        str(record.get("task_id")): {
            "task_family": record.get("task_family"),
            "round_number": numeric_metrics(record).get("round_number"),
        }
        for record in case_records
    }
    query_count = 0
    query_with_candidates = 0
    query_with_compatible = 0
    candidate_count = 0
    compatible_count = 0
    approved_count = 0
    compatibility_verdicts: Counter[str] = Counter()
    compatibility_reasons: Counter[str] = Counter()
    retrieval_decisions: Counter[str] = Counter()
    match_sources: Counter[str] = Counter()
    incompatible_candidate_ranks: Counter[int] = Counter()
    materialized_query_result_count = 0
    per_query: list[dict[str, Any]] = []

    for path in json_files(run_root / "memory_queries"):
        value = load_json(path)
        metrics = value.get("metrics") or {}
        current_queries = int(metrics.get("hybrid_memory_query_count", 0))
        current_candidates = int(metrics.get("memory_candidate_count", 0))
        current_compatible = int(metrics.get("memory_compatible_match_count", 0))
        current_approved = int(metrics.get("memory_policy_approved_match_count", 0))
        query_count += current_queries
        candidate_count += current_candidates
        compatible_count += current_compatible
        approved_count += current_approved
        query_with_candidates += int(current_candidates > 0)
        query_with_compatible += int(current_compatible > 0)

        for result in (value.get("results") or {}).values():
            if not isinstance(result, dict):
                continue
            materialized_query_result_count += 1
            retrieval_decisions[str(result.get("retrieval_decision", ""))] += 1
            for decision in result.get("compatibility_decisions", []):
                compatibility_verdicts[str(decision.get("verdict", ""))] += 1
                if decision.get("verdict") == "incompatible" and isinstance(
                    decision.get("raw_rank"), int
                ):
                    incompatible_candidate_ranks[int(decision["raw_rank"])] += 1
                for reason in decision.get("reasons", []):
                    compatibility_reasons[str(reason)] += 1
            for match in result.get("matches", []):
                match_sources[str(match.get("matched_on", ""))] += 1

        per_query.append(
            {
                "task_id": value.get("task_id"),
                **case_index.get(str(value.get("task_id")), {}),
                "query_count": current_queries,
                "candidate_count": current_candidates,
                "compatible_count": current_compatible,
                "approved_count": current_approved,
                "keyword_candidate_count": int(
                    metrics.get("memory_keyword_candidate_count", 0)
                ),
                "tag_candidate_count": int(metrics.get("memory_tag_candidate_count", 0)),
                "vector_candidate_count": int(
                    metrics.get("memory_vector_candidate_count", 0)
                ),
                "source_path": str(path),
            }
        )

    consumption_count = 0
    effect_count = 0
    query_with_consumption = 0
    query_with_effect = 0
    skipped_steps = 0
    skipped_calls = 0
    consumption_roles: Counter[str] = Counter()
    consumption_effects: Counter[str] = Counter()
    consumption_verdicts: Counter[str] = Counter()
    replay_classes: Counter[str] = Counter()
    unique_memory_ids: set[str] = set()
    materialized_consumption_record_count = 0
    per_consumption: list[dict[str, Any]] = []

    for path in json_files(run_root / "memory_consumption"):
        value = load_json(path)
        metrics = value.get("metrics") or {}
        records = value.get("records") or []
        current_consumed = int(metrics.get("memory_consumed_count", len(records)))
        current_effect = int(metrics.get("memory_behavioral_effect_count", 0))
        current_skipped_steps = int(metrics.get("skipped_step_count", 0))
        current_skipped_calls = int(metrics.get("skipped_llm_call_count", 0))
        consumption_count += current_consumed
        effect_count += current_effect
        skipped_steps += current_skipped_steps
        skipped_calls += current_skipped_calls
        query_with_consumption += int(current_consumed > 0)
        query_with_effect += int(current_effect > 0)
        for record in records:
            materialized_consumption_record_count += 1
            consumption_roles[str(record.get("consumer_role", ""))] += 1
            consumption_effects[str(record.get("behavioral_effect", ""))] += 1
            consumption_verdicts[str(record.get("compatibility_verdict", ""))] += 1
            replay_classes[str(record.get("replay_class", ""))] += 1
            memory_id = record.get("memory_id") or record.get("input_ref_id")
            if memory_id:
                unique_memory_ids.add(str(memory_id))
        per_consumption.append(
            {
                "task_id": value.get("task_id"),
                **case_index.get(str(value.get("task_id")), {}),
                "consumption_count": current_consumed,
                "effect_count": current_effect,
                "skipped_step_count": current_skipped_steps,
                "skipped_llm_call_count": current_skipped_calls,
                "assist_count": int(metrics.get("memory_assist_count", 0)),
                "validated_replay_count": int(metrics.get("validated_replay_count", 0)),
                "source_path": str(path),
            }
        )

    def rate(numerator: int, denominator: int) -> float | None:
        return numerator / denominator if denominator else None

    query_by_task = {str(row["task_id"]): row for row in per_query}
    consumption_by_task = {str(row["task_id"]): row for row in per_consumption}
    timeline = []
    for task_id in sorted(
        set(query_by_task) | set(consumption_by_task),
        key=lambda item: (
            str(case_index.get(item, {}).get("task_family", "")),
            float(case_index.get(item, {}).get("round_number") or 0),
            item,
        ),
    ):
        query = query_by_task.get(task_id, {})
        consumption = consumption_by_task.get(task_id, {})
        timeline.append(
            {
                "task_id": task_id,
                **case_index.get(task_id, {}),
                **{
                    key: query.get(key, 0)
                    for key in (
                        "query_count",
                        "candidate_count",
                        "compatible_count",
                        "approved_count",
                        "keyword_candidate_count",
                        "tag_candidate_count",
                        "vector_candidate_count",
                    )
                },
                **{
                    key: consumption.get(key, 0)
                    for key in (
                        "consumption_count",
                        "effect_count",
                        "assist_count",
                        "validated_replay_count",
                        "skipped_step_count",
                        "skipped_llm_call_count",
                    )
                },
            }
        )

    return {
        "query_count": query_count,
        "candidate_count": candidate_count,
        "compatible_count": compatible_count,
        "approved_count": approved_count,
        "consumption_count": consumption_count,
        "effect_count": effect_count,
        "skipped_step_count": skipped_steps,
        "skipped_llm_call_count": skipped_calls,
        "unique_consumed_memory_id_count": len(unique_memory_ids),
        "query_normalized_rates": {
            "candidate_query_rate": rate(query_with_candidates, query_count),
            "compatible_query_rate": rate(query_with_compatible, query_count),
            "actual_consumption_query_rate": rate(query_with_consumption, query_count),
            "effect_query_rate": rate(query_with_effect, query_count),
            "skipped_step_query_rate": rate(
                sum(row["skipped_step_count"] > 0 for row in per_consumption), query_count
            ),
            "skipped_llm_call_query_rate": rate(
                sum(row["skipped_llm_call_count"] > 0 for row in per_consumption), query_count
            ),
        },
        "candidate_normalized_rates": {
            "compatibility_rate": rate(compatible_count, candidate_count),
            "rejection_rate": rate(candidate_count - compatible_count, candidate_count),
        },
        "compatibility_verdicts": dict(compatibility_verdicts),
        "compatibility_reasons": dict(compatibility_reasons),
        "incompatible_candidate_ranks": {
            str(key): value for key, value in sorted(incompatible_candidate_ranks.items())
        },
        "retrieval_decisions": dict(retrieval_decisions),
        "match_sources": dict(match_sources),
        "consumption_roles": dict(consumption_roles),
        "consumption_effects": dict(consumption_effects),
        "consumption_verdicts": dict(consumption_verdicts),
        "consumption_replay_classes": dict(replay_classes),
        "materialized_query_result_count": materialized_query_result_count,
        "materialized_consumption_record_count": materialized_consumption_record_count,
        "per_query": per_query,
        "per_consumption": per_consumption,
        "per_task_timeline": timeline,
        "workspace_receipts": workspace_memory_receipt_summary(
            run_root, case_index
        ),
    }


def build_e2(root: Path) -> dict[str, Any]:
    records = load_case_reports(root, "E2")
    by_family = group_records(records, ("task_family",))
    run_root = root / RUNS["E2"]
    return {
        "case_count": len(records),
        "per_case": [selected_metric_row(record) for record in records],
        "family_metrics": {
            group: aggregate_metrics(items, E1_E2_METRICS)
            for group, items in by_family.items()
        },
        "decision_support_by_family": {
            group: aggregate_metrics(items, DECISION_SUPPORT_METRICS)
            for group, items in by_family.items()
        },
        "latency_diagnostics_by_family": {
            group: aggregate_metrics(items, LATENCY_DIAGNOSTIC_METRICS)
            for group, items in by_family.items()
        },
        "memory": memory_slice_summary(run_root, records),
        "artifact_promotion": workspace_artifact_promotion_summary(run_root),
        "diagnostic_nonzero_cases": diagnostic_case_rows(records),
        "all_numeric_metric_catalog": metric_catalog(records),
    }


def violation_category(value: Any) -> str:
    text = str(value).splitlines()[0]
    return text.split(":", 1)[0] if ":" in text else text


def compact_adaptive_case(record: dict[str, Any]) -> dict[str, Any]:
    generation_attempts = record.get("generation_attempts") or []
    execution_records = record.get("execution_records") or []
    terminal_reports = record.get("terminal_quality_reports") or []
    memory_commit = record.get("memory_commit_decision") or {}
    violations = [
        violation
        for attempt in generation_attempts
        for violation in (attempt.get("violations") or [])
    ]
    return {
        "task_id": record.get("task_id"),
        "task_family": record.get("task_family"),
        "operation": record.get("operation"),
        "elapsed_ms": record.get("elapsed_ms"),
        "usage": record.get("usage"),
        "selected_capability_ids": record.get("selected_capability_ids"),
        "model_roles_observed": sorted(record.get("model_roles_observed") or []),
        "approved_step_count": len(record.get("approved_steps") or []),
        "runtime_dispatch_count": len(record.get("runtime_dispatches") or []),
        "role_invocation_record_count": len(record.get("role_invocations") or []),
        "generation_attempt_record_count": len(generation_attempts),
        "generation_attempt_kinds": [attempt.get("kind") for attempt in generation_attempts],
        "generation_violation_categories": [violation_category(item) for item in violations],
        "execution_record_count": len(execution_records),
        "execution_verified_count": sum(
            execution.get("exit_code") == 0
            and not execution.get("timeout")
            and execution.get("output_quality_valid") is True
            and execution.get("output_schema_valid") is True
            for execution in execution_records
        ),
        "planner_schema_normalization_used": bool(
            record.get("planner_schema_normalization_used")
        ),
        "planner_schema_normalized_field_count": len(
            record.get("planner_schema_normalized_fields") or []
        ),
        "planner_policy_repair_used": bool(record.get("planner_policy_repair_used")),
        "initial_planner_structural_errors": record.get(
            "initial_planner_structural_errors"
        )
        or [],
        "state_consumption_record_count": len(record.get("state_consumption_records") or []),
        "memory_consumption_record_count": len(
            record.get("memory_consumption_records") or []
        ),
        "memory_commit_attempted": bool(memory_commit.get("attempted")),
        "memory_committed": bool(memory_commit.get("committed")),
        "memory_commit_benchmark_gold_used": memory_commit.get("benchmark_gold_used"),
        "terminal_quality_report_count": len(terminal_reports),
        "terminal_quality_verified_count": sum(
            report.get("verified") is True for report in terminal_reports
        ),
        "runtime_completed": record.get("runtime_completed"),
        "system_gate_passed": record.get("system_gate_passed"),
        "expected_facts_passed": (record.get("expected_facts_report") or {}).get(
            "passed"
        ),
        "benchmark_oracle_visible_to_roles": record.get(
            "benchmark_oracle_visible_to_roles"
        ),
        "ok": record.get("ok"),
        "source_path": record["_source_path"],
    }


def adaptive_case_audit(records: list[dict[str, Any]]) -> dict[str, Any]:
    compact = [compact_adaptive_case(record) for record in records]
    role_counts: Counter[str] = Counter()
    generation_kinds: Counter[str] = Counter()
    violation_categories: Counter[str] = Counter()
    planner_errors: Counter[str] = Counter()
    sandbox_backends: Counter[str] = Counter()
    sandbox_identities: Counter[str] = Counter()
    execution_record_count = 0
    verified_execution_count = 0
    timeout_count = 0
    fallback_execution_count = 0

    for record, row in zip(records, compact):
        role_counts.update(row["model_roles_observed"])
        generation_kinds.update(str(item) for item in row["generation_attempt_kinds"])
        violation_categories.update(row["generation_violation_categories"])
        planner_errors.update(row["initial_planner_structural_errors"])
        execution_record_count += row["execution_record_count"]
        verified_execution_count += row["execution_verified_count"]
        for execution in record.get("execution_records") or []:
            sandbox_backends[str(execution.get("sandbox_actual_backend", ""))] += 1
            sandbox_identities[
                f"{execution.get('sandbox_uid')}:{execution.get('sandbox_gid')}"
            ] += 1
            timeout_count += int(bool(execution.get("timeout")))
            fallback_execution_count += int(bool(execution.get("fallback_reason")))

    required_roles = {"planner", "retriever", "executor", "summarizer"}
    return {
        "workload_metrics": describe_adaptive_cases(records),
        "model_role_case_counts": dict(role_counts),
        "all_four_model_roles_case_count": sum(
            required_roles.issubset(set(row["model_roles_observed"])) for row in compact
        ),
        "approved_step_count": sum(row["approved_step_count"] for row in compact),
        "runtime_dispatch_count": sum(row["runtime_dispatch_count"] for row in compact),
        "role_invocation_record_count": sum(
            row["role_invocation_record_count"] for row in compact
        ),
        "generation_attempt_record_count": sum(
            row["generation_attempt_record_count"] for row in compact
        ),
        "generation_attempt_kinds": dict(generation_kinds),
        "generation_violation_categories": dict(violation_categories),
        "generation_repair_case_count": sum(
            "repair" in row["generation_attempt_kinds"] for row in compact
        ),
        "planner_schema_normalization_case_count": sum(
            row["planner_schema_normalization_used"] for row in compact
        ),
        "planner_schema_normalized_field_count": sum(
            row["planner_schema_normalized_field_count"] for row in compact
        ),
        "planner_policy_repair_case_count": sum(
            row["planner_policy_repair_used"] for row in compact
        ),
        "planner_structural_error_case_count": sum(
            bool(row["initial_planner_structural_errors"]) for row in compact
        ),
        "planner_structural_errors": dict(planner_errors),
        "execution_record_count": execution_record_count,
        "verified_execution_record_count": verified_execution_count,
        "execution_timeout_count": timeout_count,
        "execution_fallback_count": fallback_execution_count,
        "sandbox_backends": dict(sandbox_backends),
        "sandbox_identities": dict(sandbox_identities),
        "state_consumption_record_count": sum(
            row["state_consumption_record_count"] for row in compact
        ),
        "memory_consumption_record_count": sum(
            row["memory_consumption_record_count"] for row in compact
        ),
        "memory_commit_attempt_count": sum(row["memory_commit_attempted"] for row in compact),
        "memory_commit_count": sum(row["memory_committed"] for row in compact),
        "memory_commit_gold_used_count": sum(
            row["memory_commit_benchmark_gold_used"] is True for row in compact
        ),
        "terminal_quality_report_count": sum(
            row["terminal_quality_report_count"] for row in compact
        ),
        "terminal_quality_verified_count": sum(
            row["terminal_quality_verified_count"] for row in compact
        ),
        "runtime_completed_case_count": sum(
            row["runtime_completed"] is True for row in compact
        ),
        "system_gate_pass_count": sum(row["system_gate_passed"] is True for row in compact),
        "expected_facts_pass_count": sum(
            row["expected_facts_passed"] is True for row in compact
        ),
        "benchmark_oracle_hidden_case_count": sum(
            row["benchmark_oracle_visible_to_roles"] is False for row in compact
        ),
        "ok_case_count": sum(row["ok"] is True for row in compact),
        "per_case": compact,
    }


def build_e3(root: Path) -> dict[str, Any]:
    run_root = root / RUNS["E3"]
    summary = load_json(run_root / "summary.json")
    records = load_case_reports(root, "E3")
    registry_paths = sorted(run_root.glob("runtime/**/family_memory/commit_registry.json"))
    registry_audit: dict[str, Any] = {
        "registry_count": len(registry_paths),
        "registry_paths": [str(path) for path in registry_paths],
    }
    if len(registry_paths) == 1:
        registry = load_json(registry_paths[0])
        refs = [
            value.get("memory_ref") or {}
            for value in registry.values()
            if isinstance(value, dict)
        ]
        required_fields = (
            "memory_id",
            "source_agent",
            "created_at_ns",
            "task_theme",
            "summary",
        )
        family_memory_root = registry_paths[0].parent
        registry_audit.update(
            {
                "entry_count": len(refs),
                "required_metadata_coverage": {
                    field: sum(ref.get(field) not in (None, "") for ref in refs)
                    for field in required_fields
                },
                "tagged_entry_count": sum(bool(ref.get("tags")) for ref in refs),
                "embedding_linked_entry_count": sum(
                    bool(ref.get("embedding_ref_id")) for ref in refs
                ),
                "artifact_linked_entry_count": sum(
                    bool(ref.get("artifact_ref_id")) for ref in refs
                ),
                "committed_entry_count": sum(
                    ref.get("commit_status") == "committed" for ref in refs
                ),
                "validated_entry_count": sum(
                    ref.get("validation_status") == "passed" for ref in refs
                ),
                "source_agents": dict(
                    Counter(str(ref.get("source_agent", "")) for ref in refs)
                ),
                "memory_types": dict(
                    Counter(str(ref.get("memory_type", "")) for ref in refs)
                ),
                "backing_files": {
                    path.name: path.stat().st_size
                    for path in sorted(family_memory_root.iterdir())
                    if path.is_file()
                },
            }
        )
    return {
        "case_count": summary.get("case_count"),
        "case_order": summary.get("case_order"),
        "capability_counts": summary.get("capability_counts"),
        "memory_funnel": summary.get("memory_funnel"),
        "negative_case_gates": summary.get("negative_case_gates"),
        "per_case": summary.get("case_summaries"),
        "memory": memory_slice_summary(run_root, records),
        "memory_registry_audit": registry_audit,
        "adaptive_case_audit": adaptive_case_audit(records),
    }


def build_e4(root: Path) -> dict[str, Any]:
    run_root = root / RUNS["E4"]
    summary = load_json(run_root / "summary.json")
    records = load_case_reports(root, "E4")
    cases = {case["task_id"]: dict(case) for case in summary.get("cases", [])}
    producer_pids: set[int] = set()
    consumer_pids: set[int] = set()
    encoder_signatures: set[str] = set()
    total_selected_bytes = 0
    total_records = 0
    changed_records = 0
    selected_scores: list[float] = []
    selected_candidate_ids: set[str] = set()
    selected_candidate_occurrences = 0
    for path in json_files(run_root / "state_consumption"):
        value = load_json(path)
        task_id = str(value.get("task_id"))
        selections = value.get("selections") or {}
        consumption_records = value.get("records") or []
        selection_rows = []
        for state_ref_id, selection in selections.items():
            producer = selection.get("producer_pid")
            consumer = selection.get("consumer_pid")
            if isinstance(producer, int):
                producer_pids.add(producer)
            if isinstance(consumer, int):
                consumer_pids.add(consumer)
            if selection.get("encoder_signature"):
                encoder_signatures.add(str(selection["encoder_signature"]))
            selected_bytes = int(selection.get("selected_evidence_bytes", 0))
            total_selected_bytes += selected_bytes
            current_scores = [float(item) for item in selection.get("selected_scores", [])]
            current_ids = [str(item) for item in selection.get("selected_candidate_ids", [])]
            selected_scores.extend(current_scores)
            selected_candidate_ids.update(current_ids)
            selected_candidate_occurrences += len(current_ids)
            selection_rows.append(
                {
                    "state_ref_id": state_ref_id,
                    "producer_pid": producer,
                    "consumer_pid": consumer,
                    "selected_candidate_ids": current_ids,
                    "selected_scores": current_scores,
                    "selected_evidence_bytes": selected_bytes,
                }
            )
        total_records += len(consumption_records)
        changed_records += sum(
            record.get("behavioral_effect") == "changed"
            and record.get("input_decision_surface_hash")
            != record.get("output_decision_surface_hash")
            for record in consumption_records
        )
        cases.setdefault(task_id, {})["state_consumption"] = {
            "selection_count": len(selection_rows),
            "record_count": len(consumption_records),
            "selections": selection_rows,
            "operations": sorted(
                {str(row.get("operation")) for row in consumption_records}
            ),
            "changed_surface_count": sum(
                row.get("input_decision_surface_hash")
                != row.get("output_decision_surface_hash")
                for row in consumption_records
            ),
            "source_path": str(path),
        }
    telemetry_totals = {
        key: sum(float((record.get("telemetry") or {}).get(key, 0)) for record in records)
        for key in sorted(
            {
                key
                for record in records
                for key, value in (record.get("telemetry") or {}).items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
        )
    }
    return {
        "case_count": summary.get("case_count"),
        "capability_counts": summary.get("capability_counts"),
        "benchmark_oracle_visible_to_roles": summary.get(
            "benchmark_oracle_visible_to_roles"
        ),
        "runtime_freeze_audit": summary.get("runtime_freeze_audit"),
        "producer_pids": sorted(producer_pids),
        "consumer_pids": sorted(consumer_pids),
        "cross_pid_for_every_selection": all(
            selection["producer_pid"] != selection["consumer_pid"]
            for case in cases.values()
            for selection in case.get("state_consumption", {}).get("selections", [])
        ),
        "encoder_signatures": sorted(encoder_signatures),
        "selection_count": sum(
            case.get("state_consumption", {}).get("selection_count", 0)
            for case in cases.values()
        ),
        "consumption_record_count": total_records,
        "changed_surface_record_count": changed_records,
        "selected_evidence_bytes": total_selected_bytes,
        "selected_candidate_occurrence_count": selected_candidate_occurrences,
        "unique_selected_candidate_ids": sorted(selected_candidate_ids),
        "selection_score_distribution": describe(selected_scores),
        "adaptive_case_audit": adaptive_case_audit(records),
        "telemetry_totals": telemetry_totals,
        "event_receipt_accounting": {
            "telemetry_publish_event_count": telemetry_totals.get(
                "semantic_state_publish_count", 0
            ),
            "telemetry_transfer_event_count": telemetry_totals.get(
                "semantic_state_transfer_count", 0
            ),
            "physical_selection_count": sum(
                case.get("state_consumption", {}).get("selection_count", 0)
                for case in cases.values()
            ),
            "consumption_receipt_count": total_records,
            "release_event_count": telemetry_totals.get(
                "semantic_state_release_count", 0
            ),
            "published_bytes": telemetry_totals.get("semantic_state_bytes", 0),
            "released_bytes": telemetry_totals.get(
                "semantic_state_released_bytes", 0
            ),
        },
        "cases": [cases[key] for key in sorted(cases)],
    }


def describe_adaptive_cases(records: list[dict[str, Any]]) -> dict[str, Any]:
    elapsed = [float(record.get("elapsed_ms", 0)) for record in records]
    prompt = [float((record.get("usage") or {}).get("prompt_tokens", 0)) for record in records]
    completion = [
        float((record.get("usage") or {}).get("completion_tokens", 0)) for record in records
    ]
    total = [float((record.get("usage") or {}).get("total_tokens", 0)) for record in records]
    return {
        "case_count": len(records),
        "elapsed_ms": describe(elapsed),
        "prompt_tokens": describe(prompt),
        "completion_tokens": describe(completion),
        "total_tokens": describe(total),
        "role_invocation_records": describe(
            len(record.get("role_invocations") or []) for record in records
        ),
        "generation_attempt_records": describe(
            len(record.get("generation_attempts") or []) for record in records
        ),
    }


def build_e5(root: Path) -> dict[str, Any]:
    run_root = root / RUNS["E5"]
    summary = load_json(run_root / "summary.json")
    records = load_case_reports(root, "E5")
    by_family = group_records(records, ("task_family",))
    by_operation = group_records(records, ("operation",))

    by_executor: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    sandbox_backends: Counter[str] = Counter()
    sandbox_identities: Counter[str] = Counter()
    model_roles: Counter[str] = Counter()
    operation_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    total_state_records = 0
    total_memory_records = 0
    total_role_invocations = 0
    total_generation_attempts = 0
    capability_combinations: Counter[str] = Counter()
    for record in records:
        executor = next(
            (
                item
                for item in record.get("selected_capability_ids", [])
                if item in {"execute_analysis_dsl_v2", "execute_bounded_python_v2"}
            ),
            "unknown",
        )
        by_executor[executor].append(record)
        operation_counts[str(record.get("operation"))] += 1
        family_counts[str(record.get("task_family"))] += 1
        model_roles.update(str(role) for role in record.get("model_roles_observed", []))
        total_state_records += len(record.get("state_consumption_records") or [])
        total_memory_records += len(record.get("memory_consumption_records") or [])
        total_role_invocations += len(record.get("role_invocations") or [])
        total_generation_attempts += len(record.get("generation_attempts") or [])
        capability_combinations[
            " -> ".join(str(item) for item in record.get("selected_capability_ids", []))
        ] += 1
        for execution in record.get("execution_records", []):
            backend = str(execution.get("sandbox_actual_backend", ""))
            sandbox_backends[backend] += 1
            sandbox_identities[
                f"{execution.get('sandbox_uid')}:{execution.get('sandbox_gid')}"
            ] += 1

    compact_cases = []
    for record in records:
        compact_cases.append(
            {
                "task_id": record.get("task_id"),
                "task_family": record.get("task_family"),
                "operation": record.get("operation"),
                "elapsed_ms": record.get("elapsed_ms"),
                "usage": record.get("usage"),
                "selected_capability_ids": record.get("selected_capability_ids"),
                "role_invocation_record_count": len(record.get("role_invocations") or []),
                "generation_attempt_record_count": len(record.get("generation_attempts") or []),
                "system_gate_passed": record.get("system_gate_passed"),
                "expected_facts_passed": (record.get("expected_facts_report") or {}).get(
                    "passed"
                ),
                "ok": record.get("ok"),
                "source_path": record["_source_path"],
            }
        )

    top_elapsed = sorted(compact_cases, key=lambda row: row["elapsed_ms"], reverse=True)[:5]
    top_tokens = sorted(
        compact_cases,
        key=lambda row: float((row.get("usage") or {}).get("total_tokens", 0)),
        reverse=True,
    )[:5]
    return {
        "case_count": len(records),
        "family_counts": dict(family_counts),
        "operation_counts": dict(operation_counts),
        "formal_registry": summary.get("formal_registry"),
        "reasoning_type_counts": dict(
            Counter(
                str(item.get("reasoning_type", ""))
                for item in summary.get("formal_registry") or []
            )
        ),
        "capability_combinations": dict(capability_combinations),
        "model_role_case_counts": dict(model_roles),
        "total_role_invocation_records": total_role_invocations,
        "total_generation_attempt_records": total_generation_attempts,
        "state_consumption_record_count": total_state_records,
        "memory_consumption_record_count": total_memory_records,
        "sandbox_backends": dict(sandbox_backends),
        "sandbox_identities": dict(sandbox_identities),
        "family_metrics": {
            group: describe_adaptive_cases(items) for group, items in by_family.items()
        },
        "operation_metrics": {
            group: describe_adaptive_cases(items) for group, items in by_operation.items()
        },
        "executor_metrics": {
            group: describe_adaptive_cases(items)
            for group, items in sorted(by_executor.items())
        },
        "slowest_cases": top_elapsed,
        "highest_token_cases": top_tokens,
        "per_case": compact_cases,
        "adaptive_case_audit": adaptive_case_audit(records),
    }


def build_engineering_gate(root: Path, stage: str) -> dict[str, Any]:
    run_root = root / RUNS[stage]
    summary = load_json(run_root / "summary.json")
    pytest_log = (run_root / "pytest.log").read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r"(?P<passed>\d+) passed(?:, (?P<warnings>\d+) warnings)? in "
        r"(?P<seconds>[0-9.]+)s",
        pytest_log,
    )
    return {
        "ok": summary.get("ok"),
        "contest_stage_ok": summary.get("contest_stage_ok"),
        "pytest_passed": summary.get("pytest_passed"),
        "preflight_ok": summary.get("preflight_ok"),
        "preflight_role_path_mode": (summary.get("preflight") or {}).get(
            "role_path_mode"
        ),
        "preflight_embedding_mode": (summary.get("preflight") or {}).get(
            "embedding_mode"
        ),
        "preflight_checks": (summary.get("preflight") or {}).get("checks"),
        "pytest_result": {
            "passed": int(match.group("passed")) if match else None,
            "warnings": int(match.group("warnings") or 0) if match else None,
            "seconds": float(match.group("seconds")) if match else None,
        },
    }


def build_capability_surface(root: Path) -> dict[str, Any]:
    registry = load_json(root / RUNS["E1"] / "capability_registry.json")
    return {
        "schema_version": registry.get("schema_version"),
        "pack_id": registry.get("pack_id"),
        "registry_digest": registry.get("registry_digest"),
        "contains_expected_answers": registry.get("contains_expected_answers"),
        "capability_count": len(registry.get("capability_ids") or []),
        "capabilities": [
            {
                key: item.get(key)
                for key in (
                    "id",
                    "role",
                    "execution_kind",
                    "accepts",
                    "produces",
                    "requires",
                    "output_contract",
                    "side_effect",
                    "fallback_capability_id",
                )
            }
            for item in registry.get("public_descriptors") or []
        ],
    }


def build_e1_fairness_audit(root: Path) -> dict[str, Any]:
    manifest = load_json(root / RUNS["E1"] / "fairness_manifest.json")
    families = manifest.get("family_manifests") or []
    gold_audits = [
        lane_record.get("gold_visibility_audit") or {}
        for family in families
        for case in (family.get("cases") or {}).values()
        for lane_record in case.values()
    ]
    return {
        "comparison_valid": manifest.get("comparison_valid"),
        "family_count": len(families),
        "matched_case_lane_count": len(gold_audits),
        "unexpected_difference_count": sum(
            int(family.get("unexpected_difference_count", 0)) for family in families
        ),
        "invariant_fields_by_family": {
            str(family.get("family_id")): family.get("invariant_fields")
            for family in families
        },
        "gold_visibility_audit_pass_count": sum(
            audit.get("ok") is True for audit in gold_audits
        ),
        "gold_visibility_violation_count": sum(
            len(audit.get("violations") or []) for audit in gold_audits
        ),
        "rendered_role_request_audit_count": sum(
            len(audit.get("roles") or {}) for audit in gold_audits
        ),
    }


def build_environment_identity(root: Path) -> dict[str, Any]:
    result = {}
    for stage, run in RUNS.items():
        environment = load_json(root / run / "environment.json")
        manifest = load_json(root / run / "run_manifest.json")
        result[stage] = {
            "container_name": environment.get("container_name"),
            "container_image_digest": environment.get("container_image_digest"),
            "os": (environment.get("os_release") or {}).get("PRETTY_NAME"),
            "python": environment.get("python"),
            "physical_gpu": environment.get("physical_gpu"),
            "cuda_status": environment.get("cuda_status"),
            "embedding_device": environment.get("embedding_device"),
            "embedding_model_path": environment.get("embedding_model_path"),
            "role_model": environment.get("role_model"),
            "role_profile_digest": (environment.get("model_profiles") or {}).get(
                "profile_digest"
            ),
            "role_seeds": {
                role: profile.get("seed")
                for role, profile in (
                    (environment.get("model_profiles") or {}).get("roles") or {}
                ).items()
            },
            "temperature": {
                role: profile.get("temperature")
                for role, profile in (
                    (environment.get("model_profiles") or {}).get("roles") or {}
                ).items()
            },
            "git_sha": manifest.get("git_sha"),
            "git_dirty": manifest.get("git_dirty"),
            "serial_execution": manifest.get("serial_execution"),
            "elapsed_seconds": manifest.get("elapsed_seconds"),
            "exit_status": manifest.get("exit_status"),
            "source_task_manifest_hash": manifest.get("source_task_manifest_hash"),
            "runtime_compatibility_signature": manifest.get(
                "runtime_compatibility_signature"
            ),
            "validator_digest": manifest.get("validator_digest"),
        }
    return result


def summarize_environment_consistency(environment: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "container_name",
        "container_image_digest",
        "os",
        "python",
        "physical_gpu",
        "embedding_device",
        "embedding_model_path",
        "role_model",
        "git_sha",
        "git_dirty",
        "serial_execution",
        "runtime_compatibility_signature",
    )
    return {
        field: sorted(
            {record.get(field) for record in environment.values()}, key=str
        )
        for field in fields
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    environment_identity = build_environment_identity(args.artifact_root)
    report = {
        "schema_version": "statebus.contest_fixed_baseline_derived_metrics.v6",
        "scope": "canonical E0-E6 only; derived from existing artifacts; no workload run",
        "artifact_root": str(args.artifact_root),
        "canonical_runs": RUNS,
        "environment_identity": environment_identity,
        "environment_consistency": summarize_environment_consistency(
            environment_identity
        ),
        "capability_surface": build_capability_surface(args.artifact_root),
        "E0": build_engineering_gate(args.artifact_root, "E0"),
        "E1": build_e1(args.artifact_root),
        "E1_fairness_audit": build_e1_fairness_audit(args.artifact_root),
        "E2": build_e2(args.artifact_root),
        "E3": build_e3(args.artifact_root),
        "E4": build_e4(args.artifact_root),
        "E5": build_e5(args.artifact_root),
        "E6": build_engineering_gate(args.artifact_root, "E6"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
