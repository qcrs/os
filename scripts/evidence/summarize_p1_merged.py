#!/usr/bin/env python3
"""Merge repaired P1 slot results and emit descriptive evidence summaries.

The canonical manifest is the only denominator. Result roots are processed in
the order provided, and the first accepted row for each canonical slot wins.
This prevents later reruns from replacing an earlier valid observation merely
because they happened to be faster or cheaper.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence


LANE_ORDER = (
    "direct_single_agent",
    "pure_text_mas",
    "fixed_structured",
    "adaptive_routed",
)

SLOT_KEY_FIELDS = (
    "case_id",
    "lane",
    "split",
    "repeat",
    "round",
    "seed",
    "profile_id",
    "regime",
)

COMPARISONS = (
    ("direct_single_agent", "pure_text_mas"),
    ("direct_single_agent", "fixed_structured"),
    ("direct_single_agent", "adaptive_routed"),
    ("pure_text_mas", "fixed_structured"),
    ("pure_text_mas", "adaptive_routed"),
    ("fixed_structured", "adaptive_routed"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical-root",
        required=True,
        type=Path,
        help="P1 root containing the canonical stage2_manifest.json",
    )
    parser.add_argument(
        "--result-root",
        required=True,
        action="append",
        type=Path,
        help="Result root containing raw_rows.json; repeat in selection order",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def percentile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def numeric(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def describe(values: Iterable[object]) -> dict[str, object]:
    observed = [number for value in values if (number := numeric(value)) is not None]
    if not observed:
        return {
            "count": 0,
            "sum": None,
            "min": None,
            "p50": None,
            "p95": None,
            "max": None,
            "mean": None,
        }
    return {
        "count": len(observed),
        "sum": sum(observed),
        "min": min(observed),
        "p50": statistics.median(observed),
        "p95": percentile(observed, 0.95),
        "max": max(observed),
        "mean": statistics.fmean(observed),
    }


def canonical_key(slot: Mapping[str, object]) -> tuple[object, ...]:
    return tuple(slot.get(field) for field in SLOT_KEY_FIELDS)


def row_key(row: Mapping[str, object]) -> tuple[object, ...]:
    normalized = dict(row)
    normalized["case_id"] = row.get("task_id")
    return canonical_key(normalized)


def pair_key(row: Mapping[str, object]) -> tuple[object, ...]:
    return (
        row.get("task_id"),
        row.get("split"),
        row.get("repeat"),
        row.get("round"),
        row.get("seed"),
        row.get("profile_id"),
        row.get("regime"),
    )


def accepted(row: Mapping[str, object]) -> bool:
    if row.get("schema_version") != "statebus.stage2_pilot_raw.v2":
        return False
    if row.get("status") != "success" or row.get("terminal_class") != "success":
        return False
    if row.get("provider_invocation_status") != "response_received":
        return False
    if not row.get("provider_request_events"):
        return False
    quality = row.get("quality")
    if not isinstance(quality, Mapping) or quality.get("passed") is not True:
        return False
    gates = row.get("gates")
    if not isinstance(gates, Mapping) or any(value is False for value in gates.values()):
        return False
    return True


def family_by_case(manifest: Mapping[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in manifest.get("families", []):
        family_id, separator, case_id = str(item).partition("::")
        if separator:
            result[case_id] = family_id
    return result


def request_elapsed_sum_ms(row: Mapping[str, object]) -> float | None:
    elapsed: list[float] = []
    for event in row.get("provider_request_events", []):
        if not isinstance(event, Mapping):
            continue
        start_ns = numeric(event.get("start_ns"))
        end_ns = numeric(event.get("end_ns"))
        if start_ns is not None and end_ns is not None:
            elapsed.append((end_ns - start_ns) / 1_000_000.0)
    return sum(elapsed) if elapsed else None


def usage_value(row: Mapping[str, object], field: str) -> object:
    usage = row.get("provider_usage")
    return usage.get(field) if isinstance(usage, Mapping) else None


def metric_value(row: Mapping[str, object], metric: str) -> object:
    if metric == "provider_request_elapsed_sum_ms":
        return request_elapsed_sum_ms(row)
    if metric in {"prompt_tokens", "completion_tokens", "total_tokens"}:
        return usage_value(row, metric)
    return row.get(metric)


METRICS = (
    "e2e_latency_ms",
    "provider_latency_ms",
    "provider_request_elapsed_sum_ms",
    "provider_calls",
    "retry_count",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)


def finish_reason_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        for event in row.get("provider_request_events", []):
            if isinstance(event, Mapping):
                counts[str(event.get("finish_reason") or "missing")] += 1
    return dict(sorted(counts.items()))


def event_observation_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    row_list = list(rows)
    event_count = 0
    timed_event_count = 0
    missing_finish_reason_event_count = 0
    rows_without_timed_events = 0
    rows_with_missing_finish_reason = 0
    for row in row_list:
        events = [
            event
            for event in row.get("provider_request_events", [])
            if isinstance(event, Mapping)
        ]
        event_count += len(events)
        timed_count = sum(
            numeric(event.get("start_ns")) is not None
            and numeric(event.get("end_ns")) is not None
            for event in events
        )
        missing_finish_count = sum(event.get("finish_reason") is None for event in events)
        timed_event_count += timed_count
        missing_finish_reason_event_count += missing_finish_count
        rows_without_timed_events += timed_count == 0
        rows_with_missing_finish_reason += missing_finish_count > 0
    return {
        "event_count": event_count,
        "timed_event_count": timed_event_count,
        "missing_finish_reason_event_count": missing_finish_reason_event_count,
        "rows_without_timed_events": rows_without_timed_events,
        "rows_with_missing_finish_reason": rows_with_missing_finish_reason,
    }


def summarize_group(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "row_count": len(rows),
        "metrics": {
            metric: describe(metric_value(row, metric) for row in rows)
            for metric in METRICS
        },
        "rows_with_retry": sum((numeric(row.get("retry_count")) or 0.0) > 0 for row in rows),
        "finish_reason_counts": finish_reason_counts(rows),
        "event_observation": event_observation_counts(rows),
        "source_counts": dict(sorted(Counter(str(row["merge_source_label"]) for row in rows).items())),
    }


def flatten_summary_row(group: Mapping[str, object], summary: Mapping[str, object]) -> dict[str, object]:
    flat = dict(group)
    flat["row_count"] = summary["row_count"]
    flat["rows_with_retry"] = summary["rows_with_retry"]
    metrics = summary["metrics"]
    assert isinstance(metrics, Mapping)
    for metric in METRICS:
        description = metrics[metric]
        assert isinstance(description, Mapping)
        for statistic in ("count", "mean", "p50", "p95", "max", "sum"):
            flat[f"{metric}_{statistic}"] = description.get(statistic)
    return flat


def write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ratio(candidate: object, baseline: object) -> float | None:
    candidate_number = numeric(candidate)
    baseline_number = numeric(baseline)
    if candidate_number is None or baseline_number in {None, 0.0}:
        return None
    return candidate_number / baseline_number


def delta(candidate: object, baseline: object) -> float | None:
    candidate_number = numeric(candidate)
    baseline_number = numeric(baseline)
    if candidate_number is None or baseline_number is None:
        return None
    return candidate_number - baseline_number


def comparison_rows(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    by_pair: dict[tuple[object, ...], dict[str, Mapping[str, object]]] = defaultdict(dict)
    for row in rows:
        by_pair[pair_key(row)][str(row["lane"])] = row

    result: list[dict[str, object]] = []
    for key in sorted(by_pair, key=lambda item: tuple(str(value) for value in item)):
        lanes = by_pair[key]
        for baseline_lane, candidate_lane in COMPARISONS:
            baseline = lanes.get(baseline_lane)
            candidate = lanes.get(candidate_lane)
            if baseline is None or candidate is None:
                continue
            record: dict[str, object] = {
                "family_id": candidate["canonical_family_id"],
                "case_id": candidate["task_id"],
                "baseline_lane": baseline_lane,
                "candidate_lane": candidate_lane,
            }
            for metric in ("e2e_latency_ms", "total_tokens", "provider_calls"):
                baseline_value = metric_value(baseline, metric)
                candidate_value = metric_value(candidate, metric)
                record[f"baseline_{metric}"] = baseline_value
                record[f"candidate_{metric}"] = candidate_value
                record[f"delta_{metric}"] = delta(candidate_value, baseline_value)
                record[f"ratio_{metric}"] = ratio(candidate_value, baseline_value)
            result.append(record)
    return result


def comparison_summary(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["baseline_lane"]), str(row["candidate_lane"]))].append(row)

    result: list[dict[str, object]] = []
    for (baseline_lane, candidate_lane), group_rows in grouped.items():
        record: dict[str, object] = {
            "baseline_lane": baseline_lane,
            "candidate_lane": candidate_lane,
            "pair_count": len(group_rows),
        }
        for metric in ("e2e_latency_ms", "total_tokens", "provider_calls"):
            deltas = [row[f"delta_{metric}"] for row in group_rows]
            ratios = [row[f"ratio_{metric}"] for row in group_rows]
            observed_deltas = [value for value in deltas if numeric(value) is not None]
            record[f"delta_{metric}"] = describe(observed_deltas)
            record[f"ratio_{metric}"] = describe(ratios)
            record[f"candidate_lower_{metric}_count"] = sum(
                float(value) < 0.0 for value in observed_deltas
            )
            record[f"candidate_equal_{metric}_count"] = sum(
                float(value) == 0.0 for value in observed_deltas
            )
            record[f"candidate_higher_{metric}_count"] = sum(
                float(value) > 0.0 for value in observed_deltas
            )
        result.append(record)
    return result


def top_rows(
    rows: Sequence[Mapping[str, object]], metric: str, limit: int = 10
) -> list[dict[str, object]]:
    observed = [row for row in rows if numeric(metric_value(row, metric)) is not None]
    observed.sort(key=lambda row: float(metric_value(row, metric)), reverse=True)
    return [
        {
            "canonical_slot_id": row["slot_id"],
            "family_id": row["canonical_family_id"],
            "case_id": row["task_id"],
            "lane": row["lane"],
            "value": metric_value(row, metric),
            "source": row["merge_source_label"],
        }
        for row in observed[:limit]
    ]


def format_number(value: object, digits: int = 1) -> str:
    number = numeric(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}f}"


def markdown_report(summary: Mapping[str, object]) -> str:
    denominator = summary["denominator"]
    sources = summary["sources"]
    lane_summaries = summary["lane_summaries"]
    comparisons = summary["comparison_summaries"]
    outliers = summary["outliers"]
    gaps = summary["evidence_gaps"]
    assert isinstance(denominator, Mapping)
    assert isinstance(sources, Sequence)
    assert isinstance(lane_summaries, Sequence)
    assert isinstance(comparisons, Sequence)
    assert isinstance(outliers, Mapping)
    assert isinstance(gaps, Mapping)

    lines = [
        "# P1 merged result report",
        "",
        "## Denominator",
        "",
        f"- Canonical planned slots: {denominator['planned_slot_count']}",
        f"- Accepted merged slots: {denominator['accepted_slot_count']}",
        f"- Missing slots: {denominator['missing_slot_count']}",
        f"- Accepted coverage: {format_number(denominator['coverage_pct'], 2)}%",
        "- Selection policy: `first_accepted_root_order`",
        "",
        "This is an eventual repaired closure across multiple runs, not a clean single-campaign pass rate.",
        "",
        "## Source contribution",
        "",
        "| order | result root | input success | selected slots |",
        "|---:|---|---:|---:|",
    ]
    for source in sources:
        assert isinstance(source, Mapping)
        lines.append(
            f"| {source['root_index']} | `{source['path']}` | "
            f"{source['status_counts'].get('success', 0)} | {source['selected_count']} |"
        )

    lines.extend(
        [
            "",
            "## Lane summary",
            "",
            "| lane | rows | e2e p50 ms | e2e p95 ms | mean tokens | mean calls | retry rows |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in lane_summaries:
        assert isinstance(item, Mapping)
        metrics = item["metrics"]
        assert isinstance(metrics, Mapping)
        lines.append(
            f"| {item['lane']} | {item['row_count']} | "
            f"{format_number(metrics['e2e_latency_ms']['p50'])} | "
            f"{format_number(metrics['e2e_latency_ms']['p95'])} | "
            f"{format_number(metrics['total_tokens']['mean'])} | "
            f"{format_number(metrics['provider_calls']['mean'], 2)} | "
            f"{item['rows_with_retry']} |"
        )

    lines.extend(
        [
            "",
            "## Paired descriptive comparisons",
            "",
            "| baseline | candidate | pairs | e2e ratio p50 | token ratio p50 | candidate faster | candidate fewer tokens |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for item in comparisons:
        assert isinstance(item, Mapping)
        lines.append(
            f"| {item['baseline_lane']} | {item['candidate_lane']} | {item['pair_count']} | "
            f"{format_number(item['ratio_e2e_latency_ms']['p50'], 2)} | "
            f"{format_number(item['ratio_total_tokens']['p50'], 2)} | "
            f"{item['candidate_lower_e2e_latency_ms_count']} | "
            f"{item['candidate_lower_total_tokens_count']} |"
        )

    lines.extend(
        [
            "",
            "## Evidence gaps",
            "",
            f"- Rows missing row-level provider latency: {gaps['missing_provider_latency_count']}",
            f"- Rows missing provider usage: {gaps['missing_provider_usage_count']}",
            f"- Provider events missing request timing: {gaps['missing_request_timing_event_count']}",
            f"- Provider events missing finish reason: {gaps['missing_finish_reason_event_count']}",
            f"- Rows with non-stop finish reasons: {gaps['non_stop_finish_reason_row_count']}",
            f"- Duplicate accepted candidates kept only in audit: {gaps['duplicate_accepted_count']}",
            "",
            "## Highest latency rows",
            "",
            "| case | lane | e2e ms | source |",
            "|---|---|---:|---|",
        ]
    )
    for row in outliers["e2e_latency_ms"]:
        lines.append(
            f"| {row['case_id']} | {row['lane']} | {format_number(row['value'])} | {row['source']} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "The merged result supports P1 chain closure and descriptive cost/latency diagnosis. "
            "It must not be used as statistical superiority evidence because the rows came from "
            "different repair runs with uncontrolled provider cache and different execution times.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    canonical_root = args.canonical_root.resolve()
    result_roots = [root.resolve() for root in args.result_root]
    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    manifest = load_json(canonical_root / "stage2_manifest.json")
    planned_slots = manifest["planned_slots"]
    canonical_by_key = {canonical_key(slot): slot for slot in planned_slots}
    family_map = family_by_case(manifest)

    selected: dict[tuple[object, ...], dict[str, object]] = {}
    attempts: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    duplicate_accepted: list[dict[str, object]] = []
    noncanonical_rows: list[dict[str, object]] = []
    source_summaries: list[dict[str, object]] = []

    for root_index, result_root in enumerate(result_roots):
        rows = load_json(result_root / "raw_rows.json")
        label = f"r{root_index}:{result_root.parent.name}/{result_root.name}"
        selected_before = len(selected)
        accepted_candidate_count = 0
        for row_index, raw_row in enumerate(rows):
            row = dict(raw_row)
            key = row_key(row)
            is_accepted = accepted(row)
            if key not in canonical_by_key:
                noncanonical_rows.append(
                    {
                        "result_root": str(result_root),
                        "row_index": row_index,
                        "slot_id": row.get("slot_id"),
                    }
                )
                continue
            attempts[key].append(
                {
                    "root_index": root_index,
                    "source_label": label,
                    "status": row.get("status"),
                    "terminal_class": row.get("terminal_class"),
                    "failure": row.get("failure"),
                    "accepted": is_accepted,
                    "observed_slot_id": row.get("slot_id"),
                }
            )
            if not is_accepted:
                continue
            accepted_candidate_count += 1
            canonical_slot = canonical_by_key[key]
            if key in selected:
                duplicate_accepted.append(
                    {
                        "canonical_slot_id": canonical_slot["slot_id"],
                        "selected_source": selected[key]["merge_source_label"],
                        "duplicate_source": label,
                        "duplicate_observed_slot_id": row.get("slot_id"),
                    }
                )
                continue
            observed_slot_id = row.get("slot_id")
            row.update(
                {
                    "observed_slot_id": observed_slot_id,
                    "slot_id": canonical_slot["slot_id"],
                    "pair_id": canonical_slot["pair_id"],
                    "canonical_family_id": family_map[str(canonical_slot["case_id"])],
                    "merge_source_root": str(result_root),
                    "merge_source_label": label,
                    "merge_source_index": root_index,
                }
            )
            selected[key] = row

        source_summaries.append(
            {
                "root_index": root_index,
                "label": label,
                "path": str(result_root),
                "input_row_count": len(rows),
                "status_counts": dict(sorted(Counter(str(row.get("status")) for row in rows).items())),
                "accepted_candidate_count": accepted_candidate_count,
                "selected_count": len(selected) - selected_before,
            }
        )

    merged_rows = [selected[key] for key in canonical_by_key if key in selected]
    missing_slots = [canonical_by_key[key] for key in canonical_by_key if key not in selected]

    lane_groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    family_lane_groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for row in merged_rows:
        lane_groups[str(row["lane"])].append(row)
        family_lane_groups[(str(row["canonical_family_id"]), str(row["lane"]))].append(row)

    lane_summaries = [
        {"lane": lane, **summarize_group(lane_groups[lane])}
        for lane in LANE_ORDER
    ]
    family_lane_summaries = [
        {
            "family_id": family_id,
            "lane": lane,
            **summarize_group(family_lane_groups[(family_id, lane)]),
        }
        for family_id in sorted(set(family_map.values()))
        for lane in LANE_ORDER
    ]

    pairs = comparison_rows(merged_rows)
    pair_summaries = comparison_summary(pairs)
    non_stop_rows = [
        row
        for row in merged_rows
        if any(
            isinstance(event, Mapping) and event.get("finish_reason") not in {"stop", None}
            for event in row.get("provider_request_events", [])
        )
    ]
    retry_rows = [row for row in merged_rows if (numeric(row.get("retry_count")) or 0.0) > 0]
    summary: dict[str, object] = {
        "schema_version": "statebus.p1_merged_summary.v1",
        "claim_scope": "descriptive_repaired_p1_closure_no_superiority",
        "selection_policy": "first_accepted_root_order",
        "canonical_root": str(canonical_root),
        "result_roots": [str(root) for root in result_roots],
        "denominator": {
            "planned_slot_count": len(planned_slots),
            "accepted_slot_count": len(merged_rows),
            "missing_slot_count": len(missing_slots),
            "coverage_pct": 100.0 * len(merged_rows) / len(planned_slots),
            "case_count": len(family_map),
            "lane_count": len(LANE_ORDER),
        },
        "sources": source_summaries,
        "lane_summaries": lane_summaries,
        "family_lane_summaries": family_lane_summaries,
        "comparison_summaries": pair_summaries,
        "evidence_gaps": {
            "missing_provider_latency_count": sum(
                numeric(row.get("provider_latency_ms")) is None for row in merged_rows
            ),
            "missing_provider_usage_count": sum(
                numeric(usage_value(row, "total_tokens")) is None for row in merged_rows
            ),
            "missing_request_timing_event_count": sum(
                numeric(event.get("start_ns")) is None
                or numeric(event.get("end_ns")) is None
                for row in merged_rows
                for event in row.get("provider_request_events", [])
                if isinstance(event, Mapping)
            ),
            "missing_finish_reason_event_count": sum(
                event.get("finish_reason") is None
                for row in merged_rows
                for event in row.get("provider_request_events", [])
                if isinstance(event, Mapping)
            ),
            "rows_without_request_timing_count": sum(
                request_elapsed_sum_ms(row) is None for row in merged_rows
            ),
            "rows_with_missing_finish_reason_count": sum(
                any(
                    isinstance(event, Mapping) and event.get("finish_reason") is None
                    for event in row.get("provider_request_events", [])
                )
                for row in merged_rows
            ),
            "non_stop_finish_reason_row_count": len(non_stop_rows),
            "duplicate_accepted_count": len(duplicate_accepted),
            "noncanonical_input_row_count": len(noncanonical_rows),
        },
        "retry_rows": [
            {
                "slot_id": row["slot_id"],
                "family_id": row["canonical_family_id"],
                "case_id": row["task_id"],
                "lane": row["lane"],
                "retry_count": row["retry_count"],
                "source": row["merge_source_label"],
            }
            for row in retry_rows
        ],
        "non_stop_finish_reason_rows": [
            {
                "slot_id": row["slot_id"],
                "case_id": row["task_id"],
                "lane": row["lane"],
                "finish_reasons": finish_reason_counts([row]),
                "source": row["merge_source_label"],
            }
            for row in non_stop_rows
        ],
        "outliers": {
            "e2e_latency_ms": top_rows(merged_rows, "e2e_latency_ms"),
            "total_tokens": top_rows(merged_rows, "total_tokens"),
            "provider_calls": top_rows(merged_rows, "provider_calls"),
        },
    }

    merge_audit = {
        "schema_version": "statebus.p1_merge_audit.v1",
        "selection_policy": "first_accepted_root_order",
        "slot_key_fields": list(SLOT_KEY_FIELDS),
        "accepted_requirements": [
            "schema_version=statebus.stage2_pilot_raw.v2",
            "status=success",
            "terminal_class=success",
            "provider_invocation_status=response_received",
            "provider_request_events_non_empty",
            "quality.passed=true",
            "no_explicit_false_gate",
        ],
        "sources": source_summaries,
        "missing_slots": missing_slots,
        "duplicate_accepted": duplicate_accepted,
        "noncanonical_rows": noncanonical_rows,
        "slot_attempts": [
            {
                "canonical_slot_id": canonical_by_key[key]["slot_id"],
                "attempts": attempts.get(key, []),
            }
            for key in canonical_by_key
        ],
    }

    write_json(output_root / "merged_rows.json", merged_rows)
    write_json(output_root / "merge_audit.json", merge_audit)
    write_json(output_root / "summary.json", summary)
    write_csv(
        output_root / "lane_summary.csv",
        [flatten_summary_row({"lane": row["lane"]}, row) for row in lane_summaries],
    )
    write_csv(
        output_root / "family_lane_summary.csv",
        [
            flatten_summary_row(
                {"family_id": row["family_id"], "lane": row["lane"]}, row
            )
            for row in family_lane_summaries
        ],
    )
    write_csv(output_root / "paired_comparisons.csv", pairs)
    (output_root / "REPORT.md").write_text(markdown_report(summary), encoding="utf-8")

    print(
        json.dumps(
            {
                "planned": len(planned_slots),
                "accepted": len(merged_rows),
                "missing": len(missing_slots),
                "output_root": str(output_root),
                "selected_by_source": {
                    source["label"]: source["selected_count"] for source in source_summaries
                },
            },
            sort_keys=True,
        )
    )
    return 0 if not missing_slots else 2


if __name__ == "__main__":
    raise SystemExit(main())
