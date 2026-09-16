from __future__ import annotations

from collections.abc import Iterable, Mapping
import random

from statebus.benchmark.models import BenchmarkCaseReport


def finalize_case_telemetry_summary(
    summary: Mapping[str, float],
    cases: Iterable[BenchmarkCaseReport],
) -> dict[str, float]:
    """Recompute non-additive metrics after additive case aggregation."""

    result = {str(key): float(value) for key, value in summary.items()}
    case_list = tuple(cases)

    if any("task_ms" in case.metrics for case in case_list):
        result["task_ms"] = sum(float(case.metrics.get("task_ms", 0.0)) for case in case_list)

    hit_key = "neural_prefix_cache_hit_count_estimate"
    query_key = "neural_prefix_cache_query_count_estimate"
    rate_key = "neural_prefix_cache_hit_rate_estimate"
    if hit_key in result or query_key in result or rate_key in result:
        hits = float(result.get(hit_key, 0.0))
        queries = float(result.get(query_key, 0.0))
        result[rate_key] = hits / queries if queries else 0.0

    observed_hit_key = "vllm_prefix_observed_hit_delta"
    observed_query_key = "vllm_prefix_observed_query_delta"
    observed_rate_key = "vllm_prefix_observed_hit_rate"
    if (
        observed_hit_key in result
        or observed_query_key in result
        or observed_rate_key in result
    ):
        observed_hits = float(result.get(observed_hit_key, 0.0))
        observed_queries = float(result.get(observed_query_key, 0.0))
        result[observed_rate_key] = (
            observed_hits / observed_queries if observed_queries else 0.0
        )

    savings_key = "neural_prefix_prefill_saved_tokens_estimate"
    ratio_key = "neural_prefix_prefill_savings_ratio_estimate"
    if savings_key in result or ratio_key in result:
        total_prefill_tokens = sum(
            float(case.metrics.get("neural_prefix_estimated_prefix_tokens", 0.0))
            * float(case.metrics.get(query_key, 0.0))
            for case in case_list
        )
        result[ratio_key] = (
            float(result.get(savings_key, 0.0)) / total_prefill_tokens
            if total_prefill_tokens
            else 0.0
        )

    return result


def project_metric_availability(*, observed: Mapping[str, object] | None = None) -> dict[str, object]:
    """Project only directly observed metrics; unavailable values stay explicit."""
    observed = dict(observed or {})
    result: dict[str, object] = {}
    for name, reason in (
        ("wire_bytes", "wire_bytes_not_observed"),
        ("copy_bytes", "copy_bytes_not_observed"),
        ("hydration_bytes", "hydration_bytes_not_observed"),
        ("provider_tokens", "provider_usage_not_observed"),
        ("provider_latency", "provider_latency_not_observed"),
        ("state_bytes", "state_bytes_not_observed"),
        ("route_metrics", "route_metrics_not_observed"),
        ("memory_actual_use", "memory_actual_use_not_observed"),
        ("interval_span_ms", "interval_span_not_observed"),
    ):
        value = observed.get(name)
        # Raw frame lengths are transport diagnostics, not the canonical
        # profiling metric.  Only a caller that explicitly identifies the
        # frozen canonical surface may project ``wire_bytes`` as observed.
        if name == "wire_bytes" and isinstance(value, Mapping):
            if value.get("status") == "observed" and value.get("source") != "canonical_wire_observation":
                result[name] = {"status": "unsupported", "reason": "wire_bytes_not_observed"}
                continue
        if isinstance(value, Mapping) and value.get("status") in {"observed", "unsupported"}:
            result[name] = dict(value)
        elif name in observed and value is not None and name != "wire_bytes":
            result[name] = {"status": "observed", "value": value}
        else:
            result[name] = {"status": "unsupported", "reason": reason}
    pairings = observed.get("c2c_pairings", ())
    denominator = observed.get("c2c_denominator")
    if isinstance(pairings, Iterable) and not isinstance(pairings, (str, bytes, Mapping)):
        pair_rows = [item for item in pairings if isinstance(item, Mapping)]
        denominator_mapping = denominator if isinstance(denominator, Mapping) else None
        result["provider_work_avoided"] = _c2c_provider_work_avoided_metric(
            pair_rows,
            denominator_mapping,
        )
        result["quality_non_regression"] = _c2c_quality_non_regression_metric(pair_rows)
    else:
        result["provider_work_avoided"] = {
            "status": "unsupported",
            "value": None,
            "reason": "no_matched_baseline_or_runtime_skip_receipt",
        }
        result["quality_non_regression"] = {
            "status": "unsupported",
            "reason": "no_matched_baseline",
        }
    result["verified_recipe_work_avoided"] = {
        "status": "unsupported",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
    }
    exact_projection = {
        "status": "unsupported",
        "value": None,
        "reason": "c2_exact_restore_not_implemented",
    }
    result["exact_replay"] = dict(exact_projection)
    result["exact_replay_count"] = dict(exact_projection)
    result["recipe_step_skip"] = {
        "status": "deferred",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
    }
    result["recipe_skip_observed_count"] = {
        "status": "unsupported",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
    }
    return result


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def summarize_metric_values(values: Iterable[object]) -> dict[str, object]:
    """Return observed case-level count/p50/p95; unsupported values are explicit."""
    observed: list[float] = []
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        try:
            observed.append(float(value))
        except (TypeError, ValueError):
            continue
    if not observed:
        return {"status": "unsupported", "reason": "metric_values_not_observed", "count": 0}
    return {
        "status": "observed",
        "count": len(observed),
        "p50": _percentile(observed, 0.50),
        "p95": _percentile(observed, 0.95),
        "values": observed,
    }


def paired_deltas(
    left: Iterable[Mapping[str, object]],
    right: Iterable[Mapping[str, object]],
    *,
    key: str,
) -> list[float]:
    """Compute pair-key matched deltas only when both sides are observed."""
    left_by_key = {str(row.get("pair_key", "")): row for row in left}
    right_by_key = {str(row.get("pair_key", "")): row for row in right}
    deltas: list[float] = []
    for pair_key in sorted(left_by_key.keys() & right_by_key.keys()):
        lv, rv = left_by_key[pair_key].get(key), right_by_key[pair_key].get(key)
        try:
            if lv is None or rv is None:
                continue
            deltas.append(float(rv) - float(lv))
        except (TypeError, ValueError):
            continue
    return deltas


def _c2c_provider_work_avoided_metric(
    pairings: Iterable[Mapping[str, object]],
    denominator: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project provider-generation avoidance from validated C2-C pair rows.

    This helper deliberately accepts pair validation output rather than raw
    timings or counters.  A pair is eligible only when the projection has
    already joined a real memory-off provider invocation with a Runtime-owned
    provider-not-started observation and current quality/admission evidence.
    """
    pairs = [dict(row) for row in pairings]
    eligible = [
        row
        for row in pairs
        if row.get("status") == "eligible"
        and bool(row.get("source_receipt_hashes"))
        and bool(dict(row.get("quality_non_regression", {})).get("passed"))
    ]
    denominator_ok = denominator is not None and bool(denominator.get("arithmetic_closed"))
    if eligible and denominator_ok:
        return {
            "status": "observed",
            "value": len(eligible),
            "eligible_matched_pair_count": len(eligible),
            "source_receipt_hashes": sorted({
                str(receipt)
                for row in eligible
                for receipt in row.get("source_receipt_hashes", ())
                if str(receipt)
            }),
        }
    return {
        "status": "unsupported",
        "value": None,
        "reason": "no_matched_baseline_or_runtime_skip_receipt",
        "eligible_matched_pair_count": 0,
        "source_receipt_hashes": [],
    }


def _c2c_quality_non_regression_metric(
    pairings: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Project quality non-regression only for equivalent accepted pairs."""
    eligible = [
        dict(row)
        for row in pairings
        if row.get("status") == "eligible" and bool(row.get("source_receipt_hashes"))
    ]
    if not eligible:
        return {"status": "unsupported", "reason": "no_matched_baseline"}
    if all(bool(dict(row.get("quality_non_regression", {})).get("passed")) for row in eligible):
        return {
            "status": "observed",
            "value": True,
            "matched_pair_count": len(eligible),
            "source_receipt_hashes": sorted({
                str(receipt)
                for row in eligible
                for receipt in row.get("source_receipt_hashes", ())
                if str(receipt)
            }),
        }
    return {"status": "unsupported", "reason": "quality_non_regression_failed"}


def _g6b_evidence_counts(
    pairings: Iterable[Mapping[str, object]],
    denominator: Mapping[str, object],
) -> dict[str, object]:
    """Recompute G6-B evidence counts from eligible pair rows."""
    eligible = [dict(row) for row in pairings if row.get("status") == "eligible"]
    source_receipts = sorted({
        receipt
        for row in eligible
        for receipt in row.get("source_receipt_hashes", ())
        if isinstance(receipt, str) and receipt
    })
    denominator_closed = (
        denominator.get("arithmetic_closed") is True
        and denominator.get("row_arithmetic_closed") is True
        and denominator.get("eligible_matched_pair_count") == len(eligible)
    )
    baseline_count = sum(
        row.get("baseline_provider_invocation_status") in {"started", "completed"}
        and isinstance(row.get("baseline_provider_invocation_id"), str)
        and bool(row.get("baseline_provider_invocation_id"))
        for row in eligible
    )
    replay_count = sum(
        row.get("replay_provider_invocation_status") == "not_started"
        and row.get("replay_skip_receipt_status") == "observed"
        and isinstance(row.get("replay_skip_receipt_id"), str)
        and bool(row.get("replay_skip_receipt_id"))
        for row in eligible
    )
    evidence_complete = (
        bool(eligible)
        and baseline_count == len(eligible)
        and replay_count == len(eligible)
        and bool(source_receipts)
    )
    return {
        "status": "observed" if evidence_complete and denominator_closed else "not_applicable",
        "eligible_matched_pair_count": len(eligible),
        "baseline_provider_invocation_count": baseline_count,
        "replay_provider_not_started_count": replay_count,
        "source_receipt_hashes": source_receipts,
    }


def _g6b_quality_non_regression(
    pairings: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Project pairwise quality only; never promote it to superiority."""
    eligible = [dict(row) for row in pairings if row.get("status") == "eligible"]
    if not eligible:
        return {
            "status": "unsupported",
            "value": None,
            "reason": "no_matched_baseline",
            "matched_pair_count": 0,
            "source_receipt_hashes": [],
        }
    passed = [
        row
        for row in eligible
        if isinstance(row.get("quality_non_regression"), Mapping)
        and row["quality_non_regression"].get("status") == "observed"
        and row["quality_non_regression"].get("passed") is True
    ]
    if len(passed) != len(eligible):
        return {
            "status": "unsupported",
            "value": None,
            "reason": "quality_non_regression_failed",
            "matched_pair_count": len(eligible),
            "passed_pair_count": len(passed),
            "source_receipt_hashes": [],
        }
    return {
        "status": "observed",
        "value": True,
        "reason": "pairwise_observation_only",
        "matched_pair_count": len(eligible),
        "passed_pair_count": len(passed),
        "source_receipt_hashes": sorted({
            receipt
            for row in eligible
            for receipt in row.get("source_receipt_hashes", ())
            if isinstance(receipt, str) and receipt
        }),
    }


def _g6b_metric_availability(
    pairings: Iterable[Mapping[str, object]],
    denominator: Mapping[str, object],
    *,
    stage: str,
) -> dict[str, object]:
    """Freeze G6-B observed and unsupported metric boundaries."""
    pairings = [dict(row) for row in pairings]
    evidence_counts = _g6b_evidence_counts(pairings, denominator)
    metrics: dict[str, object] = {}

    if stage == "G6-B1" and evidence_counts["status"] == "observed":
        for name in (
            "eligible_matched_pair_count",
            "baseline_provider_invocation_count",
            "replay_provider_not_started_count",
        ):
            metrics[name] = {
                "status": "observed",
                "value": evidence_counts[name],
                "reason": "",
                "source_receipt_hashes": evidence_counts["source_receipt_hashes"],
            }
    else:
        for name in (
            "eligible_matched_pair_count",
            "baseline_provider_invocation_count",
            "replay_provider_not_started_count",
        ):
            metrics[name] = {
                "status": "not_applicable",
                "value": None,
                "reason": "g6b1_campaign_not_run",
                "source_receipt_hashes": [],
            }

    quality = _g6b_quality_non_regression(pairings)
    metrics["quality_non_regression"] = quality
    if (
        stage == "G6-B1"
        and evidence_counts["status"] == "observed"
        and quality.get("status") == "observed"
        and bool(denominator.get("arithmetic_closed"))
    ):
        metrics["provider_work_avoided"] = {
            "status": "observed",
            "value": evidence_counts["eligible_matched_pair_count"],
            "reason": "eligible_pair_count_only",
            "source_receipt_hashes": evidence_counts["source_receipt_hashes"],
        }
    else:
        metrics["provider_work_avoided"] = {
            "status": "unsupported",
            "value": None,
            "reason": "no_matched_baseline_or_runtime_skip_receipt",
            "source_receipt_hashes": [],
        }

    fixed_unsupported = {
        "provider_latency": "provider_latency_not_observed",
        "provider_work_units": "provider_work_units_not_observed",
        "provider_tokens": "provider_usage_not_observed",
        "copy_bytes": "copy_bytes_not_observed",
        "wire_bytes": "wire_bytes_not_observed",
        "hydration_bytes": "hydration_bytes_not_observed",
        "state_bytes": "state_bytes_not_observed",
        "memory_bandwidth": "memory_bandwidth_not_observed",
        "gpu_kernel_timing": "gpu_kernel_timing_not_observed",
        "allocation_reclaim_timing": "allocation_reclaim_timing_not_observed",
        "replay_restore_timing": "exact_restore_not_implemented",
        "cache_hit_count": "cache_observation_not_available",
        "cache_miss_count": "cache_observation_not_available",
        "exact_replay_count": "c2_exact_restore_not_implemented",
        "recipe_skip_observed_count": "recipe_step_skip_deferred_to_c2",
    }
    for name, reason in fixed_unsupported.items():
        metrics[name] = {
            "status": "unsupported",
            "value": None,
            "reason": reason,
            "source_receipt_hashes": [],
        }
    metrics["exact_replay"] = {
        "status": "unsupported",
        "value": None,
        "reason": "c2_exact_restore_not_implemented",
        "source_receipt_hashes": [],
    }
    metrics["recipe_step_skip"] = {
        "status": "deferred",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
        "source_receipt_hashes": [],
    }
    metrics["verified_recipe_work_avoided"] = {
        "status": "unsupported",
        "value": None,
        "reason": "recipe_step_skip_deferred_to_c2",
        "source_receipt_hashes": [],
    }
    return metrics


def bootstrap_mean_ci(
    deltas: Iterable[float],
    *,
    resamples: int = 10_000,
    seed: int = 2027,
) -> dict[str, object]:
    """Paired-difference percentile bootstrap with the frozen C2B seed/count."""
    values = [float(value) for value in deltas]
    if not values:
        return {"status": "unsupported", "reason": "paired_denominator_empty", "resamples": resamples, "seed": seed}
    rng = random.Random(seed)
    means = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(resamples)]
    means.sort()
    return {
        "status": "observed",
        "n": len(values),
        "mean": sum(values) / len(values),
        "ci95": [_percentile(means, 0.025), _percentile(means, 0.975)],
        "resamples": resamples,
        "seed": seed,
    }


def holm_adjust(p_values: Mapping[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values for the pre-registered contrasts."""
    ordered = sorted(((str(name), float(value)) for name, value in p_values.items()), key=lambda item: item[1])
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, value * (total - index)))
        adjusted[name] = running
    return adjusted


def aggregate_c2b_statistics(rows: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Build descriptive lane/family/repeat summaries without estimating missing metrics."""
    rows = [dict(row) for row in rows]
    grouped: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (str(row.get("lane", "")), str(row.get("family_id", "")), str(row.get("repeat_id", "")))
        grouped.setdefault(key, []).append(row)
    summaries = []
    for (lane, family, repeat), group in sorted(grouped.items()):
        summaries.append({
            "lane": lane,
            "family_id": family,
            "repeat_id": repeat,
            "row_count": len(group),
            "terminal_counts": {
                status: sum(str(item.get("terminal_status", "")) == status for item in group)
                for status in ("success", "quality_fail", "timeout", "unsupported", "runtime_fail", "policy_reject", "environment_fail")
            },
            "wall_time": summarize_metric_values(item.get("wall_time") for item in group),
            "prompt_tokens": summarize_metric_values(item.get("prompt_tokens") for item in group),
            "completion_tokens": summarize_metric_values(item.get("completion_tokens") for item in group),
        })
    return {"schema_version": "statebus.c2b.statistics.v1", "row_count": len(rows), "groups": summaries}


def _g6b2_evidence_counts(
    baseline_rows: Iterable[Mapping[str, object]] = (),
    replay_rows: Iterable[Mapping[str, object]] = (),
    pair_projection: Iterable[Mapping[str, object]] = (),
    failure_rows: Iterable[Mapping[str, object]] = (),
    denominator: Mapping[str, object] | None = None,
    producer_rows: Iterable[Mapping[str, object]] = (),
    stage_rows: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Recompute bounded live evidence counts from raw rows and pair projection."""
    baseline = [dict(row) for row in baseline_rows]
    replay = [dict(row) for row in replay_rows]
    pairs = [dict(row) for row in pair_projection]
    failures = [dict(row) for row in failure_rows]
    producer = [dict(row) for row in producer_rows]
    stages = [dict(row) for row in stage_rows]
    eligible = [row for row in pairs if row.get("status") == "eligible"]
    rejected = [row for row in pairs if row.get("status") == "rejected"]
    observed_baseline = sum(
        isinstance(row.get("provider_invocation_evidence"), Mapping)
        and row["provider_invocation_evidence"].get("status") == "observed"
        and row["provider_invocation_evidence"].get("invocation_status") in {"started", "completed"}
        for row in baseline
    )
    observed_replay = sum(
        isinstance(row.get("provider_not_started_observation"), Mapping)
        and row["provider_not_started_observation"].get("status") == "observed"
        and row["provider_not_started_observation"].get("provider_invocation_status") == "not_started"
        for row in replay
    )
    unmatched = sum(row.get("status") == "unmatched" for row in failures)
    terminal_rows = [*baseline, *replay, *producer, *stages]
    terminal_counts = {
        status: sum(row.get("terminal_status") == status for row in terminal_rows)
        for status in (
            "success", "runtime_fail", "timeout", "environment_fail",
            "policy_reject", "unsupported", "quality_fail",
        )
    }
    return {
        "baseline_row_count": len(baseline),
        "replay_row_count": len(replay),
        "producer_row_count": len(producer),
        "stage_row_count": len(stages),
        "matched_pair_count": len(pairs),
        "eligible_matched_pair_count": len(eligible),
        "rejected_matched_pair_count": len(rejected),
        "unmatched_row_count": unmatched,
        "live_baseline_provider_invocation_count": observed_baseline,
        "live_replay_provider_not_started_count": observed_replay,
        "attempted": len(terminal_rows),
        "success": terminal_counts["success"],
        "runtime_fail": terminal_counts["runtime_fail"],
        "timeout": terminal_counts["timeout"],
        "environment_fail": terminal_counts["environment_fail"],
        "policy_reject": terminal_counts["policy_reject"],
        "unsupported": terminal_counts["unsupported"],
        "quality_fail": terminal_counts["quality_fail"],
        "baseline_source_receipt_references": sorted({
            str(value)
            for row in baseline
            for value in row.get("source_receipt_references", row.get("source_receipt_hashes", ()))
            if isinstance(value, str) and value
        }),
        "replay_source_receipt_references": sorted({
            str(value)
            for row in replay
            for value in row.get("source_receipt_references", row.get("source_receipt_hashes", ()))
            if isinstance(value, str) and value
        }),
        "pair_source_receipt_references": sorted({
            str(value)
            for row in pairs
            for value in row.get("source_receipt_references", row.get("source_receipt_hashes", ()))
            if isinstance(value, str) and value
        }),
        "denominator_linked": denominator is not None,
    }


def _g6b2_metric_availability(
    baseline_rows: Iterable[Mapping[str, object]] = (),
    replay_rows: Iterable[Mapping[str, object]] = (),
    pair_projection: Iterable[Mapping[str, object]] = (),
    failure_rows: Iterable[Mapping[str, object]] = (),
    denominator: Mapping[str, object] | None = None,
    environment_health: Mapping[str, object] | None = None,
    producer_rows: Iterable[Mapping[str, object]] = (),
    stage_rows: Iterable[Mapping[str, object]] = (),
) -> dict[str, object]:
    """Project only receipt-backed B2 metrics; preserve explicit unsupported values."""
    baseline = [dict(row) for row in baseline_rows]
    replay = [dict(row) for row in replay_rows]
    pairs = [dict(row) for row in pair_projection]
    counts = _g6b2_evidence_counts(
        baseline, replay, pairs, failure_rows, denominator,
        producer_rows=producer_rows, stage_rows=stage_rows,
    )
    baseline_refs = counts["baseline_source_receipt_references"]
    replay_refs = counts["replay_source_receipt_references"]
    pair_refs = counts["pair_source_receipt_references"]
    all_refs = sorted(set([*baseline_refs, *replay_refs, *pair_refs]))
    denominator_refs = ["live_failure_denominator.json"] if denominator is not None else []
    closed = bool(
        denominator
        and denominator.get("arithmetic_closed")
        and denominator.get("row_arithmetic_closed")
    )
    eligible = [row for row in pairs if row.get("status") == "eligible"]
    quality_pass = bool(eligible) and all(
        isinstance(row.get("quality_non_regression"), Mapping)
        and row["quality_non_regression"].get("passed") is True
        for row in eligible
    )
    metrics: dict[str, object] = {}

    def observed(name: str, value: object, source: Iterable[str]) -> None:
        source_list = sorted({str(item) for item in source if str(item)})
        metrics[name] = {
            "status": "observed" if source_list else "unsupported",
            "value": value if source_list else None,
            "reason": "" if source_list else "source_receipt_missing",
            "source_receipt_references": source_list,
        }

    observed("live_baseline_provider_invocation_count", counts["live_baseline_provider_invocation_count"], baseline_refs)
    observed("live_replay_provider_not_started_count", counts["live_replay_provider_not_started_count"], replay_refs)
    observed("live_matched_pair_count", counts["matched_pair_count"], pair_refs)
    observed("live_eligible_matched_pair_count", counts["eligible_matched_pair_count"], pair_refs)
    metrics["provider_work_avoided"] = {
        "status": "observed" if quality_pass and closed else "unsupported",
        "value": len(eligible) if quality_pass and closed else None,
        "reason": "eligible_pair_count_only" if quality_pass and closed else "no_eligible_live_matched_pair",
        "source_receipt_references": pair_refs if quality_pass and closed else [],
    }
    observed("live_quality_non_regression", True, pair_refs) if quality_pass and closed else metrics.update({
        "live_quality_non_regression": {"status": "unsupported", "value": None, "reason": "no_eligible_quality_join", "source_receipt_references": []}
    })
    admission_pass = bool(eligible) and all(
        isinstance(row.get("equivalence_checks"), Mapping)
        and row["equivalence_checks"].get("result_admission") is True
        for row in eligible
    )
    observed("live_result_admission_closure", True, pair_refs) if admission_pass and closed else metrics.update({
        "live_result_admission_closure": {"status": "unsupported", "value": None, "reason": "result_admission_join_missing", "source_receipt_references": []}
    })
    health = dict(environment_health or {})
    health_refs = [str(item) for item in health.get("source_receipt_references", ()) if str(item)]
    metrics["live_environment_health"] = {
        "status": "observed" if health.get("status") == "observed" and health_refs else "unsupported",
        "value": True if health.get("status") == "observed" and health_refs else None,
        "reason": "" if health.get("status") == "observed" and health_refs else "environment_health_not_observed",
        "source_receipt_references": sorted(set(health_refs)),
    }
    metrics["live_failure_counts"] = {
        "status": "observed" if denominator is not None else "unsupported",
        "value": {key: counts[key] for key in ("attempted", "success", "runtime_fail", "timeout", "environment_fail", "policy_reject", "unsupported", "quality_fail")},
        "reason": "" if denominator is not None else "failure_denominator_missing",
        "source_receipt_references": sorted(set([*all_refs, *denominator_refs])),
    }
    fixed = {
        "exact_replay": ("unsupported", "c2_exact_restore_not_implemented"),
        "recipe_step_skip": ("deferred", "recipe_step_skip_deferred_to_c2"),
        "verified_recipe_work_avoided": ("unsupported", "recipe_step_skip_deferred_to_c2"),
    }
    for name, (status, reason) in fixed.items():
        metrics[name] = {"status": status, "value": None, "reason": reason, "source_receipt_references": []}
    for name in (
        "provider_latency", "provider_work_units", "provider_tokens", "gpu_kernel_timing",
        "memory_bandwidth", "copy_bytes", "wire_bytes", "hydration_bytes",
        "allocation_reclaim_timing", "cache_hit_count", "cache_miss_count", "replay_restore_timing",
    ):
        metrics[name] = {"status": "unsupported", "value": None, "reason": f"{name}_not_observed", "source_receipt_references": []}
    return metrics
