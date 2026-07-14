#!/usr/bin/env python3
"""Analyze a completed StateBus Qwen3 full-suite run without mutating it."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta
import json
from pathlib import Path
import statistics
from typing import Any, Iterable


ORACLE_TERMS = (
    '"expected_facts"',
    '"expected_route"',
    '"expected_tool_name"',
    '"oracle_answer"',
    '"correctness_hint"',
)
ROLE_VISIBLE_PATTERNS = (
    "inputs/canonical_task_spec.json",
    "inputs/planner_handoff.json",
    "inputs/*.codeact_bundle.json",
    "logs/prompt_slices/*.json",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def ratio(numerator: float, denominator: float) -> float | None:
    if not denominator:
        return None
    return numerator / denominator


def pct_delta(delta: float, baseline: float) -> float | None:
    value = ratio(delta, baseline)
    return None if value is None else value * 100.0


def numeric(values: Iterable[float]) -> dict[str, float | int | None]:
    items = list(values)
    if not items:
        return {"count": 0, "min": None, "max": None, "mean": None, "median": None}
    return {
        "count": len(items),
        "min": min(items),
        "max": max(items),
        "mean": statistics.fmean(items),
        "median": statistics.median(items),
    }


def stage_durations(run_log: Path) -> dict[str, float]:
    starts: dict[str, datetime] = {}
    durations: dict[str, float] = {}
    day = datetime(2000, 1, 1)
    for line in run_log.read_text(encoding="utf-8").splitlines():
        if not line.startswith("[") or "] " not in line:
            continue
        stamp, message = line[1:].split("] ", 1)
        try:
            current = datetime.combine(day.date(), datetime.strptime(stamp, "%H:%M:%S").time())
        except ValueError:
            continue
        parts = message.split()
        if len(parts) != 2 or parts[0] not in {"START", "PASS"}:
            continue
        action, stage = parts
        if action == "START":
            starts[stage] = current
            continue
        start = starts.get(stage)
        if start is None:
            continue
        if current < start:
            current += timedelta(days=1)
        durations[stage] = (current - start).total_seconds()
    return durations


def summarize_layer(layer: dict[str, Any]) -> dict[str, Any]:
    metrics = layer.get("telemetry_summary", {})
    aggregate = layer.get("aggregated_metrics", {})
    cases = layer.get("cases", [])
    hits = float(metrics.get("neural_prefix_cache_hit_count_estimate", 0.0))
    queries = float(metrics.get("neural_prefix_cache_query_count_estimate", 0.0))
    return {
        "layer": layer.get("layer"),
        "case_count": int(aggregate.get("case_count", len(layer.get("cases", []))) or 0),
        "quality_pass_count": int(aggregate.get("quality_floor_pass_count", 0) or 0),
        "llm_prompt_tokens": float(metrics.get("llm_prompt_tokens", 0.0)),
        "llm_completion_tokens": float(metrics.get("llm_completion_tokens", 0.0)),
        "llm_total_tokens": float(metrics.get("llm_total_tokens", 0.0)),
        "llm_wall_ms": float(metrics.get("llm_wall_ms", 0.0)),
        "task_ms": float(metrics.get("task_ms", 0.0)),
        "control_bytes": float(metrics.get("control_bytes", 0.0)),
        "semantic_state_transfer_count": float(metrics.get("semantic_state_transfer_count", 0.0)),
        "shared_memory_publish_count": float(metrics.get("shared_memory_publish_count", 0.0)),
        "memory_match_count": float(metrics.get("memory_match_count", 0.0)),
        "memory_commit_count": float(metrics.get("memory_commit_count", 0.0)),
        "artifact_reuse_count": float(metrics.get("artifact_reuse_count", 0.0)),
        "history_reuse_gain": float(metrics.get("history_reuse_gain", 0.0)),
        "history_step_reduction_count": float(metrics.get("history_step_reduction_count", 0.0)),
        "validated_replay_count": float(metrics.get("validated_replay_count", 0.0)),
        "exact_replay_count": float(metrics.get("exact_replay_count", 0.0)),
        "skipped_step_count": float(metrics.get("skipped_step_count", 0.0)),
        "planner_call_count": float(metrics.get("planner_call_count", 0.0)),
        "retriever_call_count": float(metrics.get("retriever_call_count", 0.0)),
        "executor_call_count": float(metrics.get("executor_call_count", 0.0)),
        "summarizer_call_count": float(metrics.get("summarizer_call_count", 0.0)),
        "codeact_plan_stage_count": float(metrics.get("codeact_plan_stage_count", 0.0)),
        "codeact_plan_action_count": float(metrics.get("codeact_plan_action_count", 0.0)),
        "codeact_sandbox_bwrap_count": float(metrics.get("codeact_sandbox_bwrap_count", 0.0)),
        "codeact_sandbox_fallback_count": float(metrics.get("codeact_sandbox_fallback_count", 0.0)),
        "logit_state_transfer_count": float(metrics.get("logit_state_transfer_count", 0.0)),
        "prefix_hit_count_estimate": hits,
        "prefix_query_count_estimate": queries,
        "prefix_hit_rate_recomputed": ratio(hits, queries),
        "prefix_hit_rate_aggregated_field": float(
            metrics.get("neural_prefix_cache_hit_rate_estimate", 0.0)
        ),
        "runtime_fallback_count": float(metrics.get("runtime_fallback_count", 0.0)),
        "invalidated_artifact_count": float(metrics.get("invalidated_artifact_count", 0.0)),
        "task_ms_present": "task_ms" in metrics,
        "role_call_audit": role_call_audit(cases),
    }


def summarize_continuous(payload: dict[str, Any]) -> dict[str, Any]:
    l3 = payload["layers"][3]
    rounds = []
    for case in l3.get("cases", []):
        metrics = case.get("metrics", {})
        rounds.append(
            {
                "task_id": case.get("task_id"),
                "quality_pass": bool(case.get("quality_floor", {}).get("quality_floor_pass")),
                "replay_class": case.get("replay_class"),
                "memory_match_count": float(metrics.get("memory_match_count", 0.0)),
                "artifact_reuse_count": float(metrics.get("artifact_reuse_count", 0.0)),
                "history_reuse_gain": float(metrics.get("history_reuse_gain", 0.0)),
                "history_step_reduction_count": float(
                    metrics.get("history_step_reduction_count", 0.0)
                ),
                "validated_replay_count": float(metrics.get("validated_replay_count", 0.0)),
                "skipped_step_count": float(metrics.get("skipped_step_count", 0.0)),
                "llm_prompt_tokens": float(metrics.get("llm_prompt_tokens", 0.0)),
                "llm_total_tokens": float(metrics.get("llm_total_tokens", 0.0)),
                "llm_wall_ms": float(metrics.get("llm_wall_ms", 0.0)),
                "task_ms": float(metrics.get("task_ms", 0.0)),
                "role_call_counts": {
                    role: float(metrics.get(f"{role}_call_count", 0.0))
                    for role in ("planner", "retriever", "executor", "summarizer")
                },
            }
        )
    return {
        "family_id": payload.get("metadata", {}).get("family_id"),
        "selected_round_count": payload.get("selected_round_count"),
        "available_round_count": payload.get("available_round_count"),
        "execution_scope": payload.get("execution_scope"),
        "eligible_for_quality_headline": payload.get("eligible_for_quality_headline"),
        "eligible_for_replay_headline": payload.get("eligible_for_replay_headline"),
        "comparison_summary": payload.get("comparison_summary", {}),
        "waterfall_metrics": payload.get("waterfall_metrics", {}),
        "layers": [summarize_layer(layer) for layer in payload.get("layers", [])],
        "rounds_l3": rounds,
    }


def scan_role_visible_surfaces(stage_roots: Iterable[Path]) -> dict[str, Any]:
    paths: set[Path] = set()
    for stage_root in stage_roots:
        workspace_root = stage_root / "workspaces"
        if not workspace_root.exists():
            continue
        for pattern in ROLE_VISIBLE_PATTERNS:
            paths.update(workspace_root.rglob(pattern))
    findings = []
    surface_counts: Counter[str] = Counter()
    prompt_slice_role_counts: Counter[str] = Counter()
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.name == "canonical_task_spec.json":
            surface_counts["canonical_task_spec"] += 1
        elif path.name == "planner_handoff.json":
            surface_counts["planner_handoff"] += 1
        elif path.name.endswith(".codeact_bundle.json"):
            surface_counts["codeact_bundle"] += 1
        elif path.name.endswith(".prompt_slice.json"):
            surface_counts["prompt_slice"] += 1
            prompt_slice_role_counts[path.name.removesuffix(".prompt_slice.json")] += 1
        matches = [term for term in ORACLE_TERMS if term in text]
        if matches:
            findings.append({"path": str(path), "terms": matches})
    return {
        "scanned_file_count": len(paths),
        "oracle_match_count": len(findings),
        "matches": findings,
        "surface_counts": dict(sorted(surface_counts.items())),
        "prompt_slice_role_counts": dict(sorted(prompt_slice_role_counts.items())),
    }


def role_call_audit(cases: Iterable[dict[str, Any]]) -> dict[str, Any]:
    case_list = list(cases)
    violations = []
    totals = Counter()
    for case in case_list:
        metrics = case.get("metrics", {})
        observed = {
            role: float(metrics.get(f"{role}_call_count", 0.0))
            for role in ("planner", "retriever", "executor", "summarizer")
        }
        totals.update(observed)
        if any(value != 1.0 for value in observed.values()):
            violations.append({"task_id": case.get("task_id"), "role_calls": observed})
    return {
        "case_count": len(case_list),
        "all_cases_exactly_one_call_per_role": not violations,
        "violation_count": len(violations),
        "violations": violations,
        "totals": dict(sorted(totals.items())),
    }


def logit_summary(layers: Iterable[dict[str, Any]]) -> dict[str, Any]:
    observations = []
    for layer in layers:
        for case in layer.get("cases", []):
            metrics = case.get("metrics", {})
            if not metrics.get("logit_state_transfer_count"):
                continue
            peak = int(metrics.get("logit_peak_position", -1))
            length = int(metrics.get("logit_sequence_length", 0))
            observations.append(
                {
                    "task_id": case.get("task_id"),
                    "layer": layer.get("layer"),
                    "peak_position": peak,
                    "sequence_length": length,
                    "peak_is_last": bool(length > 0 and peak == length - 1),
                    "varentropy": float(metrics.get("logit_varentropy", 0.0)),
                    "top_gap": float(metrics.get("logit_top_gap", 0.0)),
                    "decision_entropy": float(metrics.get("logit_decision_entropy", -1.0)),
                }
            )
    return {
        "observation_count": len(observations),
        "peak_is_last_count": sum(1 for item in observations if item["peak_is_last"]),
        "peak_before_last_count": sum(1 for item in observations if not item["peak_is_last"]),
        "varentropy": numeric(item["varentropy"] for item in observations),
        "top_gap": numeric(item["top_gap"] for item in observations),
        "decision_entropy": numeric(item["decision_entropy"] for item in observations),
    }


def compare_summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report["comparison_summary"]
    statebus_cases = report["statebus_report"]["cases"]
    external_cases = report["external_report"]["cases"]
    statebus_by_id = {case["task_id"]: case for case in statebus_cases}
    external_by_id = {case["task_id"]: case for case in external_cases}
    faster = Counter()
    case_deltas = []
    prompt_token_deltas = []
    for task_id in sorted(statebus_by_id.keys() & external_by_id.keys()):
        statebus_ms = float(statebus_by_id[task_id]["metrics"].get("task_ms", 0.0))
        external_ms = float(external_by_id[task_id]["metrics"].get("task_ms", 0.0))
        delta = statebus_ms - external_ms
        faster["statebus" if delta < 0 else "external" if delta > 0 else "tie"] += 1
        case_deltas.append(delta)
        statebus_prompt_tokens = float(
            statebus_by_id[task_id]["metrics"].get(
                "prompt_tokens",
                statebus_by_id[task_id]["metrics"].get("llm_prompt_tokens", 0.0),
            )
        )
        external_prompt_tokens = float(
            external_by_id[task_id]["metrics"].get(
                "prompt_tokens",
                external_by_id[task_id]["metrics"].get("llm_prompt_tokens", 0.0),
            )
        )
        prompt_token_deltas.append(statebus_prompt_tokens - external_prompt_tokens)
    external_metrics = report["external_report"]["telemetry_summary"]
    statebus_metrics = report["statebus_report"]["telemetry_summary"]
    external_fairness = report["external_report"]["aggregated_metrics"]
    fairness_manifest = report.get("fairness_manifest", {})
    return {
        "claim_level": report.get("claim_level"),
        "comparison_valid": report.get("comparison_valid"),
        "strict_equal_quality": bool(summary.get("strict_equal_quality_comparison_valid")),
        "case_count": int(summary.get("case_count", 0)),
        "statebus_quality_pass_count": int(
            report["statebus_report"]["aggregated_metrics"].get("quality_floor_pass_count", 0)
        ),
        "external_quality_pass_count": int(
            report["external_report"]["aggregated_metrics"].get("quality_floor_pass_count", 0)
        ),
        "external_fairness_pass_count": int(
            external_fairness.get("external_fairness_gate_pass_count", 0)
        ),
        "external_contamination_detected_count": int(
            external_metrics.get("contamination_detected", 0)
        ),
        "fairness_hard_gate_pass": fairness_manifest.get("pass_hard_gate"),
        "no_external_contamination": fairness_manifest.get("no_external_contamination"),
        "external_uses_internal_helpers": fairness_manifest.get("external_uses_internal_helpers"),
        "statebus_role_call_audit": role_call_audit(statebus_cases),
        "external_role_call_audit": role_call_audit(external_cases),
        "statebus_prompt_tokens": float(summary.get("statebus_prompt_tokens", 0.0)),
        "external_prompt_tokens": float(summary.get("external_prompt_tokens", 0.0)),
        "prompt_tokens_delta": float(summary.get("prompt_tokens_delta", 0.0)),
        "prompt_tokens_delta_pct_of_external": pct_delta(
            float(summary.get("prompt_tokens_delta", 0.0)),
            float(summary.get("external_prompt_tokens", 0.0)),
        ),
        "statebus_total_tokens": float(summary.get("statebus_llm_total_tokens", 0.0)),
        "external_total_tokens": float(summary.get("external_llm_total_tokens", 0.0)),
        "total_tokens_delta": float(summary.get("llm_total_tokens_delta", 0.0)),
        "total_tokens_delta_pct_of_external": pct_delta(
            float(summary.get("llm_total_tokens_delta", 0.0)),
            float(summary.get("external_llm_total_tokens", 0.0)),
        ),
        "completion_tokens_delta": float(summary.get("completion_tokens_delta", 0.0)),
        "task_ms_delta": float(summary.get("task_ms_delta", 0.0)),
        "task_ms_delta_pct_of_external": pct_delta(
            float(summary.get("task_ms_delta", 0.0)),
            float(external_metrics.get("task_ms", 0.0)),
        ),
        "llm_ms_delta": float(summary.get("llm_ms_delta", 0.0)),
        "system_overhead_ms_delta": float(summary.get("system_overhead_ms_delta", 0.0)),
        "statebus_task_ms": float(statebus_metrics.get("task_ms", 0.0)),
        "external_task_ms": float(external_metrics.get("task_ms", 0.0)),
        "per_case_faster_count": dict(faster),
        "per_case_task_ms_delta": numeric(case_deltas),
        "per_case_prompt_token_delta": numeric(prompt_token_deltas),
        "statebus_prompt_token_lower_case_count": sum(
            1 for value in prompt_token_deltas if value < 0
        ),
        "statebus_role_calls": {
            role: float(statebus_metrics.get(f"{role}_call_count", 0.0))
            for role in ("planner", "retriever", "executor", "summarizer")
        },
        "external_role_calls": {
            role: float(external_metrics.get(f"{role}_call_count", 0.0))
            for role in ("planner", "retriever", "executor", "summarizer")
        },
        "external_public_tool_execution_count": float(
            external_metrics.get("public_tool_execution_count", 0.0)
        ),
        "external_public_tool_success_count": float(
            external_metrics.get("public_tool_execution_success_count", 0.0)
        ),
    }


def build_dataset(run_root: Path) -> dict[str, Any]:
    summary = load_json(run_root / "summary.json")
    stage_payloads = {
        path.parent.name: load_json(path)
        for path in sorted((run_root / "stages").glob("*/stdout.json"))
    }
    compare_report_path = next(
        (run_root / "stages/02_compare_full/runtime/benchmark_reports").glob(
            "*-compare-local_vllm.json"
        )
    )
    compare_report = load_json(compare_report_path)
    replay = stage_payloads["03_replay_full"]
    csv_continuous = stage_payloads["04_continuous_csv_full"]
    cross_continuous = stage_payloads["05_continuous_cross_full"]
    formal = stage_payloads["06_formal_full"]
    pytest_log = (run_root / "logs/01_pytest_v2.log").read_text(encoding="utf-8")
    warning_lines = []
    for path in sorted((run_root / "logs").glob("*.stderr.log")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip() and line.strip() not in warning_lines:
                warning_lines.append(line.strip())

    formal_layers = [summarize_layer(layer) for layer in formal.get("layers", [])]
    formal_l0 = formal_layers[0]
    formal_l3 = formal_layers[3]
    formal_token_delta = formal_l3["llm_total_tokens"] - formal_l0["llm_total_tokens"]
    replay_layer = summarize_layer(replay)
    role_scan = scan_role_visible_surfaces(
        run_root / "stages" / stage
        for stage in (
            "02_compare_full",
            "03_replay_full",
            "04_continuous_csv_full",
            "05_continuous_cross_full",
            "06_formal_full",
        )
    )
    return {
        "schema_version": "statebus.full_qwen3_run_analysis.v1",
        "run_root": str(run_root),
        "suite_summary": summary,
        "stage_durations_s": stage_durations(run_root / "run.log"),
        "pytest": {
            "passed": "296 passed" in pytest_log,
            "summary_line": next(
                (line for line in reversed(pytest_log.splitlines()) if " passed" in line),
                "",
            ),
        },
        "compare": compare_summary(compare_report),
        "replay": {
            "execution_scope": replay.get("execution_scope"),
            "formal_headline_eligible": replay.get("formal_headline_eligible"),
            "eligible_for_headline": replay.get("eligible_for_headline"),
            "selected_case_count": replay.get("selected_case_count"),
            "available_case_count": replay.get("available_case_count"),
            "quality_floor_breakdown": replay.get("quality_floor_breakdown", {}),
            "replay_class_distribution": replay.get("replay_class_distribution", {}),
            "effective_replay_history_source": replay.get("effective_replay_history_source"),
            "layer": replay_layer,
            "metadata": replay.get("metadata", {}),
        },
        "continuous": {
            "csv_table_profile": summarize_continuous(csv_continuous),
            "cross_period_financial": summarize_continuous(cross_continuous),
        },
        "formal": {
            "selected_case_count": formal.get("selected_case_count"),
            "available_case_count": formal.get("available_case_count"),
            "family_count": formal.get("family_count"),
            "families": formal.get("families", []),
            "formal_headline_eligible": formal.get("formal_headline_eligible"),
            "layers": formal_layers,
            "text_l0_vs_protocol_l3": {
                "quality_pass_delta": formal.get("protocol_vs_text_quality_pass_delta"),
                "total_tokens_delta": formal_token_delta,
                "total_tokens_delta_pct_of_l0": pct_delta(
                    formal_token_delta, formal_l0["llm_total_tokens"]
                ),
                "prompt_tokens_delta": formal.get("protocol_vs_text_prompt_token_delta"),
                "prompt_bytes_delta": formal.get("protocol_vs_text_prompt_bytes_delta"),
                "control_bytes_delta": formal.get("protocol_vs_text_control_bytes_delta"),
            },
            "logit": logit_summary(formal.get("layers", [])),
            "metadata": formal.get("metadata", {}),
        },
        "role_visible_oracle_scan": role_scan,
        "stderr_unique_lines": warning_lines,
        "known_interpretation_limits": [
            "compare is serialized first-pass repeat_count=1, not a repeated statistical estimate",
            "prefix cache hit fields are estimates; aggregated rate fields are sums and must be recomputed",
            "this completed artifact predates the reporting fix and omits task_ms in formal and continuous layers; stage wall time and llm_wall_ms remain",
            "CodeAct uses deterministic plans/scripts and resource sandbox fallback, not LLM-authored code in bwrap",
            "replay full stage is a single-layer diagnostic with history bootstrap, not a formal headline",
            "formal full stage uses loopback executor transport, not subprocess UDS transport",
        ],
        "source_paths": {
            "summary": str(run_root / "summary.json"),
            "compare_report": str(compare_report_path),
            "replay": str(run_root / "stages/03_replay_full/stdout.json"),
            "continuous_csv": str(run_root / "stages/04_continuous_csv_full/stdout.json"),
            "continuous_cross": str(run_root / "stages/05_continuous_cross_full/stdout.json"),
            "formal": str(run_root / "stages/06_formal_full/stdout.json"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = build_dataset(args.run_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "output": str(args.output), "run_root": str(args.run_root)}))


if __name__ == "__main__":
    main()
