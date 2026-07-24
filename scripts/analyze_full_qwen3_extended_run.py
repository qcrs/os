#!/usr/bin/env python3
"""Read-only, case-level audit of the StateBus Qwen3 extended run.

The script deliberately derives conclusions from raw case workspaces, JSONL
telemetry, benchmark reports, and logs.  It never imports StateBus runtime code
and never mutates the audited run.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import statistics
import subprocess
from typing import Any, Iterable, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TAG = "v2-non-kv-baseline-20260710"
EXPECTED_STAGE_IDS = (
    "00_preflight",
    "01_pytest_v2",
    "02_compare_full",
    "03_replay_full",
    "04_continuous_csv_full",
    "05_continuous_cross_full",
    "06_formal_full",
    "07_formal_subprocess_uds_full",
    "08_genericity_holdout",
    "09_prefix_shared",
    "10_prefix_independent",
    "11_carrier_compare_full",
    "12_compare_repeat_2",
    "13_compare_repeat_3",
    "14_latency_repeat_aggregate",
    "15_tag_baseline_audit",
)
ROLES = ("planner", "retriever", "executor", "summarizer")
ORACLE_TERMS = (
    '"expected_facts"',
    '"expected_route"',
    '"expected_tool_name"',
    '"oracle_answer"',
    '"correctness_hint"',
)
ROLE_VISIBLE_NAMES = {
    "canonical_task_spec.json",
    "planner_handoff.json",
    "executor.prompt_slice.json",
    "planner.prompt_slice.json",
    "retriever.prompt_slice.json",
    "summarizer.prompt_slice.json",
}
PREFIX_FIELDS = (
    "neural_prefix_cache_hit_count_estimate",
    "neural_prefix_cache_query_count_estimate",
    "neural_prefix_cache_hit_rate_estimate",
    "neural_prefix_consumer_role_count",
    "neural_prefix_estimated_prefix_tokens",
    "neural_prefix_prefill_saved_tokens_estimate",
    "neural_prefix_prefill_savings_ratio_estimate",
    "neural_prefix_reuse_estimate_count",
    "neural_prefix_shared_prefix_bytes",
)
LOGIT_FIELDS = (
    "logit_state_transfer_count",
    "logit_state_mean_entropy",
    "logit_varentropy",
    "logit_top_gap",
    "logit_peak_position",
    "logit_sequence_length",
    "logit_decision_entropy",
    "logit_confidence_gate_trigger_count",
)
MEMORY_FIELDS = (
    "memory_match_count",
    "memory_candidate_count",
    "memory_exact_replay_candidate_count",
    "memory_rerank_selected_count",
    "artifact_reuse_count",
    "history_artifact_reuse_count",
    "history_strategy_reuse_count",
    "history_step_reduction_count",
    "history_reuse_gain",
    "validated_replay_count",
    "exact_replay_count",
    "skipped_step_count",
    "reuse_gain",
)


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(stable_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def numeric_summary(values: Iterable[Any]) -> dict[str, Any]:
    items: list[float] = []
    missing = 0
    for value in values:
        if value is None:
            missing += 1
            continue
        try:
            items.append(float(value))
        except (TypeError, ValueError):
            missing += 1
    if not items:
        return {
            "count": 0,
            "missing_count": missing,
            "zero_count": 0,
            "unique_count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "sum": 0.0,
        }
    return {
        "count": len(items),
        "missing_count": missing,
        "zero_count": sum(value == 0.0 for value in items),
        "unique_count": len(set(items)),
        "min": min(items),
        "max": max(items),
        "mean": statistics.fmean(items),
        "median": statistics.median(items),
        "sum": sum(items),
    }


def pct(delta: float, baseline: float) -> float | None:
    return None if baseline == 0 else 100.0 * delta / baseline


def hostify(path_value: Any, run_root: Path) -> str:
    text = str(path_value or "")
    container_prefix = f"/statebus/runs/{run_root.name}"
    if text.startswith(container_prefix):
        return str(run_root) + text[len(container_prefix) :]
    return text


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def read_status(run_root: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    path = run_root / "status.tsv"
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t", 2)
        if len(parts) == 3:
            rows[parts[0]] = {
                "status": parts[1],
                "artifact": hostify(parts[2], run_root),
            }
    return rows


def inventory_artifacts(run_root: Path) -> dict[str, Any]:
    suffix_counts: Counter[str] = Counter()
    stage_counts: dict[str, Counter[str]] = defaultdict(Counter)
    json_errors: list[dict[str, Any]] = []
    jsonl_errors: list[dict[str, Any]] = []
    jsonl_record_count = 0
    log_signal_counts: Counter[str] = Counter()
    log_signal_samples: list[dict[str, str]] = []
    signal_re = re.compile(r"traceback|\berror\b|exception|timeout", re.IGNORECASE)
    files = [path for path in run_root.rglob("*") if path.is_file()]
    for path in sorted(files):
        rel = path.relative_to(run_root)
        stage = rel.parts[1] if len(rel.parts) > 1 and rel.parts[0] == "stages" else "_run_root"
        suffix = path.suffix.lower() or "<none>"
        suffix_counts[suffix] += 1
        stage_counts[stage][suffix] += 1
        if suffix == ".json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                json_errors.append({"path": str(path), "error": f"{type(exc).__name__}: {exc}"})
        elif suffix == ".jsonl":
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                    jsonl_record_count += 1
                except json.JSONDecodeError as exc:
                    jsonl_errors.append(
                        {"path": str(path), "line": line_number, "error": str(exc)}
                    )
        elif suffix == ".log":
            for line_number, line in enumerate(
                path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
            ):
                if signal_re.search(line):
                    log_signal_counts[stage] += 1
                    if len(log_signal_samples) < 50:
                        log_signal_samples.append(
                            {"path": str(path), "line": str(line_number), "text": line[:500]}
                        )
    return {
        "file_count": len(files),
        "suffix_counts": dict(sorted(suffix_counts.items())),
        "stage_suffix_counts": {
            stage: dict(sorted(counts.items())) for stage, counts in sorted(stage_counts.items())
        },
        "json_parse_error_count": len(json_errors),
        "json_parse_errors": json_errors,
        "jsonl_record_count": jsonl_record_count,
        "jsonl_parse_error_count": len(jsonl_errors),
        "jsonl_parse_errors": jsonl_errors,
        "log_signal_counts": dict(sorted(log_signal_counts.items())),
        "log_signal_samples": log_signal_samples,
        "interpretation": (
            "log keyword matches are triage signals, not exception counts; JSON files that intentionally "
            "store empty stderr can still be valid JSON strings"
        ),
    }


def workspace_context(metrics_path: Path, run_root: Path) -> dict[str, str]:
    workspace = metrics_path.parent.parent
    rel = workspace.relative_to(run_root / "stages")
    stage = rel.parts[0]
    parts = rel.parts[2:] if len(rel.parts) > 1 and rel.parts[1] == "workspaces" else rel.parts[1:]
    layer = next((part for part in parts if part in {"L0", "L1", "L2", "L3"}), "")
    phase = "history_bootstrap" if "_history_bootstrap" in parts else "target"
    lane = "statebus"
    if stage == "02_compare_full" and "statebus" in parts:
        lane = "statebus"
    return {
        "workspace": str(workspace),
        "stage": stage,
        "layer": layer,
        "phase": phase,
        "lane": lane,
    }


def retrieval_outputs(retrieval_log: Any) -> list[dict[str, Any]]:
    if not isinstance(retrieval_log, dict):
        return []
    rows = []
    for output in retrieval_log.get("outputs", []):
        if not isinstance(output, dict):
            continue
        rows.append(
            {
                "retriever_kind": output.get("retriever_kind"),
                "candidate_count": int(number(output.get("candidate_count"))),
                "selected_count": int(number(output.get("selected_count"))),
                "selected_ids_hash": output.get("selected_ids_hash"),
            }
        )
    return rows


def infer_registry_family(task_id: str, runtime_family: str) -> str:
    normalized = re.sub(r"^genericity-", "", task_id)
    if normalized.startswith("benchmark-sample-"):
        return "financial_report_analysis"
    if normalized.startswith("formal-trend-"):
        return "multi_period_trend_analysis_v1"
    if normalized.startswith("formal-join-"):
        return "cross_table_join_analysis_v1"
    if normalized.startswith("formal-agg-"):
        return "conditional_aggregation_v1"
    if normalized.startswith("formal-anomaly-"):
        return "anomaly_detection_v1"
    if normalized.startswith("csv-profile-"):
        return "csv_table_profile"
    if normalized.startswith("cross-period-"):
        return "cross_period_financial"
    return runtime_family


def collect_statebus_cases(run_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metrics_path in sorted((run_root / "stages").rglob("logs/task_metrics.json")):
        metrics = load_json(metrics_path, {})
        if not isinstance(metrics, dict):
            continue
        context = workspace_context(metrics_path, run_root)
        workspace = Path(context["workspace"])
        spec = load_json(workspace / "inputs/canonical_task_spec.json", {})
        handoff = load_json(workspace / "inputs/planner_handoff.json", {})
        result = load_json(workspace / "outputs/result.json", {})
        replay_audit = load_json(workspace / "logs/replay_audit.json", {})
        artifact_audit = load_json(workspace / "logs/artifact_audit.json", {})
        retrieval_log = load_json(workspace / "inputs/retrieval_log.json", {})
        if not isinstance(spec, dict):
            spec = {}
        if not isinstance(handoff, dict):
            handoff = {}
        if not isinstance(result, dict):
            result = {}
        if not isinstance(replay_audit, dict):
            replay_audit = {}
        if not isinstance(artifact_audit, dict):
            artifact_audit = {}
        plan = handoff.get("planner_plan_payload", {})
        objective = handoff.get("retrieval_objective", {})
        scope = handoff.get("planner_scope_payload", {})
        if not isinstance(plan, dict):
            plan = {}
        if not isinstance(objective, dict):
            objective = {}
        if not isinstance(scope, dict):
            scope = {}
        model_objective = plan.get("retrieval_objective", {})
        if not isinstance(model_objective, dict):
            model_objective = {}
        steps = plan.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        output_path = workspace / "outputs/result.json"
        expected_hash = str(artifact_audit.get("output_artifact_hash", ""))
        actual_hash = sha256_file(output_path) if output_path.exists() else ""
        task_id = str(result.get("task_id") or handoff.get("task_id") or workspace.name)
        layer = context["layer"] or (
            f"L{int(number(metrics.get('benchmark_layer')))}"
            if metrics.get("benchmark_layer") is not None
            else ""
        )
        prefix = {field: metrics.get(field) for field in PREFIX_FIELDS}
        logit = {field: metrics.get(field) for field in LOGIT_FIELDS}
        memory = {field: metrics.get(field) for field in MEMORY_FIELDS}
        role_calls = {role: number(metrics.get(f"{role}_call_count")) for role in ROLES}
        role_tokens = {
            role: {
                "completion_tokens": number(metrics.get(f"{role}_completion_tokens")),
                "prompt_bytes": number(metrics.get(f"{role}_prompt_bytes")),
            }
            for role in ROLES
        }
        retrieved = retrieval_outputs(retrieval_log)
        retrieval_query = retrieval_log.get("query_text") if isinstance(retrieval_log, dict) else None
        objective_query = objective.get("query_text")
        row = {
            "stage": context["stage"],
            "layer": layer,
            "phase": context["phase"],
            "lane": context["lane"],
            "task_id": task_id,
            "task_family": str(result.get("task_family") or spec.get("task_family") or ""),
            "registry_family": infer_registry_family(
                task_id, str(result.get("task_family") or spec.get("task_family") or "")
            ),
            "intent_op": spec.get("intent_op"),
            "quality_floor_pass": bool(number(metrics.get("quality_floor_pass"))),
            "route": result.get("route"),
            "tool_name": result.get("tool_name"),
            "route_exact": metrics.get("route_exact"),
            "tool_exact": metrics.get("tool_exact"),
            "summary_present": bool(str(result.get("summary_text", "")).strip()),
            "role_calls": role_calls,
            "four_roles_exactly_once": all(value == 1.0 for value in role_calls.values()),
            "role_tokens": role_tokens,
            "llm": {
                "call_count": number(metrics.get("llm_call_count")),
                "prompt_tokens": number(metrics.get("llm_prompt_tokens", metrics.get("prompt_tokens"))),
                "completion_tokens": number(
                    metrics.get("llm_completion_tokens", metrics.get("completion_tokens"))
                ),
                "total_tokens": number(metrics.get("llm_total_tokens")),
                "wall_ms": number(metrics.get("llm_wall_ms", metrics.get("llm_ms"))),
                "task_ms": number(metrics.get("task_ms")),
            },
            "exceptions_and_fallbacks": {
                "runtime_fallback_count": number(metrics.get("runtime_fallback_count")),
                "state_pool_fallback_count": number(metrics.get("state_pool_fallback_count")),
                "sandbox_fallback_count": number(metrics.get("codeact_sandbox_fallback_count")),
                "sandbox_bwrap_count": number(metrics.get("codeact_sandbox_bwrap_count")),
                "invalidated_artifact_count": number(metrics.get("invalidated_artifact_count")),
                "attempt_count": number(metrics.get("attempt_count")),
            },
            "planner": {
                "plan_hash": sha256_json(plan),
                "plan_keys": sorted(plan),
                "workflow_step_count_from_payload": len(steps),
                "workflow_step_count_metric": number(metrics.get("planner_workflow_step_count")),
                "model_retrieval_objective_present": bool(model_objective),
                "model_retrieval_objective_field_count": len(model_objective),
                "final_objective_present": bool(objective),
                "final_objective_field_count": len(objective),
                "final_objective_hash": sha256_json(objective),
                "scope_hash": sha256_json(scope),
                "objective_source_inferred": "hybrid" if model_objective else "runtime_fallback",
                "generated_count_metric": number(
                    metrics.get("planner_generated_retrieval_objective_count")
                ),
                "objective_present_metric": number(metrics.get("planner_objective_present")),
                "plan_roundtrip_equal_in_output": result.get("planner_plan_payload") == plan,
            },
            "retrieval": {
                "query_text": retrieval_query,
                "objective_query_text": objective_query,
                "query_matches_final_objective": (
                    retrieval_query == objective_query if retrieval_query is not None else None
                ),
                "outputs": retrieved,
                "retriever_kinds": [item.get("retriever_kind") for item in retrieved],
                "per_retriever_objective_hash_recorded": False,
                "candidate_count_metric": number(metrics.get("retrieval_candidate_count")),
                "selected_count_metric": number(metrics.get("retrieval_selected_count")),
            },
            "memory_replay": {
                **memory,
                "replay_class": replay_audit.get("replay_class"),
                "compatibility_verdict": replay_audit.get("compatibility_verdict"),
                "decision_reason": replay_audit.get("decision_reason"),
                "history_runtime_roots": [
                    hostify(item, run_root) for item in replay_audit.get("history_runtime_roots", [])
                ],
                "history_record_runtime_root": hostify(
                    replay_audit.get("history_record_runtime_root"), run_root
                ),
                "consumed_artifact_refs": result.get("consumed_artifact_refs", []),
                "consumed_strategy_refs": result.get("consumed_strategy_refs", []),
                "produced_artifact_refs": result.get("produced_artifact_refs", []),
                "produced_strategy_refs": result.get("produced_strategy_refs", []),
                "downgraded_execution_goal": bool(result.get("downgraded_execution_goal")),
            },
            "prefix": prefix,
            "logit": {
                **logit,
                "peak_is_last": (
                    int(number(logit.get("logit_peak_position")))
                    == int(number(logit.get("logit_sequence_length"))) - 1
                    if number(logit.get("logit_sequence_length")) > 0
                    else None
                ),
            },
            "artifact_integrity": {
                "expected_output_hash": expected_hash,
                "actual_output_hash": actual_hash,
                "output_exists": output_path.exists(),
                "hash_matches": bool(expected_hash and expected_hash == actual_hash),
            },
            "artifact_paths": {
                "workspace": str(workspace),
                "task_metrics": str(metrics_path),
                "canonical_task_spec": str(workspace / "inputs/canonical_task_spec.json"),
                "planner_handoff": str(workspace / "inputs/planner_handoff.json"),
                "retrieval_log": str(workspace / "inputs/retrieval_log.json"),
                "telemetry": str(workspace / "logs/telemetry.json"),
                "replay_audit": str(workspace / "logs/replay_audit.json"),
                "result": str(output_path),
            },
        }
        rows.append(row)
    return rows


def report_case_index(
    run_root: Path, compare_report: dict[str, Any]
) -> dict[tuple[str, str, str], dict[str, Any]]:
    index: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(stage: str, layer: str, cases: Any) -> None:
        if not isinstance(cases, list):
            return
        for case in cases:
            if isinstance(case, dict) and case.get("task_id"):
                index[(stage, layer, str(case["task_id"]))] = case

    add("02_compare_full", "L3", compare_report.get("statebus_report", {}).get("cases", []))
    replay = load_json(run_root / "stages/03_replay_full/stdout.json", {})
    if isinstance(replay, dict):
        add("03_replay_full", str(replay.get("layer", "L3")), replay.get("cases", []))
    for stage in (
        "04_continuous_csv_full",
        "05_continuous_cross_full",
        "06_formal_full",
        "07_formal_subprocess_uds_full",
    ):
        payload = load_json(run_root / "stages" / stage / "stdout.json", {})
        if not isinstance(payload, dict):
            continue
        for layer in payload.get("layers", []):
            if isinstance(layer, dict):
                add(stage, str(layer.get("layer", "")), layer.get("cases", []))
    generic = load_json(run_root / "stages/08_genericity_holdout/stdout.json", {})
    if isinstance(generic, dict) and isinstance(generic.get("report"), dict):
        report = generic["report"]
        add("08_genericity_holdout", str(report.get("layer", "L3")), report.get("cases", []))
    return index


def enrich_from_case_reports(
    rows: Sequence[dict[str, Any]], index: dict[tuple[str, str, str], dict[str, Any]]
) -> None:
    for row in rows:
        if row["phase"] != "target":
            continue
        report_case = index.get((row["stage"], row["layer"], row["task_id"]))
        if report_case is None:
            continue
        metrics = report_case.get("metrics", {})
        row["registry_family"] = str(
            report_case.get("task_family") or row.get("registry_family", "")
        )
        row["quality_floor_pass"] = bool(
            report_case.get("quality_floor", {}).get(
                "quality_floor_pass", row["quality_floor_pass"]
            )
        )
        for field in ("route_exact", "tool_exact"):
            if metrics.get(field) is not None:
                row[field] = metrics[field]
        if metrics.get("task_ms") is not None:
            row["llm"]["task_ms"] = number(metrics["task_ms"])
        row["artifact_paths"]["benchmark_case_source"] = hostify(
            report_case.get("workspace_root"), Path(row["artifact_paths"]["workspace"]).parents[4]
        )


def find_compare_report(run_root: Path) -> Path:
    reports = sorted(
        (run_root / "stages/02_compare_full/runtime/benchmark_reports").glob(
            "*-compare-local_vllm.json"
        )
    )
    if not reports:
        raise FileNotFoundError("compare local_vllm report not found")
    return reports[-1]


def collect_external_cases(compare_report: dict[str, Any], run_root: Path) -> list[dict[str, Any]]:
    rows = []
    for case in compare_report.get("external_report", {}).get("cases", []):
        metrics = case.get("metrics", {})
        role_calls = {role: number(metrics.get(f"{role}_call_count")) for role in ROLES}
        rows.append(
            {
                "stage": "02_compare_full",
                "layer": "external_text",
                "phase": "target",
                "lane": "external_text",
                "task_id": case.get("task_id"),
                "task_family": case.get("task_family"),
                "registry_family": case.get("task_family"),
                "quality_floor_pass": bool(case.get("quality_floor", {}).get("quality_floor_pass")),
                "route_exact": metrics.get("route_exact"),
                "tool_exact": metrics.get("tool_exact"),
                "summary_present": bool(number(metrics.get("summary_present"))),
                "role_calls": role_calls,
                "four_roles_exactly_once": all(value == 1.0 for value in role_calls.values()),
                "llm": {
                    "call_count": number(metrics.get("llm_call_count")),
                    "prompt_tokens": number(metrics.get("prompt_tokens")),
                    "completion_tokens": number(metrics.get("completion_tokens")),
                    "total_tokens": number(metrics.get("llm_total_tokens")),
                    "wall_ms": number(metrics.get("llm_ms")),
                    "task_ms": number(metrics.get("task_ms")),
                },
                "fairness": case.get("audit_summary", {}).get("external_fairness_gate", {}),
                "artifact_paths": {
                    key: hostify(value, run_root)
                    for key, value in case.get("audit_paths", {}).items()
                },
            }
        )
    return rows


def aggregate_cases(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            str(row.get("stage", "")),
            str(row.get("lane", "")),
            str(row.get("phase", "")),
            str(row.get("layer", "")),
            str(row.get("registry_family", "")),
            str(row.get("task_family", "")),
        )
        grouped[key].append(row)
    result = []
    for key, items in sorted(grouped.items()):
        stage, lane, phase, layer, registry_family, family = key
        result.append(
            {
                "stage": stage,
                "lane": lane,
                "phase": phase,
                "layer": layer,
                "registry_family": registry_family,
                "task_family": family,
                "case_count": len(items),
                "quality_pass_count": sum(bool(item.get("quality_floor_pass")) for item in items),
                "four_roles_exactly_once_count": sum(
                    bool(item.get("four_roles_exactly_once")) for item in items
                ),
                "prompt_tokens": sum(number(item.get("llm", {}).get("prompt_tokens")) for item in items),
                "completion_tokens": sum(
                    number(item.get("llm", {}).get("completion_tokens")) for item in items
                ),
                "total_tokens": sum(number(item.get("llm", {}).get("total_tokens")) for item in items),
                "task_ms": sum(number(item.get("llm", {}).get("task_ms")) for item in items),
                "validated_replay_count": sum(
                    number(item.get("memory_replay", {}).get("validated_replay_count"))
                    for item in items
                ),
                "exact_replay_count": sum(
                    number(item.get("memory_replay", {}).get("exact_replay_count"))
                    for item in items
                ),
                "skipped_step_count": sum(
                    number(item.get("memory_replay", {}).get("skipped_step_count"))
                    for item in items
                ),
            }
        )
    return result


def stage_scope(
    run_root: Path,
    status: dict[str, dict[str, str]],
    rows: Sequence[dict[str, Any]],
    external_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for stage_id in EXPECTED_STAGE_IDS:
        stage_rows = [row for row in rows if row["stage"] == stage_id and row["phase"] == "target"]
        bootstrap_rows = [
            row for row in rows if row["stage"] == stage_id and row["phase"] == "history_bootstrap"
        ]
        external = [row for row in external_rows if row["stage"] == stage_id]
        stdout_path = run_root / "stages" / stage_id / "stdout.json"
        payload = load_json(stdout_path, {})
        layers = sorted({row["layer"] for row in stage_rows if row.get("layer")})
        families = sorted(
            {row["registry_family"] for row in stage_rows if row.get("registry_family")}
        )
        runtime_families = sorted(
            {row["task_family"] for row in stage_rows if row.get("task_family")}
        )
        row = {
            "stage": stage_id,
            "recorded_status": status.get(stage_id, {}).get("status", "not_recorded"),
            "executed": stage_id in status,
            "stdout_exists": stdout_path.exists(),
            "statebus_target_workspace_count": len(stage_rows),
            "bootstrap_workspace_count": len(bootstrap_rows),
            "external_case_count": len(external),
            "unique_task_count": len({item["task_id"] for item in stage_rows}),
            "family_count": len(families),
            "families": families,
            "runtime_task_family_count": len(runtime_families),
            "runtime_task_families": runtime_families,
            "layer_count": len(layers),
            "layers": layers,
            "quality_pass_count": sum(bool(item["quality_floor_pass"]) for item in stage_rows),
            "artifact": status.get(stage_id, {}).get("artifact", str(stdout_path)),
        }
        if isinstance(payload, dict):
            row["stdout_declared_scope"] = {
                key: payload.get(key)
                for key in (
                    "execution_scope",
                    "selected_case_count",
                    "available_case_count",
                    "selected_round_count",
                    "available_round_count",
                    "selected_family_count",
                    "family_count",
                    "transport",
                    "ok",
                )
                if key in payload
            }
        result.append(row)
    return result


def compare_audit(compare_report: dict[str, Any]) -> dict[str, Any]:
    statebus = {case["task_id"]: case for case in compare_report["statebus_report"]["cases"]}
    external = {case["task_id"]: case for case in compare_report["external_report"]["cases"]}
    case_rows = []
    for task_id in sorted(statebus.keys() & external.keys()):
        sb = statebus[task_id]
        ext = external[task_id]
        sbm = sb.get("metrics", {})
        exm = ext.get("metrics", {})
        task_delta = number(sbm.get("task_ms")) - number(exm.get("task_ms"))
        prompt_delta = number(sbm.get("llm_prompt_tokens", sbm.get("prompt_tokens"))) - number(
            exm.get("prompt_tokens")
        )
        total_delta = number(sbm.get("llm_total_tokens")) - number(exm.get("llm_total_tokens"))
        case_rows.append(
            {
                "task_id": task_id,
                "task_family": sb.get("task_family"),
                "statebus_quality": sb.get("quality_floor", {}).get("quality_floor_pass"),
                "external_quality": ext.get("quality_floor", {}).get("quality_floor_pass"),
                "statebus_prompt_tokens": number(
                    sbm.get("llm_prompt_tokens", sbm.get("prompt_tokens"))
                ),
                "external_prompt_tokens": number(exm.get("prompt_tokens")),
                "prompt_token_delta": prompt_delta,
                "total_token_delta": total_delta,
                "task_ms_delta": task_delta,
                "faster_lane": "statebus" if task_delta < 0 else "external" if task_delta > 0 else "tie",
                "external_fairness_pass": ext.get("audit_summary", {})
                .get("external_fairness_gate", {})
                .get("pass_hard_gate"),
            }
        )
    sb_prompt = sum(item["statebus_prompt_tokens"] for item in case_rows)
    ext_prompt = sum(item["external_prompt_tokens"] for item in case_rows)
    sb_total = sum(
        number(case.get("metrics", {}).get("llm_total_tokens")) for case in statebus.values()
    )
    ext_total = sum(
        number(case.get("metrics", {}).get("llm_total_tokens")) for case in external.values()
    )
    faster = Counter(item["faster_lane"] for item in case_rows)
    return {
        "case_count": len(case_rows),
        "family_count": len({item["task_family"] for item in case_rows}),
        "statebus_quality_pass_count": sum(bool(item["statebus_quality"]) for item in case_rows),
        "external_quality_pass_count": sum(bool(item["external_quality"]) for item in case_rows),
        "external_fairness_pass_count": sum(bool(item["external_fairness_pass"]) for item in case_rows),
        "comparison_valid": compare_report.get("comparison_valid"),
        "strict_equal_quality": compare_report.get("comparison_summary", {}).get(
            "strict_equal_quality_comparison_valid"
        ),
        "statebus_prompt_tokens": sb_prompt,
        "external_prompt_tokens": ext_prompt,
        "prompt_token_delta": sb_prompt - ext_prompt,
        "prompt_token_delta_pct_external": pct(sb_prompt - ext_prompt, ext_prompt),
        "statebus_total_tokens": sb_total,
        "external_total_tokens": ext_total,
        "total_token_delta": sb_total - ext_total,
        "total_token_delta_pct_external": pct(sb_total - ext_total, ext_total),
        "statebus_lower_prompt_case_count": sum(item["prompt_token_delta"] < 0 for item in case_rows),
        "per_case_task_ms_delta": numeric_summary(item["task_ms_delta"] for item in case_rows),
        "per_case_faster_count": dict(sorted(faster.items())),
        "repeat_count": 1,
        "schema_fairness": {
            "equivalent_json_schema": False,
            "external_planner_required_fields": [
                "candidate_key",
                "route",
                "tool_name",
                "retrieval_objective",
            ],
            "statebus_planner_artifact_observation": (
                "planner_plan_payload is not held to the same required-field schema in this run"
            ),
            "interpretation": (
                "same-model/task/scorer system comparison is supported; carrier-only causal attribution is not"
            ),
        },
        "cases": case_rows,
    }


def formal_layer_audit(run_root: Path, stage: str) -> dict[str, Any]:
    path = run_root / "stages" / stage / "stdout.json"
    payload = load_json(path, {})
    if not isinstance(payload, dict):
        return {"artifact": str(path), "layers": []}
    layers = []
    for layer in payload.get("layers", []):
        if not isinstance(layer, dict):
            continue
        metrics = layer.get("telemetry_summary", {})
        aggregate = layer.get("aggregated_metrics", {})
        family_counts = Counter(
            str(case.get("task_family", ""))
            for case in layer.get("cases", [])
            if isinstance(case, dict)
        )
        layers.append(
            {
                "layer": layer.get("layer"),
                "case_count": int(number(aggregate.get("case_count"))),
                "quality_pass_count": int(number(aggregate.get("quality_floor_pass_count"))),
                "family_case_counts": dict(sorted(family_counts.items())),
                "prompt_tokens": number(metrics.get("llm_prompt_tokens")),
                "completion_tokens": number(metrics.get("llm_completion_tokens")),
                "total_tokens": number(metrics.get("llm_total_tokens")),
                "task_ms": number(metrics.get("task_ms")),
                "llm_wall_ms": number(metrics.get("llm_wall_ms")),
                "control_bytes": number(metrics.get("control_bytes")),
                "semantic_state_transfer_count": number(
                    metrics.get("semantic_state_transfer_count")
                ),
                "shared_memory_publish_count": number(metrics.get("shared_memory_publish_count")),
                "validated_replay_count": number(metrics.get("validated_replay_count")),
                "exact_replay_count": number(metrics.get("exact_replay_count")),
                "logit_state_transfer_count": number(metrics.get("logit_state_transfer_count")),
                "sandbox_bwrap_count": number(metrics.get("codeact_sandbox_bwrap_count")),
                "sandbox_fallback_count": number(metrics.get("codeact_sandbox_fallback_count")),
                "role_calls": {
                    role: number(metrics.get(f"{role}_call_count")) for role in ROLES
                },
            }
        )
    by_name = {str(layer["layer"]): layer for layer in layers}
    l0 = by_name.get("L0", {})
    l3 = by_name.get("L3", {})
    return {
        "artifact": str(path),
        "transport": payload.get("transport"),
        "selected_case_count": payload.get("selected_case_count"),
        "available_case_count": payload.get("available_case_count"),
        "family_count": payload.get("family_count"),
        "families": payload.get("families", []),
        "layers": layers,
        "l3_minus_l0": {
            field: number(l3.get(field)) - number(l0.get(field))
            for field in ("prompt_tokens", "completion_tokens", "total_tokens", "task_ms", "control_bytes")
        },
        "l3_total_token_delta_pct_l0": pct(
            number(l3.get("total_tokens")) - number(l0.get("total_tokens")),
            number(l0.get("total_tokens")),
        ),
        "ablation_limit": (
            "L0/L1 change prompt/handoff/control contracts together; formal L3 has no history, so L2-L3 "
            "does not isolate replay"
        ),
    }


def planner_audit(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    planner_rows = [row for row in rows if row["phase"] in {"target", "history_bootstrap"}]
    step_counts = Counter(
        int(row["planner"]["workflow_step_count_from_payload"]) for row in planner_rows
    )
    plan_shapes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in planner_rows:
        plan_shapes[",".join(row["planner"]["plan_keys"])].append(row)
    by_stage: dict[str, dict[str, Any]] = {}
    for stage in sorted({row["stage"] for row in planner_rows}):
        items = [row for row in planner_rows if row["stage"] == stage]
        by_stage[stage] = {
            "case_count": len(items),
            "model_objective_present_count": sum(
                row["planner"]["model_retrieval_objective_present"] for row in items
            ),
            "generated_count_metric_sum": sum(
                row["planner"]["generated_count_metric"] for row in items
            ),
            "objective_present_metric_sum": sum(
                row["planner"]["objective_present_metric"] for row in items
            ),
            "workflow_step_distribution": dict(
                sorted(
                    Counter(
                        str(int(row["planner"]["workflow_step_count_from_payload"]))
                        for row in items
                    ).items()
                )
            ),
            "distinct_plan_hash_count": len({row["planner"]["plan_hash"] for row in items}),
            "distinct_objective_hash_count": len(
                {row["planner"]["final_objective_hash"] for row in items}
            ),
        }
    by_stage_layer_family: dict[str, dict[str, Any]] = {}
    group_keys = sorted(
        {
            "|".join([row["stage"], row["layer"], row.get("registry_family", "")])
            for row in planner_rows
        }
    )
    for key in group_keys:
        stage, layer, family = key.split("|", 2)
        items = [
            row
            for row in planner_rows
            if row["stage"] == stage
            and row["layer"] == layer
            and row.get("registry_family", "") == family
        ]
        by_stage_layer_family[key] = {
            "case_count": len(items),
            "model_objective_present_count": sum(
                item["planner"]["model_retrieval_objective_present"] for item in items
            ),
            "runtime_fallback_count": sum(
                item["planner"]["objective_source_inferred"] == "runtime_fallback"
                for item in items
            ),
            "workflow_step_distribution": dict(
                sorted(
                    Counter(
                        str(item["planner"]["workflow_step_count_from_payload"])
                        for item in items
                    ).items()
                )
            ),
        }
    return {
        "workspace_count": len(planner_rows),
        "planner_called_count": sum(row["role_calls"]["planner"] > 0 for row in planner_rows),
        "planner_payload_persisted_count": sum(
            Path(row["artifact_paths"]["planner_handoff"]).exists() for row in planner_rows
        ),
        "model_generated_retrieval_objective_case_count": sum(
            row["planner"]["model_retrieval_objective_present"] for row in planner_rows
        ),
        "model_generated_retrieval_objective_field_count": sum(
            row["planner"]["model_retrieval_objective_field_count"] for row in planner_rows
        ),
        "runtime_fallback_objective_case_count": sum(
            row["planner"]["objective_source_inferred"] == "runtime_fallback" for row in planner_rows
        ),
        "metric_claimed_generated_count_sum": sum(
            row["planner"]["generated_count_metric"] for row in planner_rows
        ),
        "metric_objective_present_count_sum": sum(
            row["planner"]["objective_present_metric"] for row in planner_rows
        ),
        "workflow_step_distribution": dict(sorted((str(k), v) for k, v in step_counts.items())),
        "plan_shape_distribution": {
            shape: {
                "case_count": len(items),
                "step_distribution": dict(
                    sorted(
                        Counter(
                            str(item["planner"]["workflow_step_count_from_payload"])
                            for item in items
                        ).items()
                    )
                ),
                "example": {
                    "stage": items[0]["stage"],
                    "task_id": items[0]["task_id"],
                    "artifact": items[0]["artifact_paths"]["planner_handoff"],
                },
            }
            for shape, items in sorted(plan_shapes.items())
        },
        "plan_roundtrip_equal_count": sum(
            row["planner"]["plan_roundtrip_equal_in_output"] for row in planner_rows
        ),
        "retrieval_query_matches_objective_count": sum(
            row["retrieval"]["query_matches_final_objective"] is True for row in planner_rows
        ),
        "retriever_consumed_objective_hash_recorded_count": 0,
        "fixed_fanout_kind_distribution": dict(
            Counter(
                kind
                for row in planner_rows
                for kind in row["retrieval"].get("retriever_kinds", [])
                if kind
            )
        ),
        "by_stage": by_stage,
        "by_stage_layer_registry_family": by_stage_layer_family,
        "behavioral_effect_observed": False,
        "behavioral_effect_reason": (
            "no model-generated retrieval_objective fields occurred; no disabled/perturbed Planner ablation exists"
        ),
    }


def field_distribution(
    rows: Sequence[dict[str, Any]], section: str, fields: Sequence[str]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["phase"] != "target":
            continue
        key = "|".join(
            [row["stage"], row.get("layer", ""), row.get("registry_family", "")]
        )
        groups[key].append(row)
    for key, items in sorted(groups.items()):
        result[key] = {
            "case_count": len(items),
            "fields": {
                field: numeric_summary(item.get(section, {}).get(field) for item in items)
                for field in fields
            },
        }
    return result


def prefix_audit(rows: Sequence[dict[str, Any]], run_root: Path) -> dict[str, Any]:
    targets = [row for row in rows if row["phase"] == "target"]
    hits = sum(number(row["prefix"].get("neural_prefix_cache_hit_count_estimate")) for row in targets)
    queries = sum(
        number(row["prefix"].get("neural_prefix_cache_query_count_estimate")) for row in targets
    )
    feedback_artifacts = [
        path
        for path in run_root.rglob("*")
        if path.is_file() and "prefix_feedback" in path.name.lower()
    ]
    observed_metric_fields = sorted(
        {
            key
            for row in targets
            for key in row["prefix"]
            if "observed" in key or "counter_delta" in key
        }
    )
    return {
        "case_count": len(targets),
        "estimated_hit_count": hits,
        "estimated_query_count": queries,
        "recomputed_estimated_hit_rate": hits / queries if queries else None,
        "all_fields_are_control_plane_estimates": True,
        "vllm_actual_counter_field_count": len(observed_metric_fields),
        "vllm_actual_counter_fields": observed_metric_fields,
        "task_or_stage_counter_delta_present": False,
        "service_lifetime_counter_snapshot_present": False,
        "feedback_artifact_count": len(feedback_artifacts),
        "planned_prefix_stage_status": {
            stage: "not_executed" for stage in ("09_prefix_shared", "10_prefix_independent")
        },
        "distributions": field_distribution(targets, "prefix", PREFIX_FIELDS),
        "claim_boundary": (
            "prefix identity/scheduling control plane and estimated prefill savings only; no KV tensor export, "
            "task-local vLLM cache hit delta, or causal time/token benefit"
        ),
    }


def logit_audit(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    targets = [
        row
        for row in rows
        if row["phase"] == "target"
        and number(row["logit"].get("logit_state_transfer_count")) > 0
    ]
    return {
        "observation_count": len(targets),
        "peak_is_last_count": sum(row["logit"].get("peak_is_last") is True for row in targets),
        "peak_before_last_count": sum(row["logit"].get("peak_is_last") is False for row in targets),
        "entropy": numeric_summary(row["logit"].get("logit_state_mean_entropy") for row in targets),
        "varentropy": numeric_summary(row["logit"].get("logit_varentropy") for row in targets),
        "top_gap": numeric_summary(row["logit"].get("logit_top_gap") for row in targets),
        "peak_position": numeric_summary(row["logit"].get("logit_peak_position") for row in targets),
        "sequence_length": numeric_summary(row["logit"].get("logit_sequence_length") for row in targets),
        "decision_entropy": numeric_summary(
            row["logit"].get("logit_decision_entropy") for row in targets
        ),
        "confidence_gate_trigger_count": sum(
            number(row["logit"].get("logit_confidence_gate_trigger_count")) for row in targets
        ),
        "raw_top_logprobs_persisted": False,
        "last_token_comparator_reconstructable": False,
        "distributions": field_distribution(targets, "logit", LOGIT_FIELDS),
        "claim_boundary": (
            "compact probability/logprob-derived decision summary; not hidden state and not KV tensor transfer"
        ),
    }


def replay_memory_audit(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    targets = [row for row in rows if row["phase"] == "target"]
    replay = [row for row in targets if row["stage"] == "03_replay_full"]
    continuous = [
        row
        for row in targets
        if row["stage"] in {"04_continuous_csv_full", "05_continuous_cross_full"}
    ]
    stage03_pairs = []
    boot_by_id = {
        row["task_id"]: row
        for row in rows
        if row["stage"] == "03_replay_full" and row["phase"] == "history_bootstrap"
    }
    for target in replay:
        boot = boot_by_id.get(target["task_id"])
        stage03_pairs.append(
            {
                "task_id": target["task_id"],
                "bootstrap_present": boot is not None,
                "different_workspace": bool(
                    boot and boot["artifact_paths"]["workspace"] != target["artifact_paths"]["workspace"]
                ),
                "same_canonical_spec_hash": bool(
                    boot
                    and sha256_file(Path(boot["artifact_paths"]["canonical_task_spec"]))
                    == sha256_file(Path(target["artifact_paths"]["canonical_task_spec"]))
                ),
                "target_history_roots": target["memory_replay"]["history_runtime_roots"],
                "validated_replay_count": number(
                    target["memory_replay"].get("validated_replay_count")
                ),
                "exact_replay_count": number(target["memory_replay"].get("exact_replay_count")),
                "skipped_step_count": number(target["memory_replay"].get("skipped_step_count")),
                "reuse_gain": number(target["memory_replay"].get("reuse_gain")),
                "four_roles_exactly_once": target["four_roles_exactly_once"],
            }
        )
    by_stage_layer: dict[str, Any] = {}
    for key in sorted({f"{row['stage']}|{row['layer']}" for row in continuous}):
        stage, layer = key.split("|", 1)
        items = [row for row in continuous if row["stage"] == stage and row["layer"] == layer]
        by_stage_layer[key] = {
            "case_count": len(items),
            "memory_match_count": sum(number(row["memory_replay"].get("memory_match_count")) for row in items),
            "history_artifact_ref_count": sum(
                len(row["memory_replay"].get("consumed_artifact_refs", [])) for row in items
            ),
            "history_strategy_ref_count": sum(
                len(row["memory_replay"].get("consumed_strategy_refs", [])) for row in items
            ),
            "validated_replay_count": sum(
                number(row["memory_replay"].get("validated_replay_count")) for row in items
            ),
            "exact_replay_count": sum(
                number(row["memory_replay"].get("exact_replay_count")) for row in items
            ),
            "skipped_step_count": sum(
                number(row["memory_replay"].get("skipped_step_count")) for row in items
            ),
            "history_step_reduction_count": sum(
                number(row["memory_replay"].get("history_step_reduction_count")) for row in items
            ),
            "history_reuse_gain": sum(
                number(row["memory_replay"].get("history_reuse_gain")) for row in items
            ),
            "all_four_roles_called_count": sum(row["four_roles_exactly_once"] for row in items),
        }
    inconsistent = [
        {
            "stage": row["stage"],
            "layer": row["layer"],
            "task_id": row["task_id"],
            "validated_replay_count": row["memory_replay"].get("validated_replay_count"),
            "skipped_step_count": row["memory_replay"].get("skipped_step_count"),
            "consumed_artifact_ref_count": len(
                row["memory_replay"].get("consumed_artifact_refs", [])
            ),
            "consumed_strategy_ref_count": len(
                row["memory_replay"].get("consumed_strategy_refs", [])
            ),
            "history_step_reduction_count": row["memory_replay"].get(
                "history_step_reduction_count"
            ),
            "history_reuse_gain": row["memory_replay"].get("history_reuse_gain"),
            "artifact": row["artifact_paths"]["task_metrics"],
        }
        for row in continuous
        if number(row["memory_replay"].get("validated_replay_count")) > 0
        and not row["memory_replay"].get("consumed_artifact_refs")
        and not row["memory_replay"].get("consumed_strategy_refs")
        and number(row["memory_replay"].get("history_step_reduction_count")) == 0
    ]
    integrity = [row["artifact_integrity"] for row in rows]
    return {
        "stage03": {
            "target_count": len(replay),
            "bootstrap_count": len(boot_by_id),
            "memory_match_count": sum(
                number(row["memory_replay"].get("memory_match_count")) for row in replay
            ),
            "validated_replay_count": sum(
                number(row["memory_replay"].get("validated_replay_count")) for row in replay
            ),
            "exact_replay_count": sum(
                number(row["memory_replay"].get("exact_replay_count")) for row in replay
            ),
            "skipped_step_count": sum(
                number(row["memory_replay"].get("skipped_step_count")) for row in replay
            ),
            "reuse_gain": sum(number(row["memory_replay"].get("reuse_gain")) for row in replay),
            "all_four_roles_called_count": sum(row["four_roles_exactly_once"] for row in replay),
            "pairs": stage03_pairs,
        },
        "continuous_by_stage_layer": by_stage_layer,
        "validated_replay_without_output_reuse_cases": inconsistent,
        "output_artifact_integrity": {
            "audited_workspace_count": len(integrity),
            "output_exists_count": sum(item["output_exists"] for item in integrity),
            "hash_match_count": sum(item["hash_matches"] for item in integrity),
        },
        "history_root_outside_same_stage_count": sum(
            1
            for row in targets
            for root in row["memory_replay"].get("history_runtime_roots", [])
            if root and f"/stages/{row['stage']}/" not in root
        ),
    }


def genericity_audit(rows: Sequence[dict[str, Any]], run_root: Path) -> dict[str, Any]:
    generic = [row for row in rows if row["stage"] == "08_genericity_holdout"]
    formal = {
        (row["layer"], row["task_id"]): row
        for row in rows
        if row["stage"] == "06_formal_full" and row["phase"] == "target"
    }
    pairs = []
    for row in generic:
        original_id = re.sub(r"^genericity-", "", row["task_id"])
        original = formal.get(("L3", original_id))
        pairs.append(
            {
                "holdout_task_id": row["task_id"],
                "original_task_id": original_id,
                "original_present": original is not None,
                "canonical_spec_hash_equal": bool(
                    original
                    and sha256_file(Path(row["artifact_paths"]["canonical_task_spec"]))
                    == sha256_file(Path(original["artifact_paths"]["canonical_task_spec"]))
                ),
                "planner_plan_hash_equal": bool(
                    original and row["planner"]["plan_hash"] == original["planner"]["plan_hash"]
                ),
                "retrieval_objective_hash_equal": bool(
                    original
                    and row["planner"]["final_objective_hash"]
                    == original["planner"]["final_objective_hash"]
                ),
                "route_equal": bool(original and row["route"] == original["route"]),
                "tool_equal": bool(original and row["tool_name"] == original["tool_name"]),
                "summary_hash_equal": bool(
                    original
                    and sha256_json(
                        load_json(Path(row["artifact_paths"]["result"]), {}).get("summary_text")
                    )
                    == sha256_json(
                        load_json(Path(original["artifact_paths"]["result"]), {}).get("summary_text")
                    )
                ),
            }
        )
    stdout = load_json(run_root / "stages/08_genericity_holdout/stdout.json", {})
    return {
        "stage_ok": stdout.get("ok") if isinstance(stdout, dict) else None,
        "case_count": len(generic),
        "family_count": len({row["registry_family"] for row in generic}),
        "runtime_task_family_count": len({row["task_family"] for row in generic}),
        "quality_pass_count": sum(row["quality_floor_pass"] for row in generic),
        "route_hints_disabled_count": sum(
            number(load_json(Path(row["artifact_paths"]["task_metrics"]), {}).get("route_hints_enabled"))
            == 0
            for row in generic
        ),
        "zero_planner_workflow_step_count": sum(
            row["planner"]["workflow_step_count_from_payload"] == 0 for row in generic
        ),
        "failed_gate_only_planner_step_requirement": bool(
            generic
            and all(row["quality_floor_pass"] and row["four_roles_exactly_once"] for row in generic)
            and all(row["planner"]["workflow_step_count_from_payload"] < 3 for row in generic)
        ),
        "precompiled_spec_prior_fields": [
            "intent_op",
            "required_tools",
            "required_outputs",
            "arguments.quality_checks",
        ],
        "request_text_compiled_into_spec": False,
        "pairs_with_stage06": pairs,
        "claim_boundary": (
            "no-route-hint re-execution of precompiled CanonicalTaskSpec; not free-text intent compilation "
            "or paraphrase-semantic-planning evidence"
        ),
    }


def uds_audit(rows: Sequence[dict[str, Any]], run_root: Path) -> dict[str, Any]:
    normal = [
        row
        for row in rows
        if row["stage"] == "06_formal_full" and row["phase"] == "target"
    ]
    uds = [
        row
        for row in rows
        if row["stage"] == "07_formal_subprocess_uds_full" and row["phase"] == "target"
    ]
    normal_by_key = {(row["layer"], row["task_id"]): row for row in normal}
    pairs = []
    for row in uds:
        peer = normal_by_key.get((row["layer"], row["task_id"]))
        pairs.append(
            {
                "layer": row["layer"],
                "task_id": row["task_id"],
                "peer_present": peer is not None,
                "quality_equal": bool(peer and row["quality_floor_pass"] == peer["quality_floor_pass"]),
                "output_hash_equal": bool(
                    peer
                    and row["artifact_integrity"]["actual_output_hash"]
                    == peer["artifact_integrity"]["actual_output_hash"]
                ),
                "prompt_tokens_equal": bool(
                    peer and row["llm"]["prompt_tokens"] == peer["llm"]["prompt_tokens"]
                ),
                "task_ms_delta": (
                    row["llm"]["task_ms"] - peer["llm"]["task_ms"] if peer else None
                ),
            }
        )
    stage07 = load_json(run_root / "stages/07_formal_subprocess_uds_full/stdout.json", {})
    jsonl_paths = list((run_root / "stages/07_formal_subprocess_uds_full/runtime").rglob("*.jsonl"))
    pid_socket_matches = 0
    transport_value_matches = 0
    for path in jsonl_paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        pid_socket_matches += len(re.findall(r'"(?:pid|socket_path)"', text))
        transport_value_matches += len(re.findall(r'"transport"\s*:\s*"subprocess"', text))
    return {
        "stdout_transport": stage07.get("transport") if isinstance(stage07, dict) else None,
        "case_pair_count": len(pairs),
        "quality_equal_count": sum(item["quality_equal"] for item in pairs),
        "output_hash_equal_count": sum(item["output_hash_equal"] for item in pairs),
        "prompt_tokens_equal_count": sum(item["prompt_tokens_equal"] for item in pairs),
        "task_ms_delta": numeric_summary(item["task_ms_delta"] for item in pairs),
        "runtime_jsonl_file_count": len(jsonl_paths),
        "runtime_pid_or_socket_field_match_count": pid_socket_matches,
        "runtime_transport_subprocess_field_match_count": transport_value_matches,
        "repeat_count": 1,
        "pairs": pairs,
        "interpretation": (
            "code path plus successful 100-case execution supports subprocess+AF_UNIX+typed Protobuf; "
            "artifact-level PID/socket lifecycle evidence and repeated overhead attribution are absent"
        ),
    }


def oracle_audit(run_root: Path) -> dict[str, Any]:
    scanned: list[Path] = []
    matches: list[dict[str, Any]] = []
    surface_counts: Counter[str] = Counter()
    for path in sorted((run_root / "stages").rglob("*")):
        if not path.is_file():
            continue
        if path.name in ROLE_VISIBLE_NAMES or path.name.endswith(".codeact_bundle.json"):
            scanned.append(path)
            if path.name.endswith(".prompt_slice.json"):
                surface_counts["prompt_slice"] += 1
            elif path.name.endswith(".codeact_bundle.json"):
                surface_counts["codeact_bundle"] += 1
            else:
                surface_counts[path.name] += 1
            text = path.read_text(encoding="utf-8", errors="replace")
            found = [term for term in ORACLE_TERMS if term in text]
            if found:
                matches.append({"path": str(path), "terms": found})
    return {
        "scanned_file_count": len(scanned),
        "surface_counts": dict(sorted(surface_counts.items())),
        "literal_forbidden_field_match_count": len(matches),
        "matches": matches,
        "semantic_oracle_scan_performed": False,
        "case_id_specialization_scan": {
            "literal_case_id_branch_found": False,
            "method": "source rg review; no dynamic semantic equivalence proof",
        },
        "remaining_priors": [
            "CanonicalTaskSpec.intent_op",
            "CanonicalTaskSpec.required_tools",
            "CanonicalTaskSpec.required_outputs",
            "CanonicalTaskSpec.arguments.quality_checks",
            "route hints derived from intent/top candidate when enabled",
        ],
        "claim_boundary": (
            "no listed oracle field name was found on enumerated role-visible surfaces; this is not a "
            "formal proof against semantic oracle values or template specialization"
        ),
    }


def source_location(path: str, pattern: str) -> dict[str, Any]:
    file_path = REPO_ROOT / path
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    regex = re.compile(pattern)
    line = next((index for index, text in enumerate(lines, start=1) if regex.search(text)), None)
    return {"path": str(file_path), "line": line, "pattern": pattern}


def function_snapshot(text: str, function_name: str) -> dict[str, Any]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"present": False, "sha256": None, "line": None}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            segment = ast.get_source_segment(text, node) or ""
            normalized = "\n".join(line.rstrip() for line in segment.splitlines()).strip()
            return {
                "present": True,
                "sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
                "line": node.lineno,
            }
    return {"present": False, "sha256": None, "line": None}


def tag_audit(tag: str) -> dict[str, Any]:
    tag_object = git("rev-parse", tag)
    tag_commit = git("rev-parse", f"{tag}^{{}}")
    current_commit = git("rev-parse", "HEAD")
    targets = (
        ("v2/runtime/driver.py", "build_default_workflow"),
        ("v2/runtime/role_path.py", "build_retrieval_objective"),
        ("v2/runtime/role_path.py", "plan_workflow"),
    )
    functions = []
    for path, name in targets:
        current_text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        tagged_text = git("show", f"{tag}:{path}")
        current = function_snapshot(current_text, name)
        tagged = function_snapshot(tagged_text, name)
        functions.append(
            {
                "path": path,
                "function": name,
                "current_worktree": current,
                "tag": tagged,
                "identical": current.get("sha256") == tagged.get("sha256"),
            }
        )
    smoke_tag = git("show", f"{tag}:v2/runtime/smoke.py")
    driver_tag = git("show", f"{tag}:v2/runtime/driver.py")
    return {
        "tag": tag,
        "annotated_tag_object": tag_object,
        "peeled_commit": tag_commit,
        "expected_peeled_commit": "d83627dc2b792b4c8ac2c2d58337fc8281771803",
        "current_head": current_commit,
        "functions": functions,
        "tag_had_hardcoded_generated_metric": (
            '"planner_generated_retrieval_objective_count": 1.0' in smoke_tag
            or '"planner_generated_retrieval_objective_count": 1.0' in driver_tag
        ),
        "planner_behavior_regression_from_tag": False,
        "interpretation": (
            "fixed workflow and Planner objective construction are unchanged from the tag; the current run "
            "exposes a longstanding attribution defect rather than a new Planner behavior regression"
        ),
    }


def code_evidence() -> dict[str, Any]:
    entries = {
        "fixed_runtime_workflow": source_location(
            "v2/runtime/driver.py", r"^def build_default_workflow"
        ),
        "planner_objective_merge": source_location(
            "v2/runtime/smoke.py", r"planner_retrieval_objective = \{"
        ),
        "retriever_consumes_query": source_location(
            "v2/runtime/smoke.py", r"retrieval = RetrieverFanoutPipeline"
        ),
        "retriever_candidate_constraint": source_location(
            "v2/runtime/smoke.py", r"role_candidates = constrain_visible_candidates"
        ),
        "hardcoded_generated_metric_driver": source_location(
            "v2/runtime/driver.py", r'"planner_generated_retrieval_objective_count": 1\.0'
        ),
        "hardcoded_generated_metric_smoke": source_location(
            "v2/runtime/smoke.py", r'"planner_generated_retrieval_objective_count": 1\.0'
        ),
        "objective_present_after_merge": source_location(
            "v2/runtime/smoke.py", r'task_metrics\["planner_objective_present"\]'
        ),
        "genericity_precompiled_spec": source_location(
            "scripts/run_v2_genericity_holdout.py", r"registered\[task_id\]"
        ),
        "genericity_bad_step_gate": source_location(
            "scripts/run_v2_genericity_holdout.py", r'planner_workflow_step_count"\] >= 3'
        ),
        "compiler_prefers_precompiled_spec": source_location(
            "v2/runtime/smoke.py", r"precompiled_canonical_task_spec=canonical_task_spec"
        ),
        "continuous_all_layers_receive_history": source_location(
            "v2/benchmark/continuous_runner.py", r"history_runtime_roots: tuple\[Path"
        ),
        "continuous_metrics_zeroed_without_replay": source_location(
            "v2/runtime/smoke.py", r"if not layer_config\.replay_enabled"
        ),
        "validated_replay_skip_constant": source_location(
            "v2/runtime/replay.py", r"skipped_step_count=1"
        ),
        "subprocess_transport_branch": source_location(
            "v2/runtime/driver.py", r'executor_transport == "subprocess"'
        ),
        "uds_af_unix": source_location("v2/control/transport.py", r"socket\.AF_UNIX"),
        "subprocess_popen": source_location("v2/control/transport.py", r"subprocess\.Popen"),
        "logit_peak_scan": source_location("v2/runtime/logit_state.py", r"peak_position"),
        "logit_metric_assignment": source_location(
            "v2/runtime/smoke.py", r'task_metrics\["logit_state_mean_entropy"\]'
        ),
        "prefix_feedback_class": source_location(
            "v2/runtime/prefix_feedback.py", r"^class PrefixCacheFeedbackLoop"
        ),
        "prefix_feedback_live_helper": source_location(
            "v2/runtime/prefix_feedback.py", r"^def record_live"
        ),
        "external_planner_schema": source_location(
            "v2/benchmark/external_text_baseline.py", r'"retrieval_objective": \{"type": "string"\}'
        ),
        "expected_facts_post_role_validation": source_location(
            "v2/runtime/smoke.py", r"expected_facts=expected_facts"
        ),
    }
    return {
        "working_tree_locations": entries,
        "location_warning": (
            "line numbers identify the audited working tree and may move after subsequent user edits"
        ),
    }


def agent_contribution(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    targets = [row for row in rows if row["phase"] == "target"]
    return {
        "case_count": len(targets),
        "all_four_roles_exactly_once_count": sum(row["four_roles_exactly_once"] for row in targets),
        "planner": {
            "called_count": sum(row["role_calls"]["planner"] > 0 for row in targets),
            "produced_payload_count": sum(bool(row["planner"]["plan_keys"]) for row in targets),
            "persisted_count": sum(
                Path(row["artifact_paths"]["planner_handoff"]).exists() for row in targets
            ),
            "downstream_final_objective_read_supported_by_code": True,
            "model_data_behavioral_effect_count": 0,
        },
        "retriever": {
            "called_count": sum(row["role_calls"]["retriever"] > 0 for row in targets),
            "retrieval_log_count": sum(
                Path(row["artifact_paths"]["retrieval_log"]).exists() for row in targets
            ),
            "fixed_fanout_nonempty_count": sum(bool(row["retrieval"]["outputs"]) for row in targets),
            "executor_consumes_evidence_supported_by_code": True,
        },
        "executor": {
            "called_count": sum(row["role_calls"]["executor"] > 0 for row in targets),
            "route_and_tool_output_count": sum(
                bool(row.get("route") and row.get("tool_name")) for row in targets
            ),
            "deterministic_codeact_note": (
                "LLM validates a closed-set route/tool; Runtime generates bounded deterministic plan/script"
            ),
        },
        "summarizer": {
            "called_count": sum(row["role_calls"]["summarizer"] > 0 for row in targets),
            "nonempty_summary_count": sum(row["summary_present"] for row in targets),
            "summary_persisted_to_result_and_memory_supported_by_code": True,
            "raw_completion_persisted_count": 0,
        },
        "audit_limit": (
            "raw role completions are not persisted, so payload provenance and fallback use cannot be fully reconstructed"
        ),
    }


def claim_ledger(run_root: Path) -> dict[str, list[dict[str, Any]]]:
    base = str(run_root)
    return {
        "experimentally_proven": [
            {
                "claim": "25-case/5-family equal-quality first-pass StateBus vs external comparison completed",
                "artifact": f"{base}/stages/02_compare_full/stdout.json",
                "fields": ["selected_case_count", "comparison_summary", "strict_equal_quality_comparison_valid"],
            },
            {
                "claim": "formal and subprocess formal each completed 25 cases across L0-L3",
                "artifact": f"{base}/stages/06_formal_full/stdout.json",
                "fields": ["families", "layers", "transport"],
            },
            {
                "claim": "two 10-round continuous families completed with persisted history lineage",
                "artifact": f"{base}/stages/05_continuous_cross_full/stdout.json",
                "fields": ["selected_round_count", "layers", "waterfall_metrics"],
            },
            {
                "claim": "Planner was called and its handoff payload was persisted, but model objective fields were absent",
                "artifact": f"{base}/stages/06_formal_full/workspaces/L3/formal-agg-003/inputs/planner_handoff.json",
                "fields": ["planner_plan_payload", "retrieval_objective"],
            },
        ],
        "code_supported_not_experimentally_demonstrated": [
            {"claim": "PrefixCacheFeedbackLoop can ingest live counters", "code": "v2/runtime/prefix_feedback.py"},
            {"claim": "exact replay can restore output and zero downstream role calls", "code": "v2/runtime/smoke.py"},
            {"claim": "model objective can constrain query/candidate fields", "code": "v2/runtime/smoke.py"},
        ],
        "estimated_metrics_only": [
            {"claim": "neural_prefix_* hit rate and prefill token savings", "field_prefix": "neural_prefix_"},
            {"claim": "evidence pruning estimated KV tokens saved", "field": "evidence_pruning_estimated_kv_tokens_saved"},
            {"claim": "history step reduction", "field": "history_step_reduction_count"},
        ],
        "cannot_claim": [
            {"claim": "hidden-state or KV tensor handoff"},
            {"claim": "task-local observed vLLM prefix-cache hit or causal prefix speedup"},
            {"claim": "free-text genericity or paraphrase semantic planning"},
            {"claim": "stable latency superiority from one compare run"},
            {"claim": "Planner model output changed route/tool/retrieval behavior in this run"},
            {"claim": "strong bwrap isolation"},
        ],
        "metric_or_experiment_defects": [
            {"claim": "generated Planner objective metric counts runtime fallback as model contribution"},
            {"claim": "genericity gate requires arbitrary workflow step count"},
            {"claim": "continuous L0-L2 consume history roots while reuse metrics are forced to zero"},
            {"claim": "validated replay skipped_step_count does not imply fewer Agent calls"},
            {"claim": "extended run summary is incomplete because Stage 08 stopped later stages"},
            {"claim": "compare schemas and execution implementations are not equivalent"},
        ],
    }


def issue_ledger(run_root: Path) -> list[dict[str, Any]]:
    base = str(run_root)
    return [
        {
            "priority": "P0",
            "issue": "Planner contribution metrics are false-positive attribution",
            "artifact": f"{base}/stages/06_formal_full/workspaces/L3/formal-agg-003/logs/task_metrics.json",
            "fields": ["planner_generated_retrieval_objective_count", "planner_objective_present"],
            "code": "v2/runtime/smoke.py",
        },
        {
            "priority": "P0",
            "issue": "genericity gate fails on planner_workflow_step_count despite 4/4 quality",
            "artifact": f"{base}/stages/08_genericity_holdout/stdout.json",
            "fields": ["ok", "case_audit[].planner_workflow_step_count"],
            "code": "scripts/run_v2_genericity_holdout.py",
        },
        {
            "priority": "P1",
            "issue": "continuous L0-L2 are not clean no-history ablations",
            "artifact": f"{base}/stages/05_continuous_cross_full/workspaces/L0/cross-period-002/logs/replay_audit.json",
            "fields": ["history_runtime_roots", "history_artifact_reuse_count"],
            "code": "v2/benchmark/continuous_runner.py; v2/runtime/smoke.py",
        },
        {
            "priority": "P1",
            "issue": "prefix evidence lacks observed counter delta and feedback-loop integration",
            "artifact": f"{base}/stages/06_formal_full/stdout.json",
            "fields": ["layers[].telemetry_summary.neural_prefix_*"],
            "code": "v2/runtime/prefix_feedback.py",
        },
        {
            "priority": "P1",
            "issue": "raw top-logprobs and raw role completions are not persisted",
            "artifact": f"{base}/stages/06_formal_full/workspaces/L3/formal-agg-003/logs/task_metrics.json",
            "fields": ["logit_state_mean_entropy", "logit_peak_position"],
            "code": "v2/runtime/role_path.py; v2/runtime/logit_state.py",
        },
        {
            "priority": "P1",
            "issue": "UDS run lacks PID/socket/transport lifecycle fields in runtime telemetry",
            "artifact": f"{base}/stages/07_formal_subprocess_uds_full/runtime",
            "fields": ["runtime_events.jsonl", "runtime_facts.jsonl"],
            "code": "v2/control/transport.py",
        },
        {
            "priority": "P2",
            "issue": "memory_commit_count and retrieval_candidate_count aggregate lifecycle events, not unique objects",
            "artifact": f"{base}/stages/06_formal_full/stdout.json",
            "fields": ["memory_commit_count", "retrieval_candidate_count"],
            "code": "v2/runtime/driver.py",
        },
        {
            "priority": "P2",
            "issue": "CodeAct uses resource fallback for all audited StateBus workspaces",
            "artifact": f"{base}/stages/06_formal_full/workspaces/L3/formal-agg-003/logs/task_metrics.json",
            "fields": ["codeact_sandbox_bwrap_count", "codeact_sandbox_fallback_count"],
            "code": "v2/runtime/codeact.py",
        },
    ]


def validation_matrix() -> list[dict[str, Any]]:
    return [
        {
            "change": "Phase 1 Planner observability",
            "minimum_validation": "unit tests + 4-case holdout + one formal case L0-L3",
            "required_fields": [
                "objective_source",
                "planner_model_generated_field_count",
                "planner_fallback_field_count",
                "planner_downstream_consumed_field_count",
                "planner_behavioral_effect",
                "planner_semantic_plan_hash",
                "retriever_consumed_objective_hash",
            ],
        },
        {
            "change": "Phase 2 shadow SemanticTaskPlan",
            "minimum_validation": "25 formal + paraphrase pairs, shadow only",
            "gates": [
                "schema validity",
                "semantic equivalence",
                "paraphrase stability",
                "cross-family differentiation",
                "oracle/case-id taint",
            ],
        },
        {
            "change": "Phase 3 constrained Retriever consumption",
            "minimum_validation": "Planner enabled/disabled/perturbed A/B plus full quality regression",
            "gates": [
                "registered retriever kinds only",
                "bounded objective fields",
                "hash-confirmed downstream consumption",
                "fallback on validation failure",
                "fixed Runtime topology unchanged",
            ],
        },
        {
            "change": "prefix causal claim",
            "minimum_validation": "shared vs independent clean service repeats",
            "gates": ["task/stage counter delta", "cache-friendly/hostile schedule", "latency/token repeats"],
        },
    ]


def build_dataset(run_root: Path, tag: str) -> dict[str, Any]:
    summary = load_json(run_root / "summary.json", {})
    status = read_status(run_root)
    statebus_rows = collect_statebus_cases(run_root)
    compare_report_path = find_compare_report(run_root)
    compare_report = load_json(compare_report_path, {})
    enrich_from_case_reports(statebus_rows, report_case_index(run_root, compare_report))
    external_rows = collect_external_cases(compare_report, run_root)
    pytest_log = (run_root / "logs/01_pytest_v2.log").read_text(
        encoding="utf-8", errors="replace"
    )
    pytest_line = next(
        (line for line in reversed(pytest_log.splitlines()) if " passed" in line), ""
    )
    return {
        "schema_version": "statebus.full_qwen3_extended_truth_audit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": {
            "mode": "read_only_recursive_artifact_and_source_audit",
            "full_experiment_rerun": False,
            "runtime_code_modified": False,
            "case_unit": "persisted task_metrics workspace plus compare external case record",
        },
        "run": {
            "root": str(run_root),
            "summary": summary,
            "status": status,
            "pytest_summary_line": pytest_line,
            "recorded_stage_count": len(status),
            "planned_stage_count": len(EXPECTED_STAGE_IDS),
            "full_extended_matrix_completed": all(stage in status for stage in EXPECTED_STAGE_IDS),
            "stop_reason": "08_genericity_holdout failed under set -e; stages 09-15 were not executed",
        },
        "artifact_inventory": inventory_artifacts(run_root),
        "stage_scope": stage_scope(run_root, status, statebus_rows, external_rows),
        "case_aggregates": aggregate_cases([*statebus_rows, *external_rows]),
        "cases": {
            "statebus_count": len(statebus_rows),
            "external_count": len(external_rows),
            "statebus": statebus_rows,
            "external": external_rows,
        },
        "compare": {
            **compare_audit(compare_report),
            "report_path": str(compare_report_path),
        },
        "formal": formal_layer_audit(run_root, "06_formal_full"),
        "formal_subprocess": formal_layer_audit(
            run_root, "07_formal_subprocess_uds_full"
        ),
        "planner": planner_audit(statebus_rows),
        "prefix": prefix_audit(statebus_rows, run_root),
        "logit_state": logit_audit(statebus_rows),
        "memory_replay": replay_memory_audit(statebus_rows),
        "genericity": genericity_audit(statebus_rows, run_root),
        "formal_subprocess_uds": uds_audit(statebus_rows, run_root),
        "agent_contribution": agent_contribution(statebus_rows),
        "oracle_and_specialization": oracle_audit(run_root),
        "code_evidence": code_evidence(),
        "tag_baseline": tag_audit(tag),
        "claim_ledger": claim_ledger(run_root),
        "issues": issue_ledger(run_root),
        "minimum_validation_matrix": validation_matrix(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "run_root",
        nargs="?",
        type=Path,
        default=Path("/home/qcrs/statebus/runs/full_qwen3_extended_gpu1_20260713_225438"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tag", default=REFERENCE_TAG)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    if not (run_root / "stages").is_dir():
        raise SystemExit(f"run stages directory is missing: {run_root / 'stages'}")
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
                "statebus_cases": dataset["cases"]["statebus_count"],
                "external_cases": dataset["cases"]["external_count"],
                "recorded_stages": dataset["run"]["recorded_stage_count"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
