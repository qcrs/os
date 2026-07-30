from __future__ import annotations

from statebus.runtime.vllm_metrics import (
    compute_vllm_prefix_cache_counter_delta,
    parse_vllm_prefix_cache_metrics,
)


def _metrics(queries: int, hits: int, *, worker: str = "0"):
    return parse_vllm_prefix_cache_metrics(
        f'vllm:gpu_prefix_cache_queries_total{{model_name="qwen",worker="{worker}"}} {queries}\n'
        f'vllm:gpu_prefix_cache_hits_total{{model_name="qwen",worker="{worker}"}} {hits}\n'
    )


def test_matching_labeled_token_counters_produce_valid_request_observation() -> None:
    delta = compute_vllm_prefix_cache_counter_delta(
        _metrics(10, 4),
        _metrics(15, 7),
        exclusive_interval=True,
        request_count=1,
        retry_count=0,
    )

    assert delta.valid is True
    assert delta.counter_unit == "tokens"
    assert delta.observed_query_token_delta == 5
    assert delta.observed_hit_token_delta == 3
    assert delta.observed_token_hit_rate == 0.6
    payload = delta.canonical_payload()
    assert "observed_hit_rate" not in payload
    assert payload["observed_token_hit_rate"] == 0.6


def test_label_cardinality_change_invalidates_observation() -> None:
    delta = compute_vllm_prefix_cache_counter_delta(
        _metrics(10, 4, worker="0"),
        _metrics(15, 7, worker="1"),
        exclusive_interval=True,
    )

    assert delta.valid is False
    assert delta.unavailable_reason == "counter_label_cardinality_changed"


def test_pollution_and_nonexclusive_windows_never_enter_hit_denominator() -> None:
    nonexclusive = compute_vllm_prefix_cache_counter_delta(
        _metrics(10, 4),
        _metrics(15, 7),
    )
    polluted = compute_vllm_prefix_cache_counter_delta(
        _metrics(10, 4),
        _metrics(15, 7),
        exclusive_interval=True,
        pollution_detected=True,
    )

    assert nonexclusive.valid is False
    assert nonexclusive.unavailable_reason == "exclusive_interval_not_proven"
    assert polluted.valid is False
    assert polluted.unavailable_reason == "counter_window_polluted"


def test_gauge_only_and_counter_reset_fail_closed() -> None:
    gauge_before = parse_vllm_prefix_cache_metrics("vllm:gpu_prefix_cache_hit_rate 0.5\n")
    gauge_after = parse_vllm_prefix_cache_metrics("vllm:gpu_prefix_cache_hit_rate 0.6\n")
    gauge = compute_vllm_prefix_cache_counter_delta(
        gauge_before,
        gauge_after,
        exclusive_interval=True,
    )
    reset = compute_vllm_prefix_cache_counter_delta(
        _metrics(10, 4),
        _metrics(2, 1),
        exclusive_interval=True,
    )

    assert gauge.available is False
    assert gauge.unavailable_reason == "service_lifetime_gauge_only"
    assert reset.valid is False
    assert reset.unavailable_reason == "counter_reset_or_no_queries"
