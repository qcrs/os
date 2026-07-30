#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TOTAL_METRICS = (
    "task_ms",
    "llm_wall_ms",
    "llm_call_count",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "llm_prompt_bytes",
    "prompt_visible_total_bytes",
    "raw_evidence_bytes_seen_by_llm",
    "control_bytes",
    "total_wire_bytes",
    "semantic_state_bytes",
    "semantic_state_transfer_count",
    "semantic_state_consume_count",
    "semantic_state_release_count",
    "codeact_execution_stage_ms",
    "control_plane_exchange_stage_ms",
    "runtime_driver_stage_ms",
    "runtime_signature_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "telemetry_emit_stage_ms",
    "hybrid_memory_query_count",
    "memory_candidate_count",
    "memory_compatible_match_count",
    "memory_policy_approved_match_count",
    "memory_consumed_count",
    "memory_behavioral_effect_count",
    "memory_rejected_incompatible_count",
    "memory_assist_count",
    "validated_replay_count",
    "exact_replay_count",
    "reuse_gain",
    "skipped_step_count",
    "skipped_llm_call_count",
    "runtime_fallback_count",
)

COMPARISON_METRICS = (
    "operator_wall_ms",
    "task_ms",
    "llm_wall_ms",
    "runtime_non_llm_ms",
    "llm_call_count",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
    "total_wire_bytes",
    "control_bytes",
    "semantic_state_bytes",
    "control_plane_exchange_stage_ms",
    "codeact_execution_stage_ms",
    "runtime_driver_stage_ms",
    "runtime_signature_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "telemetry_emit_stage_ms",
    "hybrid_memory_query_count",
    "memory_candidate_count",
    "memory_compatible_match_count",
    "memory_policy_approved_match_count",
    "memory_consumed_count",
    "memory_behavioral_effect_count",
    "skipped_step_count",
    "skipped_llm_call_count",
)

PAIR_METRICS = tuple(metric for metric in COMPARISON_METRICS if metric != "operator_wall_ms")

STAGE_METRICS = (
    "control_plane_exchange_stage_ms",
    "codeact_execution_stage_ms",
    "runtime_driver_stage_ms",
    "runtime_signature_stage_ms",
    "persist_and_reload_stage_ms",
    "persist_retrieval_verification_stage_ms",
    "workspace_input_stage_ms",
    "workspace_output_stage_ms",
    "telemetry_emit_stage_ms",
)

MEMORY_METRICS = (
    "hybrid_memory_query_count",
    "memory_candidate_count",
    "memory_compatible_match_count",
    "memory_policy_approved_match_count",
    "memory_consumed_count",
    "memory_behavioral_effect_count",
    "memory_rejected_incompatible_count",
    "skipped_step_count",
    "skipped_llm_call_count",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _number(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return 0.0


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    if denominator == 0.0:
        return None
    return numerator / denominator


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _quality_pass(case: dict[str, Any]) -> bool:
    quality = case.get("quality_floor", {})
    return isinstance(quality, dict) and quality.get("quality_floor_pass") is True


def _case_key(case: dict[str, Any], report: dict[str, Any]) -> str:
    family = str(case.get("task_family") or report.get("task_family") or "unknown-family")
    return f"{family}::{case.get('task_id', 'unknown-task')}"


def _load_lane(lane_dir: Path, root: Path) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    manifest = _read_json(lane_dir / "lane_manifest.json")
    layer = str(manifest.get("layer", ""))
    reports: list[tuple[Path, dict[str, Any]]] = []

    runtime_root = lane_dir / "runtime"
    if not runtime_root.is_dir():
        issues.append(f"missing runtime directory: {runtime_root.relative_to(root)}")
    else:
        for report_path in sorted(runtime_root.rglob("*.json")):
            if report_path.parent.name != "benchmark_reports":
                continue
            try:
                payload = _read_json(report_path)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if payload.get("layer") != layer or not isinstance(payload.get("cases"), list):
                continue
            reports.append((report_path, payload))

    if not reports:
        issues.append(f"no family reports found for {lane_dir.relative_to(root)}")

    cases_by_key: dict[str, dict[str, Any]] = {}
    families: set[str] = set()
    report_files: list[str] = []
    for report_path, report in reports:
        report_files.append(str(report_path.relative_to(root)))
        families.add(str(report.get("task_family", "unknown-family")))
        for raw_case in report.get("cases", []):
            if not isinstance(raw_case, dict):
                continue
            key = _case_key(raw_case, report)
            if key in cases_by_key:
                issues.append(f"duplicate case {key} in {lane_dir.relative_to(root)}")
                continue
            metrics = raw_case.get("metrics", {})
            if not isinstance(metrics, dict):
                metrics = {}
            selected_metrics = {metric: _number(metrics.get(metric)) for metric in TOTAL_METRICS}
            selected_metrics["runtime_non_llm_ms"] = (
                selected_metrics["task_ms"] - selected_metrics["llm_wall_ms"]
            )
            cases_by_key[key] = {
                "task_key": key,
                "task_id": str(raw_case.get("task_id", "")),
                "task_family": str(raw_case.get("task_family") or report.get("task_family") or ""),
                "quality_floor_pass": _quality_pass(raw_case),
                "replay_class": str(raw_case.get("replay_class", "")),
                "metrics": selected_metrics,
            }

    totals = {metric: 0.0 for metric in TOTAL_METRICS}
    for case in cases_by_key.values():
        for metric in TOTAL_METRICS:
            totals[metric] += _number(case["metrics"].get(metric))
    totals["runtime_non_llm_ms"] = totals["task_ms"] - totals["llm_wall_ms"]

    timing_path = lane_dir / "operator_timing.json"
    operator_timing = _read_json(timing_path) if timing_path.is_file() else {}
    operator_wall_ms = _number(operator_timing.get("elapsed_ms"))
    totals["operator_wall_ms"] = operator_wall_ms
    if operator_timing and int(_number(operator_timing.get("exit_code"))) != 0:
        issues.append(f"non-zero runner exit in {lane_dir.relative_to(root)}")

    case_count = len(cases_by_key)
    quality_pass_count = sum(1 for case in cases_by_key.values() if case["quality_floor_pass"])
    task_times = [case["metrics"]["task_ms"] for case in cases_by_key.values()]

    queried_cases = [
        case for case in cases_by_key.values() if case["metrics"]["hybrid_memory_query_count"] > 0
    ]
    query_case_count = len(queried_cases)
    compatible_case_count = sum(
        1 for case in queried_cases if case["metrics"]["memory_compatible_match_count"] > 0
    )
    consumed_case_count = sum(
        1 for case in queried_cases if case["metrics"]["memory_consumed_count"] > 0
    )
    effect_case_count = sum(
        1 for case in queried_cases if case["metrics"]["memory_behavioral_effect_count"] > 0
    )
    skipped_work_case_count = sum(
        1
        for case in queried_cases
        if case["metrics"]["skipped_step_count"] > 0
        or case["metrics"]["skipped_llm_call_count"] > 0
    )

    lane = {
        **manifest,
        "lane_dir": str(lane_dir.relative_to(root)),
        "report_files": report_files,
        "family_count": len(families),
        "families": sorted(families),
        "case_count": case_count,
        "quality_pass_count": quality_pass_count,
        "quality_gate_pass": case_count > 0 and quality_pass_count == case_count,
        "task_ms_p50": _percentile(task_times, 0.50),
        "task_ms_p95": _percentile(task_times, 0.95),
        "totals": totals,
        "memory_case_rates": {
            "query_case_count": query_case_count,
            "compatible_case_count": compatible_case_count,
            "compatible_case_rate": _safe_ratio(compatible_case_count, query_case_count),
            "consumed_case_count": consumed_case_count,
            "consumed_case_rate": _safe_ratio(consumed_case_count, query_case_count),
            "effect_case_count": effect_case_count,
            "effect_case_rate": _safe_ratio(effect_case_count, query_case_count),
            "skipped_work_case_count": skipped_work_case_count,
            "skipped_work_case_rate": _safe_ratio(skipped_work_case_count, query_case_count),
        },
        "cases": [cases_by_key[key] for key in sorted(cases_by_key)],
    }
    return lane, issues


def _lane_case_map(lane: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case["task_key"]): case for case in lane["cases"]}


def _metric_delta(baseline: float, candidate: float) -> dict[str, float | None]:
    delta = candidate - baseline
    return {
        "baseline": baseline,
        "candidate": candidate,
        "delta": delta,
        "delta_pct": None if baseline == 0.0 else delta / baseline * 100.0,
    }


def _paired_distribution(rows: list[dict[str, Any]], metric: str) -> dict[str, Any]:
    eligible_rows = [row for row in rows if row.get("quality_pair_pass", True)]
    deltas = [_number(row["metrics"][metric]["delta"]) for row in eligible_rows]
    epsilon = 1e-6
    lower = sum(1 for value in deltas if value < -epsilon)
    higher = sum(1 for value in deltas if value > epsilon)
    ties = len(deltas) - lower - higher
    return {
        "pair_count": len(deltas),
        "quality_excluded_pair_count": len(rows) - len(eligible_rows),
        "mean_delta": statistics.fmean(deltas) if deltas else None,
        "median_delta": statistics.median(deltas) if deltas else None,
        "p50_delta": _percentile(deltas, 0.50),
        "p95_delta": _percentile(deltas, 0.95),
        "candidate_lower_count": lower,
        "candidate_higher_count": higher,
        "tie_count": ties,
        "candidate_lower_rate": _safe_ratio(lower, len(deltas)),
    }


def _build_comparison(
    *,
    experiment: str,
    cycle: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    baseline_cases = _lane_case_map(baseline)
    candidate_cases = _lane_case_map(candidate)
    common_keys = sorted(set(baseline_cases) & set(candidate_cases))
    task_set_match = set(baseline_cases) == set(candidate_cases)

    paired_rows: list[dict[str, Any]] = []
    for key in common_keys:
        baseline_case = baseline_cases[key]
        candidate_case = candidate_cases[key]
        paired_rows.append(
            {
                "task_key": key,
                "task_id": baseline_case["task_id"],
                "task_family": baseline_case["task_family"],
                "quality_pair_pass": bool(
                    baseline_case["quality_floor_pass"] and candidate_case["quality_floor_pass"]
                ),
                "metrics": {
                    metric: _metric_delta(
                        _number(baseline_case["metrics"].get(metric)),
                        _number(candidate_case["metrics"].get(metric)),
                    )
                    for metric in PAIR_METRICS
                },
            }
        )

    totals = {
        metric: _metric_delta(
            _number(baseline["totals"].get(metric)),
            _number(candidate["totals"].get(metric)),
        )
        for metric in COMPARISON_METRICS
    }
    paired_distributions = {
        metric: _paired_distribution(paired_rows, metric) for metric in PAIR_METRICS
    }
    quality_gate_pass = bool(
        task_set_match
        and common_keys
        and baseline["quality_gate_pass"]
        and candidate["quality_gate_pass"]
        and all(row["quality_pair_pass"] for row in paired_rows)
    )
    return {
        "experiment": experiment,
        "cycle": cycle,
        "baseline_layer": baseline["layer"],
        "candidate_layer": candidate["layer"],
        "task_set_match": task_set_match,
        "pair_count": len(common_keys),
        "quality_gate_pass": quality_gate_pass,
        "totals": totals,
        "paired_distributions": paired_distributions,
        "paired_rows": paired_rows,
    }


def _combined_comparison(
    experiment: str,
    comparisons: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not comparisons:
        return None
    totals: dict[str, dict[str, float | None]] = {}
    for metric in COMPARISON_METRICS:
        baseline = sum(_number(item["totals"][metric]["baseline"]) for item in comparisons)
        candidate = sum(_number(item["totals"][metric]["candidate"]) for item in comparisons)
        totals[metric] = _metric_delta(baseline, candidate)

    paired_rows = [row for comparison in comparisons for row in comparison["paired_rows"]]
    paired_distributions = {
        metric: _paired_distribution(paired_rows, metric) for metric in PAIR_METRICS
    }

    by_family: dict[str, dict[str, Any]] = {}
    families = sorted({str(row["task_family"]) for row in paired_rows})
    for family in families:
        family_rows = [row for row in paired_rows if row["task_family"] == family]
        by_family[family] = {
            "task_ms": _paired_distribution(family_rows, "task_ms"),
            "llm_wall_ms": _paired_distribution(family_rows, "llm_wall_ms"),
        }

    return {
        "experiment": experiment,
        "cycle_count": len(comparisons),
        "quality_gate_pass": all(item["quality_gate_pass"] for item in comparisons),
        "totals": totals,
        "paired_distributions": paired_distributions,
        "by_family": by_family,
    }


def _aggregate_lanes(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    totals = {metric: 0.0 for metric in (*TOTAL_METRICS, "runtime_non_llm_ms", "operator_wall_ms")}
    rates = {
        "query_case_count": 0,
        "compatible_case_count": 0,
        "consumed_case_count": 0,
        "effect_case_count": 0,
        "skipped_work_case_count": 0,
    }
    for lane in lanes:
        for metric in totals:
            totals[metric] += _number(lane["totals"].get(metric))
        for metric in rates:
            rates[metric] += int(lane["memory_case_rates"].get(metric, 0))
    query_cases = rates["query_case_count"]
    rates.update(
        {
            "compatible_case_rate": _safe_ratio(rates["compatible_case_count"], query_cases),
            "consumed_case_rate": _safe_ratio(rates["consumed_case_count"], query_cases),
            "effect_case_rate": _safe_ratio(rates["effect_case_count"], query_cases),
            "skipped_work_case_rate": _safe_ratio(rates["skipped_work_case_count"], query_cases),
        }
    )
    return {
        "lane_count": len(lanes),
        "case_count": sum(int(lane["case_count"]) for lane in lanes),
        "quality_pass_count": sum(int(lane["quality_pass_count"]) for lane in lanes),
        "totals": totals,
        "memory_case_rates": rates,
    }


def _format_float(value: object, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{_number(value):,.{digits}f}"


def _format_pct(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{_number(value):+.2f}%"


def _format_rate(value: object) -> str:
    if value is None:
        return "n/a"
    return f"{_number(value):.2f}%"


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# StateBus Supplemental Experiment Summary",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Result root: `{report['result_root']}`",
        f"- Mode: `{report['run_manifest'].get('mode', '')}`",
        f"- Overall quality gate: `{'PASS' if report['overall_quality_gate_pass'] else 'REVIEW'}`",
        "- P0 boundary: one AB/BA sanity cycle on the existing causal-core tasks; descriptive, not a significance campaign.",
        "- P1 boundary: L2 versus L3 current-stack sanity; not a frozen-snapshot or gate-only isolation.",
        "- Prefix boundary: shared vLLM/APC service state is held operationally fixed but is not attributed as a Prefix result.",
        "",
        "## Measured Lanes",
        "",
        "| experiment | cycle | order | layer | cases | quality | operator s | task s | LLM s | non-LLM s | tokens | wire bytes | memory q/use/effect |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for lane in report["lanes"]:
        totals = lane["totals"]
        lines.append(
            f"| {lane['experiment']} | {lane['cycle']} | {lane['order']} | {lane['layer']} | "
            f"{lane['case_count']} | {lane['quality_pass_count']}/{lane['case_count']} | "
            f"{_format_float(totals['operator_wall_ms'] / 1000.0)} | "
            f"{_format_float(totals['task_ms'] / 1000.0)} | "
            f"{_format_float(totals['llm_wall_ms'] / 1000.0)} | "
            f"{_format_float(totals['runtime_non_llm_ms'] / 1000.0)} | "
            f"{_format_float(totals['llm_total_tokens'], 0)} | {_format_float(totals['total_wire_bytes'], 0)} | "
            f"{_format_float(totals['hybrid_memory_query_count'], 0)}/"
            f"{_format_float(totals['memory_consumed_count'], 0)}/"
            f"{_format_float(totals['memory_behavioral_effect_count'], 0)} |"
        )

    latency = report.get("combined", {}).get("latency")
    if latency:
        lines.extend(
            [
                "",
                "## P0 L0 Versus L3",
                "",
                f"Quality-gated paired cases: `{latency['paired_distributions']['task_ms']['pair_count']}`. "
                f"L3 is faster in `{latency['paired_distributions']['task_ms']['candidate_lower_count']}` pairs.",
                "",
                "| metric | L0 total | L3 total | L3-L0 | delta |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for metric in (
            "operator_wall_ms",
            "task_ms",
            "llm_wall_ms",
            "runtime_non_llm_ms",
            "llm_total_tokens",
            "total_wire_bytes",
        ):
            item = latency["totals"][metric]
            lines.append(
                f"| {metric} | {_format_float(item['baseline'])} | {_format_float(item['candidate'])} | "
                f"{_format_float(item['delta'])} | {_format_pct(item['delta_pct'])} |"
            )
        paired = latency["paired_distributions"]["task_ms"]
        lines.extend(
            [
                "",
                "| paired task_ms statistic | value ms |",
                "| --- | ---: |",
                f"| mean L3-L0 | {_format_float(paired['mean_delta'])} |",
                f"| median L3-L0 | {_format_float(paired['median_delta'])} |",
                f"| p95 L3-L0 | {_format_float(paired['p95_delta'])} |",
                f"| L3 faster / tie / slower | {paired['candidate_lower_count']} / {paired['tie_count']} / {paired['candidate_higher_count']} |",
                "",
                "Stage spans below are diagnostic and may be parent/child spans; do not add them into a second total.",
                "",
                "| stage | L0 ms | L3 ms | delta ms | delta |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for metric in STAGE_METRICS:
            item = latency["totals"][metric]
            lines.append(
                f"| {metric} | {_format_float(item['baseline'])} | {_format_float(item['candidate'])} | "
                f"{_format_float(item['delta'])} | {_format_pct(item['delta_pct'])} |"
            )

    memory = report.get("combined", {}).get("memory")
    if memory:
        memory_l3 = report["memory_l3_aggregate"]
        lines.extend(
            [
                "",
                "## P1-lite L2 Versus L3",
                "",
                "This measures the current L2/L3 stack difference. It does not isolate gate-only overhead and does not claim a frozen memory snapshot.",
                "",
                "| metric | L2 total | L3 total | L3-L2 | delta |",
                "| --- | ---: | ---: | ---: | ---: |",
            ]
        )
        for metric in (
            "task_ms",
            "llm_wall_ms",
            "runtime_non_llm_ms",
            "llm_call_count",
            "llm_total_tokens",
            "total_wire_bytes",
            "skipped_step_count",
            "skipped_llm_call_count",
        ):
            item = memory["totals"][metric]
            lines.append(
                f"| {metric} | {_format_float(item['baseline'])} | {_format_float(item['candidate'])} | "
                f"{_format_float(item['delta'])} | {_format_pct(item['delta_pct'])} |"
            )
        lines.extend(
            [
                "",
                "| L3 memory funnel | count |",
                "| --- | ---: |",
            ]
        )
        for metric in MEMORY_METRICS:
            lines.append(f"| {metric} | {_format_float(memory_l3['totals'][metric], 0)} |")
        rates = memory_l3["memory_case_rates"]
        lines.extend(
            [
                "",
                "| Query-case rate | value |",
                "| --- | ---: |",
                f"| compatible case rate | {_format_rate(None if rates['compatible_case_rate'] is None else rates['compatible_case_rate'] * 100.0)} |",
                f"| consumed case rate | {_format_rate(None if rates['consumed_case_rate'] is None else rates['consumed_case_rate'] * 100.0)} |",
                f"| behavioral-effect case rate | {_format_rate(None if rates['effect_case_rate'] is None else rates['effect_case_rate'] * 100.0)} |",
                f"| skipped-work case rate | {_format_rate(None if rates['skipped_work_case_rate'] is None else rates['skipped_work_case_rate'] * 100.0)} |",
                "",
                "The incompatible-negative result is inherited from canonical E3 and is intentionally not rerun here.",
            ]
        )

    if report["issues"]:
        lines.extend(["", "## Review Issues", ""])
        lines.extend(f"- {issue}" for issue in report["issues"])

    lines.append("")
    return "\n".join(lines)


def summarize(root: Path) -> dict[str, Any]:
    root = root.resolve()
    run_manifest_path = root / "run_manifest.json"
    if not run_manifest_path.is_file():
        raise FileNotFoundError(f"missing run manifest: {run_manifest_path}")
    run_manifest = _read_json(run_manifest_path)

    lanes: list[dict[str, Any]] = []
    issues: list[str] = []
    for manifest_path in sorted(root.rglob("lane_manifest.json")):
        manifest = _read_json(manifest_path)
        if manifest.get("measured") is not True:
            continue
        lane, lane_issues = _load_lane(manifest_path.parent, root)
        lanes.append(lane)
        issues.extend(lane_issues)
        if not lane["quality_gate_pass"]:
            issues.append(
                f"quality gate failed in {lane['lane_dir']}: "
                f"{lane['quality_pass_count']}/{lane['case_count']} passed"
            )

    lanes.sort(key=lambda lane: (str(lane["experiment"]), str(lane["cycle"]), int(lane["order"])))
    mode = str(run_manifest.get("mode", ""))
    expected_experiments = (
        ("latency",) if mode == "latency" else ("memory",) if mode == "memory" else ("latency", "memory")
    )
    layer_pairs = {"latency": ("L0", "L3"), "memory": ("L2", "L3")}

    comparisons: dict[str, list[dict[str, Any]]] = {name: [] for name in expected_experiments}
    for experiment in expected_experiments:
        baseline_layer, candidate_layer = layer_pairs[experiment]
        for cycle in ("AB", "BA"):
            cycle_lanes = [
                lane for lane in lanes if lane["experiment"] == experiment and lane["cycle"] == cycle
            ]
            baseline_lanes = [lane for lane in cycle_lanes if lane["layer"] == baseline_layer]
            candidate_lanes = [lane for lane in cycle_lanes if lane["layer"] == candidate_layer]
            if len(baseline_lanes) != 1 or len(candidate_lanes) != 1:
                issues.append(
                    f"{experiment}/{cycle} expected one {baseline_layer} and one {candidate_layer} lane"
                )
                continue
            comparisons[experiment].append(
                _build_comparison(
                    experiment=experiment,
                    cycle=cycle,
                    baseline=baseline_lanes[0],
                    candidate=candidate_lanes[0],
                )
            )

    combined = {
        experiment: _combined_comparison(experiment, experiment_comparisons)
        for experiment, experiment_comparisons in comparisons.items()
    }
    quality_gates = [
        item["quality_gate_pass"]
        for experiment in expected_experiments
        for item in comparisons.get(experiment, [])
    ]
    expected_comparison_count = len(expected_experiments) * 2
    observed_comparison_count = sum(len(items) for items in comparisons.values())
    overall_quality_gate_pass = bool(
        not issues
        and observed_comparison_count == expected_comparison_count
        and quality_gates
        and all(quality_gates)
    )

    memory_l3_lanes = [
        lane for lane in lanes if lane["experiment"] == "memory" and lane["layer"] == "L3"
    ]
    report = {
        "schema_version": "statebus.contest_supplemental_summary.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "result_root": str(root),
        "run_manifest": run_manifest,
        "claim_boundaries": {
            "latency": "one_AB_BA_sanity_cycle_descriptive_only",
            "memory": "L2_L3_current_stack_not_frozen_snapshot_or_gate_only",
            "t2": "not_run_existing_E4_mechanism_evidence_is_sufficient_without_carrier_speed_claim",
            "prefix": "shared_service_APC_state_no_prefix_attribution",
        },
        "lanes": lanes,
        "comparisons": comparisons,
        "combined": combined,
        "memory_l3_aggregate": _aggregate_lanes(memory_l3_lanes),
        "issues": issues,
        "overall_quality_gate_pass": overall_quality_gate_pass,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize StateBus recovery supplemental experiments.")
    parser.add_argument("result_root", type=Path)
    args = parser.parse_args()

    report = summarize(args.result_root)
    output_json = args.result_root / "supplemental_summary.json"
    output_md = args.result_root / "supplemental_summary.md"
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_md.write_text(_render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
