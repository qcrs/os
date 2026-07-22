from __future__ import annotations

from v2.benchmark.metric_aggregation import finalize_case_telemetry_summary


def test_observed_prefix_hit_rate_uses_ratio_of_sums() -> None:
    summary = {
        "vllm_prefix_observed_hit_token_delta": 10.0,
        "vllm_prefix_observed_query_token_delta": 12.0,
        "vllm_prefix_observed_token_hit_rate": 1.4,
    }

    result = finalize_case_telemetry_summary(summary, ())

    assert result["vllm_prefix_observed_token_hit_rate"] == 10.0 / 12.0


def test_observed_prefix_hit_rate_is_zero_without_queries() -> None:
    summary = {
        "vllm_prefix_observed_hit_token_delta": 0.0,
        "vllm_prefix_observed_query_token_delta": 0.0,
        "vllm_prefix_observed_token_hit_rate": 2.0,
    }

    result = finalize_case_telemetry_summary(summary, ())

    assert result["vllm_prefix_observed_token_hit_rate"] == 0.0
