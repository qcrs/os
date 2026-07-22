#!/usr/bin/env python3
"""Static audit for the 2026-07-14 Qwen3 extended 16-stage matrix.

This script reads persisted artifacts and source text only.  It deliberately
does not import StateBus runtime modules or mutate the audited run.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
from typing import Any, Iterable, Sequence

import analyze_full_qwen3_extended_run as legacy


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN_ROOT = Path(
    "/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260714_135500"
)
REFERENCE_TAG = "v2-non-kv-baseline-20260710"
ROLES = ("planner", "retriever", "executor", "summarizer")
COMPARE_STAGES = ("02_compare_full", "12_compare_repeat_2", "13_compare_repeat_3")


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def host_path(value: Any, run_root: Path) -> Path:
    text = str(value or "")
    prefix = f"/statebus/runs/{run_root.name}"
    if text.startswith(prefix):
        return Path(str(run_root) + text[len(prefix) :])
    return Path(text)


def percentile(sorted_values: Sequence[float], quantile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def describe(values: Iterable[Any]) -> dict[str, Any]:
    parsed: list[float] = []
    missing = 0
    for value in values:
        if value is None:
            missing += 1
            continue
        try:
            parsed.append(float(value))
        except (TypeError, ValueError):
            missing += 1
    parsed.sort()
    if not parsed:
        return {
            "count": 0,
            "missing_count": missing,
            "sum": 0.0,
            "mean": None,
            "median": None,
            "p90": None,
            "p95": None,
            "stddev": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(parsed),
        "missing_count": missing,
        "sum": sum(parsed),
        "mean": statistics.fmean(parsed),
        "median": statistics.median(parsed),
        "p90": percentile(parsed, 0.90),
        "p95": percentile(parsed, 0.95),
        "stddev": statistics.pstdev(parsed),
        "min": parsed[0],
        "max": parsed[-1],
    }


def locate(path: str, pattern: str) -> dict[str, Any]:
    target = REPO_ROOT / path
    regex = re.compile(pattern)
    line = None
    if target.is_file():
        for index, text in enumerate(
            target.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if regex.search(text):
                line = index
                break
    return {"path": str(target), "line": line, "pattern": pattern}


def rendered_request_counts(workspace: Path) -> dict[str, int]:
    result = {role: 0 for role in ROLES}
    for role in ROLES:
        payload = load_json(
            workspace / "logs/rendered_llm_requests" / f"{role}.rendered_request.json",
            {},
        )
        requests = payload.get("requests", []) if isinstance(payload, dict) else []
        result[role] = len(requests) if isinstance(requests, list) else 0
    return result


def enrich_case_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        paths = row.get("artifact_paths", {})
        workspace = Path(str(paths.get("workspace", "")))
        metrics = load_json(Path(str(paths.get("task_metrics", ""))), {})
        handoff = load_json(Path(str(paths.get("planner_handoff", ""))), {})
        result = load_json(Path(str(paths.get("result", ""))), {})
        replay = load_json(Path(str(paths.get("replay_audit", ""))), {})
        if not isinstance(metrics, dict):
            metrics = {}
        if not isinstance(handoff, dict):
            handoff = {}
        if not isinstance(result, dict):
            result = {}
        if not isinstance(replay, dict):
            replay = {}
        semantic = handoff.get("semantic_plan_audit", {})
        if not isinstance(semantic, dict):
            semantic = {}
        request_counts = rendered_request_counts(workspace)
        row["planner_v2"] = {
            "objective_source": semantic.get("objective_source", "unavailable"),
            "semantic_plan_valid": semantic.get("semantic_plan_valid"),
            "semantic_equivalence": semantic.get("semantic_equivalence"),
            "behavioral_effect": semantic.get("behavioral_effect_before_consumption"),
            "validation_errors": semantic.get("validation_errors", []),
            "model_generated_field_count": semantic.get(
                "model_generated_field_count",
                metrics.get("planner_model_generated_field_count"),
            ),
            "fallback_field_count": semantic.get(
                "fallback_field_count", metrics.get("planner_fallback_field_count")
            ),
            "downstream_consumed_field_count": metrics.get(
                "planner_downstream_consumed_field_count"
            ),
            "model_downstream_consumed_field_count": metrics.get(
                "planner_model_downstream_consumed_field_count"
            ),
            "model_plan_hash": semantic.get("model_plan_hash"),
            "fallback_plan_hash": semantic.get("fallback_plan_hash"),
            "effective_plan_hash": semantic.get("effective_plan_hash"),
            "retriever_consumed_objective_hashes": handoff.get(
                "retriever_consumed_objective_hashes", {}
            ),
            "retriever_consumed_hash_match_count": metrics.get(
                "planner_retriever_consumed_hash_match_count"
            ),
        }
        row["vllm_prefix_observed"] = {
            "sampling_enabled": metrics.get("vllm_prefix_metrics_sample_enabled"),
            "delta_available": metrics.get("vllm_prefix_counter_delta_available"),
            "delta_valid": metrics.get("vllm_prefix_counter_delta_valid"),
            "hit_delta": metrics.get("vllm_prefix_observed_hit_delta"),
            "query_delta": metrics.get("vllm_prefix_observed_query_delta"),
            "reported_hit_rate": metrics.get("vllm_prefix_observed_hit_rate"),
            "service_lifetime_before": metrics.get(
                "vllm_prefix_service_lifetime_hit_rate_before"
            ),
            "service_lifetime_after": metrics.get(
                "vllm_prefix_service_lifetime_hit_rate_after"
            ),
        }
        row["rendered_request_counts"] = request_counts
        row["actual_rendered_request_count"] = sum(request_counts.values())
        row["restoration"] = {
            "restored_from_memory_id": result.get("restored_from_memory_id"),
            "restored_replay_class": result.get("restored_replay_class"),
            "answer_restoration_metric": metrics.get("answer_restoration_replay_count"),
            "artifact_reuse_metric": metrics.get("artifact_reuse_count"),
            "history_record_runtime_root": replay.get("history_record_runtime_root"),
        }


def group_planner(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    target_rows = [row for row in rows if row.get("phase") == "target"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in target_rows:
        groups[f"{row['stage']}|{row.get('layer', '')}|{row.get('registry_family', '')}"].append(row)

    def summarize(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
        sources = Counter(str(item["planner_v2"].get("objective_source")) for item in items)
        return {
            "case_count": len(items),
            "objective_source_distribution": dict(sorted(sources.items())),
            "semantic_plan_valid_count": sum(
                item["planner_v2"].get("semantic_plan_valid") is True for item in items
            ),
            "semantic_equivalence_count": sum(
                item["planner_v2"].get("semantic_equivalence") is True for item in items
            ),
            "behavioral_effect_count": sum(
                item["planner_v2"].get("behavioral_effect") is True for item in items
            ),
            "model_generated_field_count": sum(
                number(item["planner_v2"].get("model_generated_field_count")) for item in items
            ),
            "fallback_field_count": sum(
                number(item["planner_v2"].get("fallback_field_count")) for item in items
            ),
            "model_downstream_consumed_field_count": sum(
                number(item["planner_v2"].get("model_downstream_consumed_field_count"))
                for item in items
            ),
            "downstream_consumed_field_count": sum(
                number(item["planner_v2"].get("downstream_consumed_field_count"))
                for item in items
            ),
            "consumed_hash_match_count": sum(
                number(item["planner_v2"].get("retriever_consumed_hash_match_count"))
                for item in items
            ),
            "validation_error_case_count": sum(
                bool(item["planner_v2"].get("validation_errors")) for item in items
            ),
        }

    return {
        "target_case_count": len(target_rows),
        "summary": summarize(target_rows),
        "by_stage_layer_family": {
            key: summarize(items) for key, items in sorted(groups.items())
        },
        "fallback_cases": [
            {
                "stage": row["stage"],
                "layer": row.get("layer"),
                "task_id": row["task_id"],
                "source": row["planner_v2"].get("objective_source"),
                "validation_errors": row["planner_v2"].get("validation_errors"),
                "artifact": row["artifact_paths"]["planner_handoff"],
            }
            for row in target_rows
            if row["planner_v2"].get("objective_source") == "runtime_fallback"
        ],
        "interpretation": (
            "model data is counted as behaviorally effective only when the persisted semantic-plan audit "
            "and consumed-objective hashes close the model/fallback/effective/consumer chain"
        ),
    }


def prefix_case_audit(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    targets = [row for row in rows if row.get("phase") == "target"]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in targets:
        groups[f"{row['stage']}|{row.get('layer', '')}|{row.get('registry_family', '')}"].append(row)

    def summarize(items: Sequence[dict[str, Any]]) -> dict[str, Any]:
        hits = sum(number(item["vllm_prefix_observed"].get("hit_delta")) for item in items)
        queries = sum(number(item["vllm_prefix_observed"].get("query_delta")) for item in items)
        rates = [item["vllm_prefix_observed"].get("reported_hit_rate") for item in items]
        return {
            "case_count": len(items),
            "delta_available_count": sum(
                number(item["vllm_prefix_observed"].get("delta_available")) > 0 for item in items
            ),
            "delta_valid_count": sum(
                number(item["vllm_prefix_observed"].get("delta_valid")) > 0 for item in items
            ),
            "hit_delta_sum": hits,
            "query_delta_sum": queries,
            "recomputed_hit_rate": hits / queries if queries else None,
            "reported_per_case_rate_sum": sum(number(value) for value in rates),
            "reported_per_case_rate_mean": (
                statistics.fmean(number(value) for value in rates) if rates else None
            ),
        }

    by_group = {key: summarize(items) for key, items in sorted(groups.items())}
    aggregate_rate_bug_groups = [
        key
        for key, data in by_group.items()
        if data["reported_per_case_rate_sum"] > 1.0 and data["case_count"] > 1
    ]
    return {
        "overall": summarize(targets),
        "by_stage_layer_family": by_group,
        "aggregate_rate_bug_group_count": len(aggregate_rate_bug_groups),
        "aggregate_rate_bug_groups": aggregate_rate_bug_groups,
        "metric_defect": (
            "telemetry summaries sum per-case vllm_prefix_observed_hit_rate; use "
            "sum(hit_delta)/sum(query_delta) instead"
        ),
        "claim_boundary": (
            "observed counters are vLLM engine-local block query/hit deltas, not request hits, "
            "KV tensor export, or cross-engine transfer"
        ),
    }


def strip_restore_metadata(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    ignored = {"restored_from_memory_id", "restored_replay_class"}
    return {key: value for key, value in payload.items() if key not in ignored}


def replay_audit(rows: Sequence[dict[str, Any]], run_root: Path) -> dict[str, Any]:
    targets = [
        row
        for row in rows
        if row["stage"] == "03_replay_full" and row.get("phase") == "target"
    ]
    boot = {
        row["task_id"]: row
        for row in rows
        if row["stage"] == "03_replay_full" and row.get("phase") == "history_bootstrap"
    }
    cases = []
    for row in targets:
        source = boot.get(row["task_id"])
        target_output = load_json(Path(row["artifact_paths"]["result"]), {})
        source_output = (
            load_json(Path(source["artifact_paths"]["result"]), {}) if source is not None else {}
        )
        exact = row["memory_replay"].get("replay_class") == "exact_replay"
        normalized_output_equal = bool(
            source
            and strip_restore_metadata(target_output) == strip_restore_metadata(source_output)
        )
        cases.append(
            {
                "task_id": row["task_id"],
                "registry_family": row.get("registry_family"),
                "replay_class": row["memory_replay"].get("replay_class"),
                "quality_floor_pass": row["quality_floor_pass"],
                "role_calls": row["role_calls"],
                "recorded_llm_call_count": row["llm"]["call_count"],
                "rendered_request_counts": row["rendered_request_counts"],
                "actual_rendered_request_count": row["actual_rendered_request_count"],
                "llm_prompt_tokens": row["llm"]["prompt_tokens"],
                "llm_completion_tokens": row["llm"]["completion_tokens"],
                "skipped_step_count": row["memory_replay"].get("skipped_step_count"),
                "artifact_reuse_count": row["memory_replay"].get("artifact_reuse_count"),
                "answer_restoration_metric": row["restoration"].get(
                    "answer_restoration_metric"
                ),
                "restored_from_memory_id": row["restoration"].get(
                    "restored_from_memory_id"
                ),
                "bootstrap_present": source is not None,
                "target_output_equals_bootstrap_after_restore_metadata_removed": (
                    normalized_output_equal if exact else None
                ),
                "target_output_hash_verified": row["artifact_integrity"]["hash_matches"],
                "artifacts": {
                    "metrics": row["artifact_paths"]["task_metrics"],
                    "replay": row["artifact_paths"]["replay_audit"],
                    "target_output": row["artifact_paths"]["result"],
                    "bootstrap_output": (
                        source["artifact_paths"]["result"] if source is not None else None
                    ),
                },
            }
        )
    exact_cases = [item for item in cases if item["replay_class"] == "exact_replay"]
    validated_cases = [item for item in cases if item["replay_class"] == "validated_replay"]
    telemetry = load_json(run_root / "stages/03_replay_full/stdout.json", {}).get(
        "telemetry_summary", {}
    )
    return {
        "case_count": len(cases),
        "quality_pass_count": sum(item["quality_floor_pass"] for item in cases),
        "exact_replay_count": len(exact_cases),
        "validated_replay_count": len(validated_cases),
        "bootstrap_count": len(boot),
        "retriever_call_count": sum(number(item["role_calls"]["retriever"]) for item in cases),
        "expected_retriever_calls_from_replay_classes": len(validated_cases),
        "downstream_zero_call_exact_count": sum(
            all(number(item["role_calls"][role]) == 0 for role in ROLES[1:])
            for item in exact_cases
        ),
        "validated_all_four_roles_count": sum(
            all(number(item["role_calls"][role]) == 1 for role in ROLES)
            for item in validated_cases
        ),
        "skipped_step_count": sum(number(item["skipped_step_count"]) for item in cases),
        "expected_skipped_steps_from_classes": 2 * len(exact_cases) + len(validated_cases),
        "artifact_reuse_count": sum(number(item["artifact_reuse_count"]) for item in cases),
        "restored_marker_exact_count": sum(
            bool(item["restored_from_memory_id"]) for item in exact_cases
        ),
        "normalized_source_output_equal_exact_count": sum(
            item["target_output_equals_bootstrap_after_restore_metadata_removed"] is True
            for item in exact_cases
        ),
        "answer_restoration_metric_sum": sum(
            number(item["answer_restoration_metric"]) for item in cases
        ),
        "recorded_llm_call_count": sum(
            number(item["recorded_llm_call_count"]) for item in cases
        ),
        "actual_rendered_request_count": sum(
            number(item["actual_rendered_request_count"]) for item in cases
        ),
        "planner_rendered_request_count": sum(
            number(item["rendered_request_counts"]["planner"]) for item in cases
        ),
        "telemetry_summary": {
            key: telemetry.get(key)
            for key in (
                "planner_call_count",
                "retriever_call_count",
                "executor_call_count",
                "summarizer_call_count",
                "llm_call_count",
                "llm_prompt_tokens",
                "llm_completion_tokens",
                "llm_total_tokens",
                "validated_replay_count",
                "exact_replay_count",
                "artifact_reuse_count",
                "answer_restoration_replay_count",
                "skipped_step_count",
            )
        },
        "failure_classification": {
            "capability_failure": False,
            "stale_launcher_gate": True,
            "llm_call_metric_conflict": True,
            "answer_restoration_metric_false_negative": True,
            "reason": (
                "the launcher required 25 calls for every role although 15 exact replays "
                "correctly skipped Retriever/Executor/Summarizer; llm_call_count also zeros "
                "the still-executed Planner request on exact replay"
            ),
        },
        "cases": cases,
    }


def tagged_payload_from_artifact(path: Path) -> dict[str, Any]:
    artifact = load_json(path, {})
    requests = artifact.get("requests", []) if isinstance(artifact, dict) else []
    if not isinstance(requests, list) or not requests:
        return {}
    messages = requests[0].get("messages", []) if isinstance(requests[0], dict) else []
    prompt = (
        str(messages[-1].get("content", ""))
        if isinstance(messages, list) and messages and isinstance(messages[-1], dict)
        else ""
    )
    matches = re.findall(r"<sb-[^>]+>\s*(\{.*?\})\s*</sb-[^>]+>", prompt, flags=re.DOTALL)
    if not matches:
        return {}
    try:
        return json.loads(matches[-1])
    except json.JSONDecodeError:
        return {}


def genericity_audit(run_root: Path) -> dict[str, Any]:
    path = run_root / "stages/08_genericity_holdout/stdout.json"
    payload = load_json(path, {})
    taint = payload.get("prompt_taint_audit", {})
    violations = taint.get("violations", []) if isinstance(taint, dict) else []
    grouped = Counter(
        (
            str(item.get("kind")),
            str(item.get("role")),
            stable_json(item.get("detail")),
        )
        for item in violations
        if isinstance(item, dict)
    )
    sp_contracts = []
    for item in violations:
        if not isinstance(item, dict) or item.get("detail") != ["sp"]:
            continue
        artifact_path = host_path(item.get("path"), run_root)
        tagged = tagged_payload_from_artifact(artifact_path)
        sp = tagged.get("sp") if isinstance(tagged, dict) else None
        sp_contracts.append(sp)
    all_sp_contracts_valid = bool(sp_contracts) and all(
        isinstance(item, dict)
        and item.get("contract") in {"statebus-shared-prefix-v1", "statebus-shared-prefix-v2"}
        and item.get("contains") == "hydrated_evidence"
        and number(item.get("bytes")) > 0
        for item in sp_contracts
    )
    paraphrase = payload.get("paraphrase_semantic_equivalence", {})
    failed_paraphrases = [key for key, value in paraphrase.items() if value is not True]
    output_comparisons = {}
    stage_root = run_root / "stages/08_genericity_holdout"
    for task_id in payload.get("planner_facts", {}):
        primary = load_json(
            stage_root / "workspaces" / f"genericity-{task_id}" / "inputs/planner_handoff.json",
            {},
        )
        original = load_json(
            stage_root
            / "workspaces-planner-audit/original"
            / f"genericity-original-{task_id}"
            / "inputs/planner_handoff.json",
            {},
        )
        primary_audit = primary.get("semantic_plan_audit", {})
        original_audit = original.get("semantic_plan_audit", {})
        output_comparisons[task_id] = {
            "model_required_outputs_primary": primary_audit.get("model_plan", {}).get(
                "required_outputs", []
            ),
            "model_required_outputs_original": original_audit.get("model_plan", {}).get(
                "required_outputs", []
            ),
            "effective_required_outputs_primary": primary_audit.get("effective_plan", {}).get(
                "required_outputs", []
            ),
            "effective_required_outputs_original": original_audit.get("effective_plan", {}).get(
                "required_outputs", []
            ),
            "effective_required_outputs_equal": (
                primary_audit.get("effective_plan", {}).get("required_outputs", [])
                == original_audit.get("effective_plan", {}).get("required_outputs", [])
            ),
        }
    planner_ablation = payload.get("planner_ablation", {})
    primary_cases = payload.get("case_audit", [])
    return {
        "artifact": str(path),
        "recorded_ok": payload.get("ok"),
        "primary_case_count": len(primary_cases),
        "primary_quality_pass_count": sum(
            item.get("quality_floor_pass") is True for item in primary_cases
        ),
        "route_hints_disabled_count": sum(
            number(item.get("route_hints_enabled"), -1) == 0 for item in primary_cases
        ),
        "primary_plan_valid_count": sum(
            number(item.get("planner_semantic_plan_valid")) == 1 for item in primary_cases
        ),
        "primary_behavioral_effect_count": sum(
            number(item.get("planner_behavioral_effect")) == 1 for item in primary_cases
        ),
        "primary_consumed_hash_match_count": sum(
            number(item.get("planner_retriever_consumed_hash_match_count")) for item in primary_cases
        ),
        "cross_family_objective_differentiation_pass": payload.get(
            "cross_family_objective_differentiation_pass"
        ),
        "cross_family_semantic_signature_count": payload.get(
            "cross_family_semantic_signature_count"
        ),
        "planner_ablation": {
            mode: {
                key: value
                for key, value in audit.items()
                if key != "facts"
            }
            for mode, audit in planner_ablation.items()
            if isinstance(audit, dict)
        },
        "paraphrase_equivalence": paraphrase,
        "paraphrase_detail": payload.get("paraphrase_semantic_equivalence_details", {}),
        "failed_paraphrase_cases": failed_paraphrases,
        "required_output_comparisons": output_comparisons,
        "taint": {
            "scanned_task_count": taint.get("scanned_task_count"),
            "scanned_request_count": taint.get("scanned_request_count"),
            "role_request_counts": taint.get("role_request_counts"),
            "preferred_candidate_match_count": taint.get(
                "preferred_candidate_match_count"
            ),
            "no_hint_preferred_candidate_absent": taint.get(
                "no_hint_preferred_candidate_absent"
            ),
            "violation_count": len(violations),
            "groups": [
                {"kind": key[0], "role": key[1], "detail": json.loads(key[2]), "count": count}
                for key, count in sorted(grouped.items())
            ],
            "all_violations_are_shared_prefix_sp_allowlist_misses": (
                bool(violations)
                and all(
                    item.get("kind") == "unexpected_role_payload_keys"
                    and item.get("detail") == ["sp"]
                    for item in violations
                    if isinstance(item, dict)
                )
                and all_sp_contracts_valid
            ),
            "verified_shared_prefix_sp_contract_count": len(sp_contracts),
            "classification": (
                "scanner false positives: sp carries shared-prefix contract/byte metadata, "
                "not expected answer, route, tool, or preferred candidate data"
            ),
        },
        "failure_classification": {
            "taint_gate_defect": True,
            "paraphrase_model_instability": bool(failed_paraphrases),
            "runtime_capability_failure": False,
            "quality_or_route_failure": False,
            "details": (
                "48 repeated taint violations are a stale allowlist; formal-agg-004 also has a real "
                "model-plan required_outputs drift, but Runtime fallback restores the complete effective contract"
            ),
        },
        "claim_boundary": payload.get("claim_boundary"),
    }


def compare_report(run_root: Path, stage: str, repeat_index: int) -> dict[str, Any]:
    stdout_path = run_root / "stages" / stage / "stdout.json"
    stdout = load_json(stdout_path, {})
    mode_reports = stdout.get("mode_reports", []) if isinstance(stdout, dict) else []
    detail_path = (
        host_path(mode_reports[0].get("report_path"), run_root)
        if mode_reports and isinstance(mode_reports[0], dict)
        else Path()
    )
    detail = load_json(detail_path, {})
    statebus_cases = detail.get("statebus_report", {}).get("cases", [])
    external_cases = detail.get("external_report", {}).get("cases", [])
    statebus_by_id = {item.get("task_id"): item for item in statebus_cases}
    external_by_id = {item.get("task_id"): item for item in external_cases}
    cases = []
    for task_id in sorted(set(statebus_by_id) & set(external_by_id)):
        sb = statebus_by_id[task_id]
        ext = external_by_id[task_id]
        sbm = sb.get("metrics", {})
        exm = ext.get("metrics", {})
        sb_prompt = number(sbm.get("llm_prompt_tokens", sbm.get("prompt_tokens")))
        ext_prompt = number(exm.get("prompt_tokens"))
        sb_total = number(sbm.get("llm_total_tokens"))
        ext_total = number(exm.get("llm_total_tokens"))
        sb_ms = number(sbm.get("task_ms"))
        ext_ms = number(exm.get("task_ms"))
        cases.append(
            {
                "stage": stage,
                "repeat_index": repeat_index,
                "task_id": task_id,
                "task_family": sb.get("task_family"),
                "statebus_quality": sb.get("quality_floor", {}).get("quality_floor_pass"),
                "external_quality": ext.get("quality_floor", {}).get("quality_floor_pass"),
                "statebus_prompt_tokens": sb_prompt,
                "external_prompt_tokens": ext_prompt,
                "prompt_token_delta": sb_prompt - ext_prompt,
                "statebus_total_tokens": sb_total,
                "external_total_tokens": ext_total,
                "total_token_delta": sb_total - ext_total,
                "statebus_task_ms": sb_ms,
                "external_task_ms": ext_ms,
                "task_ms_delta": sb_ms - ext_ms,
                "external_fairness_pass": ext.get("audit_summary", {})
                .get("external_fairness_gate", {})
                .get("pass_hard_gate"),
            }
        )
    fairness = detail.get("fairness_manifest", {})
    summary = stdout.get("comparison_summary", {})
    return {
        "stage": stage,
        "repeat_index": repeat_index,
        "stdout_artifact": str(stdout_path),
        "detail_artifact": str(detail_path),
        "comparison_valid": detail.get("comparison_valid"),
        "invalid_reason": detail.get("invalid_reason"),
        "timing_execution_contract": stdout.get("timing_execution_contract"),
        "case_count": len(cases),
        "family_count": len({item["task_family"] for item in cases}),
        "statebus_quality_pass_count": sum(item["statebus_quality"] is True for item in cases),
        "external_quality_pass_count": sum(item["external_quality"] is True for item in cases),
        "external_fairness_pass_count": sum(
            item["external_fairness_pass"] is True for item in cases
        ),
        "statebus_prompt_tokens": sum(item["statebus_prompt_tokens"] for item in cases),
        "external_prompt_tokens": sum(item["external_prompt_tokens"] for item in cases),
        "prompt_tokens_delta": sum(item["prompt_token_delta"] for item in cases),
        "statebus_total_tokens": sum(item["statebus_total_tokens"] for item in cases),
        "external_total_tokens": sum(item["external_total_tokens"] for item in cases),
        "total_tokens_delta": sum(item["total_token_delta"] for item in cases),
        "statebus_lower_prompt_case_count": sum(item["prompt_token_delta"] < 0 for item in cases),
        "statebus_lower_total_case_count": sum(item["total_token_delta"] < 0 for item in cases),
        "statebus_faster_case_count": sum(item["task_ms_delta"] < 0 for item in cases),
        "statebus_task_ms": describe(item["statebus_task_ms"] for item in cases),
        "external_task_ms": describe(item["external_task_ms"] for item in cases),
        "task_ms_delta": describe(item["task_ms_delta"] for item in cases),
        "summary_deltas": {
            key: summary.get(key)
            for key in (
                "local_vllm_prompt_tokens_delta",
                "local_vllm_completion_tokens_delta",
                "local_vllm_llm_total_tokens_delta",
                "local_vllm_task_ms_delta",
                "local_vllm_llm_ms_delta",
            )
        },
        "fairness_manifest": {
            key: fairness.get(key)
            for key in (
                "pass_hard_gate",
                "same_history_policy",
                "same_quality_floor_contract",
                "same_role_graph",
                "same_scoring_contract",
                "same_task_family",
                "same_tier",
                "no_external_contamination",
                "external_uses_internal_helpers",
            )
        },
        "schema_and_execution_limit": (
            "same task/model/role-count/scorer and external fairness hard gate pass, but prompts, "
            "Planner selection schemas, evidence exposure, and execution implementations are not carrier-identical"
        ),
        "cases": cases,
    }


def compare_repeats(run_root: Path) -> dict[str, Any]:
    reports = [
        compare_report(run_root, stage, index)
        for index, stage in enumerate(COMPARE_STAGES, start=1)
    ]
    latency_summary = load_json(run_root / "latency_repeat_summary.json", {})
    return {
        "repeat_count": len(reports),
        "all_valid": all(item["comparison_valid"] is True for item in reports),
        "all_statebus_first": all(
            item["timing_execution_contract"]
            == "serialized_statebus_then_external_within_each_mode_v1"
            for item in reports
        ),
        "token_delta": describe(item["total_tokens_delta"] for item in reports),
        "prompt_token_delta": describe(item["prompt_tokens_delta"] for item in reports),
        "task_ms_delta": describe(item["task_ms_delta"]["sum"] for item in reports),
        "latency_summary_artifact": str(run_root / "latency_repeat_summary.json"),
        "latency_summary": latency_summary,
        "interpretation": (
            "token savings are repeat-stable; latency is unfavorable in all repeats and highly variable. "
            "Fixed StateBus-first ordering does not control order effects"
        ),
        "reports": reports,
        "all_case_rows": [case for report in reports for case in report["cases"]],
    }


def layer_summary(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for layer in payload.get("layers", []):
        metrics = layer.get("telemetry_summary", {})
        aggregate = layer.get("aggregated_metrics", {})
        hits = number(metrics.get("vllm_prefix_observed_hit_delta"))
        queries = number(metrics.get("vllm_prefix_observed_query_delta"))
        result.append(
            {
                "layer": layer.get("layer"),
                "profile": layer.get("profile"),
                "case_count": int(number(aggregate.get("case_count"))),
                "quality_pass_count": int(number(aggregate.get("quality_floor_pass_count"))),
                "prompt_tokens": number(metrics.get("llm_prompt_tokens")),
                "completion_tokens": number(metrics.get("llm_completion_tokens")),
                "total_tokens": number(metrics.get("llm_total_tokens")),
                "task_ms": number(metrics.get("task_ms")),
                "llm_wall_ms": number(metrics.get("llm_wall_ms")),
                "control_bytes": number(metrics.get("control_bytes")),
                "selected_evidence_bytes": number(metrics.get("selected_evidence_bytes")),
                "semantic_state_transfer_count": number(
                    metrics.get("semantic_state_transfer_count")
                ),
                "shared_memory_publish_count": number(metrics.get("shared_memory_publish_count")),
                "memory_match_count": number(metrics.get("memory_match_count")),
                "artifact_reuse_count": number(metrics.get("artifact_reuse_count")),
                "history_artifact_reuse_count": number(
                    metrics.get("history_artifact_reuse_count")
                ),
                "history_strategy_reuse_count": number(
                    metrics.get("history_strategy_reuse_count")
                ),
                "history_step_reduction_count": number(
                    metrics.get("history_step_reduction_count")
                ),
                "validated_replay_count": number(metrics.get("validated_replay_count")),
                "exact_replay_count": number(metrics.get("exact_replay_count")),
                "skipped_step_count": number(metrics.get("skipped_step_count")),
                "reuse_gain": number(metrics.get("reuse_gain")),
                "role_calls": {
                    role: number(metrics.get(f"{role}_call_count")) for role in ROLES
                },
                "planner_behavioral_effect_count": number(
                    metrics.get("planner_behavioral_effect")
                ),
                "planner_runtime_fallback_count": number(
                    metrics.get("planner_objective_source_runtime_fallback")
                ),
                "planner_consumed_hash_match_count": number(
                    metrics.get("planner_retriever_consumed_hash_match_count")
                ),
                "prefix_observed_hit_delta": hits,
                "prefix_observed_query_delta": queries,
                "prefix_observed_recomputed_hit_rate": hits / queries if queries else None,
                "prefix_observed_reported_rate_sum": metrics.get(
                    "vllm_prefix_observed_hit_rate"
                ),
                "logit_state_transfer_count": number(
                    metrics.get("logit_state_transfer_count")
                ),
                "sandbox_bwrap_count": number(metrics.get("codeact_sandbox_bwrap_count")),
                "sandbox_fallback_count": number(
                    metrics.get("codeact_sandbox_fallback_count")
                ),
            }
        )
    return result


def formal_audit(run_root: Path, stage: str) -> dict[str, Any]:
    path = run_root / "stages" / stage / "stdout.json"
    payload = load_json(path, {})
    layers = layer_summary(payload)
    by_name = {item["layer"]: item for item in layers}
    l0 = by_name.get("L0", {})
    l3 = by_name.get("L3", {})
    return {
        "artifact": str(path),
        "transport": payload.get("transport"),
        "case_count": payload.get("selected_case_count"),
        "family_count": payload.get("family_count"),
        "families": payload.get("families", []),
        "layers": layers,
        "l3_minus_l0": {
            field: number(l3.get(field)) - number(l0.get(field))
            for field in ("prompt_tokens", "total_tokens", "task_ms", "control_bytes")
        },
        "ablation_limit": (
            "L0->L1 changes text vs typed control; L1->L2 enables semantic pruning and semantic-state "
            "transport together; formal L2->L3 has no history, so it does not measure replay"
        ),
    }


def continuous_audit(run_root: Path, stage: str) -> dict[str, Any]:
    path = run_root / "stages" / stage / "stdout.json"
    payload = load_json(path, {})
    layers = layer_summary(payload)
    return {
        "artifact": str(path),
        "round_count": payload.get("selected_round_count"),
        "available_round_count": payload.get("available_round_count"),
        "layers": layers,
        "waterfall_metrics": payload.get("waterfall_metrics", {}),
        "history_ablation_warning": (
            "all layers can observe history roots/matches in the current runner; L0-L2 suppress replay "
            "metrics, so only L3 reuse should be used for replay claims"
        ),
    }


def prefix_probe_audit(run_root: Path) -> dict[str, Any]:
    probes = {}
    for stage in ("09_prefix_shared", "10_prefix_independent"):
        path = run_root / "stages" / stage / "stdout.json"
        payload = load_json(path, {})
        requests = payload.get("requests", [])
        probes[stage] = {
            "artifact": str(path),
            "mode": payload.get("mode"),
            "run_salt": payload.get("run_salt"),
            "evidence_file": payload.get("evidence_file"),
            "evidence_bytes": payload.get("evidence_bytes"),
            "roles": payload.get("roles"),
            "summary": payload.get("summary"),
            "request_count": len(requests),
            "completion_json_valid_count_recomputed": sum(
                item.get("completion_json_valid") is True for item in requests
            ),
            "completion_contract_valid_count_recomputed": sum(
                item.get("completion_contract_valid") is True for item in requests
            ),
            "request_rows": [
                {
                    "index": item.get("index"),
                    "role": item.get("role"),
                    "ok": item.get("ok"),
                    "completion_json_valid": item.get("completion_json_valid"),
                    "completion_contract_valid": item.get("completion_contract_valid"),
                    "latency_ms": item.get("latency_ms"),
                    "ttft_ms": item.get("ttft_ms"),
                    "prompt_bytes": item.get("prompt", {}).get("bytes"),
                    "prefix_counter_delta": item.get("prefix_counter_delta"),
                }
                for item in requests
            ],
        }
    shared = probes["09_prefix_shared"]
    independent = probes["10_prefix_independent"]
    return {
        "stages": probes,
        "same_evidence_file": shared["evidence_file"] == independent["evidence_file"],
        "evidence_byte_delta": number(shared["evidence_bytes"]) - number(
            independent["evidence_bytes"]
        ),
        "shared_minus_independent_mean_ttft_ms": number(
            shared["summary"].get("mean_ttft_ms")
        )
        - number(independent["summary"].get("mean_ttft_ms")),
        "shared_minus_independent_warm_ttft_ms": number(
            shared["summary"].get("warm_candidate_mean_ttft_ms")
        )
        - number(independent["summary"].get("warm_candidate_mean_ttft_ms")),
        "quality_contract_equivalent": (
            shared["completion_contract_valid_count_recomputed"]
            == independent["completion_contract_valid_count_recomputed"]
            == shared["request_count"]
        ),
        "order_control": "shared stage ran before independent stage; no alternation in this matrix",
        "claim_boundary": (
            "the counter deltas prove engine-local prefix reuse in this probe. One shared-first pair, "
            "different completion validity, and slightly different prompt bytes prevent a stable causal E2E claim"
        ),
    }


def carrier_audit(run_root: Path) -> dict[str, Any]:
    stdout_path = run_root / "stages/11_carrier_compare_full/stdout.json"
    stdout = load_json(stdout_path, {})
    mode = stdout.get("mode_reports", [{}])[0]
    detail_path = host_path(mode.get("report_path"), run_root)
    detail = load_json(detail_path, {})
    text = detail.get("external_report", {})
    structured = detail.get("statebus_report", {})

    def lane(report: dict[str, Any]) -> dict[str, Any]:
        metrics = report.get("telemetry_summary", {})
        aggregate = report.get("aggregated_metrics", {})
        return {
            "metadata": report.get("metadata", {}),
            "case_count": aggregate.get("case_count"),
            "quality_pass_count": aggregate.get("quality_floor_pass_count"),
            "prompt_tokens": metrics.get("llm_prompt_tokens"),
            "completion_tokens": metrics.get("llm_completion_tokens"),
            "total_tokens": metrics.get("llm_total_tokens"),
            "task_ms": metrics.get("task_ms"),
            "control_bytes": metrics.get("control_bytes"),
            "prompt_visible_total_bytes": metrics.get("prompt_visible_total_bytes"),
            "raw_evidence_bytes_seen_by_llm": metrics.get("raw_evidence_bytes_seen_by_llm"),
        }

    return {
        "stdout_artifact": str(stdout_path),
        "detail_artifact": str(detail_path),
        "comparison_valid": detail.get("comparison_valid"),
        "text": lane(text),
        "structured": lane(structured),
        "comparison_summary": detail.get("comparison_summary", {}),
        "fairness_manifest": detail.get("fairness_manifest", {}),
        "interpretation": (
            "this is an internal same-mainline L0 text vs L1 typed-control comparison, not the external "
            "baseline and not a UDS/shared-memory carrier isolation. Equal quality and visible evidence "
            "support control-byte attribution; total tokens increase by 1,213"
        ),
    }


def stage_matrix(base: dict[str, Any], run_root: Path) -> list[dict[str, Any]]:
    scope = {item["stage"]: item for item in base["stage_scope"]}
    purposes = {
        "00_preflight": "environment/service/config readiness",
        "01_pytest_v2": "v2 regression tests",
        "02_compare_full": "StateBus vs external text system compare",
        "03_replay_full": "formal replay bootstrap and target",
        "04_continuous_csv_full": "10-round CSV continuous family",
        "05_continuous_cross_full": "10-round cross-period family",
        "06_formal_full": "25-case 5-family L0-L3 formal",
        "07_formal_subprocess_uds_full": "formal subprocess UDS path",
        "08_genericity_holdout": "no-hint Planner ablation/paraphrase/taint",
        "09_prefix_shared": "shared evidence prefix probe",
        "10_prefix_independent": "independent prefix control",
        "11_carrier_compare_full": "internal L0 text vs L1 typed carrier",
        "12_compare_repeat_2": "serialized external compare repeat 2",
        "13_compare_repeat_3": "serialized external compare repeat 3",
        "14_latency_repeat_aggregate": "three-repeat latency aggregation",
        "15_tag_baseline_audit": "read-only implementation/tag comparison",
    }
    strongest = {
        "00_preflight": "configured model, embedding dependency/model/device were ready",
        "01_pytest_v2": "308 v2 tests passed in the captured container environment",
        "02_compare_full": "equal-quality 25-case system compare with repeat-stable token savings",
        "03_replay_full": "15 exact and 10 validated replay cases all passed quality",
        "04_continuous_csv_full": "10 rounds completed; L3 reused artifacts/strategy but did not skip runtime steps",
        "05_continuous_cross_full": "10 rounds completed; L3 had 4 validated replays and 4 skipped steps",
        "06_formal_full": "25 cases x 4 layers passed quality; semantic/pruning path executed",
        "07_formal_subprocess_uds_full": "25 cases x 4 layers passed through subprocess transport",
        "08_genericity_holdout": "primary and ablations passed quality; Planner objectives were consumed",
        "09_prefix_shared": "shared-prefix requests produced non-zero engine-local block hits",
        "10_prefix_independent": "salted independent requests produced zero engine-local block hits",
        "11_carrier_compare_full": "typed control reduced control bytes at equal quality in the same mainline",
        "12_compare_repeat_2": "second equal-quality token result",
        "13_compare_repeat_3": "third equal-quality token result",
        "14_latency_repeat_aggregate": "all three compares valid; latency was unfavorable in all three",
        "15_tag_baseline_audit": "selected working-tree implementation differences from the tag were recorded",
    }
    limits = {
        "00_preflight": "no end-to-end task capability",
        "01_pytest_v2": "warnings remain and tests are not live performance evidence",
        "02_compare_full": "system-level comparison only; no carrier-only causal attribution",
        "03_replay_full": "launcher gate and llm/answer-restoration metrics are defective",
        "04_continuous_csv_full": "artifact references do not by themselves prove skipped Agent/tool work",
        "05_continuous_cross_full": "validated replay still executes all four roles",
        "06_formal_full": "L0-L3 are not all single-variable ablations",
        "07_formal_subprocess_uds_full": "repeat=1 and weak PID/socket lifecycle telemetry",
        "08_genericity_holdout": "precompiled CanonicalTaskSpec, not free-text spec compilation",
        "09_prefix_shared": "single shared-first probe; not StateBus E2E acceleration",
        "10_prefix_independent": "0/5 completion contracts valid, so output-quality parity is absent",
        "11_carrier_compare_full": "not external text and not a transport-only UDS/shared-memory comparison",
        "12_compare_repeat_2": "fixed StateBus-first order and slower StateBus latency",
        "13_compare_repeat_3": "fixed StateBus-first order and slower StateBus latency",
        "14_latency_repeat_aggregate": "does not establish latency superiority",
        "15_tag_baseline_audit": "static source comparison, not a rerun of the tag",
    }
    rows = []
    for stage in legacy.EXPECTED_STAGE_IDS:
        item = dict(scope.get(stage, {"stage": stage}))
        item["purpose"] = purposes[stage]
        item["strongest_supported_claim"] = strongest[stage]
        item["does_not_prove"] = limits[stage]
        rows.append(item)
    return rows


def code_evidence() -> dict[str, Any]:
    return {
        "replay_gate_all_roles": locate(
            "scripts/run_v2_full_qwen3_container.sh", r"require_role_calls\(payload, selected\)"
        ),
        "exact_replay_llm_call_metric": locate(
            "v2/runtime/smoke.py", r'"llm_call_count": 0\.0 if replay_restore_enabled'
        ),
        "answer_restoration_hardcoded_zero": locate(
            "v2/runtime/driver.py", r'"answer_restoration_replay_count": 0\.0'
        ),
        "exact_replay_output_restore": locate(
            "v2/runtime/smoke.py", r"output_payload = json\.loads\(history_record\.output_path"
        ),
        "shared_prefix_sp_payload": locate(
            "v2/runtime/role_path.py", r'suffix_payload\["sp"\]'
        ),
        "genericity_role_allowlist": locate(
            "scripts/run_v2_genericity_holdout.py", r"^ROLE_REQUEST_POLICY ="
        ),
        "genericity_pass_gate": locate(
            "scripts/run_v2_genericity_holdout.py", r"passed = bool\(case_audit\)"
        ),
        "paraphrase_comparator": locate(
            "v2/runtime/semantic_plan.py", r"^def compare_semantic_task_plans"
        ),
        "semantic_plan_merge": locate(
            "v2/runtime/semantic_plan.py", r"^def _merge_model_with_fallback"
        ),
        "retriever_consumed_objective_hash": locate(
            "v2/retrieval/pipeline.py", r"consumed_objective_hash"
        ),
        "subprocess_popen": locate("v2/control/transport.py", r"subprocess\.Popen"),
        "uds_af_unix": locate("v2/control/transport.py", r"socket\.AF_UNIX"),
        "prefix_counter_delta": locate(
            "v2/runtime/vllm_metrics.py", r"^def compute_prefix_cache_delta"
        ),
        "logit_peak_scan": locate("v2/runtime/logit_state.py", r"peak_position"),
        "precompiled_spec": locate(
            "v2/runtime/smoke.py", r"precompiled_canonical_task_spec=canonical_task_spec"
        ),
        "location_warning": "line numbers describe the current dirty working tree",
    }


def issue_ledger(run_root: Path) -> list[dict[str, Any]]:
    base = str(run_root)
    return [
        {
            "priority": "P0",
            "issue": "Stage 03 launcher gate rejects correct exact-replay downstream call reduction",
            "impact": "false full-matrix failure and misleading replay conclusion",
            "artifact": f"{base}/stages/03_replay_full/stdout.json",
            "code": "scripts/run_v2_full_qwen3_container.sh",
            "minimum_fix": "expect Planner=selected and downstream=selected-exact_replay_count",
            "minimum_test": "targeted replay stage plus exact/validated mixed unit gate test",
        },
        {
            "priority": "P0",
            "issue": "exact replay records llm_call_count=0 although Planner request/tokens exist",
            "impact": "overstates LLM call reduction by 15 calls in Stage 03",
            "artifact": f"{base}/stages/03_replay_full/workspaces/L3/benchmark-sample-1/logs/task_metrics.json",
            "code": "v2/runtime/smoke.py",
            "minimum_fix": "derive llm_call_count from per-role rendered requests or count Planner on exact replay",
            "minimum_test": "exact replay asserts llm_call_count=planner_call_count=1 and three downstream calls=0",
        },
        {
            "priority": "P0",
            "issue": "Stage 08 taint allowlist rejects legitimate shared-prefix sp metadata 48 times",
            "impact": "false genericity failure hides the independent paraphrase signal",
            "artifact": f"{base}/stages/08_genericity_holdout/stdout.json",
            "code": "scripts/run_v2_genericity_holdout.py; v2/runtime/role_path.py",
            "minimum_fix": "allow and validate the bounded sp contract for downstream roles",
            "minimum_test": "taint test accepts only sp={contract,contains,bytes} and still rejects pc/rh/oracles",
        },
        {
            "priority": "P0",
            "issue": "vllm_prefix_observed_hit_rate is summed across cases and exceeds 1 in summaries",
            "impact": "formal prefix-rate fields are mathematically invalid",
            "artifact": f"{base}/stages/06_formal_full/stdout.json",
            "code": "v2 benchmark metric aggregation",
            "minimum_fix": "aggregate numerator and denominator, then compute one ratio",
            "minimum_test": "multi-case aggregate rate equals sum(hits)/sum(queries) and remains within [0,1]",
        },
        {
            "priority": "P1",
            "issue": "formal-agg-004 paraphrase model plan drops one required output",
            "impact": "Planner paraphrase stability is not 4/4 even though Runtime fallback preserves quality",
            "artifact": f"{base}/stages/08_genericity_holdout/stdout.json",
            "code": "v2/runtime/semantic_plan.py",
            "minimum_fix": "separate model-plan stability diagnostic from effective-contract safety gate",
            "minimum_test": "repeat paraphrases and report model/effective equivalence separately",
        },
        {
            "priority": "P1",
            "issue": "independent prefix probe passes with 0/5 valid JSON/output contracts",
            "impact": "Stage 09/10 quality equivalence is absent; TTFT remains diagnostic only",
            "artifact": f"{base}/stages/10_prefix_independent/stdout.json",
            "code": "scripts/probe_local_vllm_prefix_alignment.py; full-suite prefix gate",
            "minimum_fix": "require equivalent completion contract validity or use a response-independent probe contract",
            "minimum_test": "alternating shared/independent pairs with 100% contract validity",
        },
        {
            "priority": "P1",
            "issue": "three external compares always run StateBus first and StateBus is slower in all repeats",
            "impact": "token claim is strong, latency superiority is disproven for this run",
            "artifact": f"{base}/latency_repeat_summary.json",
            "code": "v2/benchmark/comparator_runner.py",
            "minimum_fix": "retain no-latency-claim boundary and alternate lane order in future timing runs",
            "minimum_test": "serialized AB/BA repeats with median/p90/p95",
        },
        {
            "priority": "P1",
            "issue": "answer_restoration_replay_count is hardcoded zero for verified exact restoration",
            "impact": "false-negative observability conflicts with artifact_reuse_count and restored markers",
            "artifact": f"{base}/stages/03_replay_full/stdout.json",
            "code": "v2/runtime/driver.py",
            "minimum_fix": "set from exact restore execution and verified output restoration",
            "minimum_test": "restored marker/source equality/metric count agree",
        },
        {
            "priority": "P1",
            "issue": "formal CodeAct uses resource fallback rather than bwrap in all audited cases",
            "impact": "cannot claim strong sandbox isolation",
            "artifact": f"{base}/stages/06_formal_full/stdout.json",
            "code": "v2/runtime/codeact.py",
            "minimum_fix": "keep bounded-execution wording; validate stronger sandbox only in delivery environment",
            "minimum_test": "sandbox capability probe plus negative filesystem/network tests",
        },
        {
            "priority": "P2",
            "issue": "vllm_health.json is empty while preflight succeeded through a separate path",
            "impact": "one inventory parse error and incomplete health provenance",
            "artifact": f"{base}/vllm_health.json",
            "code": "scripts/run_v2_full_qwen3_container.sh",
            "minimum_fix": "persist the health response or remove the empty placeholder",
            "minimum_test": "artifact parser reports zero JSON failures",
        },
        {
            "priority": "P2",
            "issue": "generated protobuf descriptors emit 100 deprecation warnings",
            "impact": "does not invalidate 308 passing tests but adds delivery noise and future compatibility risk",
            "artifact": f"{base}/logs/01_pytest_v2.log",
            "code": "protocol/statebus_pb2.py",
            "minimum_fix": "regenerate with the pinned supported protoc/runtime pair",
            "minimum_test": "pytest warning audit",
        },
    ]


def claim_ledger(run_root: Path) -> dict[str, Any]:
    base = str(run_root)
    return {
        "latest_experiment_proves": [
            {
                "claim": "16 planned stages all recorded; 14 passed and 2 failed",
                "artifact": f"{base}/summary.json",
            },
            {
                "claim": "three equal-quality 25-case external comparisons show stable token savings",
                "artifact": f"{base}/latency_repeat_summary.json",
            },
            {
                "claim": "exact replay restores verified outputs and skips three downstream role requests",
                "artifact": f"{base}/stages/03_replay_full/stdout.json",
            },
            {
                "claim": "bounded Planner fields are consumed by four objective paths and can change them",
                "artifact": f"{base}/stages/08_genericity_holdout/stdout.json",
            },
            {
                "claim": "shared-prefix probe has engine-local block hits while independent probe has none",
                "artifact": f"{base}/stages/09_prefix_shared/stdout.json",
            },
            {
                "claim": "formal loopback and subprocess runs each pass 25 cases across L0-L3",
                "artifact": f"{base}/stages/07_formal_subprocess_uds_full/stdout.json",
            },
        ],
        "code_supported_but_not_fully_experimentally_isolated": [
            "subprocess.Popen + AF_UNIX + typed Protobuf lifecycle overhead",
            "semantic-state causal benefit separate from pruning",
            "LogitState decision-policy benefit",
            "strong CodeAct sandbox isolation",
            "openEuler final delivery compatibility",
        ],
        "proxy_or_diagnostic_only": [
            "neural_prefix_* estimates",
            "single-pair Stage 09/10 TTFT delta",
            "service-lifetime vLLM hit-rate gauges",
            "LogitState entropy/top-gap without a triggered consumer gate",
            "tag baseline source diff",
        ],
        "cannot_claim": [
            "full matrix passed",
            "free-text CanonicalTaskSpec compilation generalization",
            "cross-Agent KV tensor or hidden-state handoff",
            "StateBus latency superiority",
            "carrier-only attribution for the external system token delta",
            "secure sandboxed CodeAct",
            "validated openEuler delivery",
        ],
    }


def contest_coverage() -> list[dict[str, Any]]:
    return [
        {
            "dimension": ">=3 Agents / >=3 task types",
            "code": "four-role runtime and formal registry",
            "experiment": "25 cases, 5 registry families, four role requests on non-exact cases",
            "evidence_level": 4,
            "limit": "call count alone is not contribution; Planner ablation supplies the strongest behavior evidence",
        },
        {
            "dimension": "structured communication",
            "code": "typed Protobuf control plane and UDS transport",
            "experiment": "L0/L1 carrier compare and subprocess formal",
            "evidence_level": 4,
            "limit": "external compare is system-level, not carrier-only",
        },
        {
            "dimension": "non-text state",
            "code": "SemanticStateRef with shared_memory",
            "experiment": "L2/L3 publish/transfer counts and downstream hydration",
            "evidence_level": 4,
            "limit": "semantic pruning and state transport are bundled in L1->L2",
        },
        {
            "dimension": "shared memory reuse",
            "code": "memory search, compatibility, exact/validated replay",
            "experiment": "15 exact + 10 validated formal replay; two continuous families",
            "evidence_level": 4,
            "limit": "CSV artifact reuse mostly does not skip runtime steps",
        },
        {
            "dimension": "two continuous task groups",
            "code": "CSV and cross-period runners",
            "experiment": "10 rounds x 4 layers in both families",
            "evidence_level": 4,
            "limit": "history exposure makes L0-L2 imperfect no-history ablations",
        },
        {
            "dimension": "performance evidence",
            "code": "tokens/bytes/time/state/replay/prefix telemetry",
            "experiment": "three serialized external compares and prefix counters",
            "evidence_level": 3,
            "limit": "tokens improve; E2E latency is worse and prefix ratio aggregation is defective",
        },
        {
            "dimension": "CodeAct",
            "code": "bounded deterministic plan plus subprocess resource fallback",
            "experiment": "formal execution path exercised",
            "evidence_level": 3,
            "limit": "not a strong security sandbox",
        },
        {
            "dimension": "openEuler delivery",
            "code": "single-container target path",
            "experiment": "not validated by this run",
            "evidence_level": 1,
            "limit": "must remain a delivery validation item",
        },
    ]


def build_dataset(run_root: Path, tag: str) -> dict[str, Any]:
    base = legacy.build_dataset(run_root, tag)
    rows = base["cases"]["statebus"]
    enrich_case_rows(rows)
    comparisons = compare_repeats(run_root)
    pytest_text = (run_root / "logs/01_pytest_v2.log").read_text(
        encoding="utf-8", errors="replace"
    )
    pytest_summary = next(
        (line for line in reversed(pytest_text.splitlines()) if " passed" in line), ""
    )
    warning_match = re.search(r"(\d+) warnings", pytest_summary)
    preflight = load_json(run_root / "stages/00_preflight/stdout.json", {})
    dataset = {
        "schema_version": "statebus.full_qwen3_extended_matrix_audit.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "mode": "read_only_recursive_artifact_source_and_case_ledger_audit",
            "runtime_imported": False,
            "runtime_or_gate_modified": False,
            "full_experiment_rerun": False,
            "ratio_rule": "sum numerators / sum denominators; never sum per-case rates",
            "legacy_static_parser_reused": "scripts/analyze_full_qwen3_extended_run.py",
        },
        "run": {
            **base["run"],
            "full_extended_matrix_completed": True,
            "matrix_result": "14_pass_2_fail",
            "failed_stages": ["03_replay_full", "08_genericity_holdout"],
            "stop_reason": None,
        },
        "artifact_inventory": base["artifact_inventory"],
        "preflight": preflight,
        "pytest": {
            "artifact": str(run_root / "logs/01_pytest_v2.log"),
            "summary": pytest_summary,
            "warning_count": int(warning_match.group(1)) if warning_match else None,
            "warning_impact": "generated protobuf deprecations do not invalidate the passing tests",
        },
        "stage_matrix": stage_matrix(base, run_root),
        "case_aggregates": base["case_aggregates"],
        "cases": {
            "statebus_count": len(rows),
            "external_repeat_case_count": len(comparisons["all_case_rows"]),
            "statebus": rows,
            "external_compare_repeats": comparisons["all_case_rows"],
        },
        "compare_repeats": comparisons,
        "formal": formal_audit(run_root, "06_formal_full"),
        "formal_subprocess": formal_audit(run_root, "07_formal_subprocess_uds_full"),
        "continuous": {
            "csv": continuous_audit(run_root, "04_continuous_csv_full"),
            "cross_period": continuous_audit(run_root, "05_continuous_cross_full"),
        },
        "planner": group_planner(rows),
        "prefix_case_metrics": prefix_case_audit(rows),
        "prefix_probe": prefix_probe_audit(run_root),
        "logit_state": legacy.logit_audit(rows),
        "replay": replay_audit(rows, run_root),
        "genericity": genericity_audit(run_root),
        "carrier_compare": carrier_audit(run_root),
        "formal_subprocess_uds": base["formal_subprocess_uds"],
        "oracle_and_specialization": base["oracle_and_specialization"],
        "tag_baseline": load_json(run_root / "tag_baseline_audit.json", {}),
        "code_evidence": code_evidence(),
        "claim_ledger": claim_ledger(run_root),
        "contest_coverage": contest_coverage(),
        "issues": issue_ledger(run_root),
        "recommended_validation_order": [
            "static/unit tests for replay call metrics, answer restoration, taint sp contract, and rate aggregation",
            "rerun Stage 03 only",
            "rerun Stage 08 only with model/effective paraphrase results separated",
            "rerun alternating shared/independent prefix pairs with output-contract parity",
            "run targeted compare AB/BA timing repeats only if a latency claim is still desired",
            "rerun full matrix after all P0 gates and metrics are corrected",
            "perform openEuler delivery validation separately",
        ],
    }
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_root", nargs="?", type=Path, default=DEFAULT_RUN_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", default=REFERENCE_TAG)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    if not (run_root / "summary.json").is_file():
        raise SystemExit(f"run summary is missing: {run_root / 'summary.json'}")
    dataset = build_dataset(run_root, args.tag)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        stable_json(
            {
                "ok": True,
                "output": str(args.output),
                "recorded_stages": dataset["run"]["recorded_stage_count"],
                "statebus_cases": dataset["cases"]["statebus_count"],
                "external_repeat_cases": dataset["cases"]["external_repeat_case_count"],
                "issues": len(dataset["issues"]),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
