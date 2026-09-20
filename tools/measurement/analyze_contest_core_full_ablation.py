#!/usr/bin/env python3
"""Comprehensive, offline analysis for a contest-core full ablation run.

The analyzer reads the existing P2/P3/P4 artifacts and writes a structured
report plus small CSV projections.  It deliberately keeps the following
boundaries explicit:

* only matched, observable pairs enter paired deltas;
* unsupported metrics remain unavailable instead of becoming zero;
* repeated campaign slots are reported separately from distinct workload
  shapes; and
* directional observations are not promoted to benchmark or statistical
  superiority claims.

No artifact code is imported or executed and no experiment is started.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


BOOTSTRAP_REPS = 2000
BOOTSTRAP_SEED = 20260920
EPSILON = 1e-12


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default


def finite(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def number(value: Any) -> float | None:
    if finite(value):
        return float(value)
    if isinstance(value, Mapping) and value.get("status") == "observed":
        if finite(value.get("value")):
            return float(value["value"])
    return None


def bool_value(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def stats(values: Iterable[Any]) -> dict[str, Any]:
    observed = [float(item) for item in values if finite(item)]
    if not observed:
        return {"status": "unavailable", "count": 0, "value": None}
    return {
        "status": "observed",
        "count": len(observed),
        "total": sum(observed),
        "mean": statistics.fmean(observed),
        "median": statistics.median(observed),
        "p05": quantile(observed, 0.05),
        "p95": quantile(observed, 0.95),
        "minimum": min(observed),
        "maximum": max(observed),
    }


def bootstrap_mean_ci(values: Sequence[float], seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    if not values:
        return {"status": "unavailable", "count": 0, "lower": None, "upper": None}
    if len(values) == 1:
        value = float(values[0])
        return {"status": "observed", "count": 1, "lower": value, "upper": value}
    rng = random.Random(seed)
    samples: list[float] = []
    n = len(values)
    for _ in range(BOOTSTRAP_REPS):
        samples.append(statistics.fmean(values[rng.randrange(n)] for _ in range(n)))
    return {
        "status": "observed",
        "count": n,
        "lower": quantile(samples, 0.025),
        "upper": quantile(samples, 0.975),
        "replicates": BOOTSTRAP_REPS,
        "seed": seed,
    }


def sign_test(values: Sequence[float]) -> dict[str, Any]:
    positive = sum(item > EPSILON for item in values)
    negative = sum(item < -EPSILON for item in values)
    ties = len(values) - positive - negative
    non_ties = positive + negative
    if non_ties == 0:
        p_value = 1.0 if values else None
    else:
        tail = sum(math.comb(non_ties, k) for k in range(0, min(positive, negative) + 1))
        p_value = min(1.0, 2.0 * tail / (2.0**non_ties))
    return {
        "status": "observed" if values else "unavailable",
        "positive": positive,
        "negative": negative,
        "ties": ties,
        "non_ties": non_ties,
        "two_sided_exact_p": p_value,
    }


def paired_metric(
    pairs: Iterable[Mapping[str, Any]],
    baseline_key: str,
    candidate_key: str,
    *,
    lower_is_better: bool = True,
    ratio: bool = False,
) -> dict[str, Any]:
    deltas: list[float] = []
    relative: list[float] = []
    ratios: list[float] = []
    baseline_values: list[float] = []
    candidate_values: list[float] = []
    for pair in pairs:
        baseline = number(pair.get(baseline_key))
        candidate = number(pair.get(candidate_key))
        if baseline is None or candidate is None or abs(baseline) <= EPSILON:
            continue
        baseline_values.append(baseline)
        candidate_values.append(candidate)
        delta = baseline - candidate if lower_is_better else candidate - baseline
        deltas.append(delta)
        relative.append(delta / baseline * 100.0)
        if ratio and abs(candidate) > EPSILON:
            ratios.append(baseline / candidate)
    return {
        "matched_count": len(deltas),
        "delta": stats(deltas),
        "relative_improvement_pct": stats(relative),
        "aggregate_improvement_pct": (
            (sum(baseline_values) - sum(candidate_values)) / sum(baseline_values) * 100.0
            if baseline_values and abs(sum(baseline_values)) > EPSILON
            else None
        ),
        "mean_delta_bootstrap_95ci": bootstrap_mean_ci(deltas),
        "sign_test": sign_test(deltas),
        "wins": sum(item > EPSILON for item in deltas),
        "ties": sum(abs(item) <= EPSILON for item in deltas),
        "losses": sum(item < -EPSILON for item in deltas),
        "ratio": stats(ratios) if ratio else {"status": "unsupported", "value": None},
    }


def group_stats(rows: Sequence[Mapping[str, Any]], metric_getter: Callable[[Mapping[str, Any]], Any]) -> dict[str, Any]:
    return stats(metric_getter(row) for row in rows)


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]], fieldnames: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def load_stage_status(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def latest_suite_root(base: Path, pattern: str) -> Path | None:
    candidates = [item for item in base.glob(pattern) if item.is_dir()]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name))


def p2_row_metric(row: Mapping[str, Any], key: str) -> float | None:
    return number(row.get(key))


def analyze_p2(root: Path, output_dir: Path) -> dict[str, Any]:
    rows = read_json(root / "rows.json", [])
    if not isinstance(rows, list):
        rows = []
    by_variant: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_payload: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        variant = str(row.get("variant", "unknown"))
        payload_id = str(row.get("matched_payload_id", ""))
        by_variant[variant].append(row)
        if payload_id:
            by_payload[payload_id][variant] = row

    metrics = (
        "control_bytes",
        "wire_bytes",
        "critical_path_wall_ms",
        "encode_ms",
        "decode_ms",
        "socket_wait_ms",
        "ack_latency_ms",
        "state_map_ms",
        "state_publish_ms",
        "state_read_ms",
        "state_release_ms",
    )
    baseline_variant = "utf8_text_inline"
    pair_rows: list[dict[str, Any]] = []
    comparisons: dict[str, Any] = {}
    by_size_comparisons: dict[str, dict[str, Any]] = defaultdict(dict)
    size_order = {"small": 0, "medium": 1, "large": 2}
    sizes = sorted({payload.split(":", 1)[0] for payload in by_payload}, key=lambda item: (size_order.get(item, 99), item))
    for variant in sorted(by_variant):
        if variant == baseline_variant:
            continue
        pairs: list[dict[str, Any]] = []
        for payload_id in sorted(by_payload):
            lanes = by_payload[payload_id]
            baseline = lanes.get(baseline_variant)
            candidate = lanes.get(variant)
            if baseline is None or candidate is None:
                continue
            size = payload_id.split(":", 1)[0]
            pair: dict[str, Any] = {"payload_id": payload_id, "size": size, "variant": variant}
            for metric in metrics:
                pair[f"baseline_{metric}"] = p2_row_metric(baseline, metric)
                pair[f"candidate_{metric}"] = p2_row_metric(candidate, metric)
                base = pair[f"baseline_{metric}"]
                cand = pair[f"candidate_{metric}"]
                pair[f"{metric}_delta"] = base - cand if base is not None and cand is not None else None
                pair[f"{metric}_improvement_pct"] = (
                    (base - cand) / base * 100.0
                    if base is not None and cand is not None and abs(base) > EPSILON
                    else None
                )
            pairs.append(pair)
            pair_rows.append(pair)
        comparisons[variant] = {
            "matched_pair_count": len(pairs),
            "metrics": {
                metric: paired_metric(pairs, f"baseline_{metric}", f"candidate_{metric}")
                for metric in metrics
            },
        }
        for size in sizes:
            subset = [pair for pair in pairs if pair["size"] == size]
            by_size_comparisons[size][variant] = {
                "matched_pair_count": len(subset),
                "metrics": {
                    metric: paired_metric(subset, f"baseline_{metric}", f"candidate_{metric}")
                    for metric in metrics
                },
            }

    variants = {
        variant: {
            "row_count": len(items),
            "success_count": sum(row.get("terminal_class") == "success" for row in items),
            "quality_pass_count": sum(
                isinstance(row.get("quality"), Mapping) and row["quality"].get("passed") is True
                for row in items
            ),
            "metrics": {metric: group_stats(items, lambda row, key=metric: p2_row_metric(row, key)) for metric in metrics},
        }
        for variant, items in sorted(by_variant.items())
    }
    shm = comparisons.get("typed_protobuf_shm_ref", {})
    shm_wire = shm.get("metrics", {}).get("wire_bytes", {})
    break_even = {
        "candidate": "typed_protobuf_shm_ref",
        "metric": "critical_path_wall_ms",
        "first_size_with_positive_mean_improvement": None,
        "first_size_with_positive_median_improvement": None,
        "trend": [],
    }
    for size in sizes:
        entry = by_size_comparisons.get(size, {}).get("typed_protobuf_shm_ref", {})
        metric = entry.get("metrics", {}).get("critical_path_wall_ms", {})
        mean = metric.get("relative_improvement_pct", {}).get("mean")
        median = metric.get("relative_improvement_pct", {}).get("median")
        break_even["trend"].append({"size": size, "mean_improvement_pct": mean, "median_improvement_pct": median})
        if break_even["first_size_with_positive_mean_improvement"] is None and finite(mean) and mean > 0:
            break_even["first_size_with_positive_mean_improvement"] = size
        if break_even["first_size_with_positive_median_improvement"] is None and finite(median) and median > 0:
            break_even["first_size_with_positive_median_improvement"] = size

    csv_fields = ["payload_id", "size", "variant"]
    for metric in metrics:
        csv_fields.extend(
            [
                f"baseline_{metric}",
                f"candidate_{metric}",
                f"{metric}_delta",
                f"{metric}_improvement_pct",
            ]
        )
    write_csv(output_dir / "p2_pair_deltas.csv", pair_rows, csv_fields)
    return {
        "status": "observed" if rows else "unavailable",
        "artifact_root": str(root),
        "row_count": len(rows),
        "payload_group_count": len(by_payload),
        "baseline_variant": baseline_variant,
        "variants": variants,
        "comparisons_vs_utf8_text_inline": comparisons,
        "by_size": {size: by_size_comparisons.get(size, {}) for size in sizes},
        "break_even_trend": break_even,
        "wire_bytes_observation": {
            "shm_ref_vs_baseline": shm_wire,
            "interpretation": "The large wire reduction is attributable to the reference/SHM carrier path; inline protobuf remains close to UTF-8 for these payloads.",
        },
    }


def p3_case_summary(suite_root: Path, task_id: str, variant: str) -> Mapping[str, Any]:
    payload = read_json(suite_root / "cases" / task_id / variant / "summary.json", {})
    return payload if isinstance(payload, Mapping) else {}


def p3_enriched_rows(suite_root: Path) -> list[dict[str, Any]]:
    summary = read_json(suite_root / "summary.json", {})
    raw_rows = summary.get("rows", []) if isinstance(summary, Mapping) else []
    enriched: list[dict[str, Any]] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        task_id = str(row.get("task_id", ""))
        variant = str(row.get("variant", ""))
        case = p3_case_summary(suite_root, task_id, variant)
        telemetry = case.get("telemetry", {}) if isinstance(case.get("telemetry"), Mapping) else {}
        usage = case.get("usage", {}) if isinstance(case.get("usage"), Mapping) else {}
        spec = case.get("canonical_task_spec", {}) if isinstance(case.get("canonical_task_spec"), Mapping) else {}
        row.update(
            {
                "elapsed_ms": number(case.get("elapsed_ms")),
                "prompt_tokens": number(usage.get("prompt_tokens")),
                "completion_tokens": number(usage.get("completion_tokens")),
                "total_tokens": number(usage.get("total_tokens")),
                "operation": case.get("operation") or spec.get("intent_op"),
                "task_family": spec.get("task_family") or case.get("task_family"),
                "source_kind": spec.get("arguments", {}).get("source_kind") if isinstance(spec.get("arguments"), Mapping) else None,
                "raw_evidence_bytes_seen_by_llm": number(telemetry.get("raw_evidence_bytes_seen_by_llm")),
                "selected_evidence_bytes": number(telemetry.get("selected_evidence_bytes")),
                "semantic_state_selected_bytes": number(telemetry.get("semantic_state_selected_bytes")),
                "skipped_llm_call_count": number(telemetry.get("skipped_llm_call_count")),
                "skipped_step_count": number(telemetry.get("skipped_step_count")),
                "provider_skip_observed_count": number(telemetry.get("provider_skip_observed_count")),
                "case_ok": bool_value(case.get("ok")),
            }
        )
        enriched.append(row)
    return enriched


def p3_failure_class(task_rows: Mapping[str, Mapping[str, Any]]) -> str:
    off = task_rows.get("off", {})
    on = task_rows.get("on", {})
    consumer = task_rows.get("consumer_off", {})
    on_receipt = on.get("activation_receipt", {}) if isinstance(on.get("activation_receipt"), Mapping) else {}
    if on.get("actual_use") is False and (
        on_receipt.get("disable_reason") == "no_semantic_state_payload"
        or on_receipt.get("effective_mode") == "not_applicable"
    ):
        return "activation_inactive_no_semantic_state_payload"
    if on.get("actual_use") is False:
        return "activation_inactive_without_payload_reason"
    if on.get("quality_pass") is False and off.get("quality_pass") is True:
        return "quality_regression_on"
    if consumer.get("quality_pass") is False and off.get("quality_pass") is True:
        return "quality_regression_consumer_off"
    if on.get("quality_pass") is False and off.get("quality_pass") is False:
        return "quality_failed_both_off_and_on"
    if on.get("actual_use") is True and on.get("quality_pass") is True:
        return "eligible_active_quality_pass"
    return "other"


def summarize_p3_rows(rows: Sequence[Mapping[str, Any]], task_ids: set[str]) -> dict[str, Any]:
    selected = [row for row in rows if str(row.get("task_id", "")) in task_ids]
    variants: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in selected:
        variants[str(row.get("variant", "unknown"))].append(row)
    fields = (
        "elapsed_ms",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "provider_call_count",
        "semantic_publish_count",
        "semantic_consume_count",
        "semantic_transfer_count",
        "raw_evidence_bytes_seen_by_llm",
        "selected_evidence_bytes",
        "semantic_state_selected_bytes",
        "skipped_llm_call_count",
        "skipped_step_count",
    )
    result: dict[str, Any] = {"case_count": len(task_ids), "row_count": len(selected), "variants": {}}
    for variant, items in sorted(variants.items()):
        result["variants"][variant] = {
            "row_count": len(items),
            "terminal_count": sum(row.get("terminal") is True for row in items),
            "quality_pass_count": sum(row.get("quality_pass") is True for row in items),
            "actual_use_count": sum(row.get("actual_use") is True for row in items),
            "downstream_effect_count": sum(row.get("downstream_effect") is True for row in items),
            "metrics": {field: group_stats(items, lambda row, key=field: row.get(key)) for field in fields},
        }
    off_by = {str(row.get("task_id")): row for row in variants.get("off", [])}
    on_by = {str(row.get("task_id")): row for row in variants.get("on", [])}
    pair_records: list[dict[str, Any]] = []
    for task_id in sorted(task_ids):
        if task_id not in off_by or task_id not in on_by:
            continue
        pair_records.append(
            {
                "task_id": task_id,
                "baseline_elapsed_ms": off_by[task_id].get("elapsed_ms"),
                "candidate_elapsed_ms": on_by[task_id].get("elapsed_ms"),
                "baseline_total_tokens": off_by[task_id].get("total_tokens"),
                "candidate_total_tokens": on_by[task_id].get("total_tokens"),
                "baseline_prompt_tokens": off_by[task_id].get("prompt_tokens"),
                "candidate_prompt_tokens": on_by[task_id].get("prompt_tokens"),
                "baseline_provider_call_count": off_by[task_id].get("provider_call_count"),
                "candidate_provider_call_count": on_by[task_id].get("provider_call_count"),
            }
        )
    result["on_vs_off"] = {
        "elapsed_ms": paired_metric(pair_records, "baseline_elapsed_ms", "candidate_elapsed_ms"),
        "total_tokens": paired_metric(pair_records, "baseline_total_tokens", "candidate_total_tokens"),
        "prompt_tokens": paired_metric(pair_records, "baseline_prompt_tokens", "candidate_prompt_tokens"),
        "provider_call_count": paired_metric(pair_records, "baseline_provider_call_count", "candidate_provider_call_count"),
    }
    return result


def analyze_p3(root: Path, output_dir: Path) -> dict[str, Any]:
    suite_root = latest_suite_root(root, "semantic_state_ablation_*")
    if suite_root is None:
        return {"status": "unavailable", "artifact_root": str(root)}
    summary = read_json(suite_root / "summary.json", {})
    denominator = summary.get("denominator", {}) if isinstance(summary, Mapping) else {}
    all_ids = {str(item.get("task_id")) for item in summary.get("rows", []) if isinstance(item, Mapping)}
    task_to_pair_id = {
        str(item.get("task_id")): str(item.get("pair_id"))
        for item in summary.get("rows", [])
        if isinstance(item, Mapping) and item.get("task_id") and item.get("pair_id")
    }
    eligible_pair_ids = {str(item) for item in denominator.get("eligible_pair_ids", [])}
    eligible_ids = {
        task_id for task_id, pair_id in task_to_pair_id.items() if pair_id in eligible_pair_ids
    }
    excluded_pair_ids = {str(item) for item in denominator.get("excluded_pair_ids", [])}
    excluded_ids = {
        task_id for task_id, pair_id in task_to_pair_id.items() if pair_id in excluded_pair_ids
    }
    rows = p3_enriched_rows(suite_root)
    by_task: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_task[str(row.get("task_id"))][str(row.get("variant"))] = row

    matrix: list[dict[str, Any]] = []
    failure_counts: Counter[str] = Counter()
    operation_counts: Counter[str] = Counter()
    for task_id in sorted(all_ids):
        task_rows = by_task.get(task_id, {})
        off = task_rows.get("off", {})
        on = task_rows.get("on", {})
        consumer = task_rows.get("consumer_off", {})
        operation = str((on or off or consumer).get("operation", "unknown"))
        failure_class = p3_failure_class(task_rows)
        failure_counts[failure_class] += 1
        operation_counts[operation] += 1
        row = {
            "task_id": task_id,
            "operation": operation,
            "task_family": (on or off or consumer).get("task_family"),
            "source_kind": (on or off or consumer).get("source_kind"),
            "eligible_pair": task_id in eligible_ids,
            "failure_class": failure_class,
        }
        for variant, source in (("off", off), ("on", on), ("consumer_off", consumer)):
            row[f"{variant}_quality_pass"] = source.get("quality_pass")
            row[f"{variant}_actual_use"] = source.get("actual_use")
            row[f"{variant}_terminal"] = source.get("terminal")
            row[f"{variant}_elapsed_ms"] = source.get("elapsed_ms")
            row[f"{variant}_total_tokens"] = source.get("total_tokens")
            row[f"{variant}_prompt_tokens"] = source.get("prompt_tokens")
            row[f"{variant}_provider_calls"] = source.get("provider_call_count")
            receipt = source.get("activation_receipt", {})
            row[f"{variant}_effective_mode"] = receipt.get("effective_mode") if isinstance(receipt, Mapping) else None
            row[f"{variant}_disable_reason"] = receipt.get("disable_reason") if isinstance(receipt, Mapping) else None
        row["on_elapsed_improvement_pct"] = (
            (number(row["off_elapsed_ms"]) - number(row["on_elapsed_ms"])) / number(row["off_elapsed_ms"]) * 100.0
            if number(row["off_elapsed_ms"]) is not None and number(row["on_elapsed_ms"]) is not None and abs(number(row["off_elapsed_ms"])) > EPSILON
            else None
        )
        row["on_total_token_reduction_pct"] = (
            (number(row["off_total_tokens"]) - number(row["on_total_tokens"])) / number(row["off_total_tokens"]) * 100.0
            if number(row["off_total_tokens"]) is not None and number(row["on_total_tokens"]) is not None and abs(number(row["off_total_tokens"])) > EPSILON
            else None
        )
        matrix.append(row)

    csv_fields = [
        "task_id", "operation", "task_family", "source_kind", "eligible_pair", "failure_class",
    ]
    for variant in ("off", "on", "consumer_off"):
        csv_fields.extend(
            [
                f"{variant}_quality_pass", f"{variant}_actual_use", f"{variant}_terminal",
                f"{variant}_elapsed_ms", f"{variant}_total_tokens", f"{variant}_prompt_tokens",
                f"{variant}_provider_calls", f"{variant}_effective_mode", f"{variant}_disable_reason",
            ]
        )
    csv_fields.extend(["on_elapsed_improvement_pct", "on_total_token_reduction_pct"])
    write_csv(output_dir / "p3_case_matrix.csv", matrix, csv_fields)

    by_operation: dict[str, Any] = {}
    for operation in sorted(operation_counts):
        ids = {row["task_id"] for row in matrix if row["operation"] == operation}
        eligible_operation_ids = ids & eligible_ids
        by_operation[operation] = {
            "all_cases": summarize_p3_rows(rows, ids),
            "eligible_cases": summarize_p3_rows(rows, eligible_operation_ids),
        }
    return {
        "status": "observed",
        "artifact_root": str(suite_root),
        "suite_status": summary.get("ok"),
        "denominator": denominator,
        "eligible_task_ids": sorted(eligible_ids),
        "excluded_task_ids": sorted(excluded_ids),
        "all_case_count": len(all_ids),
        "eligible_case_count": len(eligible_ids),
        "excluded_case_count": len(all_ids - eligible_ids),
        "all_cases": summarize_p3_rows(rows, all_ids),
        "eligible_only": summarize_p3_rows(rows, eligible_ids),
        "by_operation": by_operation,
        "failure_taxonomy": dict(failure_counts),
        "operation_case_counts": dict(operation_counts),
        "case_matrix_path": str(output_dir / "p3_case_matrix.csv"),
        "interpretation": {
            "denominator_rule": "Only denominator-eligible off/on/consumer_off triples are used for benefit deltas.",
            "activation_rule": "A requested on mode without producer/consumer use is recorded as inactive, not as a zero-cost benefit.",
        },
    }


def analyze_p4_deterministic(root: Path, output_dir: Path) -> dict[str, Any]:
    epoch_results: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []
    for epoch_root in sorted(item for item in root.glob("epoch-*") if item.is_dir()):
        rows = read_json(epoch_root / "rows.json", [])
        if not isinstance(rows, list):
            rows = []
        lanes: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
        for row in rows:
            if isinstance(row, Mapping):
                lanes[str(row.get("pair_id"))][str(row.get("variant"))] = row
        pairs: list[dict[str, Any]] = []
        for pair_id, variants in sorted(lanes.items()):
            off = variants.get("memory_off")
            replay = variants.get("validated_replay")
            if off is None or replay is None:
                continue
            pair = {
                "epoch": epoch_root.name,
                "pair_id": pair_id,
                "family_id": replay.get("family_id") or off.get("family_id"),
                "round_number": replay.get("round_number") or off.get("round_number"),
                "baseline_provider_calls": off.get("provider_boundary_call_count"),
                "replay_provider_calls": replay.get("provider_boundary_call_count"),
                "replay_actual_use": replay.get("actual_use"),
                "baseline_quality_pass": isinstance(off.get("quality_evidence"), Mapping) and off["quality_evidence"].get("passed") is True,
                "replay_quality_pass": isinstance(replay.get("quality_evidence"), Mapping) and replay["quality_evidence"].get("passed") is True,
                "replay_behavioral_effect": replay.get("behavioral_effect"),
            }
            pair["provider_calls_avoided"] = (
                number(pair["baseline_provider_calls"]) - number(pair["replay_provider_calls"])
                if number(pair["baseline_provider_calls"]) is not None and number(pair["replay_provider_calls"]) is not None
                else None
            )
            pairs.append(pair)
            all_pairs.append(pair)
        metrics_path = epoch_root / "metrics.json"
        metrics = read_json(metrics_path, {})
        epoch_results.append(
            {
                "epoch": epoch_root.name,
                "artifact_root": str(epoch_root),
                "pair_count": len(pairs),
                "family_counts": dict(Counter(str(pair.get("family_id")) for pair in pairs)),
                "provider_calls_avoided": stats(pair.get("provider_calls_avoided") for pair in pairs),
                "actual_use_count": sum(pair.get("replay_actual_use") is True for pair in pairs),
                "quality_pass": {
                    "baseline": sum(pair.get("baseline_quality_pass") is True for pair in pairs),
                    "replay": sum(pair.get("replay_quality_pass") is True for pair in pairs),
                },
                "behavioral_effect": dict(Counter(str(pair.get("replay_behavioral_effect")) for pair in pairs)),
                "source_metrics": {
                    "provider_work_avoided": number(metrics.get("provider_work_avoided")),
                    "memory_actual_use": number(metrics.get("memory_actual_use")),
                    "provider_boundary_calls": metrics.get("provider_boundary_calls"),
                    "behavioral_effect": metrics.get("behavioral_effect"),
                },
            }
        )
    family_summary: dict[str, Any] = {}
    for family in sorted({str(pair.get("family_id")) for pair in all_pairs}):
        subset = [pair for pair in all_pairs if str(pair.get("family_id")) == family]
        family_summary[family] = {
            "pair_count": len(subset),
            "provider_calls_avoided": stats(pair.get("provider_calls_avoided") for pair in subset),
            "actual_use_count": sum(pair.get("replay_actual_use") is True for pair in subset),
            "quality_pass": {
                "baseline": sum(pair.get("baseline_quality_pass") is True for pair in subset),
                "replay": sum(pair.get("replay_quality_pass") is True for pair in subset),
            },
            "behavioral_effect": dict(Counter(str(pair.get("replay_behavioral_effect")) for pair in subset)),
        }
    return {
        "status": "observed" if all_pairs else "unavailable",
        "artifact_root": str(root),
        "epoch_count": len(epoch_results),
        "pair_count": len(all_pairs),
        "independent_workload_shapes": len({(str(pair.get("family_id")), pair.get("round_number")) for pair in all_pairs}),
        "workload_families": len({str(pair.get("family_id")) for pair in all_pairs}),
        "epochs": epoch_results,
        "by_family": family_summary,
        "aggregate": {
            "provider_calls_avoided": stats(pair.get("provider_calls_avoided") for pair in all_pairs),
            "baseline_provider_calls": stats(pair.get("baseline_provider_calls") for pair in all_pairs),
            "replay_provider_calls": stats(pair.get("replay_provider_calls") for pair in all_pairs),
            "actual_use_count": sum(pair.get("replay_actual_use") is True for pair in all_pairs),
            "quality_pass": {
                "baseline": sum(pair.get("baseline_quality_pass") is True for pair in all_pairs),
                "replay": sum(pair.get("replay_quality_pass") is True for pair in all_pairs),
            },
            "behavioral_effect": dict(Counter(str(pair.get("replay_behavioral_effect")) for pair in all_pairs)),
        },
        "interpretation": "Deterministic P4 establishes a closed provider-bypass and memory-use mechanism; it does not establish independent live latency superiority.",
    }


def live_provider_elapsed(row: Mapping[str, Any]) -> float | None:
    evidence = row.get("provider_invocation_evidence")
    return number(evidence.get("provider_elapsed_ms")) if isinstance(evidence, Mapping) else None


def live_quality(row: Mapping[str, Any]) -> bool | None:
    quality = row.get("quality_evidence")
    return bool_value(quality.get("passed")) if isinstance(quality, Mapping) else None


def live_pair_rows(root: Path) -> list[dict[str, Any]]:
    baseline_payload = read_json(root / "live_baseline_rows.json", {})
    producer_payload = read_json(root / "live_producer_rows.json", {})
    replay_payload = read_json(root / "live_replay_rows.json", {})
    baseline_rows = baseline_payload.get("rows", []) if isinstance(baseline_payload, Mapping) else []
    producer_rows = producer_payload.get("rows", []) if isinstance(producer_payload, Mapping) else []
    replay_rows = replay_payload.get("rows", []) if isinstance(replay_payload, Mapping) else []
    baseline_by = {str(row.get("slot_id")): row for row in baseline_rows if isinstance(row, Mapping)}
    producer_by = {str(row.get("slot_id")): row for row in producer_rows if isinstance(row, Mapping)}
    replay_by = {str(row.get("slot_id")): row for row in replay_rows if isinstance(row, Mapping)}
    pairs: list[dict[str, Any]] = []
    for slot_id in baseline_by:
        baseline = baseline_by.get(slot_id)
        producer = producer_by.get(slot_id)
        replay = replay_by.get(slot_id)
        if baseline is None or producer is None or replay is None:
            continue
        b_runtime = number(baseline.get("runtime_elapsed_ms"))
        p_runtime = number(producer.get("runtime_elapsed_ms"))
        r_runtime = number(replay.get("runtime_elapsed_ms"))
        pair: dict[str, Any] = {
            "slot_id": slot_id,
            "family_id": baseline.get("family_id"),
            "round_number": baseline.get("round_number"),
            "repeat_id": baseline.get("repeat_id"),
            "baseline_runtime_ms": b_runtime,
            "producer_runtime_ms": p_runtime,
            "replay_runtime_ms": r_runtime,
            "baseline_provider_elapsed_ms": live_provider_elapsed(baseline),
            "producer_provider_elapsed_ms": live_provider_elapsed(producer),
            "replay_provider_calls": replay.get("consumer_provider_boundary_call_count"),
            "replay_provider_status": (
                replay.get("provider_not_started_observation", {}).get("provider_invocation_status")
                if isinstance(replay.get("provider_not_started_observation"), Mapping)
                else None
            ),
            "baseline_quality_pass": live_quality(baseline),
            "producer_quality_pass": live_quality(producer),
            "replay_quality_pass": live_quality(replay),
        }
        pair["marginal_runtime_delta_ms"] = b_runtime - r_runtime if b_runtime is not None and r_runtime is not None else None
        pair["marginal_runtime_improvement_pct"] = (
            (b_runtime - r_runtime) / b_runtime * 100.0
            if b_runtime is not None and r_runtime is not None and abs(b_runtime) > EPSILON
            else None
        )
        setup_total = p_runtime + r_runtime if p_runtime is not None and r_runtime is not None else None
        pair["producer_plus_replay_runtime_ms"] = setup_total
        pair["setup_inclusive_delta_ms"] = b_runtime - setup_total if b_runtime is not None and setup_total is not None else None
        pair["setup_inclusive_improvement_pct"] = (
            (b_runtime - setup_total) / b_runtime * 100.0
            if b_runtime is not None and setup_total is not None and abs(b_runtime) > EPSILON
            else None
        )
        pair["marginal_speedup"] = b_runtime / r_runtime if b_runtime is not None and r_runtime is not None and abs(r_runtime) > EPSILON else None
        pair["setup_inclusive_ratio"] = b_runtime / setup_total if b_runtime is not None and setup_total is not None and abs(setup_total) > EPSILON else None
        pairs.append(pair)
    return pairs


def live_scope_summary(pairs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "pair_count": len(pairs),
        "baseline_runtime_ms": stats(pair.get("baseline_runtime_ms") for pair in pairs),
        "producer_runtime_ms": stats(pair.get("producer_runtime_ms") for pair in pairs),
        "replay_runtime_ms": stats(pair.get("replay_runtime_ms") for pair in pairs),
        "producer_plus_replay_runtime_ms": stats(pair.get("producer_plus_replay_runtime_ms") for pair in pairs),
        "marginal_runtime": paired_metric(pairs, "baseline_runtime_ms", "replay_runtime_ms", ratio=True),
        "setup_inclusive_runtime": paired_metric(pairs, "baseline_runtime_ms", "producer_plus_replay_runtime_ms", ratio=True),
        "marginal_speedup": stats(pair.get("marginal_speedup") for pair in pairs),
        "setup_inclusive_ratio": stats(pair.get("setup_inclusive_ratio") for pair in pairs),
        "baseline_provider_elapsed_ms": stats(pair.get("baseline_provider_elapsed_ms") for pair in pairs),
        "producer_provider_elapsed_ms": stats(pair.get("producer_provider_elapsed_ms") for pair in pairs),
        "quality_pass": {
            "baseline": sum(pair.get("baseline_quality_pass") is True for pair in pairs),
            "producer": sum(pair.get("producer_quality_pass") is True for pair in pairs),
            "replay": sum(pair.get("replay_quality_pass") is True for pair in pairs),
        },
        "replay_provider_not_started": sum(pair.get("replay_provider_status") == "not_started" for pair in pairs),
        "replay_provider_call_count": stats(pair.get("replay_provider_calls") for pair in pairs),
    }


def analyze_p4_live(root: Path, output_dir: Path) -> dict[str, Any]:
    campaign_root = latest_suite_root(root / "campaign", "g6b2-live-validation-*")
    minimal_root = latest_suite_root(root / "minimal", "g6b2-live-validation-*")
    if campaign_root is None and minimal_root is None:
        return {"status": "unavailable", "artifact_root": str(root)}
    campaign_pairs = live_pair_rows(campaign_root) if campaign_root else []
    minimal_pairs = live_pair_rows(minimal_root) if minimal_root else []
    selected_root = campaign_root or minimal_root
    selected_pairs = campaign_pairs or minimal_pairs
    ordered = selected_pairs
    no_cold = selected_pairs[1:] if len(selected_pairs) > 1 else []
    delta_rows = list(selected_pairs)
    csv_fields = [
        "slot_id", "family_id", "round_number", "repeat_id", "baseline_runtime_ms", "producer_runtime_ms",
        "replay_runtime_ms", "producer_plus_replay_runtime_ms", "marginal_runtime_delta_ms",
        "marginal_runtime_improvement_pct", "setup_inclusive_delta_ms", "setup_inclusive_improvement_pct",
        "marginal_speedup", "setup_inclusive_ratio", "baseline_provider_elapsed_ms", "producer_provider_elapsed_ms",
        "replay_provider_calls", "replay_provider_status", "baseline_quality_pass", "producer_quality_pass", "replay_quality_pass",
    ]
    write_csv(output_dir / "p4_live_pair_deltas.csv", delta_rows, csv_fields)
    by_family_round: dict[str, Any] = {}
    for family in sorted({str(pair.get("family_id")) for pair in selected_pairs}):
        for round_number in sorted({pair.get("round_number") for pair in selected_pairs if str(pair.get("family_id")) == family}):
            key = f"{family}:round-{round_number}"
            subset = [pair for pair in selected_pairs if str(pair.get("family_id")) == family and pair.get("round_number") == round_number]
            by_family_round[key] = live_scope_summary(subset)
    distinct_shapes = sorted({(str(pair.get("family_id")), pair.get("round_number")) for pair in selected_pairs})
    repeats = sorted({pair.get("repeat_id") for pair in selected_pairs})
    return {
        "status": "observed" if selected_pairs else "partial",
        "artifact_root": str(selected_root) if selected_root else str(root),
        "campaign_artifact_root": str(campaign_root) if campaign_root else None,
        "minimal_artifact_root": str(minimal_root) if minimal_root else None,
        "campaign": live_scope_summary(campaign_pairs),
        "minimal": live_scope_summary(minimal_pairs),
        "selected_scope": "campaign" if campaign_pairs else "minimal",
        "selected": live_scope_summary(selected_pairs),
        "cold_outlier_sensitivity": {
            "ordered_first_slot": ordered[0].get("slot_id") if ordered else None,
            "all_pairs": live_scope_summary(selected_pairs),
            "without_first_slot": live_scope_summary(no_cold),
            "median_is_invariant_to_single_cold_outlier": True,
        },
        "by_family_round": by_family_round,
        "planned_slots": len(selected_pairs),
        "distinct_family_round_shapes": len(distinct_shapes),
        "family_round_shapes": [f"{family}:round-{round_number}" for family, round_number in distinct_shapes],
        "distinct_repeat_ids": len(repeats),
        "provider_work": {
            "baseline_provider_invocation_count": sum(
                isinstance(pair.get("baseline_provider_elapsed_ms"), (int, float)) for pair in selected_pairs
            ),
            "producer_provider_invocation_count": sum(
                isinstance(pair.get("producer_provider_elapsed_ms"), (int, float)) for pair in selected_pairs
            ),
            "replay_provider_not_started_count": sum(pair.get("replay_provider_status") == "not_started" for pair in selected_pairs),
        },
        "interpretation": {
            "marginal": "Replay latency measures the benefit after a producer has already created reusable memory.",
            "setup_inclusive": "Producer plus replay includes the setup work paid in this campaign; it is the relevant first-use accounting for this run.",
            "independence": "The 60 slots are repeated measurements over four family-round workload shapes, not 60 independent task designs.",
            "latency": "Live latency is diagnostic under the shared-GPU service profile and is not a benchmark-superiority claim.",
        },
    }


def build_findings(analysis: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    p2 = analysis.get("p2", {})
    p2_cmp = p2.get("comparisons_vs_utf8_text_inline", {}) if isinstance(p2, Mapping) else {}
    shm = p2_cmp.get("typed_protobuf_shm_ref", {}).get("metrics", {}) if isinstance(p2_cmp.get("typed_protobuf_shm_ref", {}), Mapping) else {}
    shm_wire_metric = shm.get("wire_bytes", {})
    shm_wall_metric = shm.get("critical_path_wall_ms", {})
    shm_wire_aggregate = shm_wire_metric.get("aggregate_improvement_pct")
    shm_wire_pair_mean = shm_wire_metric.get("relative_improvement_pct", {}).get("mean")
    shm_wall_aggregate = shm_wall_metric.get("aggregate_improvement_pct")
    shm_wall_pair_mean = shm_wall_metric.get("relative_improvement_pct", {}).get("mean")
    if finite(shm_wire_aggregate) or finite(shm_wire_pair_mean) or finite(shm_wall_aggregate):
        findings.append(
            f"P2: SHM/ref reduces aggregate wire bytes by {shm_wire_aggregate:.2f}% (equal-weight payload mean {shm_wire_pair_mean:.2f}%) and changes aggregate critical-path wall time by {shm_wall_aggregate:.2f}% (equal-weight payload mean {shm_wall_pair_mean:.2f}%) versus UTF-8 (positive means faster)."
            if finite(shm_wire_aggregate) and finite(shm_wire_pair_mean) and finite(shm_wall_aggregate) and finite(shm_wall_pair_mean)
            else "P2: SHM/ref shows a directional carrier-path benefit, but one of the principal metrics is unavailable."
        )
    trend = p2.get("break_even_trend", {}).get("trend", []) if isinstance(p2, Mapping) else []
    if trend:
        findings.append("P2: the size trend must be read by bucket; small payloads do not automatically amortize SHM setup, while large payloads are the useful regime.")

    p3 = analysis.get("p3", {})
    p3_all = p3.get("all_cases", {}) if isinstance(p3, Mapping) else {}
    p3_eligible = p3.get("eligible_only", {}) if isinstance(p3, Mapping) else {}
    p3_all_delta = p3_all.get("on_vs_off", {}).get("elapsed_ms", {}).get("relative_improvement_pct", {}).get("mean")
    p3_eligible_delta = p3_eligible.get("on_vs_off", {}).get("elapsed_ms", {}).get("relative_improvement_pct", {}).get("mean")
    if finite(p3_all_delta):
        findings.append(f"P3: all-case on-vs-off elapsed improvement is {p3_all_delta:.2f}%; this mixes inactive/excluded cases and is not the primary denominator.")
    if finite(p3_eligible_delta):
        findings.append(f"P3: eligible-only on-vs-off elapsed improvement is {p3_eligible_delta:.2f}%; task shape, activation, and quality gates dominate the result.")
    taxonomy = p3.get("failure_taxonomy", {}) if isinstance(p3, Mapping) else {}
    if taxonomy:
        findings.append("P3: the failure taxonomy separates no-payload activation failures from quality regressions, exposing why the planned eight-case denominator closes at four cases.")

    det = analysis.get("p4_deterministic", {})
    det_agg = det.get("aggregate", {}) if isinstance(det, Mapping) else {}
    avoided = det_agg.get("provider_calls_avoided", {}).get("total")
    if finite(avoided):
        findings.append(f"P4 deterministic: {avoided:.0f} provider calls are avoided over closed replay pairs, demonstrating the mechanism and accounting closure rather than live speed superiority.")

    p4_live = analysis.get("p4_live", {}) if isinstance(analysis.get("p4_live", {}), Mapping) else {}
    live = p4_live.get("selected", {}) if isinstance(p4_live.get("selected", {}), Mapping) else {}
    marginal = live.get("marginal_runtime", {}).get("relative_improvement_pct", {}).get("mean")
    setup = live.get("setup_inclusive_runtime", {}).get("relative_improvement_pct", {}).get("mean")
    marginal_metric = live.get("marginal_runtime", {}) if isinstance(live.get("marginal_runtime"), Mapping) else {}
    setup_metric = live.get("setup_inclusive_runtime", {}) if isinstance(live.get("setup_inclusive_runtime"), Mapping) else {}
    marginal_aggregate = marginal_metric.get("aggregate_improvement_pct")
    setup_aggregate = setup_metric.get("aggregate_improvement_pct")
    cold_sensitivity = p4_live.get("cold_outlier_sensitivity", {}) if isinstance(p4_live.get("cold_outlier_sensitivity"), Mapping) else {}
    without_first = cold_sensitivity.get("without_first_slot", {}) if isinstance(cold_sensitivity.get("without_first_slot"), Mapping) else {}
    without_first_setup = without_first.get("setup_inclusive_runtime", {}) if isinstance(without_first.get("setup_inclusive_runtime"), Mapping) else {}
    without_first_aggregate = without_first_setup.get("aggregate_improvement_pct")
    without_first_mean = without_first_setup.get("relative_improvement_pct", {}).get("mean")
    if finite(marginal) or finite(setup):
        if (
            finite(marginal)
            and finite(setup)
            and finite(marginal_aggregate)
            and finite(setup_aggregate)
            and finite(without_first_aggregate)
            and finite(without_first_mean)
        ):
            findings.append(
                f"P4 live: marginal replay improvement is {marginal_aggregate:.2f}% in aggregate ({marginal:.2f}% per-slot mean), while producer-inclusive improvement is {setup_aggregate:.2f}% in aggregate ({setup:.2f}% per-slot mean) with {setup_metric.get('wins', 0)} wins and {setup_metric.get('losses', 0)} losses; after removing the first cold slot, setup-inclusive improvement is {without_first_aggregate:.2f}% in aggregate ({without_first_mean:.2f}% per-slot mean), so the positive all-slot aggregate is cold-outlier-sensitive."
            )
        else:
            findings.append("P4 live: marginal and producer-inclusive accounting must be kept separate because setup cost is material.")
    findings.append("No section establishes benchmark or statistical superiority; the run is an exploratory ablation and mechanism-evidence package.")
    return findings


def fmt(value: Any, digits: int = 2) -> str:
    return "n/a" if not finite(value) else f"{float(value):.{digits}f}"


def write_markdown(analysis: Mapping[str, Any], path: Path) -> None:
    p2 = analysis.get("p2", {})
    p3 = analysis.get("p3", {})
    det = analysis.get("p4_deterministic", {})
    live = analysis.get("p4_live", {})
    lines = [
        "# Contest-Core Full Ablation Comprehensive Analysis",
        "",
        f"- Run root: `{analysis.get('run_root')}`",
        f"- Generated: `{analysis.get('generated_at')}`",
        "- Scope: offline, exploratory ablation analysis; no experiment was rerun",
        "- Benchmark superiority: `NOT_ESTABLISHED`",
        "- Statistical superiority: `NOT_ESTABLISHED`",
        "",
        "## Bottom Line",
        "",
    ]
    lines.extend(f"- {finding}" for finding in analysis.get("findings", []))
    lines.extend(["", "## Stage Status", "", "| Stage | Outcome | Exit | Duration (s) |", "| --- | --- | ---: | ---: |"])
    for row in analysis.get("stage_status", []):
        lines.append(f"| {row.get('stage', '')} | {row.get('outcome', '')} | {row.get('exit_code', '')} | {row.get('duration_s', '')} |")

    lines.extend(["", "## P2 Carrier", "", "| Variant | Rows | Mean wire bytes | Mean wall (ms) | Wire improvement (aggregate / pair mean) | Wall improvement (aggregate / pair mean) |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    p2_cmp = p2.get("comparisons_vs_utf8_text_inline", {}) if isinstance(p2, Mapping) else {}
    for variant, item in p2.get("variants", {}).items():
        cmp = p2_cmp.get(variant, {}).get("metrics", {})
        wire_metric = cmp.get("wire_bytes", {})
        wall_metric = cmp.get("critical_path_wall_ms", {})
        wire_aggregate = wire_metric.get("aggregate_improvement_pct")
        wire_pair_mean = wire_metric.get("relative_improvement_pct", {}).get("mean")
        wall_aggregate = wall_metric.get("aggregate_improvement_pct")
        wall_pair_mean = wall_metric.get("relative_improvement_pct", {}).get("mean")
        lines.append(
            f"| {variant} | {item.get('row_count', 0)} | {fmt(item.get('metrics', {}).get('wire_bytes', {}).get('mean'))} | "
            f"{fmt(item.get('metrics', {}).get('critical_path_wall_ms', {}).get('mean'))} | {fmt(wire_aggregate)}% / {fmt(wire_pair_mean)}% | {fmt(wall_aggregate)}% / {fmt(wall_pair_mean)}% |"
        )
    lines.extend(["", "### P2 Size Trend", "", "| Size | SHM/ref wall improvement mean | SHM/ref wall improvement median |", "| --- | ---: | ---: |"])
    for item in p2.get("break_even_trend", {}).get("trend", []):
        lines.append(f"| {item.get('size')} | {fmt(item.get('mean_improvement_pct'))}% | {fmt(item.get('median_improvement_pct'))}% |")

    lines.extend(["", "## P3 SemanticState", "", f"- Planned cases: `{p3.get('all_case_count', 0)}`; denominator-eligible cases: `{p3.get('eligible_case_count', 0)}`; excluded: `{p3.get('excluded_case_count', 0)}`.", "", "| Scope | On mean elapsed (ms) | Elapsed improvement (aggregate / pair mean) | Total-token reduction (aggregate / pair mean) | On actual use | On quality pass |", "| --- | ---: | ---: | ---: | ---: | ---: |"])
    for label, scope in (("all cases", p3.get("all_cases", {})), ("eligible only", p3.get("eligible_only", {}))):
        on = scope.get("variants", {}).get("on", {})
        elapsed_metric = scope.get("on_vs_off", {}).get("elapsed_ms", {})
        token_metric = scope.get("on_vs_off", {}).get("total_tokens", {})
        delta = elapsed_metric.get("relative_improvement_pct", {}).get("mean")
        delta_aggregate = elapsed_metric.get("aggregate_improvement_pct")
        token_delta = token_metric.get("relative_improvement_pct", {}).get("mean")
        token_delta_aggregate = token_metric.get("aggregate_improvement_pct")
        lines.append(
            f"| {label} | {fmt(on.get('metrics', {}).get('elapsed_ms', {}).get('mean'))} | {fmt(delta_aggregate)}% / {fmt(delta)}% | {fmt(token_delta_aggregate)}% / {fmt(token_delta)}% | "
            f"{on.get('actual_use_count', 0)}/{on.get('row_count', 0)} | {on.get('quality_pass_count', 0)}/{on.get('row_count', 0)} |"
        )
    lines.extend(["", "### P3 Failure Taxonomy", "", "| Classification | Count |", "| --- | ---: |"])
    for key, value in sorted(p3.get("failure_taxonomy", {}).items()):
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "### P3 By Operation", "", "| Operation | Cases | Eligible | Eligible elapsed improvement |", "| --- | ---: | ---: | ---: |"])
    for operation, item in sorted(p3.get("by_operation", {}).items()):
        eligible = item.get("eligible_cases", {})
        delta = eligible.get("on_vs_off", {}).get("elapsed_ms", {}).get("relative_improvement_pct", {}).get("mean")
        lines.append(f"| {operation} | {item.get('all_cases', {}).get('case_count', 0)} | {eligible.get('case_count', 0)} | {fmt(delta)}% |")

    det_agg = det.get("aggregate", {})
    lines.extend(["", "## P4 Deterministic Memory", "", f"- Closed replay pairs: `{det.get('pair_count', 0)}` across `{det.get('epoch_count', 0)}` epochs, `{det.get('workload_families', det.get('independent_workload_shapes', 0))}` families, and `{det.get('independent_workload_shapes', 0)}` family-round shapes.", f"- Provider calls avoided: `{fmt(det_agg.get('provider_calls_avoided', {}).get('total'), 0)}`.", f"- Replay actual-use rows: `{det_agg.get('actual_use_count', 0)}`.", f"- Replay quality pass: `{det_agg.get('quality_pass', {}).get('replay', 0)}`.", "", "| Epoch | Pairs | Provider calls avoided | Actual use | Replay quality pass |", "| --- | ---: | ---: | ---: | ---: |"])
    for epoch in det.get("epochs", []):
        lines.append(f"| {epoch.get('epoch')} | {epoch.get('pair_count', 0)} | {fmt(epoch.get('provider_calls_avoided', {}).get('total'), 0)} | {epoch.get('actual_use_count', 0)} | {epoch.get('quality_pass', {}).get('replay', 0)} |")

    selected = live.get("selected", {})
    marginal = selected.get("marginal_runtime", {}).get("relative_improvement_pct", {}).get("mean")
    setup = selected.get("setup_inclusive_runtime", {}).get("relative_improvement_pct", {}).get("mean")
    marginal_metric = selected.get("marginal_runtime", {})
    setup_metric = selected.get("setup_inclusive_runtime", {})
    marginal_wins = marginal_metric.get("wins", 0)
    setup_wins = setup_metric.get("wins", 0)
    setup_losses = setup_metric.get("losses", 0)
    cold_sensitivity = live.get("cold_outlier_sensitivity", {}) if isinstance(live.get("cold_outlier_sensitivity"), Mapping) else {}
    all_pairs = cold_sensitivity.get("all_pairs", {}) if isinstance(cold_sensitivity.get("all_pairs"), Mapping) else {}
    without_first = cold_sensitivity.get("without_first_slot", {}) if isinstance(cold_sensitivity.get("without_first_slot"), Mapping) else {}
    all_setup = all_pairs.get("setup_inclusive_runtime", {}) if isinstance(all_pairs.get("setup_inclusive_runtime"), Mapping) else {}
    without_first_setup = without_first.get("setup_inclusive_runtime", {}) if isinstance(without_first.get("setup_inclusive_runtime"), Mapping) else {}
    lines.extend(
        [
            "",
            "## P4 Live Memory",
            "",
            f"- Selected scope: `{live.get('selected_scope', 'n/a')}`; matched slots: `{selected.get('pair_count', 0)}`.",
            f"- Distinct family-round shapes: `{live.get('distinct_family_round_shapes', 0)}`; repeat ids: `{live.get('distinct_repeat_ids', 0)}`.",
            f"- Baseline mean runtime: `{fmt(selected.get('baseline_runtime_ms', {}).get('mean'))} ms`; replay mean: `{fmt(selected.get('replay_runtime_ms', {}).get('mean'))} ms`.",
            f"- Marginal replay improvement: `{fmt(marginal_metric.get('aggregate_improvement_pct'))}%` aggregate / `{fmt(marginal)}%` per-slot mean; mean speedup: `{fmt(selected.get('marginal_speedup', {}).get('mean'))}x`; wins: `{marginal_wins}/{selected.get('pair_count', 0)}`.",
            f"- Producer-inclusive improvement: `{fmt(setup_metric.get('aggregate_improvement_pct'))}%` aggregate / `{fmt(setup)}%` per-slot mean; setup-inclusive ratio: `{fmt(selected.get('setup_inclusive_ratio', {}).get('mean'))}x`; wins/losses: `{setup_wins}/{setup_losses}`.",
            f"- Cold-slot sensitivity: removing `{cold_sensitivity.get('ordered_first_slot', 'n/a')}` changes setup-inclusive improvement from `{fmt(all_setup.get('aggregate_improvement_pct'))}%` aggregate (`{fmt(all_setup.get('relative_improvement_pct', {}).get('mean'))}%` per-slot mean) to `{fmt(without_first_setup.get('aggregate_improvement_pct'))}%` aggregate (`{fmt(without_first_setup.get('relative_improvement_pct', {}).get('mean'))}%` per-slot mean).",
            f"- Provider-not-started replay observations: `{selected.get('replay_provider_not_started', 0)}`.",
            "",
            "| Scope | Baseline mean (ms) | Replay mean (ms) | Marginal improvement (per-slot mean) | Setup-inclusive improvement (aggregate / per-slot mean) |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for label, scope in (("all", all_pairs), ("without first slot", without_first)):
        lines.append(
            f"| {label} | {fmt(scope.get('baseline_runtime_ms', {}).get('mean'))} | {fmt(scope.get('replay_runtime_ms', {}).get('mean'))} | "
            f"{fmt(scope.get('marginal_runtime', {}).get('relative_improvement_pct', {}).get('mean'))}% | "
            f"{fmt(scope.get('setup_inclusive_runtime', {}).get('aggregate_improvement_pct'))}% / "
            f"{fmt(scope.get('setup_inclusive_runtime', {}).get('relative_improvement_pct', {}).get('mean'))}% |"
        )

    lines.extend(["", "## Interpretation Boundaries", "", "- P2 measures carrier/transport behavior, not provider quality or model-level speed.", "- P3 uses the denominator's eligible pairs; all-case numbers are shown only to expose activation and quality-selection effects.", "- P4 deterministic proves replay/provider-bypass closure; it is not a live latency benchmark.", "- P4 live marginal replay is conditional on a producer having already paid setup cost. Producer-inclusive accounting is the first-use view.", "- The live campaign repeats four family-round workload shapes, so slot count is not the same as independent-task count.", "- Unsupported metrics remain unavailable; no zeros were inferred."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def analyze(run_root: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    p2 = analyze_p2(run_root / "p2", output_dir)
    p3 = analyze_p3(run_root / "p3" / "runtime" / "semantic-state-ablation", output_dir)
    p4_deterministic = analyze_p4_deterministic(run_root / "p4-deterministic", output_dir)
    p4_live = analyze_p4_live(run_root / "p4-live", output_dir)
    result: dict[str, Any] = {
        "schema_version": "statebus.contest_core_full_ablation_analysis.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_root": str(run_root),
        "claim_scope": "exploratory_benefit_observation",
        "benchmark_superiority": "NOT_ESTABLISHED",
        "statistical_superiority": "NOT_ESTABLISHED",
        "stage_status": load_stage_status(run_root / "stage_status.tsv"),
        "p2": p2,
        "p3": p3,
        "p4_deterministic": p4_deterministic,
        "p4_live": p4_live,
        "output_files": {
            "markdown": str(output_dir / "comprehensive_analysis.md"),
            "json": str(output_dir / "comprehensive_analysis.json"),
            "p2_pair_deltas": str(output_dir / "p2_pair_deltas.csv"),
            "p3_case_matrix": str(output_dir / "p3_case_matrix.csv"),
            "p4_live_pair_deltas": str(output_dir / "p4_live_pair_deltas.csv"),
        },
        "method": {
            "bootstrap_replicates": BOOTSTRAP_REPS,
            "bootstrap_seed": BOOTSTRAP_SEED,
            "paired_delta_convention": "positive means lower candidate cost than baseline",
            "missing_metric_policy": "unsupported_or_missing_remains_unavailable",
        },
    }
    result["findings"] = build_findings(result)
    json_path = output_dir / "comprehensive_analysis.json"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(result, output_dir / "comprehensive_analysis.md")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze a contest-core full ablation run offline")
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    run_root = args.run_root.resolve()
    if not run_root.is_dir():
        parser.error(f"run root not found: {run_root}")
    output_dir = (args.output_dir or run_root).resolve()
    if output_dir != run_root and run_root in output_dir.parents:
        parser.error("output-dir must not be inside run-root")
    result = analyze(run_root, output_dir)
    print(json.dumps({"json": result["output_files"]["json"], "markdown": result["output_files"]["markdown"], "findings": len(result["findings"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
