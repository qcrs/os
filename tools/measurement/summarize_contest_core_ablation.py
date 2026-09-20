#!/usr/bin/env python3
"""Summarize one contest-core P2/P3/P4 ablation run.

The report is intentionally descriptive. It reads existing artifacts, keeps
missing metrics unavailable, and does not promote directional observations to
benchmark or statistical superiority claims.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _observed_number(value: Any) -> float | None:
    if _finite(value):
        return float(value)
    if (
        isinstance(value, Mapping)
        and value.get("status") == "observed"
        and _finite(value.get("value"))
    ):
        return float(value["value"])
    return None


def _stats(values: Iterable[Any]) -> dict[str, Any]:
    observed = [float(value) for value in values if _finite(value)]
    if not observed:
        return {"status": "unavailable", "count": 0, "value": None}
    return {
        "status": "observed",
        "count": len(observed),
        "total": sum(observed),
        "mean": statistics.fmean(observed),
        "median": statistics.median(observed),
        "minimum": min(observed),
        "maximum": max(observed),
    }


def _sum_observed(values: Iterable[Any]) -> dict[str, Any]:
    observed = [float(value) for value in values if _finite(value)]
    return {
        "status": "observed" if observed else "unavailable",
        "observed_count": len(observed),
        "value": sum(observed) if observed else None,
    }


def _lower_is_better(base: Any, candidate: Any) -> dict[str, Any]:
    if not _finite(base) or not _finite(candidate) or float(base) == 0.0:
        return {"status": "unavailable", "value": None, "direction": "unknown"}
    value = (float(base) - float(candidate)) / float(base) * 100.0
    direction = "improved" if value > 0 else "regressed" if value < 0 else "unchanged"
    return {"status": "observed", "value": value, "direction": direction}


def _matched_aggregate_improvement(
    base_metric: Mapping[str, Any],
    candidate_metric: Mapping[str, Any],
    *,
    aggregate_key: str,
) -> dict[str, Any]:
    base_count = base_metric.get("count")
    candidate_count = candidate_metric.get("count")
    if (
        not isinstance(base_count, int)
        or not isinstance(candidate_count, int)
        or base_count < 1
        or base_count != candidate_count
    ):
        return {
            "status": "unavailable",
            "value": None,
            "direction": "unknown",
            "reason": "observed_denominators_do_not_match",
            "base_observed_count": base_count,
            "candidate_observed_count": candidate_count,
        }
    result = _lower_is_better(
        base_metric.get(aggregate_key), candidate_metric.get(aggregate_key)
    )
    result["matched_observed_count"] = base_count
    return result


def _total(metric: Mapping[str, Any]) -> float | None:
    value = metric.get("total")
    return float(value) if _finite(value) else None


def _mean(metric: Mapping[str, Any]) -> float | None:
    value = metric.get("mean")
    return float(value) if _finite(value) else None


def _load_stage_status(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def summarize_p2(root: Path) -> dict[str, Any]:
    rows_path = root / "rows.json"
    if not rows_path.is_file():
        return {"status": "unavailable", "artifact_root": str(root)}
    rows = _read_json(rows_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_size: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        variant = str(row.get("variant", "unknown"))
        grouped[variant].append(row)
        size = str(row.get("matched_payload_id", "unknown")).split(":", 1)[0]
        by_size[size][variant].append(row)

    def project(group: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "row_count": len(group),
            "success_count": sum(row.get("terminal_class") == "success" for row in group),
            "quality_pass_count": sum(
                isinstance(row.get("quality"), Mapping)
                and row["quality"].get("passed") is True
                for row in group
            ),
            "control_bytes": _stats(row.get("control_bytes") for row in group),
            "wire_bytes": _stats(
                _observed_number(row.get("wire_bytes")) for row in group
            ),
            "critical_path_wall_ms": _stats(
                row.get("critical_path_wall_ms") for row in group
            ),
            "encode_ms": _stats(row.get("encode_ms") for row in group),
            "decode_ms": _stats(row.get("decode_ms") for row in group),
        }

    variants = {name: project(group) for name, group in sorted(grouped.items())}
    baseline = variants.get("utf8_text_inline", {})
    comparisons: dict[str, Any] = {}
    for name, metrics in variants.items():
        if name == "utf8_text_inline":
            continue
        comparisons[name] = {
            "control_bytes_reduction_pct": _matched_aggregate_improvement(
                baseline.get("control_bytes", {}),
                metrics.get("control_bytes", {}),
                aggregate_key="total",
            ),
            "wire_bytes_reduction_pct": _matched_aggregate_improvement(
                baseline.get("wire_bytes", {}),
                metrics.get("wire_bytes", {}),
                aggregate_key="total",
            ),
            "critical_path_improvement_pct": _matched_aggregate_improvement(
                baseline.get("critical_path_wall_ms", {}),
                metrics.get("critical_path_wall_ms", {}),
                aggregate_key="mean",
            ),
        }
    acceptance = (
        _read_json(root / "acceptance.json")
        if (root / "acceptance.json").is_file()
        else {}
    )
    return {
        "status": "observed",
        "artifact_root": str(root),
        "acceptance_status": acceptance.get("status", "unavailable"),
        "denominator": acceptance.get("denominator"),
        "variants": variants,
        "by_size": {
            size: {
                name: project(group) for name, group in sorted(size_groups.items())
            }
            for size, size_groups in sorted(by_size.items())
        },
        "comparisons_vs_utf8_text_inline": comparisons,
    }


def _p3_case_summary(suite_root: Path, row: Mapping[str, Any]) -> Mapping[str, Any]:
    path = (
        suite_root
        / "cases"
        / str(row.get("task_id", ""))
        / str(row.get("variant", ""))
        / "summary.json"
    )
    if not path.is_file():
        return {}
    payload = _read_json(path)
    return payload if isinstance(payload, Mapping) else {}


def summarize_p3(base: Path) -> dict[str, Any]:
    candidates = sorted(base.glob("semantic_state_ablation_*/summary.json"))
    if not candidates:
        return {"status": "unavailable", "artifact_root": str(base)}
    summary_path = candidates[-1]
    suite_root = summary_path.parent
    summary = _read_json(summary_path)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_row in summary.get("rows", []):
        row = dict(raw_row)
        case_summary = _p3_case_summary(suite_root, row)
        telemetry = case_summary.get("telemetry", {})
        usage = case_summary.get("usage", {})
        row["case_elapsed_ms"] = case_summary.get("elapsed_ms")
        row["prompt_tokens"] = (
            usage.get("prompt_tokens") if isinstance(usage, Mapping) else None
        )
        row["completion_tokens"] = (
            usage.get("completion_tokens") if isinstance(usage, Mapping) else None
        )
        row["total_tokens"] = (
            usage.get("total_tokens") if isinstance(usage, Mapping) else None
        )
        row["raw_evidence_bytes_seen_by_llm"] = (
            telemetry.get("raw_evidence_bytes_seen_by_llm")
            if isinstance(telemetry, Mapping)
            else None
        )
        row["selected_evidence_bytes"] = (
            telemetry.get("selected_evidence_bytes")
            if isinstance(telemetry, Mapping)
            else None
        )
        row["semantic_state_selected_bytes"] = (
            telemetry.get("semantic_state_selected_bytes")
            if isinstance(telemetry, Mapping)
            else None
        )
        grouped[str(row.get("variant", "unknown"))].append(row)

    variants: dict[str, Any] = {}
    for name, rows in sorted(grouped.items()):
        variants[name] = {
            "row_count": len(rows),
            "terminal_count": sum(row.get("terminal") is True for row in rows),
            "quality_pass_count": sum(row.get("quality_pass") is True for row in rows),
            "actual_use_count": sum(row.get("actual_use") is True for row in rows),
            "downstream_effect_count": sum(
                row.get("downstream_effect") is True for row in rows
            ),
            "provider_call_count": _stats(
                row.get("provider_call_count") for row in rows
            ),
            "elapsed_ms": _stats(row.get("case_elapsed_ms") for row in rows),
            "prompt_tokens": _stats(row.get("prompt_tokens") for row in rows),
            "completion_tokens": _stats(
                row.get("completion_tokens") for row in rows
            ),
            "total_tokens": _stats(row.get("total_tokens") for row in rows),
            "raw_evidence_bytes_seen_by_llm": _stats(
                row.get("raw_evidence_bytes_seen_by_llm") for row in rows
            ),
            "selected_evidence_bytes": _stats(
                row.get("selected_evidence_bytes") for row in rows
            ),
            "semantic_state_selected_bytes": _stats(
                row.get("semantic_state_selected_bytes") for row in rows
            ),
            "semantic_publish_count": _stats(
                row.get("semantic_publish_count") for row in rows
            ),
            "semantic_consume_count": _stats(
                row.get("semantic_consume_count") for row in rows
            ),
        }

    off = variants.get("off", {})
    on = variants.get("on", {})
    comparison = {
        "mean_elapsed_improvement_pct": _matched_aggregate_improvement(
            off.get("elapsed_ms", {}),
            on.get("elapsed_ms", {}),
            aggregate_key="mean",
        ),
        "total_token_reduction_pct": _matched_aggregate_improvement(
            off.get("total_tokens", {}),
            on.get("total_tokens", {}),
            aggregate_key="total",
        ),
        "prompt_token_reduction_pct": _matched_aggregate_improvement(
            off.get("prompt_tokens", {}),
            on.get("prompt_tokens", {}),
            aggregate_key="total",
        ),
        "provider_call_reduction_pct": _matched_aggregate_improvement(
            off.get("provider_call_count", {}),
            on.get("provider_call_count", {}),
            aggregate_key="total",
        ),
    }
    return {
        "status": "observed",
        "artifact_root": str(suite_root),
        "suite_ok": summary.get("ok"),
        "case_count": summary.get("case_count"),
        "denominator": summary.get("denominator"),
        "variants": variants,
        "comparison_on_vs_off": comparison,
    }


def summarize_p4_deterministic(base: Path) -> dict[str, Any]:
    epoch_roots = sorted(path.parent for path in base.glob("epoch-*/metrics.json"))
    if not epoch_roots:
        return {"status": "unavailable", "artifact_root": str(base)}
    epochs: list[dict[str, Any]] = []
    for epoch_root in epoch_roots:
        metrics = _read_json(epoch_root / "metrics.json")
        acceptance = (
            _read_json(epoch_root / "acceptance.json")
            if (epoch_root / "acceptance.json").is_file()
            else {}
        )
        epochs.append(
            {
                "epoch": epoch_root.name,
                "artifact_root": str(epoch_root),
                "acceptance_status": acceptance.get("status", "unavailable"),
                "denominator": acceptance.get("denominator"),
                "provider_work_avoided": _observed_number(
                    metrics.get("provider_work_avoided")
                ),
                "memory_actual_use": _observed_number(
                    metrics.get("memory_actual_use")
                ),
                "validated_replay": _observed_number(
                    metrics.get("validated_replay")
                ),
                "provider_calls_memory_off": _observed_number(
                    metrics.get("provider_boundary_calls", {}).get("memory_off")
                ),
                "provider_calls_validated_replay": _observed_number(
                    metrics.get("provider_boundary_calls", {}).get(
                        "validated_replay"
                    )
                ),
                "behavioral_effect_changed": _observed_number(
                    metrics.get("behavioral_effect", {}).get("changed")
                ),
                "behavioral_effect_no_effect": _observed_number(
                    metrics.get("behavioral_effect", {}).get("no_effect")
                ),
            }
        )
    baseline_calls = _sum_observed(
        epoch["provider_calls_memory_off"] for epoch in epochs
    )
    replay_calls = _sum_observed(
        epoch["provider_calls_validated_replay"] for epoch in epochs
    )
    denominator_fields = (
        "planned_pairs",
        "closed_pairs",
        "incomplete_pairs",
        "planned_measured_rows",
        "observed_measured_rows",
    )
    denominator = {
        field: _sum_observed(
            epoch.get("denominator", {}).get(field) for epoch in epochs
        )
        for field in denominator_fields
    }
    return {
        "status": "observed",
        "artifact_root": str(base),
        "epoch_count": len(epochs),
        "epochs": epochs,
        "aggregate": {
            "denominator": denominator,
            "provider_work_avoided": _sum_observed(
                epoch["provider_work_avoided"] for epoch in epochs
            ),
            "memory_actual_use": _sum_observed(
                epoch["memory_actual_use"] for epoch in epochs
            ),
            "validated_replay": _sum_observed(
                epoch["validated_replay"] for epoch in epochs
            ),
            "provider_calls_memory_off": baseline_calls,
            "provider_calls_validated_replay": replay_calls,
            "provider_call_reduction_pct": (
                _lower_is_better(
                    baseline_calls.get("value"), replay_calls.get("value")
                )
                if baseline_calls.get("observed_count")
                == replay_calls.get("observed_count")
                and baseline_calls.get("observed_count", 0) > 0
                else {
                    "status": "unavailable",
                    "value": None,
                    "direction": "unknown",
                    "reason": "observed_epoch_denominators_do_not_match",
                }
            ),
            "behavioral_effect_changed": _sum_observed(
                epoch["behavioral_effect_changed"] for epoch in epochs
            ),
            "behavioral_effect_no_effect": _sum_observed(
                epoch["behavioral_effect_no_effect"] for epoch in epochs
            ),
        },
    }


def _latest_live_root(base: Path) -> Path | None:
    candidates = [
        path
        for path in base.glob("g6b2-live-validation-*")
        if path.is_dir()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))


def _live_payload(root: Path | None) -> dict[str, Any]:
    if root is None:
        return {"status": "unavailable", "artifact_root": None}
    baseline_path = root / "live_baseline_rows.json"
    replay_path = root / "live_replay_rows.json"
    if not baseline_path.is_file() or not replay_path.is_file():
        return {"status": "partial", "artifact_root": str(root)}
    baseline_rows = _read_json(baseline_path).get("rows", [])
    replay_rows = _read_json(replay_path).get("rows", [])
    baseline_by_slot = {str(row.get("slot_id")): row for row in baseline_rows}
    replay_by_slot = {str(row.get("slot_id")): row for row in replay_rows}
    matched_slots = sorted(set(baseline_by_slot) & set(replay_by_slot))
    baseline_elapsed = [
        baseline_by_slot[slot].get("runtime_elapsed_ms") for slot in matched_slots
    ]
    replay_elapsed = [
        replay_by_slot[slot].get("runtime_elapsed_ms") for slot in matched_slots
    ]
    pair_speedups = []
    for slot in matched_slots:
        baseline = baseline_by_slot[slot].get("runtime_elapsed_ms")
        replay = replay_by_slot[slot].get("runtime_elapsed_ms")
        if _finite(baseline) and _finite(replay) and float(replay) != 0.0:
            pair_speedups.append(float(baseline) / float(replay))
    baseline_stats = _stats(baseline_elapsed)
    replay_stats = _stats(replay_elapsed)
    denominator = (
        _read_json(root / "live_failure_denominator.json")
        if (root / "live_failure_denominator.json").is_file()
        else None
    )
    acceptance = (
        _read_json(root / "g6b2_acceptance.json")
        if (root / "g6b2_acceptance.json").is_file()
        else {}
    )
    return {
        "status": "observed",
        "artifact_root": str(root),
        "acceptance_status": acceptance.get("status", "unavailable"),
        "matched_slot_count": len(matched_slots),
        "denominator": denominator,
        "baseline_runtime_elapsed_ms": baseline_stats,
        "replay_runtime_elapsed_ms": replay_stats,
        "runtime_improvement_pct": _lower_is_better(
            _total(baseline_stats), _total(replay_stats)
        ),
        "pair_speedup": _stats(pair_speedups),
        "baseline_provider_elapsed_ms": _stats(
            baseline_by_slot[slot]
            .get("provider_invocation_evidence", {})
            .get("provider_elapsed_ms")
            for slot in matched_slots
        ),
        "provider_not_started_count": sum(
            replay_by_slot[slot]
            .get("provider_not_started_observation", {})
            .get("provider_invocation_status")
            == "not_started"
            for slot in matched_slots
        ),
        "replay_consumer_provider_call_count": sum(
            int(replay_by_slot[slot].get("consumer_provider_boundary_call_count", 0))
            for slot in matched_slots
            if isinstance(
                replay_by_slot[slot].get("consumer_provider_boundary_call_count"),
                int,
            )
        ),
        "baseline_quality_pass_count": sum(
            baseline_by_slot[slot].get("quality_evidence", {}).get("passed") is True
            for slot in matched_slots
        ),
        "replay_quality_pass_count": sum(
            replay_by_slot[slot].get("quality_evidence", {}).get("passed") is True
            for slot in matched_slots
        ),
        "provider_tokens": {
            "status": "unsupported",
            "value": None,
            "reason": "live_rows_do_not_observe_provider_usage",
        },
    }


def summarize_p4_live(base: Path) -> dict[str, Any]:
    minimal = _live_payload(_latest_live_root(base / "minimal"))
    campaign = _live_payload(_latest_live_root(base / "campaign"))
    return {
        "status": (
            "observed"
            if campaign.get("status") == "observed"
            or minimal.get("status") == "observed"
            else "unavailable"
        ),
        "artifact_root": str(base),
        "minimal": minimal,
        "campaign": campaign,
    }


def _signal(metric: Any) -> bool | None:
    if not isinstance(metric, Mapping) or metric.get("status") != "observed":
        return None
    value = metric.get("value")
    return bool(_finite(value) and float(value) > 0.0)


def build_summary(run_root: Path) -> dict[str, Any]:
    p2 = summarize_p2(run_root / "p2")
    p3 = summarize_p3(run_root / "p3" / "runtime" / "semantic-state-ablation")
    p4_deterministic = summarize_p4_deterministic(run_root / "p4-deterministic")
    p4_live = summarize_p4_live(run_root / "p4-live")
    p2_comparisons = p2.get("comparisons_vs_utf8_text_inline", {})
    p3_comparison = p3.get("comparison_on_vs_off", {})
    p4_det_aggregate = p4_deterministic.get("aggregate", {})
    live_campaign = p4_live.get("campaign", {})
    live_observation = (
        live_campaign
        if live_campaign.get("status") == "observed"
        else p4_live.get("minimal", {})
    )
    return {
        "schema_version": "statebus.contest_core_ablation_benefit.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "claim_scope": "exploratory_benefit_observation",
        "correctness_gate_policy": "recorded_but_not_used_to_stop_orchestration",
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "stage_status": _load_stage_status(run_root / "stage_status.tsv"),
        "p2_low_overhead": p2,
        "p3_semantic_state": p3,
        "p4_memory_deterministic": p4_deterministic,
        "p4_memory_live": p4_live,
        "directional_signals": {
            "p2_protobuf_inline_lower_wire_bytes": _signal(
                p2_comparisons.get("typed_protobuf_inline", {}).get(
                    "wire_bytes_reduction_pct"
                )
            ),
            "p2_shm_ref_lower_wire_bytes": _signal(
                p2_comparisons.get("typed_protobuf_shm_ref", {}).get(
                    "wire_bytes_reduction_pct"
                )
            ),
            "p3_on_lower_mean_elapsed_ms": _signal(
                p3_comparison.get("mean_elapsed_improvement_pct")
            ),
            "p3_on_lower_total_tokens": _signal(
                p3_comparison.get("total_token_reduction_pct")
            ),
            "p4_deterministic_provider_calls_avoided": (
                bool(
                    _finite(
                        p4_det_aggregate.get("provider_work_avoided", {}).get(
                            "value"
                        )
                    )
                    and float(
                        p4_det_aggregate["provider_work_avoided"]["value"]
                    )
                    > 0.0
                )
                if p4_det_aggregate
                else None
            ),
            "p4_live_lower_runtime_elapsed_ms": _signal(
                live_observation.get("runtime_improvement_pct")
            ),
        },
        "interpretation_notes": [
            "Positive directional signals are observations, not superiority claims.",
            "Quality and validator results remain in source artifacts even though stage failures do not stop later stages.",
            "Live latency is diagnostic unless the operator provides an isolated GPU and controlled service conditions.",
            "Unsupported or missing metrics remain null and are never zero-filled.",
        ],
    }


def _fmt(value: Any, digits: int = 2) -> str:
    if not _finite(value):
        return "n/a"
    return f"{float(value):.{digits}f}"


def _metric_value(metric: Any, key: str = "value") -> Any:
    return metric.get(key) if isinstance(metric, Mapping) else None


def write_markdown(summary: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Contest-Core Full Ablation Benefit Summary",
        "",
        f"- Run root: `{summary['run_root']}`",
        "- Scope: exploratory directional benefit observation",
        "- Correctness/quality gates: recorded, but nonzero stages did not stop later stages",
        "- Benchmark superiority: `NOT_ESTABLISHED`",
        "",
        "## Stage Status",
        "",
        "| Stage | Outcome | Exit | Artifact root |",
        "| --- | --- | ---: | --- |",
    ]
    for row in summary.get("stage_status", []):
        lines.append(
            f"| {row.get('stage', '')} | {row.get('outcome', '')} | "
            f"{row.get('exit_code', '')} | `{row.get('artifact_root', '')}` |"
        )

    p2 = summary.get("p2_low_overhead", {})
    lines.extend(
        [
            "",
            "## P2 Low-Overhead Carrier",
            "",
            "| Variant | Rows | Mean wire bytes | Mean wall ms | Wire reduction vs UTF-8 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    comparisons = p2.get("comparisons_vs_utf8_text_inline", {})
    for name, metrics in p2.get("variants", {}).items():
        reduction = comparisons.get(name, {}).get("wire_bytes_reduction_pct", {})
        reduction_text = _fmt(_metric_value(reduction))
        if reduction_text != "n/a":
            reduction_text += "%"
        lines.append(
            f"| {name} | {metrics.get('row_count', 0)} | "
            f"{_fmt(_metric_value(metrics.get('wire_bytes'), 'mean'))} | "
            f"{_fmt(_metric_value(metrics.get('critical_path_wall_ms'), 'mean'))} | "
            f"{reduction_text} |"
        )

    p3 = summary.get("p3_semantic_state", {})
    lines.extend(
        [
            "",
            "## P3 SemanticState",
            "",
            "| Variant | Rows | Actual use | Mean elapsed ms | Total tokens | Quality pass |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name, metrics in p3.get("variants", {}).items():
        lines.append(
            f"| {name} | {metrics.get('row_count', 0)} | "
            f"{metrics.get('actual_use_count', 0)} | "
            f"{_fmt(_metric_value(metrics.get('elapsed_ms'), 'mean'))} | "
            f"{_fmt(_metric_value(metrics.get('total_tokens'), 'total'), 0)} | "
            f"{metrics.get('quality_pass_count', 0)} |"
        )
    p3_delta = p3.get("comparison_on_vs_off", {})
    lines.append(
        "\nOn vs off: mean elapsed improvement "
        f"`{_fmt(_metric_value(p3_delta.get('mean_elapsed_improvement_pct')))}%`, "
        "total token reduction "
        f"`{_fmt(_metric_value(p3_delta.get('total_token_reduction_pct')))}%`."
    )

    p4_det = summary.get("p4_memory_deterministic", {}).get("aggregate", {})
    lines.extend(
        [
            "",
            "## P4 Memory Deterministic",
            "",
            f"- Provider work avoided: `{_fmt(_metric_value(p4_det.get('provider_work_avoided')), 0)}`",
            f"- Memory actual use: `{_fmt(_metric_value(p4_det.get('memory_actual_use')), 0)}`",
            f"- Baseline provider calls: `{_fmt(_metric_value(p4_det.get('provider_calls_memory_off')), 0)}`",
            f"- Replay provider calls: `{_fmt(_metric_value(p4_det.get('provider_calls_validated_replay')), 0)}`",
            "- Provider call reduction: "
            f"`{_fmt(_metric_value(p4_det.get('provider_call_reduction_pct')))}%`",
        ]
    )

    p4_live = summary.get("p4_memory_live", {})
    live = p4_live.get("campaign", {})
    if live.get("status") != "observed":
        live = p4_live.get("minimal", {})
    lines.extend(
        [
            "",
            "## P4 Memory Live",
            "",
            f"- Artifact: `{live.get('artifact_root') or 'n/a'}`",
            f"- Matched slots: `{live.get('matched_slot_count', 0)}`",
            f"- Provider-not-started observations: `{live.get('provider_not_started_count', 0)}`",
            "- Baseline mean runtime: "
            f"`{_fmt(_metric_value(live.get('baseline_runtime_elapsed_ms'), 'mean'))} ms`",
            "- Replay mean runtime: "
            f"`{_fmt(_metric_value(live.get('replay_runtime_elapsed_ms'), 'mean'))} ms`",
            "- Runtime improvement: "
            f"`{_fmt(_metric_value(live.get('runtime_improvement_pct')))}%`",
            "",
            "## Interpretation Boundary",
            "",
            "This report is an exploratory benefit observation. It does not establish benchmark or statistical superiority. Missing metrics remain unavailable, and live latency is diagnostic under shared-GPU conditions.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize a contest-core full ablation run without rerunning it."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    if not run_root.is_dir():
        parser.error(f"run root not found: {run_root}")
    summary = build_summary(run_root)
    json_path = run_root / "benefit_summary.json"
    markdown_path = run_root / "benefit_summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_markdown(summary, markdown_path)
    print(json.dumps({"json": str(json_path), "markdown": str(markdown_path)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
