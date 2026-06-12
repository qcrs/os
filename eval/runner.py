from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import socket
import subprocess
import shutil
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Iterator

from agents.sample_agents import build_sample_agents_with_executor
from memory.store import (
    DEFAULT_EMBEDDING_MODEL_PATH,
    EmbeddingProvider,
    SentenceTransformerEmbeddingProvider,
)
from runtime.executor_runtime import (
    _feature_bundle_from_executor_decision_packet,
    _feature_bundle_from_natural_handoff,
    _feature_bundle_from_text_packet,
    _feature_bundle_from_transfer_brief,
    default_tool_registry,
)
from runtime.llm import LLMClient, LLMConfig, build_llm_client
from runtime.langgraph_adapter import StateBusGraphRunner, langgraph_available
from runtime.orchestrator import Orchestrator, RunContext, RunSession
from statepool.store import StatePoolConfig
from tasks.sample_tasks import DEFAULT_TASK_SET, SampleTask, load_task_set_bundle

METRIC_FIELDS = (
    "message_count",
    "text_chars",
    "text_bytes",
    "protocol_bytes",
    "mmap_state_ref_count",
    "mmap_state_bytes",
    "shared_memory_state_ref_count",
    "shared_memory_state_bytes",
    "state_ref_count",
    "state_bytes",
    "handoff_ref_count",
    "handoff_bytes",
    "handoff_payload_bytes",
    "handoff_wire_bytes",
    "handoff_textual_ref_count",
    "handoff_textual_bytes",
    "handoff_nontext_ref_count",
    "handoff_nontext_bytes",
    "memory_hits",
    "memory_query_count",
    "memory_hit_task_count",
    "replay_probe_count",
    "replay_probe_hits",
    "replay_probe_hit_task_count",
    "memory_assist_task_count",
    "memory_assist_prior_applied_task_count",
    "memory_assist_candidate_reduction",
    "memory_assist_route_agreement_task_count",
    "memory_assist_rescue_task_count",
    "validated_reuse_task_count",
    "memory_rejected_task_count",
    "planned_step_count",
    "skipped_step_count",
    "llm_request_count",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "planner_llm_request_count",
    "planner_prompt_tokens",
    "planner_completion_tokens",
    "planner_total_tokens",
    "summarizer_llm_request_count",
    "summarizer_prompt_tokens",
    "summarizer_completion_tokens",
    "summarizer_total_tokens",
    "planner_ms",
    "retrieve_ms",
    "execute_ms",
    "summarize_ms",
    "task_ms",
    "blob_fetch_count",
    "blob_fetch_bytes",
    "blob_fetch_hits",
    "trajectory_step_count",
    "trajectory_commit_count",
    "trajectory_diff_count",
    "dag_integrity_check_count",
    "dag_integrity_violation_count",
    "invariant_check_count",
    "invariant_violation_count",
)

COUNTER_FIELDS = (
    "message_count",
    "text_chars",
    "text_bytes",
    "protocol_bytes",
)

REUSE_SLICE_ORDER = (
    "cold_start",
    "reject_control",
    "assist",
    "validated_replay",
    "exact_replay",
)

REUSE_AXIS_ORDER = (
    "fresh_retrieval",
    "step_skipping",
)

BENCHMARK_LANE_ORDER = (
    "internal_regression",
    "communication",
    "state_transfer",
    "memory",
    "integrity",
)

TRANSFER_STRATEGY_ORDER = (
    "natural_handoff_text",
    "channel_store_hashref",
    "text_brief",
    "text_packet_minimal",
    "state_packet_minimal",
    "flat_state_ref",
)

MEMORY_POLICY_ORDER = (
    "memory_off",
    "working_assist",
    "long_term_assist",
    "validated_replay",
    "exact_replay",
)

MISFIRE_FIELD_ORDER = (
    "route",
    "route_source",
    "tool_name",
    "top_doc_id",
)

MISFIRE_SECTION_TITLES = {
    "route": "Route Misfire Summary",
    "route_source": "Route-Source Misfire Summary",
    "tool_name": "Tool-Choice Misfire Summary",
    "top_doc_id": "Top-Doc Misfire Summary",
}


def _public_transfer_strategy(value: str, mode: str | None = None) -> str:
    normalized = str(value or "").strip()
    if normalized == "state_ref":
        return "channel_store_hashref"
    if normalized == "text_brief":
        return "text_brief"
    if normalized == "mode_split_text_brief_vs_state_ref":
        return "natural_handoff_text" if str(mode or "").strip().lower() == "text" else "channel_store_hashref"
    return normalized


def _sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _feature_bundle_observability(ctx: RunContext, result: Any) -> dict[str, Any]:
    feature_ref = next((ref for ref in result.output_state_refs if ref.kind == "FEATURE_BUNDLE"), None)
    if feature_ref is None:
        feature_state_id = str(result.payload.get("feature_state_id", "")).strip()
        if feature_state_id:
            try:
                resolved = ctx.resolve_ref(feature_state_id)
            except Exception:
                resolved = None
            if resolved is not None and resolved.kind == "FEATURE_BUNDLE":
                feature_ref = resolved
    feature_bundle: dict[str, Any] | None = None
    if feature_ref is not None:
        try:
            feature_bundle = ctx.get_feature_state(feature_ref)
        except Exception:
            feature_bundle = None
    if feature_bundle is None:
        evidence_ref = next((ref for ref in result.output_state_refs if ref.kind == "DENSE_EVIDENCE"), None)
        decision_packet_ref = next(
            (ref for ref in result.output_state_refs if ref.kind == "EXECUTOR_DECISION_PACKET"),
            None,
        )
        brief_ref = next((ref for ref in result.output_state_refs if ref.kind == "TOOL_ARTIFACT"), None)
        transfer_strategy = str(result.payload.get("transfer_strategy", "text_brief")).strip()
        if evidence_ref is None:
            return {}
        try:
            if transfer_strategy == "state_packet_minimal" and decision_packet_ref is not None:
                feature_bundle = _feature_bundle_from_executor_decision_packet(
                    query_text=result.payload.get("query", ""),
                    evidence_text=ctx.get_text_state(evidence_ref),
                    decision_packet=ctx.get_executor_decision_state(decision_packet_ref),
                    registry=default_tool_registry(),
                )
            elif brief_ref is None:
                return {}
            else:
                brief_text = ctx.get_text_state(brief_ref)
                if transfer_strategy == "text_packet_minimal":
                    feature_bundle = _feature_bundle_from_text_packet(
                        query_text=result.payload.get("query", ""),
                        evidence_text=ctx.get_text_state(evidence_ref),
                        packet_text=brief_text,
                        registry=default_tool_registry(),
                    )
                elif transfer_strategy == "natural_handoff_text":
                    feature_bundle = _feature_bundle_from_natural_handoff(
                        query_text=result.payload.get("query", ""),
                        evidence_text=ctx.get_text_state(evidence_ref),
                        handoff_text=brief_text,
                        registry=default_tool_registry(),
                    )
                else:
                    feature_bundle = _feature_bundle_from_transfer_brief(
                        query_text=result.payload.get("query", ""),
                        evidence_text=ctx.get_text_state(evidence_ref),
                        brief_text=brief_text,
                        registry=default_tool_registry(),
                    )
        except Exception:
            return {}
    return {
        "route": str(feature_bundle.get("route", "")),
        "tool_name": str(feature_bundle.get("tool_name", "")),
        "route_source": str(feature_bundle.get("route_source", "")),
        "route_confidence": float(feature_bundle.get("route_confidence", 0.0)),
        "route_provenance": [
            str(item) for item in feature_bundle.get("route_provenance", []) if str(item).strip()
        ],
        "hint_doc_ids": [
            str(item) for item in feature_bundle.get("hint_doc_ids", []) if str(item).strip()
        ],
        "matched_signals": [
            str(item) for item in feature_bundle.get("matched_signals", []) if str(item).strip()
        ],
        "matched_tags": [
            str(item) for item in feature_bundle.get("matched_tags", []) if str(item).strip()
        ],
        "match_score": int(feature_bundle.get("match_score", 0)),
        "memory_prior_id": str(feature_bundle.get("memory_prior_id", "")),
        "memory_prior_route": str(feature_bundle.get("memory_prior_route", "")),
        "memory_prior_tool_name": str(feature_bundle.get("memory_prior_tool_name", "")),
        "memory_prior_applied": bool(feature_bundle.get("memory_prior_applied", False)),
        "memory_candidate_reduction": int(feature_bundle.get("memory_candidate_reduction", 0)),
        "memory_prior_route_agreement": bool(
            feature_bundle.get("memory_prior_route_agreement", False)
        ),
        "memory_prior_rescue": bool(feature_bundle.get("memory_prior_rescue", False)),
        "tool_candidates": [
            {
                "tool_name": str(item.get("tool_name", "")),
                "route": str(item.get("route", "")),
                "score": int(item.get("score", 0)),
                "matched_signals": [str(sig) for sig in item.get("matched_signals", [])],
                "matched_tags": [str(tag) for tag in item.get("matched_tags", [])],
                "source": str(item.get("source", "")),
            }
            for item in feature_bundle.get("tool_candidates", [])
            if isinstance(item, dict)
        ],
    }


def _restored_replay_refs(ctx: RunContext) -> list[Any]:
    if ctx.reuse_hit is None:
        return []
    memory_id = ctx.reuse_hit.memory_id
    return [
        ref
        for ref in ctx.state_refs.values()
        if ref.metadata.get("reused_from_memory_id") == memory_id
    ]


def _reuse_artifact_payload(ctx: RunContext, actual_reuse_mode: str) -> dict[str, Any]:
    restored_refs = _restored_replay_refs(ctx)
    cas_summary = ctx.statepool.cas_summary()
    return {
        "applied": ctx.reuse_hit is not None,
        "mode": actual_reuse_mode,
        "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
        "reuse_source": None if ctx.reuse_hit is None else ctx.reuse_hit.reuse_source,
        "skipped_step_ids": list(ctx.pruned_step_ids),
        "rejected_memory_id": None
        if ctx.rejected_memory_hit is None
        else ctx.rejected_memory_hit.memory_id,
        "replay_class": None if ctx.reuse_hit is None else ctx.reuse_hit.replay_class,
        "replay_candidate_count": ctx.metrics.replay_probe_hits,
        "replay_reject_reason": "" if ctx.reuse_hit is not None else (
            "no_candidate" if ctx.metrics.replay_probe_count > 0 else "not_probed"
        ),
        "replay_restored_state_ref_count": len(restored_refs),
        "replay_restored_channel_names": sorted(
            {
                str(ref.metadata.get("channel_name", "")).strip()
                for ref in restored_refs
                if str(ref.metadata.get("channel_name", "")).strip()
            }
        ),
        "physical_blob_reused": bool(any(ref.is_cas for ref in restored_refs)),
        "logical_replay_reuse": bool(ctx.reuse_hit is not None),
        "physical_blob_reuse": bool(cas_summary.get("dedup_hit", False)),
        "dedup_bytes_saved": int(cas_summary.get("dedup_bytes_saved", 0)),
        "cas_hit_rate": float(cas_summary.get("cas_hit_rate", 0.0)),
    }


def _runtime_integrity_payload(ctx: RunContext) -> dict[str, Any]:
    commit_hash = ctx.execution_dag.task_order[-1] if ctx.execution_dag.task_order else ""
    commit = ctx.execution_dag.task_commits.get(commit_hash)
    channel_snapshot_hash = "" if commit is None else commit.channel_snapshot_hash
    if not channel_snapshot_hash:
        route_snapshot = ctx.channel_snapshots.get("route")
        channel_snapshot_hash = "" if route_snapshot is None else route_snapshot.snapshot_hash
    blob_fetch_count = int(ctx.blob_fetch_metrics.get("blob_fetch_count", 0))
    blob_fetch_hits = int(ctx.blob_fetch_metrics.get("blob_fetch_hits", 0))
    return {
        "trajectory_commit_hash": commit_hash,
        "channel_snapshot_hash": channel_snapshot_hash,
        "dag_integrity_ok": bool(ctx.execution_dag.verify_integrity()),
        "trajectory_diff_count": int(ctx.metrics.trajectory_diff_count),
        "blob_fetch_count": blob_fetch_count,
        "blob_fetch_bytes": int(ctx.blob_fetch_metrics.get("blob_fetch_bytes", 0)),
        "blob_cache_hit_rate": (
            blob_fetch_hits / blob_fetch_count if blob_fetch_count else 0.0
        ),
    }


def _pure_text_guard_payload(ctx: RunContext, transfer_strategy: str) -> dict[str, Any]:
    if transfer_strategy != "natural_handoff_text":
        return {"pure_text_guard": {"enabled": False}}
    execute_refs = ctx.step_input_refs("execute")
    input_kinds = [ref.kind for ref in execute_refs]
    forbidden_kinds = {
        "DENSE_EVIDENCE",
        "FEATURE_BUNDLE",
        "TOOL_CANDIDATE_SET",
        "EXECUTOR_DECISION_PACKET",
        "CHANNEL_PATCH",
        "CHANNEL_SNAPSHOT",
        "RANKED_EVIDENCE_BUNDLE",
        "REPLAY_ELIGIBILITY_BUNDLE",
        "EMBEDDING",
    }
    leaked_kinds = sorted({kind for kind in input_kinds if kind in forbidden_kinds})
    handoff_text = ""
    handoff_ref = next((ref for ref in execute_refs if ref.kind == "TOOL_ARTIFACT"), None)
    if handoff_ref is not None:
        try:
            handoff_text = ctx.get_text_state(handoff_ref)
        except Exception:
            handoff_text = ""
    structured_shadow_markers = ("Route:", "Tool:", "Suggested route:", "Suggested tool:")
    structured_text_shadow = any(marker in handoff_text for marker in structured_shadow_markers)
    return {
        "pure_text_guard": {
            "enabled": True,
            "executor_input_kinds": input_kinds,
            "forbidden_ref_kinds": leaked_kinds,
            "structured_text_shadow": structured_text_shadow,
            "handoff_text_bytes": len(handoff_text.encode("utf-8")),
            "passed": not leaked_kinds and not structured_text_shadow and bool(handoff_text.strip()),
        }
    }


def _task_sort_key(task: SampleTask) -> tuple[str, int, str]:
    return (task.task_group, task.task_order, task.task_id)


def _task_reuse_slice(task_run: dict[str, object]) -> str:
    expected_mode = str(task_run.get("expected_reuse_mode", "none")).strip().lower()
    task_order = int(task_run.get("task_order", 0))
    if expected_mode == "assist":
        return "assist"
    if expected_mode == "skip_execute":
        return "validated_replay"
    if expected_mode == "skip_retrieve_execute":
        return "exact_replay"
    if task_order <= 1:
        return "cold_start"
    return "reject_control"


def _task_reuse_axis(task_run: dict[str, object]) -> str:
    if _task_reuse_slice(task_run) in {"validated_replay", "exact_replay"}:
        return "step_skipping"
    return "fresh_retrieval"


def _task_benchmark_lane(task_run: dict[str, object]) -> str:
    return str(task_run.get("benchmark_lane", "internal_regression")).strip() or "internal_regression"


def _task_transfer_strategy(task_run: dict[str, object]) -> str:
    return str(task_run.get("transfer_strategy", "flat_state_ref")).strip() or "flat_state_ref"


def _task_memory_policy(task_run: dict[str, object]) -> str:
    contract = str(task_run.get("runtime_reuse_contract", "assist_allowed")).strip().lower()
    if contract == "reuse_disabled":
        return "memory_off"
    if contract == "assist_allowed":
        layer = str(task_run.get("memory_layer", "")).strip().lower()
        return "long_term_assist" if layer == "long_term" else "working_assist"
    return contract if contract in {"validated_replay", "exact_replay"} else "validated_replay"


def _task_channel_form(task_run: dict[str, object]) -> str:
    strategy = str(task_run.get("transfer_strategy", "flat_state_ref")).strip()
    if strategy in {"flat_state_ref", "channel_store_hashref", "state_packet_minimal"}:
        return "typed_channel"
    return "text_channel"


def _control_metric_key(mode: str) -> str:
    return "text_bytes" if mode == "text" else "protocol_bytes"


def _task_artifact_expectations(task_run: dict[str, object]) -> dict[str, str]:
    raw = task_run.get("artifact_expectations", {})
    if not isinstance(raw, dict):
        raw = {}
    return {
        field_name: str(raw.get(field_name, "")).strip() for field_name in MISFIRE_FIELD_ORDER
    }


def _format_artifact_match_rate(field_summary: dict[str, object]) -> str:
    expected_count = int(field_summary.get("expected_count", 0))
    if expected_count <= 0:
        return "n/a"
    return f"{float(field_summary.get('match_rate', 0.0)):.2f}"


def _task_artifact_actuals(task_run: dict[str, object]) -> dict[str, str]:
    results = task_run.get("results", {})
    if not isinstance(results, dict):
        results = {}
    retrieve_result = results.get("retrieve", {})
    if not isinstance(retrieve_result, dict):
        retrieve_result = {}
    execute_result = results.get("execute", {})
    if not isinstance(execute_result, dict):
        execute_result = {}
    retrieve_payload = retrieve_result.get("payload", {})
    if not isinstance(retrieve_payload, dict):
        retrieve_payload = {}
    execute_payload = execute_result.get("payload", {})
    if not isinstance(execute_payload, dict):
        execute_payload = {}
    observability = retrieve_result.get("feature_observability", {})
    if not isinstance(observability, dict):
        observability = {}
    retrieved_doc_ids = retrieve_payload.get("retrieved_doc_ids", [])
    if not isinstance(retrieved_doc_ids, list):
        retrieved_doc_ids = []
    top_doc_id = next((str(item).strip() for item in retrieved_doc_ids if str(item).strip()), "")
    return {
        "route": str(retrieve_payload.get("feature_route", "")).strip()
        or str(observability.get("route", "")).strip(),
        "route_source": str(retrieve_payload.get("feature_route_source", "")).strip()
        or str(observability.get("route_source", "")).strip(),
        "tool_name": str(execute_payload.get("tool_name", "")).strip()
        or str(observability.get("tool_name", "")).strip(),
        "top_doc_id": top_doc_id,
    }


def _build_artifact_misfire(task_run: dict[str, object]) -> dict[str, object]:
    expected = _task_artifact_expectations(task_run)
    actual = _task_artifact_actuals(task_run)
    fields: dict[str, dict[str, object]] = {}
    expected_field_count = 0
    matched_field_count = 0
    for field_name in MISFIRE_FIELD_ORDER:
        expected_value = expected[field_name]
        actual_value = actual[field_name]
        enabled = bool(expected_value)
        matched = enabled and expected_value == actual_value
        if enabled:
            expected_field_count += 1
            matched_field_count += int(matched)
        fields[field_name] = {
            "enabled": enabled,
            "expected": expected_value,
            "actual": actual_value,
            "matched": matched,
        }
    return {
        "has_expectations": expected_field_count > 0,
        "expected": expected,
        "actual": actual,
        "fields": fields,
        "expected_field_count": expected_field_count,
        "matched_field_count": matched_field_count,
        "mismatched_field_count": expected_field_count - matched_field_count,
        "all_matched": expected_field_count == matched_field_count,
    }


def _annotate_artifact_misfires(task_runs: list[dict[str, object]]) -> None:
    for task_run in task_runs:
        task_run["artifact_misfire"] = _build_artifact_misfire(task_run)


def _relative_reduction(current: float, baseline: float) -> float:
    if baseline <= 0.0:
        return 0.0
    return 1.0 - (current / baseline)


def _zero_metric_row() -> dict[str, float]:
    payload = {field: 0.0 for field in METRIC_FIELDS}
    payload["memory_hit_rate"] = 0.0
    payload["replay_probe_hit_rate"] = 0.0
    payload["reuse_gain"] = 0.0
    payload["memory_assist_rate"] = 0.0
    payload["memory_reject_rate"] = 0.0
    payload["phase_accounted_ms"] = 0.0
    payload["phase_overhead_ms"] = 0.0
    payload["blob_cache_hit_rate"] = 0.0
    payload["dag_integrity_ok"] = 0.0
    return payload


def _zero_counter_row() -> dict[str, float]:
    return {field: 0.0 for field in COUNTER_FIELDS}


def _sum_metric_rows(metric_rows: list[dict[str, object]]) -> dict[str, float]:
    if not metric_rows:
        return _zero_metric_row()
    totals = {
        field: float(sum(float(row.get(field, 0.0)) for row in metric_rows))
        for field in METRIC_FIELDS
    }
    totals["memory_hit_rate"] = (
        totals["memory_hit_task_count"] / totals["memory_query_count"]
        if totals["memory_query_count"] > 0.0
        else 0.0
    )
    totals["replay_probe_hit_rate"] = (
        totals["replay_probe_hit_task_count"] / totals["replay_probe_count"]
        if totals["replay_probe_count"] > 0.0
        else 0.0
    )
    totals["reuse_gain"] = (
        totals["skipped_step_count"] / totals["planned_step_count"]
        if totals["planned_step_count"] > 0.0
        else 0.0
    )
    totals["memory_assist_rate"] = (
        totals["memory_assist_task_count"] / totals["memory_query_count"]
        if totals["memory_query_count"] > 0.0
        else 0.0
    )
    totals["memory_reject_rate"] = (
        totals["memory_rejected_task_count"] / totals["memory_query_count"]
        if totals["memory_query_count"] > 0.0
        else 0.0
    )
    totals["phase_accounted_ms"] = (
        totals["planner_ms"]
        + totals["retrieve_ms"]
        + totals["execute_ms"]
        + totals["summarize_ms"]
    )
    totals["phase_overhead_ms"] = max(
        totals["task_ms"] - totals["phase_accounted_ms"],
        0.0,
    )
    totals["blob_cache_hit_rate"] = (
        totals["blob_fetch_hits"] / totals["blob_fetch_count"]
        if totals["blob_fetch_count"] > 0.0
        else 0.0
    )
    totals["dag_integrity_ok"] = 1.0 if totals["dag_integrity_violation_count"] == 0.0 else 0.0
    return totals


def _average_metric_rows(metric_rows: list[dict[str, object]]) -> dict[str, float]:
    if not metric_rows:
        return _zero_metric_row()
    averaged = {
        field: float(mean(float(row.get(field, 0.0)) for row in metric_rows))
        for field in METRIC_FIELDS
    }
    averaged["memory_hit_rate"] = (
        averaged["memory_hit_task_count"] / averaged["memory_query_count"]
        if averaged["memory_query_count"] > 0.0
        else 0.0
    )
    averaged["replay_probe_hit_rate"] = (
        averaged["replay_probe_hit_task_count"] / averaged["replay_probe_count"]
        if averaged["replay_probe_count"] > 0.0
        else 0.0
    )
    averaged["reuse_gain"] = (
        averaged["skipped_step_count"] / averaged["planned_step_count"]
        if averaged["planned_step_count"] > 0.0
        else 0.0
    )
    averaged["memory_assist_rate"] = (
        averaged["memory_assist_task_count"] / averaged["memory_query_count"]
        if averaged["memory_query_count"] > 0.0
        else 0.0
    )
    averaged["memory_reject_rate"] = (
        averaged["memory_rejected_task_count"] / averaged["memory_query_count"]
        if averaged["memory_query_count"] > 0.0
        else 0.0
    )
    averaged["phase_accounted_ms"] = (
        averaged["planner_ms"]
        + averaged["retrieve_ms"]
        + averaged["execute_ms"]
        + averaged["summarize_ms"]
    )
    averaged["phase_overhead_ms"] = max(
        averaged["task_ms"] - averaged["phase_accounted_ms"],
        0.0,
    )
    averaged["blob_cache_hit_rate"] = (
        averaged["blob_fetch_hits"] / averaged["blob_fetch_count"]
        if averaged["blob_fetch_count"] > 0.0
        else 0.0
    )
    averaged["dag_integrity_ok"] = 1.0 if averaged["dag_integrity_violation_count"] == 0.0 else 0.0
    return averaged


def _sum_counter_rows(counter_rows: list[dict[str, object]]) -> dict[str, float]:
    if not counter_rows:
        return _zero_counter_row()
    return {
        field: float(sum(float(row.get(field, 0.0)) for row in counter_rows))
        for field in COUNTER_FIELDS
    }


def _average_counter_rows(counter_rows: list[dict[str, object]]) -> dict[str, float]:
    if not counter_rows:
        return _zero_counter_row()
    return {
        field: float(mean(float(row.get(field, 0.0)) for row in counter_rows))
        for field in COUNTER_FIELDS
    }


def _combine_setup_and_steady(
    setup: dict[str, float],
    steady: dict[str, float],
) -> dict[str, float]:
    combined = dict(steady)
    for field in COUNTER_FIELDS:
        combined[field] = float(setup.get(field, 0.0)) + float(steady.get(field, 0.0))
    combined["setup_message_count"] = float(setup["message_count"])
    combined["setup_text_chars"] = float(setup["text_chars"])
    combined["setup_text_bytes"] = float(setup["text_bytes"])
    combined["setup_protocol_bytes"] = float(setup["protocol_bytes"])
    combined["steady_state_message_count"] = float(steady["message_count"])
    combined["steady_state_text_chars"] = float(steady["text_chars"])
    combined["steady_state_text_bytes"] = float(steady["text_bytes"])
    combined["steady_state_protocol_bytes"] = float(steady["protocol_bytes"])
    return combined


def _merge_reuse_summary(
    target: dict[str, float],
    rows: list[dict[str, object]],
    mode: str,
) -> dict[str, float]:
    target.update(_summarize_reuse_rows(rows, mode))
    return target


def _build_run_session(mode: str) -> RunSession:
    return RunSession(mode=mode)


def _mode_order_for_run(modes: tuple[str, ...], run_index: int) -> tuple[str, ...]:
    if run_index % 2 == 0:
        return modes
    return tuple(reversed(modes))


def _matches_reuse_expectation(*, expected_mode: str, actual_mode: str) -> bool:
    normalized_expected = (expected_mode or "none").strip().lower()
    normalized_actual = (actual_mode or "none").strip().lower()
    if normalized_expected not in {"none", "assist", "skip_execute", "skip_retrieve_execute"}:
        raise ValueError(f"unsupported expected_reuse_mode: {expected_mode}")
    return normalized_expected == normalized_actual


async def _run_mode_once(
    *,
    mode: str,
    engine: str,
    run_index: int,
    root: Path,
    tasks: list[SampleTask],
    embedder: EmbeddingProvider,
    llm_client: LLMClient,
    statepool_config: StatePoolConfig,
    executor_transport: str,
    executor_socket_path: str | None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    session = _build_run_session(mode)
    orchestrator = Orchestrator(
        build_sample_agents_with_executor(
            llm_client=llm_client,
            executor_transport=executor_transport,
            executor_socket_path=executor_socket_path,
        )
    )
    graph_runner = StateBusGraphRunner(
        llm_client=llm_client,
        embedder=embedder,
        statepool_config=statepool_config,
        executor_transport=executor_transport,
        executor_socket_path=executor_socket_path,
    )
    ordered_tasks = [
        task for task in sorted(tasks, key=_task_sort_key) if task.supports_mode(mode)
    ]
    task_runs: list[dict[str, object]] = []
    group_db_paths = {
        task.task_group: root / f"{task.task_group}.sqlite3" for task in ordered_tasks
    }
    run_status = "completed"
    run_error: str | None = None
    for task_index, task in enumerate(ordered_tasks, start=1):
        ctx = Orchestrator.create_context(
            mode=mode,
            task_id=task.task_id,
            task_group=task.task_group,
            task_theme=task.task_theme,
            state_root=root / task.task_group / task.task_id,
            memory_db_path=group_db_paths[task.task_group],
            embedder=embedder,
            session=session,
            statepool_config=statepool_config,
            task_corpus_doc_ids=task.corpus_doc_ids,
            task_corpus_path=task.corpus_path,
            runtime_profile=task.runtime_profile,
        )
        task_payload: dict[str, object]
        try:
            if engine == "langgraph":
                graph_result = await graph_runner.run_task(
                    task,
                    mode=mode,
                    state_root=root / task.task_group / task.task_id,
                    memory_db_path=group_db_paths[task.task_group],
                    session=session,
                    ctx=ctx,
                )
                actual_reuse_mode = ctx.reuse_mode if ctx.reuse_hit is not None else "none"
                task_payload = {
                    "task_id": task.task_id,
                    "task_group": task.task_group,
                    "task_order": task.task_order,
                    "task_theme": task.task_theme,
                    "goal": task.goal,
                    "engine": engine,
                    "channel_form": _task_channel_form(
                        {"transfer_strategy": task.runtime_profile.effective_transfer_strategy(mode)}
                    ),
                    "memory_db_path": str(group_db_paths[task.task_group]),
                    "corpus_path": task.corpus_path,
                    "artifact_expectations": dict(task.artifact_expectations),
                    "expected_reuse_mode": task.expected_reuse_mode,
                    "benchmark_lane": task.benchmark_lane,
                    "transfer_strategy": _public_transfer_strategy(
                        task.runtime_profile.effective_transfer_strategy(mode),
                        mode,
                    ),
                    "reuse_expectation": {
                        "mode": task.expected_reuse_mode,
                        "task_order": task.task_order,
                        "expected_reuse": task.expected_reuse,
                    },
                    "runtime_reuse_contract": task.runtime_reuse_contract,
                    "runtime_gates": dict(task.runtime_gates),
                    "status": "completed",
                    "error": None,
                    "metrics": graph_result.metrics,
                    **_runtime_integrity_payload(ctx),
                    **_pure_text_guard_payload(
                        ctx,
                        task.runtime_profile.effective_transfer_strategy(mode),
                    ),
                    "memory_hits": graph_result.memory_hits,
                    "reuse": _reuse_artifact_payload(ctx, actual_reuse_mode),
                    "reuse_validation": {
                        "expected_reuse_mode": task.expected_reuse_mode,
                        "actual_reuse_mode": actual_reuse_mode,
                        "matched_expectation": _matches_reuse_expectation(
                            expected_mode=task.expected_reuse_mode,
                            actual_mode=actual_reuse_mode,
                        ),
                    },
                    "state_refs": graph_result.state_refs,
                    "state_channels": graph_result.state_channels,
                    "cas_summary": ctx.statepool.cas_summary(),
                    "graph_state": graph_result.graph_state,
                    "results": {
                        step_id: {
                            "success": result.success,
                            "skipped": result.skipped,
                            "reused_from_memory_id": result.reused_from_memory_id,
                            "has_memory_commit": (
                                result.memory_commit is not None or bool(result.memory_commits)
                            ),
                            "memory_commit_count": (
                                (1 if result.memory_commit is not None else 0)
                                + len(result.memory_commits)
                            ),
                            "payload": _sanitize_payload(result.payload),
                            "feature_observability": _feature_bundle_observability(ctx, result),
                        }
                        for step_id, result in graph_result.results.items()
                    },
                }
            else:
                await orchestrator.run_task(task, ctx)
                actual_reuse_mode = ctx.reuse_mode if ctx.reuse_hit is not None else "none"
                task_payload = {
                    "task_id": task.task_id,
                    "task_group": task.task_group,
                    "task_order": task.task_order,
                    "task_theme": task.task_theme,
                    "goal": task.goal,
                    "engine": engine,
                    "channel_form": _task_channel_form(
                        {"transfer_strategy": task.runtime_profile.effective_transfer_strategy(mode)}
                    ),
                    "memory_db_path": str(group_db_paths[task.task_group]),
                    "corpus_path": task.corpus_path,
                    "artifact_expectations": dict(task.artifact_expectations),
                    "expected_reuse_mode": task.expected_reuse_mode,
                    "benchmark_lane": task.benchmark_lane,
                    "transfer_strategy": _public_transfer_strategy(
                        task.runtime_profile.effective_transfer_strategy(mode),
                        mode,
                    ),
                    "reuse_expectation": {
                        "mode": task.expected_reuse_mode,
                        "task_order": task.task_order,
                        "expected_reuse": task.expected_reuse,
                    },
                    "runtime_reuse_contract": task.runtime_reuse_contract,
                    "runtime_gates": dict(task.runtime_gates),
                    "status": "completed",
                    "error": None,
                    "metrics": ctx.metrics.to_dict(),
                    **_runtime_integrity_payload(ctx),
                    **_pure_text_guard_payload(
                        ctx,
                        task.runtime_profile.effective_transfer_strategy(mode),
                    ),
                    "memory_hits": [hit.memory_id for hit in ctx.memory_hits],
                    "reuse": _reuse_artifact_payload(ctx, actual_reuse_mode),
                    "reuse_validation": {
                        "expected_reuse_mode": task.expected_reuse_mode,
                        "actual_reuse_mode": actual_reuse_mode,
                        "matched_expectation": _matches_reuse_expectation(
                            expected_mode=task.expected_reuse_mode,
                            actual_mode=actual_reuse_mode,
                        ),
                    },
                    "state_refs": {
                        state_id: {
                            "kind": ref.kind,
                            "storage": ref.storage,
                            "handle": ref.handle,
                            "length": ref.length,
                            "metadata": dict(ref.metadata),
                        }
                        for state_id, ref in ctx.state_refs.items()
                    },
                    "cas_summary": ctx.statepool.cas_summary(),
                    "results": {
                        step_id: {
                            "success": result.success,
                            "skipped": result.skipped,
                            "reused_from_memory_id": result.reused_from_memory_id,
                            "has_memory_commit": (
                                result.memory_commit is not None or bool(result.memory_commits)
                            ),
                            "memory_commit_count": (
                                (1 if result.memory_commit is not None else 0)
                                + len(result.memory_commits)
                            ),
                            "payload": _sanitize_payload(result.payload),
                            "feature_observability": _feature_bundle_observability(ctx, result),
                        }
                        for step_id, result in ctx.results.items()
                    },
                }
            if progress_callback is not None:
                progress_callback(
                    {
                        "mode": mode,
                        "engine": engine,
                        "run_index": run_index,
                        "task_index": task_index,
                        "task_count": len(ordered_tasks),
                        "task_id": task.task_id,
                        "status": "completed",
                        "llm_total_tokens": ctx.metrics.llm_total_tokens,
                        "task_ms": ctx.metrics.task_ms,
                    }
                )
        except Exception as exc:
            run_status = "failed"
            run_error = f"{type(exc).__name__}: {exc}"
            actual_reuse_mode = ctx.reuse_mode if ctx.reuse_hit is not None else "none"
            task_payload = {
                "task_id": task.task_id,
                "task_group": task.task_group,
                "task_order": task.task_order,
                "task_theme": task.task_theme,
                "goal": task.goal,
                "engine": engine,
                "channel_form": _task_channel_form(
                    {"transfer_strategy": task.runtime_profile.effective_transfer_strategy(mode)}
                ),
                "memory_db_path": str(group_db_paths[task.task_group]),
                "corpus_path": task.corpus_path,
                "artifact_expectations": dict(task.artifact_expectations),
                "expected_reuse_mode": task.expected_reuse_mode,
                "benchmark_lane": task.benchmark_lane,
                "transfer_strategy": _public_transfer_strategy(
                    task.runtime_profile.effective_transfer_strategy(mode),
                    mode,
                ),
                "reuse_expectation": {
                    "mode": task.expected_reuse_mode,
                    "task_order": task.task_order,
                    "expected_reuse": task.expected_reuse,
                },
                "runtime_reuse_contract": task.runtime_reuse_contract,
                "runtime_gates": dict(task.runtime_gates),
                "status": "failed",
                "error": run_error,
                "metrics": ctx.metrics.to_dict(),
                **_runtime_integrity_payload(ctx),
                **_pure_text_guard_payload(
                    ctx,
                    task.runtime_profile.effective_transfer_strategy(mode),
                ),
                "memory_hits": [hit.memory_id for hit in ctx.memory_hits],
                "reuse": {
                    "applied": ctx.reuse_hit is not None,
                    "mode": actual_reuse_mode,
                    "memory_id": None if ctx.reuse_hit is None else ctx.reuse_hit.memory_id,
                    "reuse_source": None if ctx.reuse_hit is None else ctx.reuse_hit.reuse_source,
                    "skipped_step_ids": list(ctx.pruned_step_ids),
                    "rejected_memory_id": None
                    if ctx.rejected_memory_hit is None
                    else ctx.rejected_memory_hit.memory_id,
                    "replay_class": None if ctx.reuse_hit is None else ctx.reuse_hit.replay_class,
                    "replay_candidate_count": ctx.metrics.replay_probe_hits,
                    "replay_reject_reason": "exception",
                    "replay_restored_state_ref_count": 0,
                    "replay_restored_channel_names": [],
                    "physical_blob_reused": False,
                    "logical_replay_reuse": False,
                    "physical_blob_reuse": False,
                    "dedup_bytes_saved": 0,
                    "cas_hit_rate": 0.0,
                },
                "reuse_validation": {
                    "expected_reuse_mode": task.expected_reuse_mode,
                    "actual_reuse_mode": actual_reuse_mode,
                    "matched_expectation": False,
                },
                "state_refs": {
                    state_id: {
                        "kind": ref.kind,
                        "storage": ref.storage,
                        "handle": ref.handle,
                        "length": ref.length,
                        "metadata": dict(ref.metadata),
                    }
                    for state_id, ref in ctx.state_refs.items()
                },
                "cas_summary": ctx.statepool.cas_summary(),
                "results": {},
            }
            if progress_callback is not None:
                progress_callback(
                    {
                        "mode": mode,
                        "engine": engine,
                        "run_index": run_index,
                        "task_index": task_index,
                        "task_count": len(ordered_tasks),
                        "task_id": task.task_id,
                        "status": "failed",
                        "error": run_error,
                        "llm_total_tokens": ctx.metrics.llm_total_tokens,
                        "task_ms": ctx.metrics.task_ms,
                    }
                )
            task_runs.append(task_payload)
            ctx.memory_store.close()
            break
        finally:
            if not ctx.memory_store.conn is None:
                try:
                    ctx.memory_store.close()
                except Exception:
                    pass
        task_runs.append(task_payload)

    _annotate_artifact_misfires(task_runs)
    _annotate_reuse_effects(task_runs, mode)
    setup_metrics = session.setup_metrics()
    steady_rows = [task_run["metrics"] for task_run in task_runs]
    steady_aggregate = _merge_reuse_summary(_sum_metric_rows(steady_rows), task_runs, mode)
    aggregate = _merge_reuse_summary(
        _combine_setup_and_steady(setup_metrics, steady_aggregate),
        task_runs,
        mode,
    )
    message_breakdown = session.message_breakdown_rows()
    session.cleanup()
    return {
        "mode": mode,
        "engine": engine,
        "run_index": run_index,
        "status": run_status,
        "error": run_error,
        "memory_db_paths": {
            group: str(path) for group, path in sorted(group_db_paths.items(), key=lambda item: item[0])
        },
        "setup_metrics": setup_metrics,
        "steady_state_aggregate": steady_aggregate,
        "aggregate": aggregate,
        "message_breakdown": message_breakdown,
        "task_groups": _aggregate_task_groups(task_runs),
        "tasks": task_runs,
    }


def _annotate_reuse_effects(task_runs: list[dict[str, object]], mode: str) -> None:
    control_key = _control_metric_key(mode)
    grouped: dict[str, list[dict[str, object]]] = {}
    for task_run in task_runs:
        if task_run["status"] != "completed":
            continue
        grouped.setdefault(str(task_run["task_group"]), []).append(task_run)
    for task_group in sorted(grouped):
        rows = sorted(grouped[task_group], key=lambda item: (int(item["task_order"]), str(item["task_id"])))
        baseline = rows[0]
        baseline_metrics = baseline["metrics"]
        baseline_control = float(baseline_metrics[control_key])
        baseline_tokens = float(baseline_metrics["llm_total_tokens"])
        baseline_task_ms = float(baseline_metrics["task_ms"])
        for row in rows:
            metrics = row["metrics"]
            applied = bool(row["reuse"]["applied"])
            row["reuse_effect"] = {
                "baseline_task_id": str(baseline["task_id"]),
                "applied": applied,
                "control_bytes_reduction_vs_cold": _relative_reduction(
                    float(metrics[control_key]),
                    baseline_control,
                )
                if applied
                else 0.0,
                "llm_total_tokens_reduction_vs_cold": _relative_reduction(
                    float(metrics["llm_total_tokens"]),
                    baseline_tokens,
                )
                if applied
                else 0.0,
                "task_ms_reduction_vs_cold": _relative_reduction(
                    float(metrics["task_ms"]),
                    baseline_task_ms,
                )
                if applied
                else 0.0,
            }
    for task_run in task_runs:
        task_run.setdefault(
            "reuse_effect",
            {
                "baseline_task_id": str(task_run["task_id"]),
                "applied": False,
                "control_bytes_reduction_vs_cold": 0.0,
                "llm_total_tokens_reduction_vs_cold": 0.0,
                "task_ms_reduction_vs_cold": 0.0,
            },
        )


def _summarize_reuse_rows(
    rows: list[dict[str, object]],
    mode: str,
) -> dict[str, float]:
    del mode
    completed_rows = [row for row in rows if row["status"] == "completed"]
    if not completed_rows:
        return {
            "reuse_apply_rate": 0.0,
            "expectation_match_rate": 0.0,
            "control_bytes_reduction_vs_cold": 0.0,
            "llm_total_tokens_reduction_vs_cold": 0.0,
            "task_ms_reduction_vs_cold": 0.0,
        }
    return {
        "reuse_apply_rate": float(
            mean(1.0 if bool(row["reuse"]["applied"]) else 0.0 for row in completed_rows)
        ),
        "expectation_match_rate": float(
            mean(
                1.0 if bool(row["reuse_validation"]["matched_expectation"]) else 0.0
                for row in completed_rows
            )
        ),
        "control_bytes_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["control_bytes_reduction_vs_cold"]) for row in completed_rows)
        ),
        "llm_total_tokens_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["llm_total_tokens_reduction_vs_cold"]) for row in completed_rows)
        ),
        "task_ms_reduction_vs_cold": float(
            mean(float(row["reuse_effect"]["task_ms_reduction_vs_cold"]) for row in completed_rows)
        ),
    }


def _empty_artifact_misfire_summary() -> dict[str, object]:
    return {
        "task_count": 0,
        "observed_task_runs": 0,
        "expected_field_runs": 0,
        "matched_field_runs": 0,
        "mismatched_task_runs": 0,
        "field_match_rate": 0.0,
        "task_match_rate": 0.0,
        "fields": {
            field_name: {
                "expected_count": 0,
                "matched_count": 0,
                "match_rate": 0.0,
            }
            for field_name in MISFIRE_FIELD_ORDER
        },
    }


def _summarize_artifact_misfire_rows(rows: list[dict[str, object]]) -> dict[str, object]:
    audits = []
    for row in rows:
        audit = row.get("artifact_misfire")
        if not isinstance(audit, dict):
            audit = _build_artifact_misfire(row)
        if bool(audit.get("has_expectations")):
            audits.append((row, audit))
    if not audits:
        return _empty_artifact_misfire_summary()
    expected_field_runs = sum(int(audit["expected_field_count"]) for _, audit in audits)
    matched_field_runs = sum(int(audit["matched_field_count"]) for _, audit in audits)
    field_rows: dict[str, dict[str, float | int]] = {}
    for field_name in MISFIRE_FIELD_ORDER:
        expected_count = sum(1 for _, audit in audits if bool(audit["fields"][field_name]["enabled"]))
        matched_count = sum(1 for _, audit in audits if bool(audit["fields"][field_name]["matched"]))
        field_rows[field_name] = {
            "expected_count": expected_count,
            "matched_count": matched_count,
            "match_rate": (matched_count / expected_count) if expected_count else 0.0,
        }
    return {
        "task_count": len({str(row["task_id"]) for row, _ in audits}),
        "observed_task_runs": len(audits),
        "expected_field_runs": expected_field_runs,
        "matched_field_runs": matched_field_runs,
        "mismatched_task_runs": sum(1 for _, audit in audits if not bool(audit["all_matched"])),
        "field_match_rate": (matched_field_runs / expected_field_runs) if expected_field_runs else 0.0,
        "task_match_rate": mean(1.0 if bool(audit["all_matched"]) else 0.0 for _, audit in audits),
        "fields": field_rows,
    }


def _summarize_reuse_misfire_rows(rows: list[dict[str, object]]) -> dict[str, float | int]:
    completed_rows = [row for row in rows if row.get("status") == "completed"]
    if not completed_rows:
        return {
            "expected_count": 0,
            "matched_count": 0,
            "match_rate": 0.0,
            "mismatched_count": 0,
        }
    matched_count = sum(
        1 for row in completed_rows if bool(row["reuse_validation"]["matched_expectation"])
    )
    expected_count = len(completed_rows)
    return {
        "expected_count": expected_count,
        "matched_count": matched_count,
        "match_rate": matched_count / expected_count,
        "mismatched_count": expected_count - matched_count,
    }


def _aggregate_task_groups(task_runs: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for task_run in task_runs:
        grouped.setdefault(str(task_run["task_group"]), []).append(task_run)
    summaries: list[dict[str, object]] = []
    for task_group in sorted(grouped):
        rows = sorted(grouped[task_group], key=lambda item: (int(item["task_order"]), str(item["task_id"])))
        summaries.append(
            {
                "task_group": task_group,
                "task_ids": [str(item["task_id"]) for item in rows],
                "aggregate": _merge_reuse_summary(
                    _sum_metric_rows([item["metrics"] for item in rows]),
                    rows,
                    "protocol",
                ),
            }
        )
    return summaries


def _aggregate_named_task_summaries(
    *,
    task_runs: list[dict[str, object]],
    mode: str,
    classifier: Callable[[dict[str, object]], str],
    order: tuple[str, ...],
    key_name: str,
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = {}
    for task_run in task_runs:
        grouped.setdefault(classifier(task_run), []).append(task_run)
    summaries: list[dict[str, object]] = []
    for name in order:
        rows = grouped.get(name, [])
        if not rows:
            continue
        completed_rows = [
            row for row in sorted(rows, key=lambda item: (int(item["task_order"]), str(item["task_id"])))
            if row["status"] == "completed"
        ]
        if not completed_rows:
            continue
        summaries.append(
            {
                key_name: name,
                "task_ids": [str(item["task_id"]) for item in completed_rows],
                **_merge_reuse_summary(
                    _average_metric_rows([item["metrics"] for item in completed_rows]),
                    completed_rows,
                    mode,
                ),
                "baseline_task_id": str(completed_rows[0]["task_id"]),
            }
        )
    return summaries


def _aggregate_message_breakdown(runs: list[dict[str, object]]) -> list[dict[str, float | str]]:
    grouped: dict[str, dict[str, float]] = {}
    for run in runs:
        if run["status"] != "completed":
            continue
        for row in run["message_breakdown"]:
            name = str(row["message_type"])
            entry = grouped.setdefault(
                name,
                {
                    "message_count": 0.0,
                    "protocol_bytes": 0.0,
                    "text_bytes": 0.0,
                    "setup_message_count": 0.0,
                    "setup_protocol_bytes": 0.0,
                    "setup_text_bytes": 0.0,
                    "steady_message_count": 0.0,
                    "steady_protocol_bytes": 0.0,
                    "steady_text_bytes": 0.0,
                },
            )
            for key in entry:
                entry[key] += float(row[key])
    rows: list[dict[str, float | str]] = []
    for name in sorted(grouped):
        entry = grouped[name]
        rows.append(
            {
                "message_type": name,
                **entry,
                "delta": entry["protocol_bytes"] - entry["text_bytes"],
            }
        )
    return rows


def _aggregate_mode_runs(runs: list[dict[str, object]]) -> dict[str, object]:
    completed_runs = [run for run in runs if run["status"] == "completed"]
    failures = [
        {
            "run_index": run["run_index"],
            "error": run["error"],
        }
        for run in runs
        if run["status"] != "completed"
    ]
    if not completed_runs:
        return {
            "run_count": 0,
            "failure_count": len(failures),
            "failures": failures,
            "aggregate": _combine_setup_and_steady(_zero_counter_row(), _zero_metric_row()),
            "setup": _zero_counter_row(),
            "steady_state": _zero_metric_row(),
            "task_groups": [],
            "reuse_slices": [],
            "reuse_axes": [],
            "benchmark_lanes": [],
            "transfer_strategies": [],
            "memory_policies": [],
            "tasks": [],
            "message_breakdown": [],
            "stability": {},
            "misfire_audit": {
                "artifact": _empty_artifact_misfire_summary(),
                "reuse": _summarize_reuse_misfire_rows([]),
            },
        }

    task_order_lookup = [
        (str(task["task_id"]), str(task["task_group"]), int(task["task_order"]))
        for task in completed_runs[0]["tasks"]
        if task["status"] == "completed"
    ]
    group_lookup = [str(group["task_group"]) for group in completed_runs[0]["task_groups"]]
    task_summaries = []
    for task_id, task_group, task_order in task_order_lookup:
        matching = [
            task_run
            for run in completed_runs
            for task_run in run["tasks"]
            if task_run["task_id"] == task_id and task_run["status"] == "completed"
        ]
        task_summaries.append(
            {
                "task_id": task_id,
                "task_group": task_group,
                "task_order": task_order,
                **_average_metric_rows([item["metrics"] for item in matching]),
                **_summarize_reuse_rows(matching, str(completed_runs[0]["mode"])),
                "baseline_task_id": str(matching[0]["reuse_effect"]["baseline_task_id"]),
            }
        )
    group_summaries = []
    for task_group in group_lookup:
        matching = [
            group_summary
            for run in completed_runs
            for group_summary in run["task_groups"]
            if group_summary["task_group"] == task_group
        ]
        task_rows = [
            task_run
            for run in completed_runs
            for task_run in run["tasks"]
            if task_run["task_group"] == task_group and task_run["status"] == "completed"
        ]
        group_summaries.append(
            {
                "task_group": task_group,
                "task_ids": list(matching[0]["task_ids"]),
                **_average_metric_rows([item["aggregate"] for item in matching]),
                **_summarize_reuse_rows(task_rows, str(completed_runs[0]["mode"])),
                "baseline_task_id": str(matching[0]["task_ids"][0]),
            }
        )
    task_rows = [task_run for run in completed_runs for task_run in run["tasks"]]
    reuse_slices = _aggregate_named_task_summaries(
        task_runs=task_rows,
        mode=str(completed_runs[0]["mode"]),
        classifier=_task_reuse_slice,
        order=REUSE_SLICE_ORDER,
        key_name="reuse_slice",
    )
    reuse_axes = _aggregate_named_task_summaries(
        task_runs=task_rows,
        mode=str(completed_runs[0]["mode"]),
        classifier=_task_reuse_axis,
        order=REUSE_AXIS_ORDER,
        key_name="reuse_axis",
    )
    benchmark_lanes = _aggregate_named_task_summaries(
        task_runs=task_rows,
        mode=str(completed_runs[0]["mode"]),
        classifier=_task_benchmark_lane,
        order=BENCHMARK_LANE_ORDER,
        key_name="benchmark_lane",
    )
    transfer_strategies = _aggregate_named_task_summaries(
        task_runs=task_rows,
        mode=str(completed_runs[0]["mode"]),
        classifier=_task_transfer_strategy,
        order=TRANSFER_STRATEGY_ORDER,
        key_name="transfer_strategy",
    )
    memory_policies = _aggregate_named_task_summaries(
        task_runs=task_rows,
        mode=str(completed_runs[0]["mode"]),
        classifier=_task_memory_policy,
        order=MEMORY_POLICY_ORDER,
        key_name="memory_policy",
    )
    setup = _average_counter_rows([run["setup_metrics"] for run in completed_runs])
    steady_state = _merge_reuse_summary(
        _average_metric_rows([run["steady_state_aggregate"] for run in completed_runs]),
        task_rows,
        str(completed_runs[0]["mode"]),
    )
    aggregate = _merge_reuse_summary(
        _combine_setup_and_steady(setup, steady_state),
        task_rows,
        str(completed_runs[0]["mode"]),
    )
    return {
        "run_count": len(completed_runs),
        "failure_count": len(failures),
        "failures": failures,
        "aggregate": aggregate,
        "setup": setup,
        "steady_state": steady_state,
        "task_groups": group_summaries,
        "reuse_slices": reuse_slices,
        "reuse_axes": reuse_axes,
        "benchmark_lanes": benchmark_lanes,
        "transfer_strategies": transfer_strategies,
        "memory_policies": memory_policies,
        "tasks": task_summaries,
        "message_breakdown": _aggregate_message_breakdown(completed_runs),
        "stability": _build_stability_summary(completed_runs),
        "misfire_audit": {
            "artifact": _summarize_artifact_misfire_rows(task_rows),
            "reuse": _summarize_reuse_misfire_rows(task_rows),
        },
    }


def _executor_observability_summary(
    result: dict[str, object], mode: str
) -> dict[str, object]:
    route_source_counts: dict[str, int] = {}
    observed_tasks = 0
    hint_consensus = 0
    with_signals = 0
    with_tags = 0
    signals_ge_2 = 0
    score_ge_20 = 0
    top_candidate_matches_selected_tool = 0
    for run in result["mode_runs"].get(mode, []):
        for task_run in run.get("tasks", []):
            retrieve_result = task_run.get("results", {}).get("retrieve", {})
            observability = retrieve_result.get("feature_observability", {})
            if not isinstance(observability, dict) or not observability:
                continue
            observed_tasks += 1
            route_source = str(observability.get("route_source", "")).strip() or "unknown"
            route_source_counts[route_source] = route_source_counts.get(route_source, 0) + 1
            if route_source != "hint_consensus":
                continue
            hint_consensus += 1
            matched_signals = [
                str(item) for item in observability.get("matched_signals", []) if str(item).strip()
            ]
            matched_tags = [
                str(item) for item in observability.get("matched_tags", []) if str(item).strip()
            ]
            tool_candidates = [
                item for item in observability.get("tool_candidates", []) if isinstance(item, dict)
            ]
            selected_tool = str(observability.get("tool_name", "")).strip()
            if matched_signals:
                with_signals += 1
            if matched_tags:
                with_tags += 1
            if len(matched_signals) >= 2:
                signals_ge_2 += 1
            if int(observability.get("match_score", 0)) >= 20:
                score_ge_20 += 1
            if tool_candidates and str(tool_candidates[0].get("tool_name", "")).strip() == selected_tool:
                top_candidate_matches_selected_tool += 1
    return {
        "observed_tasks": observed_tasks,
        "route_source_counts": route_source_counts,
        "hint_consensus_support": {
            "hint_consensus": hint_consensus,
            "with_signals": with_signals,
            "with_tags": with_tags,
            "signals_ge_2": signals_ge_2,
            "score_ge_20": score_ge_20,
            "top_candidate_matches_selected_tool": top_candidate_matches_selected_tool,
        },
    }


def _build_stability_summary(runs: list[dict[str, object]]) -> dict[str, dict[str, float]]:
    mode = str(runs[0]["mode"])
    steady_key = _control_metric_key(mode)
    summary: dict[str, dict[str, float]] = {}
    series_map = {
        "message_count": [float(run["aggregate"]["message_count"]) for run in runs],
        "control_bytes": [float(run["aggregate"][steady_key]) for run in runs],
        "steady_state_control_bytes": [float(run["steady_state_aggregate"][steady_key]) for run in runs],
        "setup_control_bytes": [float(run["setup_metrics"][steady_key]) for run in runs],
        "llm_total_tokens": [float(run["aggregate"]["llm_total_tokens"]) for run in runs],
        "planner_total_tokens": [float(run["aggregate"]["planner_total_tokens"]) for run in runs],
        "summarizer_total_tokens": [float(run["aggregate"]["summarizer_total_tokens"]) for run in runs],
        "memory_hit_rate": [float(run["aggregate"]["memory_hit_rate"]) for run in runs],
        "skipped_step_count": [float(run["aggregate"]["skipped_step_count"]) for run in runs],
        "reuse_gain": [float(run["aggregate"]["reuse_gain"]) for run in runs],
        "planner_ms": [float(run["aggregate"]["planner_ms"]) for run in runs],
        "retrieve_ms": [float(run["aggregate"]["retrieve_ms"]) for run in runs],
        "execute_ms": [float(run["aggregate"]["execute_ms"]) for run in runs],
        "summarize_ms": [float(run["aggregate"]["summarize_ms"]) for run in runs],
        "phase_overhead_ms": [float(run["aggregate"]["phase_overhead_ms"]) for run in runs],
        "task_ms": [float(run["aggregate"]["task_ms"]) for run in runs],
    }
    for field, values in series_map.items():
        field_mean = mean(values)
        variance = mean((value - field_mean) ** 2 for value in values) if values else 0.0
        summary[field] = {
            "mean": float(field_mean),
            "min": float(min(values)) if values else 0.0,
            "max": float(max(values)) if values else 0.0,
            "stddev": float(variance ** 0.5),
        }
    return summary


def _artifact_mismatch_rows(
    result: dict[str, object], mode: str, field_name: str
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in result["mode_runs"].get(mode, []):
        for task_run in run.get("tasks", []):
            audit = task_run.get("artifact_misfire")
            if not isinstance(audit, dict):
                audit = _build_artifact_misfire(task_run)
            field = audit.get("fields", {}).get(field_name, {})
            if not isinstance(field, dict):
                continue
            if not bool(field.get("enabled")) or bool(field.get("matched")):
                continue
            rows.append(
                {
                    "run_index": int(run["run_index"]),
                    "task_id": str(task_run.get("task_id", "")),
                    "expected": str(field.get("expected", "")).strip(),
                    "actual": str(field.get("actual", "")).strip(),
                }
            )
    return rows


def _reuse_mismatch_rows(result: dict[str, object], mode: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for run in result["mode_runs"].get(mode, []):
        for task_run in run.get("tasks", []):
            validation = task_run.get("reuse_validation", {})
            if not isinstance(validation, dict):
                continue
            if bool(validation.get("matched_expectation")):
                continue
            rows.append(
                {
                    "run_index": int(run["run_index"]),
                    "task_id": str(task_run.get("task_id", "")),
                    "expected": str(validation.get("expected_reuse_mode", "")).strip(),
                    "actual": str(validation.get("actual_reuse_mode", "")).strip(),
                }
            )
    return rows


def _progress_line(event: dict[str, object]) -> None:
    status = str(event["status"])
    if status == "completed":
        print(
            "[statebus] "
            f"mode={event['mode']} run={int(event['run_index']):02d} "
            f"task={int(event['task_index'])}/{int(event['task_count'])} "
            f"id={event['task_id']} llm_tokens={int(event['llm_total_tokens'])} "
            f"task_ms={float(event['task_ms']):.2f}",
            flush=True,
        )
        return
    print(
        "[statebus] "
        f"mode={event['mode']} run={int(event['run_index']):02d} "
        f"task={int(event['task_index'])}/{int(event['task_count'])} "
        f"id={event['task_id']} failed={event.get('error', 'unknown')}",
        flush=True,
    )


@contextmanager
def _executor_transport_context(
    *,
    out_dir: Path,
    transport: str,
    socket_path: str | None,
    statepool_config: StatePoolConfig,
) -> Iterator[str | None]:
    normalized = (transport or "local").strip().lower()
    if normalized == "local":
        yield None
        return
    if normalized != "uds":
        raise ValueError(f"unsupported executor transport: {transport}")
    if not _unix_sockets_available():
        raise RuntimeError(
            "executor transport 'uds' requires AF_UNIX socket support on the current host"
        )
    active_socket_path = socket_path or str(out_dir / "runtime" / "executor.sock")
    socket_file = Path(active_socket_path)
    socket_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "runtime.remote_executor",
        "--socket-path",
        active_socket_path,
        "--statepool-backend",
        statepool_config.default_backend,
        "--embed-state-backend",
        statepool_config.embedding_backend,
    ]
    server = subprocess.Popen(
        command,
        cwd=Path(__file__).resolve().parent.parent,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and not socket_file.exists():
            if server.poll() is not None:
                stdout = "" if server.stdout is None else server.stdout.read()
                stderr = "" if server.stderr is None else server.stderr.read()
                raise RuntimeError(
                    "remote executor exited before binding UDS socket: "
                    f"stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.05)
        if not socket_file.exists():
            raise RuntimeError(f"remote executor did not create socket: {active_socket_path}")
        yield active_socket_path
    finally:
        if server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
        try:
            socket_file.unlink()
        except FileNotFoundError:
            pass


def _unix_sockets_available() -> bool:
    with tempfile.TemporaryDirectory(prefix="statebus-uds-probe-") as tmpdir:
        socket_path = Path(tmpdir) / "probe.sock"
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.bind(str(socket_path))
        except (PermissionError, OSError):
            return False
        finally:
            try:
                probe.close()
            except Exception:
                pass
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        return True


def _build_result(
    *,
    task_set_path: str | Path,
    task_set_metadata: dict[str, object],
    tasks: list[SampleTask],
    modes: tuple[str, ...],
    repeat: int,
    seed: int,
    active_embedder: EmbeddingProvider,
    active_llm: LLMClient,
    llm_description: dict[str, object],
    statepool_config: StatePoolConfig,
    executor_transport: str,
    executor_socket_path: str | None,
    engine: str,
    mode_runs: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    summary = {mode: _aggregate_mode_runs(runs) for mode, runs in mode_runs.items()}
    expected_reuse_mode_counts = {
        expected_mode: sum(1 for task in tasks if task.expected_reuse_mode == expected_mode)
        for expected_mode in ("none", "assist", "skip_execute", "skip_retrieve_execute")
    }
    task_mode_counts = {
        mode: sum(1 for task in tasks if task.supports_mode(mode))
        for mode in modes
    }
    benchmark_lane_counts = {
        lane: sum(1 for task in tasks if task.benchmark_lane == lane)
        for lane in BENCHMARK_LANE_ORDER
    }
    transfer_strategy_counts = {
        strategy: sum(
            1
            for task in tasks
            if _public_transfer_strategy(task.transfer_strategy) == strategy
        )
        for strategy in TRANSFER_STRATEGY_ORDER
    }
    channel_form_counts = {
        "text_channel": sum(
            1
            for task in tasks
            if _task_channel_form({"transfer_strategy": _public_transfer_strategy(task.transfer_strategy)}) == "text_channel"
        ),
        "typed_channel": sum(
            1
            for task in tasks
            if _task_channel_form({"transfer_strategy": _public_transfer_strategy(task.transfer_strategy)}) == "typed_channel"
        ),
    }
    memory_policy_counts = {
        "memory_off": sum(1 for task in tasks if task.runtime_reuse_contract == "reuse_disabled"),
        "working_assist": sum(
            1
            for task in tasks
            if task.runtime_reuse_contract == "assist_allowed"
            and str(getattr(task, "memory_layer", "")).strip().lower() != "long_term"
        ),
        "long_term_assist": sum(
            1
            for task in tasks
            if task.runtime_reuse_contract == "assist_allowed"
            and str(getattr(task, "memory_layer", "")).strip().lower() == "long_term"
        ),
        "validated_replay": sum(1 for task in tasks if task.runtime_reuse_contract == "validated_replay"),
        "exact_replay": sum(1 for task in tasks if task.runtime_reuse_contract == "exact_replay"),
    }
    artifact_expectation_counts = {
        field_name: sum(1 for task in tasks if task.artifact_expectations[field_name])
        for field_name in MISFIRE_FIELD_ORDER
    }
    return {
        "manifest": {
            "task_set_path": str(Path(task_set_path)),
            "task_set_name": str(task_set_metadata.get("name", "")),
            "task_pack_type": str(task_set_metadata.get("pack_type", "ad_hoc")),
            "task_set_description": str(task_set_metadata.get("description", "")),
            "task_set_reading_contract": str(task_set_metadata.get("reading_contract", "")),
            "task_set_claim_lanes": list(task_set_metadata.get("claim_lanes", [])),
            "support_evidence_only": bool(task_set_metadata.get("support_only", False)),
            "task_count": len(tasks),
            "continuous_task_count": len(tasks),
            "task_mode_counts": task_mode_counts,
            "expected_reuse_task_count": sum(1 for task in tasks if task.expected_reuse),
            "reuse_expectation_policy": "benchmark_label_only",
            "expected_reuse_mode_counts": expected_reuse_mode_counts,
            "benchmark_lane_counts": benchmark_lane_counts,
            "transfer_strategy_counts": transfer_strategy_counts,
            "channel_form_counts": channel_form_counts,
            "memory_policy_counts": memory_policy_counts,
            "artifact_expectation_counts": artifact_expectation_counts,
            "artifact_expectation_task_count": sum(
                1 for task in tasks if any(task.artifact_expectations.values())
            ),
            "task_contract_counts": {
                "allow_memory_assist": sum(
                    1 for task in tasks if task.runtime_gates["allow_memory_assist"]
                ),
                "allow_execute_prune": sum(
                    1 for task in tasks if task.runtime_gates["allow_execute_prune"]
                ),
                "allow_exact_replay": sum(
                    1 for task in tasks if task.runtime_gates["allow_exact_replay"]
                ),
            },
            "task_groups": sorted({task.task_group for task in tasks}),
            "modes": list(modes),
            "engine": engine,
            "langgraph_available": langgraph_available(),
            "mode_schedule": "paired_round_robin_alternating",
            "text_baseline": "natural_language_briefs_and_narrative_frames",
            "protocol_baseline": "protobuf_control_frames",
            "repeat": repeat,
            "seed": seed,
            "encoder_id": active_embedder.encoder_id,
            "vector_dim": active_embedder.vector_dim,
            "llm_backend": str(llm_description["backend"]),
            "llm_mode": str(llm_description["mode"]),
            "llm_config_source": str(llm_description["source"]),
            "llm_providers": llm_description["providers"],
            "planner_provider": str(llm_description["planner_provider"]),
            "planner_model": str(llm_description["planner_model"]),
            "summarizer_provider": str(llm_description["summarizer_provider"]),
            "summarizer_model": str(llm_description["summarizer_model"]),
            "statepool_backend": statepool_config.default_backend,
            "embed_state_backend": statepool_config.embedding_backend,
            "executor_transport": executor_transport,
            "executor_socket_path": executor_socket_path or "",
        },
        "mode_runs": mode_runs,
        "summary": summary,
    }


async def run_benchmark(
    *,
    task_set_path: str | Path = DEFAULT_TASK_SET,
    modes: tuple[str, ...] = ("text", "protocol"),
    repeat: int = 10,
    seed: int = 42,
    out_dir: str | Path,
    embedder: EmbeddingProvider | None = None,
    embedder_model_path: str | Path = DEFAULT_EMBEDDING_MODEL_PATH,
    llm_client: LLMClient | None = None,
    llm_config: LLMConfig | None = None,
    statepool_config: StatePoolConfig | None = None,
    executor_transport: str = "local",
    executor_socket_path: str | None = None,
    engine: str = "langgraph",
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    task_bundle = load_task_set_bundle(task_set_path)
    tasks = list(task_bundle.tasks)
    task_set_metadata = {
        "name": task_bundle.metadata.name,
        "pack_type": task_bundle.metadata.pack_type,
        "description": task_bundle.metadata.description,
        "reading_contract": task_bundle.metadata.reading_contract,
        "claim_lanes": list(task_bundle.metadata.claim_lanes),
        "support_only": task_bundle.metadata.support_only,
    }
    active_embedder = embedder or SentenceTransformerEmbeddingProvider(embedder_model_path)
    active_llm = llm_client or build_llm_client(llm_config)
    llm_description = active_llm.describe()
    active_statepool_config = statepool_config or StatePoolConfig.from_env()
    if engine != "langgraph":
        raise ValueError("hard-break mainline only supports --engine langgraph")
    selected_engines = ("langgraph",)
    engine_results: dict[str, dict[str, object]] = {}
    for selected_engine in selected_engines:
        mode_runs: dict[str, list[dict[str, object]]] = {mode: [] for mode in modes}
        with _executor_transport_context(
            out_dir=out_path / selected_engine,
            transport=executor_transport,
            socket_path=executor_socket_path,
            statepool_config=active_statepool_config,
        ) as active_socket_path:
            for run_index in range(repeat):
                for mode in _mode_order_for_run(modes, run_index):
                    run_root = out_path / "artifacts" / selected_engine / mode / f"run_{run_index:02d}"
                    if run_root.exists():
                        shutil.rmtree(run_root)
                    run_root.mkdir(parents=True, exist_ok=True)
                    mode_runs[mode].append(
                        await _run_mode_once(
                            mode=mode,
                            engine=selected_engine,
                            run_index=run_index,
                            root=run_root,
                            tasks=tasks,
                            embedder=active_embedder,
                            llm_client=active_llm,
                            statepool_config=active_statepool_config,
                            executor_transport=executor_transport,
                            executor_socket_path=active_socket_path,
                            progress_callback=progress_callback,
                        )
                    )
            engine_results[selected_engine] = _build_result(
                task_set_path=task_set_path,
                task_set_metadata=task_set_metadata,
                tasks=tasks,
                modes=modes,
                repeat=repeat,
                seed=seed,
                active_embedder=active_embedder,
                active_llm=active_llm,
                llm_description=llm_description,
                statepool_config=active_statepool_config,
                executor_transport=executor_transport,
                executor_socket_path=active_socket_path,
                engine=selected_engine,
                mode_runs=mode_runs,
            )
            _write_results(
                out_path / selected_engine if engine == "both" else out_path,
                engine_results[selected_engine],
            )
    return engine_results[selected_engines[0]]


def _write_results(out_dir: Path, result: dict[str, object]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    _write_compare_csv(out_dir / "benchmark_compare.csv", result)
    _write_message_breakdown_csv(out_dir / "benchmark_message_breakdown.csv", result)
    (out_dir / "benchmark_message_sizes.md").write_text(_build_message_sizes_md(result), encoding="utf-8")
    (out_dir / "benchmark_report.md").write_text(_build_report(result), encoding="utf-8")


def _write_message_breakdown_csv(path: Path, result: dict[str, object]) -> None:
    fieldnames = [
        "mode",
        "message_type",
        "message_count",
        "protocol_bytes",
        "text_bytes",
        "delta",
        "setup_message_count",
        "setup_protocol_bytes",
        "setup_text_bytes",
        "steady_message_count",
        "steady_protocol_bytes",
        "steady_text_bytes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for mode in result["manifest"]["modes"]:
            mode_summary = result["summary"].get(mode)
            if not mode_summary:
                continue
            for row in mode_summary["message_breakdown"]:
                writer.writerow({"mode": mode, **row})


def _write_compare_csv(path: Path, result: dict[str, object]) -> None:
    summary = result["summary"]
    available_modes = [
        mode
        for mode in ("text", "protocol")
        if mode in summary and int(summary[mode].get("run_count", 0)) > 0
    ]
    if not available_modes:
        path.write_text("scope,identifier\nno_successful_modes,none\n", encoding="utf-8")
        return
    if len(available_modes) < 2:
        _write_single_mode_csv(path, summary[available_modes[0]], available_modes[0])
        return
    text_tasks = {item["task_id"]: item for item in summary["text"]["tasks"]}
    protocol_tasks = {item["task_id"]: item for item in summary["protocol"]["tasks"]}
    text_groups = {item["task_group"]: item for item in summary["text"]["task_groups"]}
    protocol_groups = {item["task_group"]: item for item in summary["protocol"]["task_groups"]}
    text_slices = {item["reuse_slice"]: item for item in summary["text"]["reuse_slices"]}
    protocol_slices = {item["reuse_slice"]: item for item in summary["protocol"]["reuse_slices"]}
    text_axes = {item["reuse_axis"]: item for item in summary["text"]["reuse_axes"]}
    protocol_axes = {item["reuse_axis"]: item for item in summary["protocol"]["reuse_axes"]}
    text_lanes = {item["benchmark_lane"]: item for item in summary["text"]["benchmark_lanes"]}
    protocol_lanes = {item["benchmark_lane"]: item for item in summary["protocol"]["benchmark_lanes"]}
    text_transfer = {
        item["transfer_strategy"]: item for item in summary["text"]["transfer_strategies"]
    }
    protocol_transfer = {
        item["transfer_strategy"]: item for item in summary["protocol"]["transfer_strategies"]
    }
    text_memory_policy = {
        item["memory_policy"]: item for item in summary["text"]["memory_policies"]
    }
    protocol_memory_policy = {
        item["memory_policy"]: item for item in summary["protocol"]["memory_policies"]
    }
    fieldnames = [
        "row_kind",
        "row_id",
        "text_message_count",
        "protocol_message_count",
        "message_delta",
        "text_setup_control_bytes",
        "protocol_setup_control_bytes",
        "setup_control_bytes_delta",
        "text_steady_state_control_bytes",
        "protocol_steady_state_control_bytes",
        "steady_state_control_bytes_delta",
        "text_control_bytes",
        "protocol_control_bytes",
        "control_bytes_delta",
        "text_state_bytes",
        "protocol_state_bytes",
        "state_bytes_delta",
        "text_handoff_ref_count",
        "protocol_handoff_ref_count",
        "handoff_ref_count_delta",
        "text_handoff_bytes",
        "protocol_handoff_bytes",
        "handoff_bytes_delta",
        "text_handoff_payload_bytes",
        "protocol_handoff_payload_bytes",
        "handoff_payload_bytes_delta",
        "text_handoff_wire_bytes",
        "protocol_handoff_wire_bytes",
        "handoff_wire_bytes_delta",
        "text_handoff_textual_ref_count",
        "protocol_handoff_textual_ref_count",
        "handoff_textual_ref_count_delta",
        "text_handoff_textual_bytes",
        "protocol_handoff_textual_bytes",
        "handoff_textual_bytes_delta",
        "text_handoff_nontext_ref_count",
        "protocol_handoff_nontext_ref_count",
        "handoff_nontext_ref_count_delta",
        "text_handoff_nontext_bytes",
        "protocol_handoff_nontext_bytes",
        "handoff_nontext_bytes_delta",
        "text_mmap_state_bytes",
        "protocol_mmap_state_bytes",
        "mmap_state_bytes_delta",
        "text_shared_memory_state_bytes",
        "protocol_shared_memory_state_bytes",
        "shared_memory_state_bytes_delta",
        "text_llm_total_tokens",
        "protocol_llm_total_tokens",
        "llm_total_tokens_delta",
        "text_planner_total_tokens",
        "protocol_planner_total_tokens",
        "planner_total_tokens_delta",
        "text_summarizer_total_tokens",
        "protocol_summarizer_total_tokens",
        "summarizer_total_tokens_delta",
        "text_memory_query_count",
        "protocol_memory_query_count",
        "memory_query_count_delta",
        "text_memory_hit_rate",
        "protocol_memory_hit_rate",
        "memory_hit_rate_delta",
        "text_planned_step_count",
        "protocol_planned_step_count",
        "planned_step_count_delta",
        "text_skipped_step_count",
        "protocol_skipped_step_count",
        "skipped_step_count_delta",
        "text_reuse_gain",
        "protocol_reuse_gain",
        "reuse_gain_delta",
        "text_reuse_apply_rate",
        "protocol_reuse_apply_rate",
        "reuse_apply_rate_delta",
        "text_expectation_match_rate",
        "protocol_expectation_match_rate",
        "expectation_match_rate_delta",
        "text_control_bytes_reduction_vs_cold",
        "protocol_control_bytes_reduction_vs_cold",
        "control_bytes_reduction_vs_cold_delta",
        "text_llm_total_tokens_reduction_vs_cold",
        "protocol_llm_total_tokens_reduction_vs_cold",
        "llm_total_tokens_reduction_vs_cold_delta",
        "text_task_ms_reduction_vs_cold",
        "protocol_task_ms_reduction_vs_cold",
        "task_ms_reduction_vs_cold_delta",
        "text_planner_ms",
        "protocol_planner_ms",
        "planner_ms_delta",
        "text_retrieve_ms",
        "protocol_retrieve_ms",
        "retrieve_ms_delta",
        "text_execute_ms",
        "protocol_execute_ms",
        "execute_ms_delta",
        "text_summarize_ms",
        "protocol_summarize_ms",
        "summarize_ms_delta",
        "text_phase_overhead_ms",
        "protocol_phase_overhead_ms",
        "phase_overhead_ms_delta",
        "text_task_ms",
        "protocol_task_ms",
        "task_ms_delta",
    ]
    rows = []
    for task_id in sorted(text_tasks, key=lambda item: (text_tasks[item]["task_group"], text_tasks[item]["task_order"], item)):
        rows.append(_compare_row("task", task_id, text_tasks[task_id], protocol_tasks[task_id], summary["text"], summary["protocol"]))
    for task_group in sorted(text_groups):
        rows.append(_compare_row("task_group", task_group, text_groups[task_group], protocol_groups[task_group], summary["text"], summary["protocol"]))
    for reuse_slice in REUSE_SLICE_ORDER:
        if reuse_slice in text_slices and reuse_slice in protocol_slices:
            rows.append(
                _compare_row(
                    "reuse_slice",
                    reuse_slice,
                    text_slices[reuse_slice],
                    protocol_slices[reuse_slice],
                    summary["text"],
                    summary["protocol"],
                )
            )
    for reuse_axis in REUSE_AXIS_ORDER:
        if reuse_axis in text_axes and reuse_axis in protocol_axes:
            rows.append(
                _compare_row(
                    "reuse_axis",
                    reuse_axis,
                    text_axes[reuse_axis],
                    protocol_axes[reuse_axis],
                    summary["text"],
                    summary["protocol"],
                )
            )
    for benchmark_lane in BENCHMARK_LANE_ORDER:
        if benchmark_lane in text_lanes and benchmark_lane in protocol_lanes:
            rows.append(
                _compare_row(
                    "benchmark_lane",
                    benchmark_lane,
                    text_lanes[benchmark_lane],
                    protocol_lanes[benchmark_lane],
                    summary["text"],
                    summary["protocol"],
                )
            )
    for transfer_strategy in TRANSFER_STRATEGY_ORDER:
        if transfer_strategy in text_transfer and transfer_strategy in protocol_transfer:
            rows.append(
                _compare_row(
                    "transfer_strategy",
                    transfer_strategy,
                    text_transfer[transfer_strategy],
                    protocol_transfer[transfer_strategy],
                    summary["text"],
                    summary["protocol"],
                )
            )
    for memory_policy in MEMORY_POLICY_ORDER:
        if memory_policy in text_memory_policy and memory_policy in protocol_memory_policy:
            rows.append(
                _compare_row(
                    "memory_policy",
                    memory_policy,
                    text_memory_policy[memory_policy],
                    protocol_memory_policy[memory_policy],
                    summary["text"],
                    summary["protocol"],
                )
            )
    rows.append(_compare_row("aggregate", "__aggregate__", summary["text"]["aggregate"], summary["protocol"]["aggregate"], summary["text"], summary["protocol"]))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _compare_row(
    row_kind: str,
    row_id: str,
    text_row: dict[str, float],
    protocol_row: dict[str, float],
    text_summary: dict[str, object],
    protocol_summary: dict[str, object],
) -> dict[str, float | str]:
    del text_summary, protocol_summary
    return {
        "row_kind": row_kind,
        "row_id": row_id,
        "text_message_count": round(float(text_row["message_count"]), 4),
        "protocol_message_count": round(float(protocol_row["message_count"]), 4),
        "message_delta": round(float(protocol_row["message_count"]) - float(text_row["message_count"]), 4),
        "text_setup_control_bytes": round(float(text_row.get("setup_text_bytes", text_row.get("text_bytes", 0.0))), 4),
        "protocol_setup_control_bytes": round(float(protocol_row.get("setup_protocol_bytes", protocol_row.get("protocol_bytes", 0.0))), 4),
        "setup_control_bytes_delta": round(
            float(protocol_row.get("setup_protocol_bytes", protocol_row.get("protocol_bytes", 0.0)))
            - float(text_row.get("setup_text_bytes", text_row.get("text_bytes", 0.0))),
            4,
        ),
        "text_steady_state_control_bytes": round(float(text_row.get("steady_state_text_bytes", text_row.get("text_bytes", 0.0))), 4),
        "protocol_steady_state_control_bytes": round(float(protocol_row.get("steady_state_protocol_bytes", protocol_row.get("protocol_bytes", 0.0))), 4),
        "steady_state_control_bytes_delta": round(
            float(protocol_row.get("steady_state_protocol_bytes", protocol_row.get("protocol_bytes", 0.0)))
            - float(text_row.get("steady_state_text_bytes", text_row.get("text_bytes", 0.0))),
            4,
        ),
        "text_control_bytes": round(float(text_row["text_bytes"]), 4),
        "protocol_control_bytes": round(float(protocol_row["protocol_bytes"]), 4),
        "control_bytes_delta": round(float(protocol_row["protocol_bytes"]) - float(text_row["text_bytes"]), 4),
        "text_state_bytes": round(float(text_row["state_bytes"]), 4),
        "protocol_state_bytes": round(float(protocol_row["state_bytes"]), 4),
        "state_bytes_delta": round(float(protocol_row["state_bytes"]) - float(text_row["state_bytes"]), 4),
        "text_handoff_ref_count": round(float(text_row["handoff_ref_count"]), 4),
        "protocol_handoff_ref_count": round(float(protocol_row["handoff_ref_count"]), 4),
        "handoff_ref_count_delta": round(
            float(protocol_row["handoff_ref_count"]) - float(text_row["handoff_ref_count"]),
            4,
        ),
        "text_handoff_bytes": round(float(text_row["handoff_bytes"]), 4),
        "protocol_handoff_bytes": round(float(protocol_row["handoff_bytes"]), 4),
        "handoff_bytes_delta": round(
            float(protocol_row["handoff_bytes"]) - float(text_row["handoff_bytes"]),
            4,
        ),
        "text_handoff_payload_bytes": round(
            float(text_row.get("handoff_payload_bytes", text_row["handoff_bytes"])),
            4,
        ),
        "protocol_handoff_payload_bytes": round(
            float(protocol_row.get("handoff_payload_bytes", protocol_row["handoff_bytes"])),
            4,
        ),
        "handoff_payload_bytes_delta": round(
            float(protocol_row.get("handoff_payload_bytes", protocol_row["handoff_bytes"]))
            - float(text_row.get("handoff_payload_bytes", text_row["handoff_bytes"])),
            4,
        ),
        "text_handoff_wire_bytes": round(float(text_row.get("handoff_wire_bytes", 0.0)), 4),
        "protocol_handoff_wire_bytes": round(float(protocol_row.get("handoff_wire_bytes", 0.0)), 4),
        "handoff_wire_bytes_delta": round(
            float(protocol_row.get("handoff_wire_bytes", 0.0))
            - float(text_row.get("handoff_wire_bytes", 0.0)),
            4,
        ),
        "text_handoff_textual_ref_count": round(float(text_row["handoff_textual_ref_count"]), 4),
        "protocol_handoff_textual_ref_count": round(float(protocol_row["handoff_textual_ref_count"]), 4),
        "handoff_textual_ref_count_delta": round(
            float(protocol_row["handoff_textual_ref_count"])
            - float(text_row["handoff_textual_ref_count"]),
            4,
        ),
        "text_handoff_textual_bytes": round(float(text_row["handoff_textual_bytes"]), 4),
        "protocol_handoff_textual_bytes": round(float(protocol_row["handoff_textual_bytes"]), 4),
        "handoff_textual_bytes_delta": round(
            float(protocol_row["handoff_textual_bytes"])
            - float(text_row["handoff_textual_bytes"]),
            4,
        ),
        "text_handoff_nontext_ref_count": round(float(text_row["handoff_nontext_ref_count"]), 4),
        "protocol_handoff_nontext_ref_count": round(float(protocol_row["handoff_nontext_ref_count"]), 4),
        "handoff_nontext_ref_count_delta": round(
            float(protocol_row["handoff_nontext_ref_count"])
            - float(text_row["handoff_nontext_ref_count"]),
            4,
        ),
        "text_handoff_nontext_bytes": round(float(text_row["handoff_nontext_bytes"]), 4),
        "protocol_handoff_nontext_bytes": round(float(protocol_row["handoff_nontext_bytes"]), 4),
        "handoff_nontext_bytes_delta": round(
            float(protocol_row["handoff_nontext_bytes"])
            - float(text_row["handoff_nontext_bytes"]),
            4,
        ),
        "text_mmap_state_bytes": round(float(text_row["mmap_state_bytes"]), 4),
        "protocol_mmap_state_bytes": round(float(protocol_row["mmap_state_bytes"]), 4),
        "mmap_state_bytes_delta": round(float(protocol_row["mmap_state_bytes"]) - float(text_row["mmap_state_bytes"]), 4),
        "text_shared_memory_state_bytes": round(float(text_row["shared_memory_state_bytes"]), 4),
        "protocol_shared_memory_state_bytes": round(float(protocol_row["shared_memory_state_bytes"]), 4),
        "shared_memory_state_bytes_delta": round(
            float(protocol_row["shared_memory_state_bytes"]) - float(text_row["shared_memory_state_bytes"]),
            4,
        ),
        "text_llm_total_tokens": round(float(text_row["llm_total_tokens"]), 4),
        "protocol_llm_total_tokens": round(float(protocol_row["llm_total_tokens"]), 4),
        "llm_total_tokens_delta": round(float(protocol_row["llm_total_tokens"]) - float(text_row["llm_total_tokens"]), 4),
        "text_planner_total_tokens": round(float(text_row["planner_total_tokens"]), 4),
        "protocol_planner_total_tokens": round(float(protocol_row["planner_total_tokens"]), 4),
        "planner_total_tokens_delta": round(
            float(protocol_row["planner_total_tokens"]) - float(text_row["planner_total_tokens"]),
            4,
        ),
        "text_summarizer_total_tokens": round(float(text_row["summarizer_total_tokens"]), 4),
        "protocol_summarizer_total_tokens": round(float(protocol_row["summarizer_total_tokens"]), 4),
        "summarizer_total_tokens_delta": round(
            float(protocol_row["summarizer_total_tokens"]) - float(text_row["summarizer_total_tokens"]),
            4,
        ),
        "text_memory_query_count": round(float(text_row["memory_query_count"]), 4),
        "protocol_memory_query_count": round(float(protocol_row["memory_query_count"]), 4),
        "memory_query_count_delta": round(float(protocol_row["memory_query_count"]) - float(text_row["memory_query_count"]), 4),
        "text_memory_hit_rate": round(float(text_row["memory_hit_rate"]), 4),
        "protocol_memory_hit_rate": round(float(protocol_row["memory_hit_rate"]), 4),
        "memory_hit_rate_delta": round(float(protocol_row["memory_hit_rate"]) - float(text_row["memory_hit_rate"]), 4),
        "text_planned_step_count": round(float(text_row["planned_step_count"]), 4),
        "protocol_planned_step_count": round(float(protocol_row["planned_step_count"]), 4),
        "planned_step_count_delta": round(float(protocol_row["planned_step_count"]) - float(text_row["planned_step_count"]), 4),
        "text_skipped_step_count": round(float(text_row["skipped_step_count"]), 4),
        "protocol_skipped_step_count": round(float(protocol_row["skipped_step_count"]), 4),
        "skipped_step_count_delta": round(float(protocol_row["skipped_step_count"]) - float(text_row["skipped_step_count"]), 4),
        "text_reuse_gain": round(float(text_row["reuse_gain"]), 4),
        "protocol_reuse_gain": round(float(protocol_row["reuse_gain"]), 4),
        "reuse_gain_delta": round(float(protocol_row["reuse_gain"]) - float(text_row["reuse_gain"]), 4),
        "text_reuse_apply_rate": round(float(text_row["reuse_apply_rate"]), 4),
        "protocol_reuse_apply_rate": round(float(protocol_row["reuse_apply_rate"]), 4),
        "reuse_apply_rate_delta": round(float(protocol_row["reuse_apply_rate"]) - float(text_row["reuse_apply_rate"]), 4),
        "text_expectation_match_rate": round(float(text_row["expectation_match_rate"]), 4),
        "protocol_expectation_match_rate": round(float(protocol_row["expectation_match_rate"]), 4),
        "expectation_match_rate_delta": round(float(protocol_row["expectation_match_rate"]) - float(text_row["expectation_match_rate"]), 4),
        "text_control_bytes_reduction_vs_cold": round(float(text_row["control_bytes_reduction_vs_cold"]), 4),
        "protocol_control_bytes_reduction_vs_cold": round(float(protocol_row["control_bytes_reduction_vs_cold"]), 4),
        "control_bytes_reduction_vs_cold_delta": round(
            float(protocol_row["control_bytes_reduction_vs_cold"]) - float(text_row["control_bytes_reduction_vs_cold"]),
            4,
        ),
        "text_llm_total_tokens_reduction_vs_cold": round(float(text_row["llm_total_tokens_reduction_vs_cold"]), 4),
        "protocol_llm_total_tokens_reduction_vs_cold": round(float(protocol_row["llm_total_tokens_reduction_vs_cold"]), 4),
        "llm_total_tokens_reduction_vs_cold_delta": round(
            float(protocol_row["llm_total_tokens_reduction_vs_cold"]) - float(text_row["llm_total_tokens_reduction_vs_cold"]),
            4,
        ),
        "text_task_ms_reduction_vs_cold": round(float(text_row["task_ms_reduction_vs_cold"]), 4),
        "protocol_task_ms_reduction_vs_cold": round(float(protocol_row["task_ms_reduction_vs_cold"]), 4),
        "task_ms_reduction_vs_cold_delta": round(
            float(protocol_row["task_ms_reduction_vs_cold"]) - float(text_row["task_ms_reduction_vs_cold"]),
            4,
        ),
        "text_planner_ms": round(float(text_row["planner_ms"]), 4),
        "protocol_planner_ms": round(float(protocol_row["planner_ms"]), 4),
        "planner_ms_delta": round(float(protocol_row["planner_ms"]) - float(text_row["planner_ms"]), 4),
        "text_retrieve_ms": round(float(text_row["retrieve_ms"]), 4),
        "protocol_retrieve_ms": round(float(protocol_row["retrieve_ms"]), 4),
        "retrieve_ms_delta": round(float(protocol_row["retrieve_ms"]) - float(text_row["retrieve_ms"]), 4),
        "text_execute_ms": round(float(text_row["execute_ms"]), 4),
        "protocol_execute_ms": round(float(protocol_row["execute_ms"]), 4),
        "execute_ms_delta": round(float(protocol_row["execute_ms"]) - float(text_row["execute_ms"]), 4),
        "text_summarize_ms": round(float(text_row["summarize_ms"]), 4),
        "protocol_summarize_ms": round(float(protocol_row["summarize_ms"]), 4),
        "summarize_ms_delta": round(float(protocol_row["summarize_ms"]) - float(text_row["summarize_ms"]), 4),
        "text_phase_overhead_ms": round(float(text_row["phase_overhead_ms"]), 4),
        "protocol_phase_overhead_ms": round(float(protocol_row["phase_overhead_ms"]), 4),
        "phase_overhead_ms_delta": round(
            float(protocol_row["phase_overhead_ms"]) - float(text_row["phase_overhead_ms"]),
            4,
        ),
        "text_task_ms": round(float(text_row["task_ms"]), 4),
        "protocol_task_ms": round(float(protocol_row["task_ms"]), 4),
        "task_ms_delta": round(float(protocol_row["task_ms"]) - float(text_row["task_ms"]), 4),
    }


def _build_message_sizes_md(result: dict[str, object]) -> str:
    lines = [
        "# StateBus Message Size Breakdown",
        "",
    ]
    for mode in result["manifest"]["modes"]:
        mode_summary = result["summary"].get(mode)
        if not mode_summary:
            continue
        lines.extend(
            [
                f"## {mode}",
                "",
                "| message_type | count | protocol_bytes | text_bytes | delta | setup_count | steady_count |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in mode_summary["message_breakdown"]:
            lines.append(
                f"| {row['message_type']} | {row['message_count']:.0f} | {row['protocol_bytes']:.0f} | "
                f"{row['text_bytes']:.0f} | {row['delta']:.0f} | {row['setup_message_count']:.0f} | "
                f"{row['steady_message_count']:.0f} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def _named_summary_lookup(
    rows: list[dict[str, object]], key_name: str
) -> dict[str, dict[str, object]]:
    return {str(item[key_name]): item for item in rows if key_name in item}


def _aggregate_filtered_mode_task_runs(
    result: dict[str, object],
    mode: str,
    *,
    benchmark_lane: str | None = None,
    transfer_strategy: str | None = None,
) -> dict[str, object] | None:
    matched_rows: list[dict[str, object]] = []
    task_ids: list[str] = []
    for run in result["mode_runs"].get(mode, []):
        for task_run in run.get("tasks", []):
            if task_run.get("status") != "completed":
                continue
            if benchmark_lane is not None and str(task_run.get("benchmark_lane", "")) != benchmark_lane:
                continue
            if transfer_strategy is not None and str(task_run.get("transfer_strategy", "")) != transfer_strategy:
                continue
            matched_rows.append(task_run)
            task_id = str(task_run.get("task_id", "")).strip()
            if task_id and task_id not in task_ids:
                task_ids.append(task_id)
    if not matched_rows:
        return None
    return {
        "task_count": len(task_ids),
        "task_ids": task_ids,
        **_merge_reuse_summary(
            _average_metric_rows([row["metrics"] for row in matched_rows]),
            matched_rows,
            mode,
        ),
    }


def _pack_available_modes(result: dict[str, object]) -> list[str]:
    manifest = result["manifest"]
    summary = result["summary"]
    task_mode_counts = dict(manifest.get("task_mode_counts", {}))
    return [
        mode
        for mode in ("text", "protocol")
        if int(task_mode_counts.get(mode, 0)) > 0 and int(summary.get(mode, {}).get("run_count", 0)) > 0
    ]


def _report_header_lines(result: dict[str, object]) -> list[str]:
    manifest = result["manifest"]
    lines = [
        "# StateBus Benchmark Report",
        "",
        f"- Task set: `{manifest['task_set_path']}`",
        f"- Task set name: `{manifest.get('task_set_name', '')}`",
        f"- Task pack type: `{manifest.get('task_pack_type', 'ad_hoc')}`",
        f"- Task groups: `{', '.join(manifest['task_groups'])}`",
        f"- Modes: `{', '.join(manifest['modes'])}`",
        f"- Mode-specific task counts: `{manifest.get('task_mode_counts', {})}`",
        f"- Repeat: `{manifest['repeat']}`",
        f"- StatePool backend: `{manifest['statepool_backend']}`",
        f"- Embedding state backend: `{manifest['embed_state_backend']}`",
        f"- Executor transport: `{manifest.get('executor_transport', 'local')}`",
    ]
    task_set_description = str(manifest.get("task_set_description", "")).strip()
    if task_set_description:
        lines.append(f"- Task set description: `{task_set_description}`")
    claim_lanes = [str(item) for item in manifest.get("task_set_claim_lanes", []) if str(item).strip()]
    if claim_lanes:
        lines.append(f"- Claim lanes for this pack: `{', '.join(claim_lanes)}`")
    reading_contract = str(manifest.get("task_set_reading_contract", "")).strip()
    if reading_contract:
        lines.append(f"- Task set reading contract: `{reading_contract}`")
    if bool(manifest.get("support_evidence_only", False)):
        lines.append(
            "- Pack boundary: `support evidence only; do not promote this pack into formal headline claims without a separate controlled rerun`"
        )
    return lines


def _append_protocol_only_handoff_table(
    lines: list[str],
    *,
    result: dict[str, object],
    left_strategy: str,
    right_strategy: str,
    title: str,
    scope_note: str,
) -> None:
    left = _aggregate_filtered_mode_task_runs(
        result,
        "protocol",
        benchmark_lane="state_transfer",
        transfer_strategy=left_strategy,
    )
    right = _aggregate_filtered_mode_task_runs(
        result,
        "protocol",
        benchmark_lane="state_transfer",
        transfer_strategy=right_strategy,
    )
    if left is None or right is None:
        return
    lines.extend(
        [
            "",
            f"## {title}",
            "",
            f"- Scope note: `{scope_note}`",
            "",
            "| handoff_strategy | task_count | control_bytes | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            f"| {left_strategy} | {left['task_count']} | {left['protocol_bytes']:.2f} | "
            f"{left.get('handoff_wire_bytes', 0.0):.2f} | "
            f"{left.get('handoff_payload_bytes', left['handoff_bytes']):.2f} | "
            f"{left['handoff_textual_bytes']:.2f} | {left['handoff_nontext_bytes']:.2f} | "
            f"{left['llm_total_tokens']:.2f} | {left['task_ms']:.2f} |",
            f"| {right_strategy} | {right['task_count']} | {right['protocol_bytes']:.2f} | "
            f"{right.get('handoff_wire_bytes', 0.0):.2f} | "
            f"{right.get('handoff_payload_bytes', right['handoff_bytes']):.2f} | "
            f"{right['handoff_textual_bytes']:.2f} | {right['handoff_nontext_bytes']:.2f} | "
            f"{right['llm_total_tokens']:.2f} | {right['task_ms']:.2f} |",
            f"| delta({right_strategy} - {left_strategy}) | n/a | {right['protocol_bytes'] - left['protocol_bytes']:.2f} | "
            f"{right.get('handoff_wire_bytes', 0.0) - left.get('handoff_wire_bytes', 0.0):.2f} | "
            f"{right.get('handoff_payload_bytes', right['handoff_bytes']) - left.get('handoff_payload_bytes', left['handoff_bytes']):.2f} | "
            f"{right['handoff_textual_bytes'] - left['handoff_textual_bytes']:.2f} | "
            f"{right['handoff_nontext_bytes'] - left['handoff_nontext_bytes']:.2f} | "
            f"{right['llm_total_tokens'] - left['llm_total_tokens']:.2f} | "
            f"{right['task_ms'] - left['task_ms']:.2f} |",
        ]
    )


def _append_headline_claim_sections(
    lines: list[str],
    *,
    result: dict[str, object],
    summary: dict[str, object],
) -> None:
    available_modes = _pack_available_modes(result)
    if len(available_modes) != 2:
        return
    manifest = result["manifest"]
    text_reuse_axes = _named_summary_lookup(summary["text"]["reuse_axes"], "reuse_axis")
    protocol_reuse_axes = _named_summary_lookup(summary["protocol"]["reuse_axes"], "reuse_axis")
    text_lanes = _named_summary_lookup(summary["text"]["benchmark_lanes"], "benchmark_lane")
    protocol_lanes = _named_summary_lookup(summary["protocol"]["benchmark_lanes"], "benchmark_lane")
    claim_lane_order = [
        str(item)
        for item in manifest.get("task_set_claim_lanes", [])
        if str(item) in BENCHMARK_LANE_ORDER
    ]
    lines.extend(
        [
            "",
            "## Structured-vs-Text By Reuse Axis",
            "",
            "- Audit note: `fresh_retrieval best isolates structured-vs-text communication and orchestration deltas; step_skipping includes replay effects.`",
            "- Memory note: `assist tiers are diagnostic support rows; validated_replay and exact_replay are the headline memory rows.`",
            "- State-transfer note: `the dedicated typed-handoff table below separates wire bytes from payload bytes; only wire bytes should be read as communication overhead.`",
            "",
            "| reuse_axis | text_control_bytes | protocol_control_bytes | control_bytes_delta | text_planner_tokens | protocol_planner_tokens | planner_tokens_delta | text_summarizer_tokens | protocol_summarizer_tokens | summarizer_tokens_delta | text_llm_total_tokens | protocol_llm_total_tokens | llm_total_tokens_delta | text_task_ms | protocol_task_ms | task_ms_delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for reuse_axis in REUSE_AXIS_ORDER:
        if reuse_axis not in text_reuse_axes or reuse_axis not in protocol_reuse_axes:
            continue
        text_axis = text_reuse_axes[reuse_axis]
        protocol_axis = protocol_reuse_axes[reuse_axis]
        lines.append(
            f"| {reuse_axis} | {text_axis['text_bytes']:.2f} | {protocol_axis['protocol_bytes']:.2f} | "
            f"{protocol_axis['protocol_bytes'] - text_axis['text_bytes']:.2f} | "
            f"{text_axis['planner_total_tokens']:.2f} | {protocol_axis['planner_total_tokens']:.2f} | "
            f"{protocol_axis['planner_total_tokens'] - text_axis['planner_total_tokens']:.2f} | "
            f"{text_axis['summarizer_total_tokens']:.2f} | {protocol_axis['summarizer_total_tokens']:.2f} | "
            f"{protocol_axis['summarizer_total_tokens'] - text_axis['summarizer_total_tokens']:.2f} | "
            f"{text_axis['llm_total_tokens']:.2f} | {protocol_axis['llm_total_tokens']:.2f} | "
            f"{protocol_axis['llm_total_tokens'] - text_axis['llm_total_tokens']:.2f} | "
            f"{text_axis['task_ms']:.2f} | {protocol_axis['task_ms']:.2f} | "
            f"{protocol_axis['task_ms'] - text_axis['task_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Contest Claim Lane Deltas",
            "",
            "| benchmark_lane | text_control_bytes | protocol_control_bytes | control_bytes_delta | text_handoff_wire_bytes | protocol_handoff_wire_bytes | text_handoff_payload_bytes | protocol_handoff_payload_bytes | llm_total_tokens_delta | task_ms_delta |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for benchmark_lane in claim_lane_order:
        if benchmark_lane not in text_lanes or benchmark_lane not in protocol_lanes:
            continue
        text_lane = text_lanes[benchmark_lane]
        protocol_lane = protocol_lanes[benchmark_lane]
        lines.append(
            f"| {benchmark_lane} | {text_lane['text_bytes']:.2f} | {protocol_lane['protocol_bytes']:.2f} | "
            f"{protocol_lane['protocol_bytes'] - text_lane['text_bytes']:.2f} | "
            f"{text_lane.get('handoff_wire_bytes', 0.0):.2f} | {protocol_lane.get('handoff_wire_bytes', 0.0):.2f} | "
            f"{text_lane.get('handoff_payload_bytes', text_lane['handoff_bytes']):.2f} | "
            f"{protocol_lane.get('handoff_payload_bytes', protocol_lane['handoff_bytes']):.2f} | "
            f"{protocol_lane['llm_total_tokens'] - text_lane['llm_total_tokens']:.2f} | "
            f"{protocol_lane['task_ms'] - text_lane['task_ms']:.2f} |"
        )
    text_state_transfer = _aggregate_filtered_mode_task_runs(
        result,
        "text",
        benchmark_lane="state_transfer",
    )
    protocol_state_transfer = _aggregate_filtered_mode_task_runs(
        result,
        "protocol",
        benchmark_lane="state_transfer",
    )
    if text_state_transfer is not None and protocol_state_transfer is not None:
        lines.extend(
            [
                "",
                "## Typed-Handoff State-Transfer Headline",
                "",
                "- Scope note: `this state_transfer read compares pure natural-text handoff against typed hash-first state handoff on the same controlled tasks.`",
                "- Metric note: `handoff_wire_bytes counts serialized StateRefLite pointers on the wire; handoff_payload_bytes counts local StatePool payload bytes available to the executor.`",
                "",
                "| mode / handoff | task_count | control_bytes | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                f"| text / natural_handoff_text | {text_state_transfer['task_count']} | {text_state_transfer['text_bytes']:.2f} | "
                f"{text_state_transfer.get('handoff_wire_bytes', 0.0):.2f} | "
                f"{text_state_transfer.get('handoff_payload_bytes', text_state_transfer['handoff_bytes']):.2f} | "
                f"{text_state_transfer['handoff_textual_bytes']:.2f} | {text_state_transfer['handoff_nontext_bytes']:.2f} | "
                f"{text_state_transfer['llm_total_tokens']:.2f} | {text_state_transfer['task_ms']:.2f} |",
                f"| protocol / channel_store_hashref | {protocol_state_transfer['task_count']} | {protocol_state_transfer['protocol_bytes']:.2f} | "
                f"{protocol_state_transfer.get('handoff_wire_bytes', 0.0):.2f} | "
                f"{protocol_state_transfer.get('handoff_payload_bytes', protocol_state_transfer['handoff_bytes']):.2f} | "
                f"{protocol_state_transfer['handoff_textual_bytes']:.2f} | {protocol_state_transfer['handoff_nontext_bytes']:.2f} | "
                f"{protocol_state_transfer['llm_total_tokens']:.2f} | {protocol_state_transfer['task_ms']:.2f} |",
                f"| delta(protocol/channel_store_hashref - text/natural_handoff_text) | n/a | {protocol_state_transfer['protocol_bytes'] - text_state_transfer['text_bytes']:.2f} | "
                f"{protocol_state_transfer.get('handoff_wire_bytes', 0.0) - text_state_transfer.get('handoff_wire_bytes', 0.0):.2f} | "
                f"{protocol_state_transfer.get('handoff_payload_bytes', protocol_state_transfer['handoff_bytes']) - text_state_transfer.get('handoff_payload_bytes', text_state_transfer['handoff_bytes']):.2f} | "
                f"{protocol_state_transfer['handoff_textual_bytes'] - text_state_transfer['handoff_textual_bytes']:.2f} | "
                f"{protocol_state_transfer['handoff_nontext_bytes'] - text_state_transfer['handoff_nontext_bytes']:.2f} | "
                f"{protocol_state_transfer['llm_total_tokens'] - text_state_transfer['llm_total_tokens']:.2f} | "
                f"{protocol_state_transfer['task_ms'] - text_state_transfer['task_ms']:.2f} |",
            ]
        )


def _build_specialized_pack_report(result: dict[str, object]) -> str | None:
    pack_type = str(result["manifest"].get("task_pack_type", "ad_hoc"))
    available_modes = _pack_available_modes(result)
    lines = _report_header_lines(result)
    if pack_type == "state_transfer_carrier":
        _append_protocol_only_handoff_table(
            lines,
            result=result,
            left_strategy="text_packet_minimal",
            right_strategy="state_packet_minimal",
            title="Protocol-Only Carrier Efficiency",
            scope_note="this table holds executor decision semantics fixed as a minimal packet and changes only the carrier: text packet versus non-text state packet.",
        )
        return "\n".join(lines) + "\n"
    if pack_type == "state_transfer_authenticity":
        _append_protocol_only_handoff_table(
            lines,
            result=result,
            left_strategy="text_brief",
            right_strategy="channel_store_hashref",
            title="Protocol-Only Typed-Handoff Authenticity",
            scope_note="this table fixes control mode at protocol and compares the legacy text_brief handoff against the rich channel-store hashref handoff.",
        )
        return "\n".join(lines) + "\n"
    if pack_type == "state_transfer_pure_text":
        _append_protocol_only_handoff_table(
            lines,
            result=result,
            left_strategy="natural_handoff_text",
            right_strategy="channel_store_hashref",
            title="Protocol-Only Pure-Text Versus Typed-State",
            scope_note="this table fixes control mode at protocol and compares natural free-text handoff against the real channel-store hashref typed handoff.",
        )
        return "\n".join(lines) + "\n"
    if pack_type == "state_transfer_natural_support":
        lines.append("- Support note: `this pack is support-only by design; use it to contextualize natural free-text handoff, not as the carrier headline.`")
        _append_protocol_only_handoff_table(
            lines,
            result=result,
            left_strategy="natural_handoff_text",
            right_strategy="state_packet_minimal",
            title="Protocol-Only Natural-Text Support",
            scope_note="this support table compares free-text retriever handoff against the same minimal state packet baseline.",
        )
        return "\n".join(lines) + "\n"
    if pack_type == "communication":
        if len(available_modes) == 2:
            text_lane = _aggregate_filtered_mode_task_runs(result, "text", benchmark_lane="communication")
            protocol_lane = _aggregate_filtered_mode_task_runs(result, "protocol", benchmark_lane="communication")
            if text_lane is not None and protocol_lane is not None:
                lines.extend(
                    [
                        "",
                        "## Communication Claim Surface",
                        "",
                        "| mode | task_count | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
                        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
                        f"| text | {text_lane['task_count']} | {text_lane['text_bytes']:.2f} | {text_lane['handoff_textual_bytes']:.2f} | {text_lane['handoff_nontext_bytes']:.2f} | {text_lane['llm_total_tokens']:.2f} | {text_lane['task_ms']:.2f} |",
                        f"| protocol | {protocol_lane['task_count']} | {protocol_lane['protocol_bytes']:.2f} | {protocol_lane['handoff_textual_bytes']:.2f} | {protocol_lane['handoff_nontext_bytes']:.2f} | {protocol_lane['llm_total_tokens']:.2f} | {protocol_lane['task_ms']:.2f} |",
                        f"| delta(protocol - text) | n/a | {protocol_lane['protocol_bytes'] - text_lane['text_bytes']:.2f} | {protocol_lane['handoff_textual_bytes'] - text_lane['handoff_textual_bytes']:.2f} | {protocol_lane['handoff_nontext_bytes'] - text_lane['handoff_nontext_bytes']:.2f} | {protocol_lane['llm_total_tokens'] - text_lane['llm_total_tokens']:.2f} | {protocol_lane['task_ms'] - text_lane['task_ms']:.2f} |",
                    ]
                )
        return "\n".join(lines) + "\n"
    if pack_type == "memory":
        protocol_memory_policies = _named_summary_lookup(
            result["summary"]["protocol"]["memory_policies"],
            "memory_policy",
        )
        lines.extend(
            [
                "",
                "## Memory Claim Surface",
                "",
                "- Boundary note: `working_assist and long_term_assist are diagnostic assist rows; validated_replay and exact_replay are the memory-reuse claim rows.`",
                "",
                "| memory_policy | task_count | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for memory_policy in MEMORY_POLICY_ORDER:
            row = protocol_memory_policies.get(memory_policy)
            if row is None:
                continue
            lines.append(
                f"| {memory_policy} | {len(row['task_ids'])} | {row['llm_total_tokens']:.2f} | {row['memory_hit_rate']:.2f} | {row['skipped_step_count']:.2f} | {row['reuse_gain']:.2f} | {row['task_ms']:.2f} |"
            )
        return "\n".join(lines) + "\n"
    return None


def _build_report(result: dict[str, object]) -> str:
    specialized = _build_specialized_pack_report(result)
    if specialized is not None:
        return specialized
    summary = result["summary"]
    manifest = result["manifest"]
    available_modes = _pack_available_modes(result)
    observability_summary = {
        mode: _executor_observability_summary(result, mode) for mode in available_modes
    }
    lines = [
        "# StateBus Benchmark Report",
        "",
        f"- Task set: `{manifest['task_set_path']}`",
        f"- Task set name: `{manifest.get('task_set_name', '')}`",
        f"- Task pack type: `{manifest.get('task_pack_type', 'ad_hoc')}`",
        f"- Task groups: `{', '.join(manifest['task_groups'])}`",
        f"- Modes: `{', '.join(manifest['modes'])}`",
        f"- Mode schedule: `{manifest.get('mode_schedule', 'legacy_blocked')}`",
        f"- Text baseline: `{manifest['text_baseline']}`",
        f"- Protocol baseline: `{manifest['protocol_baseline']}`",
        f"- Repeat: `{manifest['repeat']}`",
        f"- Continuous tasks per run: `{manifest['continuous_task_count']}`",
        f"- Mode-specific task counts: `{manifest.get('task_mode_counts', {})}`",
        f"- Expected reuse tasks per run: `{manifest['expected_reuse_task_count']}`",
        f"- Reuse expectation policy: `{manifest['reuse_expectation_policy']}`",
        f"- Expected reuse mode counts: `{json.dumps(manifest['expected_reuse_mode_counts'], sort_keys=True)}`",
        f"- Benchmark lane counts: `{json.dumps(manifest['benchmark_lane_counts'], sort_keys=True)}`",
        f"- Transfer strategy counts: `{json.dumps(manifest['transfer_strategy_counts'], sort_keys=True)}`",
        f"- Memory policy counts: `{json.dumps(manifest['memory_policy_counts'], sort_keys=True)}`",
        f"- Artifact expectation counts: `{json.dumps(manifest['artifact_expectation_counts'], sort_keys=True)}`",
        f"- Artifact expectation tasks per run: `{manifest['artifact_expectation_task_count']}`",
        f"- Task contract counts: `{json.dumps(manifest['task_contract_counts'], sort_keys=True)}`",
        f"- Encoder: `{manifest['encoder_id']}`",
        f"- StatePool backend: `{manifest['statepool_backend']}`",
        f"- Embedding state backend: `{manifest['embed_state_backend']}`",
        f"- Executor transport: `{manifest.get('executor_transport', 'local')}`",
        f"- LLM backend: `{manifest['llm_backend']}`",
        f"- LLM config: `{manifest['llm_config_source']}`",
        f"- Planner provider: `{manifest['planner_provider']}`",
        f"- Planner model: `{manifest['planner_model']}`",
        f"- Summarizer provider: `{manifest['summarizer_provider']}`",
        f"- Summarizer model: `{manifest['summarizer_model']}`",
        "- Reuse query policy: `memory assist stays runtime-contract gated; step-skipping now requires runtime evidence; expected_reuse_mode stays in benchmark validation`",
    ]
    if str(manifest.get("task_pack_type", "")) == "formal_controlled":
        lines.extend(
            [
                "- Headline note: `this frozen formal_controlled pack is lane-first; read the reuse-axis, lane-delta, and dedicated state_transfer sections before the aggregate.`",
                "- Interpretation note: `aggregate mixes the two controlled replay chains with the dedicated communication/state_transfer/memory lanes and now serves only as a secondary overview.`",
                "- State-transfer note: `read state_transfer with two layers: handoff_wire_bytes for communication overhead, handoff_payload_bytes for executor-visible local payload size; do not use raw state_bytes as the transfer headline.`",
                "- State-transfer baseline note: `the frozen headline pack compares natural_handoff_text against channel_store_hashref as the typed-handoff mainline`",
            ]
        )
    task_set_description = str(manifest.get("task_set_description", "")).strip()
    if task_set_description:
        lines.append(f"- Task set description: `{task_set_description}`")
    claim_lanes = [str(item) for item in manifest.get("task_set_claim_lanes", []) if str(item).strip()]
    if claim_lanes:
        lines.append(f"- Claim lanes for this pack: `{', '.join(claim_lanes)}`")
    reading_contract = str(manifest.get("task_set_reading_contract", "")).strip()
    if reading_contract:
        lines.append(f"- Task set reading contract: `{reading_contract}`")
    if bool(manifest.get("support_evidence_only", False)):
        lines.append(
            "- Pack boundary: `support evidence only; do not promote this pack into formal communication/state_transfer/memory headline claims without a separate controlled rerun`"
        )
    elif str(manifest.get("task_pack_type", "")) == "state_transfer_carrier":
        lines.append(
            "- Pack boundary: `formal carrier pack; use this pack only for the protocol-only carrier headline and keep other lanes in their dedicated packs`"
        )
    task_mode_counts = manifest.get("task_mode_counts", {})
    text_tasks = int(task_mode_counts.get("text", 0))
    protocol_tasks = int(task_mode_counts.get("protocol", 0))
    if text_tasks != protocol_tasks:
        lines.extend(
            [
                "",
                "> **Aggregate interpretation note**: text and protocol run different numbers of tasks "
                f"(text={text_tasks}, protocol={protocol_tasks}). "
                "Protocol's higher aggregate control_bytes reflects the extra tasks, not an inherent "
                "protocol disadvantage. **Use lane-level tables and the fresh_retrieval axis below for "
                "apples-to-apples comparison.**",
            ]
        )
    if str(manifest.get("task_pack_type", "")) == "formal_controlled":
        _append_headline_claim_sections(lines, result=result, summary=summary)
    lines.extend(
        [
            "",
            "## Aggregate",
            "",
            "- Secondary view note: `this table remains useful for whole-pack smoke checks, but the headline read now lives in the three sections above.`",
            "",
            "| mode | message_count | control_bytes | state_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        control_bytes = aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"]
        lines.append(
            f"| {mode} | {aggregate['message_count']:.2f} | {control_bytes:.2f} | "
            f"{aggregate['state_bytes']:.2f} | {aggregate['llm_total_tokens']:.2f} | "
            f"{aggregate['memory_hit_rate']:.2f} | {aggregate['skipped_step_count']:.2f} | "
            f"{aggregate['reuse_gain']:.2f} | {aggregate['task_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Diagnostic Appendix",
            "",
            "- Appendix note: `the sections below are secondary diagnostics and artifact audits; keep the frozen headline read on the reuse-axis, claim-lane, typed-handoff, and aggregate sections above.`",
        ]
    )
    lines.extend(
        [
            "",
            "## Role-Level LLM Tokens",
            "",
            "| mode | planner_requests | planner_total_tokens | summarizer_requests | summarizer_total_tokens | llm_total_tokens |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {aggregate['planner_llm_request_count']:.2f} | "
            f"{aggregate['planner_total_tokens']:.2f} | {aggregate['summarizer_llm_request_count']:.2f} | "
            f"{aggregate['summarizer_total_tokens']:.2f} | {aggregate['llm_total_tokens']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Phase Timing Breakdown",
            "",
            "| mode | planner_ms | retrieve_ms | execute_ms | summarize_ms | phase_overhead_ms | task_ms |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {aggregate['planner_ms']:.2f} | {aggregate['retrieve_ms']:.2f} | "
            f"{aggregate['execute_ms']:.2f} | {aggregate['summarize_ms']:.2f} | "
            f"{aggregate['phase_overhead_ms']:.2f} | {aggregate['task_ms']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Executor Handoff Breakdown",
            "",
            "| mode | handoff_ref_count | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_ref_count | handoff_textual_bytes | handoff_nontext_ref_count | handoff_nontext_bytes |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {aggregate['handoff_ref_count']:.2f} | {aggregate.get('handoff_wire_bytes', 0.0):.2f} | "
            f"{aggregate.get('handoff_payload_bytes', aggregate['handoff_bytes']):.2f} | "
            f"{aggregate['handoff_textual_ref_count']:.2f} | {aggregate['handoff_textual_bytes']:.2f} | "
            f"{aggregate['handoff_nontext_ref_count']:.2f} | {aggregate['handoff_nontext_bytes']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Reuse Query Accounting",
            "",
            "| mode | memory_query_count | memory_hit_task_count | memory_hit_rate |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {aggregate['memory_query_count']:.2f} | "
            f"{aggregate['memory_hit_task_count']:.2f} | {aggregate['memory_hit_rate']:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Setup Vs Steady-State Control Bytes",
            "",
            "| mode | setup_control_bytes | steady_state_control_bytes | total_control_bytes |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        aggregate = summary[mode]["aggregate"]
        setup = summary[mode]["setup"]
        steady = summary[mode]["steady_state"]
        setup_control = setup["text_bytes"] if mode == "text" else setup["protocol_bytes"]
        steady_control = steady["text_bytes"] if mode == "text" else steady["protocol_bytes"]
        total_control = aggregate["text_bytes"] if mode == "text" else aggregate["protocol_bytes"]
        lines.append(
            f"| {mode} | {setup_control:.2f} | {steady_control:.2f} | {total_control:.2f} |"
        )
    lines.extend(
        [
            "",
            "## Stability Summary",
            "",
            "| mode | runs | control_bytes_mean | steady_state_control_bytes_mean | setup_control_bytes_mean | llm_total_tokens_mean | task_ms_mean | expectation_match_rate | failure_count |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        stability = summary[mode]["stability"]
        aggregate = summary[mode]["aggregate"]
        lines.append(
            f"| {mode} | {summary[mode]['run_count']} | {stability['control_bytes']['mean']:.2f} | "
            f"{stability['steady_state_control_bytes']['mean']:.2f} | "
            f"{stability['setup_control_bytes']['mean']:.2f} | {stability['llm_total_tokens']['mean']:.2f} | "
            f"{stability['task_ms']['mean']:.2f} | {aggregate['expectation_match_rate']:.2f} | "
            f"{summary[mode]['failure_count']} |"
        )
    lines.extend(
        [
            "",
            "## Task Group Reuse Summary",
            "",
            "| task_group | mode | control_bytes | memory_hit_rate | skipped_step_count | reuse_gain | reuse_apply_rate | expectation_match_rate | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for group in summary[mode]["task_groups"]:
            control_bytes = group["text_bytes"] if mode == "text" else group["protocol_bytes"]
            lines.append(
                f"| {group['task_group']} | {mode} | {control_bytes:.2f} | "
                f"{group['memory_hit_rate']:.2f} | {group['skipped_step_count']:.2f} | "
                f"{group['reuse_gain']:.2f} | {group['reuse_apply_rate']:.2f} | "
                f"{group['expectation_match_rate']:.2f} | {group['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Replay Contract Slice Summary",
            "",
            "| reuse_slice | mode | task_count | control_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | reuse_apply_rate | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for slice_summary in summary[mode]["reuse_slices"]:
            control_bytes = slice_summary["text_bytes"] if mode == "text" else slice_summary["protocol_bytes"]
            lines.append(
                f"| {slice_summary['reuse_slice']} | {mode} | {len(slice_summary['task_ids'])} | "
                f"{control_bytes:.2f} | {slice_summary['llm_total_tokens']:.2f} | {slice_summary['memory_hit_rate']:.2f} | "
                f"{slice_summary['skipped_step_count']:.2f} | {slice_summary['reuse_gain']:.2f} | "
                f"{slice_summary['reuse_apply_rate']:.2f} | {slice_summary['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Communication Vs Replay Axes",
            "",
            "| reuse_axis | mode | task_count | control_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | reuse_apply_rate | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for axis_summary in summary[mode]["reuse_axes"]:
            control_bytes = axis_summary["text_bytes"] if mode == "text" else axis_summary["protocol_bytes"]
            lines.append(
                f"| {axis_summary['reuse_axis']} | {mode} | {len(axis_summary['task_ids'])} | "
                f"{control_bytes:.2f} | {axis_summary['llm_total_tokens']:.2f} | {axis_summary['memory_hit_rate']:.2f} | "
                f"{axis_summary['skipped_step_count']:.2f} | {axis_summary['reuse_gain']:.2f} | "
                f"{axis_summary['reuse_apply_rate']:.2f} | {axis_summary['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Benchmark Lane Diagnostics",
            "",
            "| benchmark_lane | mode | task_count | control_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for lane_summary in summary[mode]["benchmark_lanes"]:
            control_bytes = lane_summary["text_bytes"] if mode == "text" else lane_summary["protocol_bytes"]
            lines.append(
                f"| {lane_summary['benchmark_lane']} | {mode} | {len(lane_summary['task_ids'])} | "
                f"{control_bytes:.2f} | {lane_summary['handoff_textual_bytes']:.2f} | "
                f"{lane_summary['handoff_nontext_bytes']:.2f} | {lane_summary['llm_total_tokens']:.2f} | "
                f"{lane_summary['memory_hit_rate']:.2f} | {lane_summary['skipped_step_count']:.2f} | "
                f"{lane_summary['reuse_gain']:.2f} | {lane_summary['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## State Transfer Strategies",
            "",
            "| transfer_strategy | mode | task_count | control_bytes | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for transfer_summary in summary[mode]["transfer_strategies"]:
            control_bytes = transfer_summary["text_bytes"] if mode == "text" else transfer_summary["protocol_bytes"]
            lines.append(
                f"| {transfer_summary['transfer_strategy']} | {mode} | {len(transfer_summary['task_ids'])} | "
                f"{control_bytes:.2f} | {transfer_summary.get('handoff_wire_bytes', 0.0):.2f} | "
                f"{transfer_summary.get('handoff_payload_bytes', transfer_summary['handoff_bytes']):.2f} | "
                f"{transfer_summary['handoff_textual_bytes']:.2f} | {transfer_summary['handoff_nontext_bytes']:.2f} | "
                f"{transfer_summary['llm_total_tokens']:.2f} | {transfer_summary['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Memory Policies",
            "",
            "| memory_policy | mode | task_count | control_bytes | llm_total_tokens | memory_hit_rate | skipped_step_count | reuse_gain | task_ms |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for policy_summary in summary[mode]["memory_policies"]:
            control_bytes = policy_summary["text_bytes"] if mode == "text" else policy_summary["protocol_bytes"]
            lines.append(
                f"| {policy_summary['memory_policy']} | {mode} | {len(policy_summary['task_ids'])} | "
                f"{control_bytes:.2f} | {policy_summary['llm_total_tokens']:.2f} | {policy_summary['memory_hit_rate']:.2f} | "
                f"{policy_summary['skipped_step_count']:.2f} | {policy_summary['reuse_gain']:.2f} | {policy_summary['task_ms']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Memory Assist Diagnostics",
            "",
            "| memory_policy | mode | task_count | prior_applied_rate | candidate_reduction | route_agreement_rate | rescue_rate |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for policy_summary in summary[mode]["memory_policies"]:
            lines.append(
                f"| {policy_summary['memory_policy']} | {mode} | {len(policy_summary['task_ids'])} | "
                f"{policy_summary['memory_assist_prior_applied_task_count']:.2f} | "
                f"{policy_summary['memory_assist_candidate_reduction']:.2f} | "
                f"{policy_summary['memory_assist_route_agreement_task_count']:.2f} | "
                f"{policy_summary['memory_assist_rescue_task_count']:.2f} |"
            )
    if len(available_modes) == 2:
        text_memory_policies = _named_summary_lookup(summary["text"]["memory_policies"], "memory_policy")
        protocol_memory_policies = _named_summary_lookup(summary["protocol"]["memory_policies"], "memory_policy")
        protocol_transfer_text_packet = _aggregate_filtered_mode_task_runs(
            result,
            "protocol",
            benchmark_lane="state_transfer",
            transfer_strategy="text_packet_minimal",
        )
        protocol_transfer_state_packet = _aggregate_filtered_mode_task_runs(
            result,
            "protocol",
            benchmark_lane="state_transfer",
            transfer_strategy="state_packet_minimal",
        )
        if (
            protocol_transfer_text_packet is not None
            and protocol_transfer_state_packet is not None
        ):
            lines.extend(
                [
                    "",
                    "### Protocol-Only Carrier Efficiency",
                    "",
                    "- Scope note: `this table holds executor decision semantics fixed as a minimal packet and changes only the carrier: text packet versus non-text state packet.`",
                    "",
                    "| handoff_strategy | task_count | control_bytes | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                    f"| text_packet_minimal | {protocol_transfer_text_packet['task_count']} | {protocol_transfer_text_packet['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_text_packet.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_text_packet.get('handoff_payload_bytes', protocol_transfer_text_packet['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_text_packet['handoff_textual_bytes']:.2f} | {protocol_transfer_text_packet['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_text_packet['llm_total_tokens']:.2f} | {protocol_transfer_text_packet['task_ms']:.2f} |",
                    f"| state_packet_minimal | {protocol_transfer_state_packet['task_count']} | {protocol_transfer_state_packet['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_payload_bytes', protocol_transfer_state_packet['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_state_packet['handoff_textual_bytes']:.2f} | {protocol_transfer_state_packet['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['llm_total_tokens']:.2f} | {protocol_transfer_state_packet['task_ms']:.2f} |",
                    f"| delta(state_packet_minimal - text_packet_minimal) | n/a | {protocol_transfer_state_packet['protocol_bytes'] - protocol_transfer_text_packet['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_wire_bytes', 0.0) - protocol_transfer_text_packet.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_payload_bytes', protocol_transfer_state_packet['handoff_bytes']) - protocol_transfer_text_packet.get('handoff_payload_bytes', protocol_transfer_text_packet['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_state_packet['handoff_textual_bytes'] - protocol_transfer_text_packet['handoff_textual_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['handoff_nontext_bytes'] - protocol_transfer_text_packet['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['llm_total_tokens'] - protocol_transfer_text_packet['llm_total_tokens']:.2f} | "
                    f"{protocol_transfer_state_packet['task_ms'] - protocol_transfer_text_packet['task_ms']:.2f} |",
                ]
            )
        protocol_transfer_natural_handoff = _aggregate_filtered_mode_task_runs(
            result,
            "protocol",
            benchmark_lane="state_transfer",
            transfer_strategy="natural_handoff_text",
        )
        if (
            protocol_transfer_natural_handoff is not None
            and protocol_transfer_state_packet is not None
        ):
            lines.extend(
                [
                    "",
                    "### Protocol-Only Natural-Text Support",
                    "",
                    "- Scope note: `this support table compares free-text retriever handoff against the same minimal state packet baseline. Read it as natural-text support evidence, not the main carrier headline.`",
                    "",
                    "| handoff_strategy | task_count | control_bytes | handoff_wire_bytes | handoff_payload_bytes | handoff_textual_bytes | handoff_nontext_bytes | llm_total_tokens | task_ms |",
                    "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                    f"| natural_handoff_text | {protocol_transfer_natural_handoff['task_count']} | {protocol_transfer_natural_handoff['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_natural_handoff.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_natural_handoff.get('handoff_payload_bytes', protocol_transfer_natural_handoff['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_natural_handoff['handoff_textual_bytes']:.2f} | {protocol_transfer_natural_handoff['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_natural_handoff['llm_total_tokens']:.2f} | {protocol_transfer_natural_handoff['task_ms']:.2f} |",
                    f"| state_packet_minimal | {protocol_transfer_state_packet['task_count']} | {protocol_transfer_state_packet['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_payload_bytes', protocol_transfer_state_packet['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_state_packet['handoff_textual_bytes']:.2f} | {protocol_transfer_state_packet['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['llm_total_tokens']:.2f} | {protocol_transfer_state_packet['task_ms']:.2f} |",
                    f"| delta(state_packet_minimal - natural_handoff_text) | n/a | {protocol_transfer_state_packet['protocol_bytes'] - protocol_transfer_natural_handoff['protocol_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_wire_bytes', 0.0) - protocol_transfer_natural_handoff.get('handoff_wire_bytes', 0.0):.2f} | "
                    f"{protocol_transfer_state_packet.get('handoff_payload_bytes', protocol_transfer_state_packet['handoff_bytes']) - protocol_transfer_natural_handoff.get('handoff_payload_bytes', protocol_transfer_natural_handoff['handoff_bytes']):.2f} | "
                    f"{protocol_transfer_state_packet['handoff_textual_bytes'] - protocol_transfer_natural_handoff['handoff_textual_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['handoff_nontext_bytes'] - protocol_transfer_natural_handoff['handoff_nontext_bytes']:.2f} | "
                    f"{protocol_transfer_state_packet['llm_total_tokens'] - protocol_transfer_natural_handoff['llm_total_tokens']:.2f} | "
                    f"{protocol_transfer_state_packet['task_ms'] - protocol_transfer_natural_handoff['task_ms']:.2f} |",
                ]
            )
        lines.extend(
            [
                "",
                "### Memory Policy Claim Surface",
                "",
                "| memory_policy | text_llm_total_tokens | protocol_llm_total_tokens | text_task_ms | protocol_task_ms | text_skipped_step_count | protocol_skipped_step_count | text_reuse_gain | protocol_reuse_gain |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for memory_policy in MEMORY_POLICY_ORDER:
            if memory_policy not in text_memory_policies or memory_policy not in protocol_memory_policies:
                continue
            text_policy = text_memory_policies[memory_policy]
            protocol_policy = protocol_memory_policies[memory_policy]
            lines.append(
                f"| {memory_policy} | {text_policy['llm_total_tokens']:.2f} | {protocol_policy['llm_total_tokens']:.2f} | "
                f"{text_policy['task_ms']:.2f} | {protocol_policy['task_ms']:.2f} | "
                f"{text_policy['skipped_step_count']:.2f} | {protocol_policy['skipped_step_count']:.2f} | "
                f"{text_policy['reuse_gain']:.2f} | {protocol_policy['reuse_gain']:.2f} |"
            )
    lines.extend(
        [
            "",
            "## Executor Feature Observability",
            "",
            "- Artifact-only note: `these counts are reconstructed from benchmark artifacts and do not add fields to the live control plane`",
            "",
            "### Route Source Distribution",
            "",
            "| mode | route_source | task_count | observed_tasks |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        route_counts = observability_summary[mode]["route_source_counts"]
        for route_source, task_count in sorted(route_counts.items(), key=lambda item: (-item[1], item[0])):
            lines.append(
                f"| {mode} | {route_source} | {task_count} | "
                f"{observability_summary[mode]['observed_tasks']} |"
            )
    lines.extend(
        [
            "",
            "### Hint-Consensus Support",
            "",
            "| mode | hint_consensus | with_signals | with_tags | signals_ge_2 | score_ge_20 | top_candidate_matches_selected_tool |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        hint_support = observability_summary[mode]["hint_consensus_support"]
        lines.append(
            f"| {mode} | {hint_support['hint_consensus']} | {hint_support['with_signals']} | "
            f"{hint_support['with_tags']} | {hint_support['signals_ge_2']} | "
            f"{hint_support['score_ge_20']} | {hint_support['top_candidate_matches_selected_tool']} |"
        )
    lines.extend(
        [
            "",
            "## Misfire Audit",
            "",
            "- Artifact-only note: `task expectations are declared in the task YAML and checked against archived route/tool/doc outputs only`",
            "",
            "| mode | expected_tasks | observed_task_runs | expected_field_runs | field_match_rate | task_match_rate | route_match_rate | route_source_match_rate | tool_match_rate | top_doc_match_rate | reuse_match_rate |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        artifact_audit = summary[mode]["misfire_audit"]["artifact"]
        reuse_audit = summary[mode]["misfire_audit"]["reuse"]
        lines.append(
            f"| {mode} | {artifact_audit['task_count']} | {artifact_audit['observed_task_runs']} | "
            f"{artifact_audit['expected_field_runs']} | {artifact_audit['field_match_rate']:.2f} | "
            f"{artifact_audit['task_match_rate']:.2f} | "
            f"{_format_artifact_match_rate(artifact_audit['fields']['route'])} | "
            f"{_format_artifact_match_rate(artifact_audit['fields']['route_source'])} | "
            f"{_format_artifact_match_rate(artifact_audit['fields']['tool_name'])} | "
            f"{_format_artifact_match_rate(artifact_audit['fields']['top_doc_id'])} | "
            f"{float(reuse_audit['match_rate']):.2f} |"
        )
    for field_name in MISFIRE_FIELD_ORDER:
        lines.extend(["", f"### {MISFIRE_SECTION_TITLES[field_name]}", ""])
        for mode in available_modes:
            lines.append(f"#### {mode}")
            mismatches = _artifact_mismatch_rows(result, mode, field_name)
            if mismatches:
                for mismatch in mismatches:
                    expected_value = mismatch["expected"] or "<empty>"
                    actual_value = mismatch["actual"] or "<empty>"
                    lines.append(
                        f"- run={mismatch['run_index']:02d} task={mismatch['task_id']} "
                        f"expected={expected_value} actual={actual_value}"
                    )
            else:
                lines.append("- none")
            lines.append("")
    lines.extend(["### Reuse Misfire Summary", ""])
    for mode in available_modes:
        lines.append(f"#### {mode}")
        mismatches = _reuse_mismatch_rows(result, mode)
        if mismatches:
            for mismatch in mismatches:
                expected_value = mismatch["expected"] or "<empty>"
                actual_value = mismatch["actual"] or "<empty>"
                lines.append(
                    f"- run={mismatch['run_index']:02d} task={mismatch['task_id']} "
                    f"expected_reuse_mode={expected_value} actual_reuse_mode={actual_value}"
                )
        else:
            lines.append("- none")
        lines.append("")
    if len(available_modes) == 2:
        lines.extend(
            [
                "",
                "## Live Token Delta by Mode",
                "",
                f"- protocol minus text total tokens: {summary['protocol']['aggregate']['llm_total_tokens'] - summary['text']['aggregate']['llm_total_tokens']:.2f}",
            ]
        )
    lines.extend(
        [
            "",
            "## Message Type Breakdown",
            "",
            "| mode | message_type | count | protocol_bytes | text_bytes | delta |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for mode in available_modes:
        for row in summary[mode]["message_breakdown"]:
            lines.append(
                f"| {mode} | {row['message_type']} | {row['message_count']:.0f} | "
                f"{row['protocol_bytes']:.0f} | {row['text_bytes']:.0f} | {row['delta']:.0f} |"
            )
    lines.extend(["", "## Reuse Validation", ""])
    mismatch_rows: list[str] = []
    for mode in available_modes:
        lines.append(f"### {mode}")
        mode_mismatches = []
        for run in result["mode_runs"][mode]:
            for task_run in run["tasks"]:
                if not task_run["reuse_validation"]["matched_expectation"]:
                    mode_mismatches.append(
                        f"run={run['run_index']:02d} task={task_run['task_id']} "
                        f"expected_reuse_mode={task_run['reuse_validation']['expected_reuse_mode']} "
                        f"actual_reuse_mode={task_run['reuse_validation'].get('actual_reuse_mode', 'none')}"
                    )
        if mode_mismatches:
            mismatch_rows.extend(mode_mismatches)
            lines.extend(f"- {row}" for row in mode_mismatches)
        else:
            lines.append("- all reuse outcomes matched expectations")
        lines.append("")
    lines.extend(["", "## Memory Reuse Decisions By Mode", ""])
    for mode in available_modes:
        lines.append(f"### {mode}")
        reuse_rows = []
        for run in result["mode_runs"][mode]:
            for task_run in run["tasks"]:
                if task_run["reuse"]["applied"]:
                    reuse_rows.append(
                        f"run={run['run_index']:02d} task={task_run['task_id']} "
                        f"memory={task_run['reuse']['memory_id']} "
                        f"mode={task_run['reuse']['mode']}"
                    )
                elif task_run["reuse"].get("rejected_memory_id"):
                    reuse_rows.append(
                        f"run={run['run_index']:02d} task={task_run['task_id']} "
                        f"rejected_memory={task_run['reuse']['rejected_memory_id']}"
                    )
        if reuse_rows:
            lines.extend(f"- {row}" for row in reuse_rows)
        else:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Failure/Retry Summary", ""])
    lines.append("- none" if all(
        int(summary[m]["failure_count"]) == 0 for m in available_modes
    ) else "- see per-mode failure lists below")
    lines.append("")
    lines.extend(["## Protocol Compliance (Invariant Checks)", ""])
    invariant_data = result.get("invariant_checks", {})
    if invariant_data:
        total_checks = invariant_data.get("total_checks", 0)
        total_violations = invariant_data.get("total_violations", 0)
        lines.append(f"- Total invariant checks: {total_checks}")
        lines.append(f"- Total violations: {total_violations}")
        compliance = 100.0 if total_checks == 0 else 100.0 * (1.0 - total_violations / total_checks)
        lines.append(f"- Compliance rate: {compliance:.1f}%")
        for inv_name, inv_info in invariant_data.get("details", {}).items():
            lines.append(f"- {inv_name}: {inv_info['checks']} checks, {inv_info['violations']} violations")
    else:
        lines.append("- Total invariant checks: 0")
        lines.append("- Total violations: 0")
    lines.append("")
    failure_rows = []
    for mode in available_modes:
        for failure in summary[mode]["failures"]:
            failure_rows.append(f"{mode} run={failure['run_index']:02d} error={failure['error']}")
    if failure_rows:
        lines.extend(f"- {row}" for row in failure_rows)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _write_single_mode_csv(path: Path, mode_summary: dict[str, object], mode: str) -> None:
    control_key = _control_metric_key(mode)
    fieldnames = [
        "row_kind",
        "row_id",
        "mode",
        "message_count",
        "setup_control_bytes",
        "steady_state_control_bytes",
        "control_bytes",
        "state_bytes",
        "shared_memory_state_bytes",
        "mmap_state_bytes",
        "llm_total_tokens",
        "planner_total_tokens",
        "summarizer_total_tokens",
        "memory_query_count",
        "memory_hit_rate",
        "planned_step_count",
        "skipped_step_count",
        "reuse_gain",
        "reuse_apply_rate",
        "expectation_match_rate",
        "control_bytes_reduction_vs_cold",
        "llm_total_tokens_reduction_vs_cold",
        "task_ms_reduction_vs_cold",
        "planner_ms",
        "retrieve_ms",
        "execute_ms",
        "summarize_ms",
        "phase_overhead_ms",
        "task_ms",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for task in mode_summary["tasks"]:
            writer.writerow(
                {
                    "row_kind": "task",
                    "row_id": task["task_id"],
                    "mode": mode,
                    "message_count": round(float(task["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(task[control_key]), 4),
                    "control_bytes": round(float(task[control_key]), 4),
                    "state_bytes": round(float(task["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(task["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(task["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(task["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(task["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(task["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(task["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(task["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(task["planned_step_count"]), 4),
                    "skipped_step_count": round(float(task["skipped_step_count"]), 4),
                    "reuse_gain": round(float(task["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(task["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(task["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(task["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(task["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(task["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(task["planner_ms"]), 4),
                    "retrieve_ms": round(float(task["retrieve_ms"]), 4),
                    "execute_ms": round(float(task["execute_ms"]), 4),
                    "summarize_ms": round(float(task["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(task["phase_overhead_ms"]), 4),
                    "task_ms": round(float(task["task_ms"]), 4),
                }
            )
        for slice_summary in mode_summary.get("reuse_slices", []):
            writer.writerow(
                {
                    "row_kind": "reuse_slice",
                    "row_id": slice_summary["reuse_slice"],
                    "mode": mode,
                    "message_count": round(float(slice_summary["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(slice_summary[control_key]), 4),
                    "control_bytes": round(float(slice_summary[control_key]), 4),
                    "state_bytes": round(float(slice_summary["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(slice_summary["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(slice_summary["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(slice_summary["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(slice_summary["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(slice_summary["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(slice_summary["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(slice_summary["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(slice_summary["planned_step_count"]), 4),
                    "skipped_step_count": round(float(slice_summary["skipped_step_count"]), 4),
                    "reuse_gain": round(float(slice_summary["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(slice_summary["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(slice_summary["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(slice_summary["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(slice_summary["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(slice_summary["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(slice_summary["planner_ms"]), 4),
                    "retrieve_ms": round(float(slice_summary["retrieve_ms"]), 4),
                    "execute_ms": round(float(slice_summary["execute_ms"]), 4),
                    "summarize_ms": round(float(slice_summary["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(slice_summary["phase_overhead_ms"]), 4),
                    "task_ms": round(float(slice_summary["task_ms"]), 4),
                }
            )
        for axis_summary in mode_summary.get("reuse_axes", []):
            writer.writerow(
                {
                    "row_kind": "reuse_axis",
                    "row_id": axis_summary["reuse_axis"],
                    "mode": mode,
                    "message_count": round(float(axis_summary["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(axis_summary[control_key]), 4),
                    "control_bytes": round(float(axis_summary[control_key]), 4),
                    "state_bytes": round(float(axis_summary["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(axis_summary["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(axis_summary["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(axis_summary["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(axis_summary["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(axis_summary["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(axis_summary["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(axis_summary["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(axis_summary["planned_step_count"]), 4),
                    "skipped_step_count": round(float(axis_summary["skipped_step_count"]), 4),
                    "reuse_gain": round(float(axis_summary["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(axis_summary["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(axis_summary["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(axis_summary["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(axis_summary["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(axis_summary["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(axis_summary["planner_ms"]), 4),
                    "retrieve_ms": round(float(axis_summary["retrieve_ms"]), 4),
                    "execute_ms": round(float(axis_summary["execute_ms"]), 4),
                    "summarize_ms": round(float(axis_summary["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(axis_summary["phase_overhead_ms"]), 4),
                    "task_ms": round(float(axis_summary["task_ms"]), 4),
                }
            )
        for lane_summary in mode_summary.get("benchmark_lanes", []):
            writer.writerow(
                {
                    "row_kind": "benchmark_lane",
                    "row_id": lane_summary["benchmark_lane"],
                    "mode": mode,
                    "message_count": round(float(lane_summary["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(lane_summary[control_key]), 4),
                    "control_bytes": round(float(lane_summary[control_key]), 4),
                    "state_bytes": round(float(lane_summary["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(lane_summary["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(lane_summary["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(lane_summary["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(lane_summary["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(lane_summary["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(lane_summary["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(lane_summary["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(lane_summary["planned_step_count"]), 4),
                    "skipped_step_count": round(float(lane_summary["skipped_step_count"]), 4),
                    "reuse_gain": round(float(lane_summary["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(lane_summary["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(lane_summary["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(lane_summary["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(lane_summary["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(lane_summary["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(lane_summary["planner_ms"]), 4),
                    "retrieve_ms": round(float(lane_summary["retrieve_ms"]), 4),
                    "execute_ms": round(float(lane_summary["execute_ms"]), 4),
                    "summarize_ms": round(float(lane_summary["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(lane_summary["phase_overhead_ms"]), 4),
                    "task_ms": round(float(lane_summary["task_ms"]), 4),
                }
            )
        for transfer_summary in mode_summary.get("transfer_strategies", []):
            writer.writerow(
                {
                    "row_kind": "transfer_strategy",
                    "row_id": transfer_summary["transfer_strategy"],
                    "mode": mode,
                    "message_count": round(float(transfer_summary["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(transfer_summary[control_key]), 4),
                    "control_bytes": round(float(transfer_summary[control_key]), 4),
                    "state_bytes": round(float(transfer_summary["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(transfer_summary["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(transfer_summary["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(transfer_summary["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(transfer_summary["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(transfer_summary["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(transfer_summary["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(transfer_summary["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(transfer_summary["planned_step_count"]), 4),
                    "skipped_step_count": round(float(transfer_summary["skipped_step_count"]), 4),
                    "reuse_gain": round(float(transfer_summary["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(transfer_summary["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(transfer_summary["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(transfer_summary["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(transfer_summary["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(transfer_summary["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(transfer_summary["planner_ms"]), 4),
                    "retrieve_ms": round(float(transfer_summary["retrieve_ms"]), 4),
                    "execute_ms": round(float(transfer_summary["execute_ms"]), 4),
                    "summarize_ms": round(float(transfer_summary["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(transfer_summary["phase_overhead_ms"]), 4),
                    "task_ms": round(float(transfer_summary["task_ms"]), 4),
                }
            )
        for policy_summary in mode_summary.get("memory_policies", []):
            writer.writerow(
                {
                    "row_kind": "memory_policy",
                    "row_id": policy_summary["memory_policy"],
                    "mode": mode,
                    "message_count": round(float(policy_summary["message_count"]), 4),
                    "setup_control_bytes": 0.0,
                    "steady_state_control_bytes": round(float(policy_summary[control_key]), 4),
                    "control_bytes": round(float(policy_summary[control_key]), 4),
                    "state_bytes": round(float(policy_summary["state_bytes"]), 4),
                    "shared_memory_state_bytes": round(float(policy_summary["shared_memory_state_bytes"]), 4),
                    "mmap_state_bytes": round(float(policy_summary["mmap_state_bytes"]), 4),
                    "llm_total_tokens": round(float(policy_summary["llm_total_tokens"]), 4),
                    "planner_total_tokens": round(float(policy_summary["planner_total_tokens"]), 4),
                    "summarizer_total_tokens": round(float(policy_summary["summarizer_total_tokens"]), 4),
                    "memory_query_count": round(float(policy_summary["memory_query_count"]), 4),
                    "memory_hit_rate": round(float(policy_summary["memory_hit_rate"]), 4),
                    "planned_step_count": round(float(policy_summary["planned_step_count"]), 4),
                    "skipped_step_count": round(float(policy_summary["skipped_step_count"]), 4),
                    "reuse_gain": round(float(policy_summary["reuse_gain"]), 4),
                    "reuse_apply_rate": round(float(policy_summary["reuse_apply_rate"]), 4),
                    "expectation_match_rate": round(float(policy_summary["expectation_match_rate"]), 4),
                    "control_bytes_reduction_vs_cold": round(float(policy_summary["control_bytes_reduction_vs_cold"]), 4),
                    "llm_total_tokens_reduction_vs_cold": round(float(policy_summary["llm_total_tokens_reduction_vs_cold"]), 4),
                    "task_ms_reduction_vs_cold": round(float(policy_summary["task_ms_reduction_vs_cold"]), 4),
                    "planner_ms": round(float(policy_summary["planner_ms"]), 4),
                    "retrieve_ms": round(float(policy_summary["retrieve_ms"]), 4),
                    "execute_ms": round(float(policy_summary["execute_ms"]), 4),
                    "summarize_ms": round(float(policy_summary["summarize_ms"]), 4),
                    "phase_overhead_ms": round(float(policy_summary["phase_overhead_ms"]), 4),
                    "task_ms": round(float(policy_summary["task_ms"]), 4),
                }
            )
        aggregate = mode_summary["aggregate"]
        setup = mode_summary["setup"]
        writer.writerow(
            {
                "row_kind": "aggregate",
                "row_id": "__aggregate__",
                "mode": mode,
                "message_count": round(float(aggregate["message_count"]), 4),
                "setup_control_bytes": round(float(setup[control_key]), 4),
                "steady_state_control_bytes": round(float(aggregate[f"steady_state_{control_key}"]), 4),
                "control_bytes": round(float(aggregate[control_key]), 4),
                "state_bytes": round(float(aggregate["state_bytes"]), 4),
                "shared_memory_state_bytes": round(float(aggregate["shared_memory_state_bytes"]), 4),
                "mmap_state_bytes": round(float(aggregate["mmap_state_bytes"]), 4),
                "llm_total_tokens": round(float(aggregate["llm_total_tokens"]), 4),
                "planner_total_tokens": round(float(aggregate["planner_total_tokens"]), 4),
                "summarizer_total_tokens": round(float(aggregate["summarizer_total_tokens"]), 4),
                "memory_query_count": round(float(aggregate["memory_query_count"]), 4),
                "memory_hit_rate": round(float(aggregate["memory_hit_rate"]), 4),
                "planned_step_count": round(float(aggregate["planned_step_count"]), 4),
                "skipped_step_count": round(float(aggregate["skipped_step_count"]), 4),
                "reuse_gain": round(float(aggregate["reuse_gain"]), 4),
                "reuse_apply_rate": round(float(aggregate["reuse_apply_rate"]), 4),
                "expectation_match_rate": round(float(aggregate["expectation_match_rate"]), 4),
                "control_bytes_reduction_vs_cold": round(float(aggregate["control_bytes_reduction_vs_cold"]), 4),
                "llm_total_tokens_reduction_vs_cold": round(float(aggregate["llm_total_tokens_reduction_vs_cold"]), 4),
                "task_ms_reduction_vs_cold": round(float(aggregate["task_ms_reduction_vs_cold"]), 4),
                "planner_ms": round(float(aggregate["planner_ms"]), 4),
                "retrieve_ms": round(float(aggregate["retrieve_ms"]), 4),
                "execute_ms": round(float(aggregate["execute_ms"]), 4),
                "summarize_ms": round(float(aggregate["summarize_ms"]), 4),
                "phase_overhead_ms": round(float(aggregate["phase_overhead_ms"]), 4),
                "task_ms": round(float(aggregate["task_ms"]), 4),
            }
        )


def _default_out_dir() -> str:
    runs_dir = Path(os.getenv("STATEBUS_RUNS_DIR", str(Path.home() / "statebus" / "runs")))
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(runs_dir / f"benchmark_{stamp}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the StateBus benchmark.")
    parser.add_argument("--task-set", default=str(DEFAULT_TASK_SET))
    parser.add_argument("--modes", default="text,protocol")
    parser.add_argument("--repeat", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", default=None)
    parser.add_argument("--embedding-model", default=str(DEFAULT_EMBEDDING_MODEL_PATH))
    parser.add_argument("--llm-config", default=None)
    parser.add_argument("--llm-mode", choices=("deterministic", "api"), default=None)
    parser.add_argument("--llm-base-url", default=None)
    parser.add_argument("--planner-model", default=None)
    parser.add_argument("--summarizer-model", default=None)
    parser.add_argument("--statepool-backend", default=None)
    parser.add_argument("--embed-state-backend", default=None)
    parser.add_argument("--executor-transport", choices=("local", "uds"), default="local")
    parser.add_argument("--executor-socket-path", default=None)
    parser.add_argument("--engine", choices=("langgraph",), default="langgraph")
    parser.add_argument("--quiet-progress", action="store_true")
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    modes = tuple(part.strip() for part in args.modes.split(",") if part.strip())
    llm_config = LLMConfig.from_runtime(args.llm_config)
    if args.llm_mode is not None:
        llm_config = llm_config.with_mode(args.llm_mode)
    if args.llm_base_url is not None:
        for provider_name in llm_config.providers:
            llm_config = llm_config.with_provider_override(
                provider_name,
                base_url=args.llm_base_url,
            )
    if args.planner_model is not None:
        llm_config = llm_config.with_role_override("planner", model=args.planner_model)
    if args.summarizer_model is not None:
        llm_config = llm_config.with_role_override("summarizer", model=args.summarizer_model)
    statepool_config = StatePoolConfig.from_env(
        default_backend=args.statepool_backend,
        embedding_backend=args.embed_state_backend,
    )
    out_dir = args.out or _default_out_dir()
    asyncio.run(
        run_benchmark(
            task_set_path=args.task_set,
            modes=modes,
            repeat=args.repeat,
            seed=args.seed,
            out_dir=out_dir,
            embedder_model_path=args.embedding_model,
            llm_config=llm_config,
            statepool_config=statepool_config,
            executor_transport=args.executor_transport,
            executor_socket_path=args.executor_socket_path,
            engine=args.engine,
            progress_callback=None if args.quiet_progress else _progress_line,
        )
    )


if __name__ == "__main__":
    main()
