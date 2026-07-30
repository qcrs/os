from __future__ import annotations

from scripts.probe_local_vllm_prefix_alignment import _counter_delta
from statebus.runtime.prefix_feedback import PrefixCacheFeedbackLoop, record_live
from statebus.runtime.vllm_metrics import (
    VllmPrefixCacheMetrics,
    compute_vllm_prefix_cache_counter_delta,
    parse_vllm_prefix_cache_metrics,
)


def test_vllm_gauge_is_not_misclassified_as_task_local_counter() -> None:
    before = parse_vllm_prefix_cache_metrics(
        'vllm:gpu_prefix_cache_hit_rate{model_name="qwen"} 0.5\n'
    )
    after = parse_vllm_prefix_cache_metrics(
        'vllm:gpu_prefix_cache_hit_rate{model_name="qwen"} 0.6\n'
    )

    delta = compute_vllm_prefix_cache_counter_delta(
        before,
        after,
        exclusive_interval=True,
    )

    assert before.observation_kind == "service_lifetime_gauge_only"
    assert delta.available is False
    assert delta.valid is False
    assert delta.unavailable_reason == "service_lifetime_gauge_only"
    assert delta.observed_hit_rate is None


def test_record_live_skips_network_failure(monkeypatch) -> None:
    loop = PrefixCacheFeedbackLoop(window_size=3)

    def fail_fetch(**kwargs):
        del kwargs
        raise OSError("metrics unavailable")

    monkeypatch.setattr(
        "statebus.runtime.prefix_feedback.fetch_vllm_prefix_cache_metrics",
        fail_fetch,
    )

    snapshot = record_live(
        loop,
        0.8,
        before=VllmPrefixCacheMetrics(
            queries_total=10.0,
            hits_total=5.0,
            raw_metric_names=("vllm:gpu_prefix_cache_queries_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
        exclusive_interval=True,
    )

    assert snapshot.sample_count == 0
    assert snapshot.mean_error == 0.0
    assert snapshot.should_reorder is False
    assert snapshot.unavailable_observation_count == 1


def test_record_live_skips_response_without_prefix_metrics(monkeypatch) -> None:
    loop = PrefixCacheFeedbackLoop(window_size=3)
    monkeypatch.setattr(
        "statebus.runtime.prefix_feedback.fetch_vllm_prefix_cache_metrics",
        lambda **kwargs: VllmPrefixCacheMetrics(),
    )

    snapshot = record_live(
        loop,
        0.8,
        before=VllmPrefixCacheMetrics(
            queries_total=10.0,
            hits_total=5.0,
            raw_metric_names=("vllm:gpu_prefix_cache_queries_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
        exclusive_interval=True,
    )

    assert snapshot.sample_count == 0
    assert snapshot.unavailable_observation_count == 1


def test_record_live_uses_task_local_counter_delta(monkeypatch) -> None:
    loop = PrefixCacheFeedbackLoop(window_size=3, error_threshold=0.5)
    monkeypatch.setattr(
        "statebus.runtime.prefix_feedback.fetch_vllm_prefix_cache_metrics",
        lambda **kwargs: VllmPrefixCacheMetrics(
            queries_total=14.0,
            hits_total=5.0,
            raw_metric_names=("vllm:gpu_prefix_cache_hits_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
    )

    snapshot = record_live(
        loop,
        0.8,
        before=VllmPrefixCacheMetrics(
            queries_total=10.0,
            hits_total=5.0,
            raw_metric_names=("vllm:gpu_prefix_cache_hits_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
        exclusive_interval=True,
    )

    assert snapshot.sample_count == 1
    assert snapshot.mean_observed == 0.0
    assert snapshot.mean_error == 0.8
    assert snapshot.should_reorder is True
    assert snapshot.unavailable_observation_count == 0


def test_record_live_skips_counter_reset(monkeypatch) -> None:
    loop = PrefixCacheFeedbackLoop(window_size=3)
    monkeypatch.setattr(
        "statebus.runtime.prefix_feedback.fetch_vllm_prefix_cache_metrics",
        lambda **kwargs: VllmPrefixCacheMetrics(
            queries_total=2.0,
            hits_total=1.0,
            raw_metric_names=("vllm:gpu_prefix_cache_queries_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
    )

    snapshot = record_live(
        loop,
        0.8,
        before=VllmPrefixCacheMetrics(
            queries_total=10.0,
            hits_total=5.0,
            raw_metric_names=("vllm:gpu_prefix_cache_queries_total",),
            counter_metric_names=(
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ),
        ),
        exclusive_interval=True,
    )

    assert snapshot.sample_count == 0
    assert snapshot.unavailable_observation_count == 1


def test_prefix_probe_reports_task_local_counter_delta() -> None:
    before = {
        "prefix_cache": {
            "queries_total": 10.0,
            "hits_total": 4.0,
            "raw_metric_names": ["vllm:gpu_prefix_cache_queries_total"],
            "counter_metric_names": [
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ],
        }
    }
    after = {
        "prefix_cache": {
            "queries_total": 14.0,
            "hits_total": 7.0,
            "raw_metric_names": ["vllm:gpu_prefix_cache_queries_total"],
            "counter_metric_names": [
                "vllm:gpu_prefix_cache_queries_total",
                "vllm:gpu_prefix_cache_hits_total",
            ],
        }
    }
    delta = _counter_delta(before, after)
    assert delta == {
        "available": True,
        "valid": True,
        "queries": 4.0,
        "hits": 3.0,
        "hit_rate": 0.75,
        "unavailable_reason": "",
    }
