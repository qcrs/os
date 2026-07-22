from __future__ import annotations

from collections.abc import Iterable, Mapping

from v2.benchmark.models import BenchmarkCaseReport


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

    observed_hit_key = "vllm_prefix_observed_hit_token_delta"
    observed_query_key = "vllm_prefix_observed_query_token_delta"
    observed_rate_key = "vllm_prefix_observed_token_hit_rate"
    legacy_observed_hit_key = "vllm_prefix_observed_hit_delta"
    legacy_observed_query_key = "vllm_prefix_observed_query_delta"
    legacy_observed_rate_key = "vllm_prefix_observed_hit_rate"
    if observed_hit_key not in result and legacy_observed_hit_key in result:
        result[observed_hit_key] = result[legacy_observed_hit_key]
    if observed_query_key not in result and legacy_observed_query_key in result:
        result[observed_query_key] = result[legacy_observed_query_key]
    if observed_rate_key not in result and legacy_observed_rate_key in result:
        result[observed_rate_key] = result[legacy_observed_rate_key]
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
