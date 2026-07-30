from __future__ import annotations

from dataclasses import dataclass
import time
from urllib.request import urlopen


@dataclass(frozen=True)
class VllmPrefixCacheMetrics:
    queries_total: float = 0.0
    hits_total: float = 0.0
    hit_rate: float = 0.0
    raw_metric_names: tuple[str, ...] = ()
    counter_metric_names: tuple[str, ...] = ()
    gauge_metric_names: tuple[str, ...] = ()
    sampled_at_ns: int = 0

    @property
    def has_query_hit_counters(self) -> bool:
        query_names = {name for name in self.counter_metric_names if "queries_total" in name}
        hit_names = {name for name in self.counter_metric_names if "hits_total" in name}
        return bool(query_names and hit_names)

    @property
    def observation_kind(self) -> str:
        if self.has_query_hit_counters:
            return "query_hit_counters"
        if self.gauge_metric_names:
            return "service_lifetime_gauge_only"
        return "unavailable"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "queries_total": self.queries_total,
            "hits_total": self.hits_total,
            "hit_rate": self.hit_rate,
            "service_lifetime_hit_rate": self.hit_rate,
            "raw_metric_names": list(self.raw_metric_names),
            "counter_metric_names": list(self.counter_metric_names),
            "gauge_metric_names": list(self.gauge_metric_names),
            "sampled_at_ns": self.sampled_at_ns,
            "has_query_hit_counters": self.has_query_hit_counters,
            "observation_kind": self.observation_kind,
            "schema_version": "statebus.vllm_prefix_cache_metrics.v2",
        }


@dataclass(frozen=True)
class VllmPrefixCacheCounterDelta:
    available: bool
    valid: bool
    queries: float = 0.0
    hits: float = 0.0
    observed_hit_rate: float | None = None
    unavailable_reason: str = ""
    service_lifetime_hit_rate_before: float = 0.0
    service_lifetime_hit_rate_after: float = 0.0
    sample_interval_ms: float = 0.0

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": "statebus.vllm_prefix_cache_counter_delta.v1",
            "available": self.available,
            "valid": self.valid,
            "queries": self.queries,
            "hits": self.hits,
            "observed_hit_rate": self.observed_hit_rate,
            "unavailable_reason": self.unavailable_reason,
            "service_lifetime_hit_rate_before": self.service_lifetime_hit_rate_before,
            "service_lifetime_hit_rate_after": self.service_lifetime_hit_rate_after,
            "sample_interval_ms": self.sample_interval_ms,
            "claim_boundary": (
                "task_local_hit_rate_only_when_explicit_monotonic_query_and_hit_counters_exist"
            ),
        }


def parse_vllm_prefix_cache_metrics(metrics_text: str) -> VllmPrefixCacheMetrics:
    values: dict[str, float] = {}
    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name = line.split("{", 1)[0].split(" ", 1)[0]
        if "prefix_cache" not in name and "cache_hit" not in name:
            continue
        value_text = line.rsplit(" ", 1)[-1]
        try:
            value = float(value_text)
            values[name] = values.get(name, 0.0) + value
        except ValueError:
            continue

    queries_total = _first_metric_value(
        values,
        (
            "vllm:gpu_prefix_cache_queries_total",
            "vllm_gpu_prefix_cache_queries_total",
            "vllm:prefix_cache_queries_total",
            "vllm_prefix_cache_queries_total",
        ),
    )
    hits_total = _first_metric_value(
        values,
        (
            "vllm:gpu_prefix_cache_hits_total",
            "vllm_gpu_prefix_cache_hits_total",
            "vllm:prefix_cache_hits_total",
            "vllm_prefix_cache_hits_total",
        ),
    )
    hit_rate = _first_metric_value(
        values,
        (
            "vllm:gpu_prefix_cache_hit_rate",
            "vllm_gpu_prefix_cache_hit_rate",
            "vllm:prefix_cache_hit_rate",
            "vllm_prefix_cache_hit_rate",
        ),
    )
    if hit_rate == 0.0 and queries_total > 0.0:
        hit_rate = hits_total / queries_total
    return VllmPrefixCacheMetrics(
        queries_total=queries_total,
        hits_total=hits_total,
        hit_rate=hit_rate,
        raw_metric_names=tuple(sorted(values)),
        counter_metric_names=tuple(
            sorted(
                name
                for name in values
                if name.endswith("_queries_total") or name.endswith("_hits_total")
            )
        ),
        gauge_metric_names=tuple(
            sorted(name for name in values if name.endswith("_prefix_cache_hit_rate"))
        ),
        sampled_at_ns=time.time_ns(),
    )


def compute_vllm_prefix_cache_counter_delta(
    before: VllmPrefixCacheMetrics,
    after: VllmPrefixCacheMetrics,
) -> VllmPrefixCacheCounterDelta:
    interval_ms = (
        max(after.sampled_at_ns - before.sampled_at_ns, 0) / 1_000_000.0
        if before.sampled_at_ns and after.sampled_at_ns
        else 0.0
    )
    common_counters = set(before.counter_metric_names) & set(after.counter_metric_names)
    if not before.has_query_hit_counters or not after.has_query_hit_counters:
        reason = (
            "service_lifetime_gauge_only"
            if before.gauge_metric_names or after.gauge_metric_names
            else "prefix_cache_metrics_unavailable"
        )
        return VllmPrefixCacheCounterDelta(
            available=False,
            valid=False,
            unavailable_reason=reason,
            service_lifetime_hit_rate_before=before.hit_rate,
            service_lifetime_hit_rate_after=after.hit_rate,
            sample_interval_ms=interval_ms,
        )
    if not common_counters:
        return VllmPrefixCacheCounterDelta(
            available=False,
            valid=False,
            unavailable_reason="counter_schema_changed_between_snapshots",
            service_lifetime_hit_rate_before=before.hit_rate,
            service_lifetime_hit_rate_after=after.hit_rate,
            sample_interval_ms=interval_ms,
        )
    query_delta = after.queries_total - before.queries_total
    hit_delta = after.hits_total - before.hits_total
    if query_delta <= 0.0:
        reason = "counter_reset_or_no_queries"
    elif hit_delta < 0.0:
        reason = "counter_reset"
    elif hit_delta > query_delta:
        reason = "hit_delta_exceeds_query_delta"
    else:
        return VllmPrefixCacheCounterDelta(
            available=True,
            valid=True,
            queries=query_delta,
            hits=hit_delta,
            observed_hit_rate=hit_delta / query_delta,
            service_lifetime_hit_rate_before=before.hit_rate,
            service_lifetime_hit_rate_after=after.hit_rate,
            sample_interval_ms=interval_ms,
        )
    return VllmPrefixCacheCounterDelta(
        available=True,
        valid=False,
        unavailable_reason=reason,
        service_lifetime_hit_rate_before=before.hit_rate,
        service_lifetime_hit_rate_after=after.hit_rate,
        sample_interval_ms=interval_ms,
    )


def fetch_vllm_prefix_cache_metrics(
    metrics_url: str = "http://127.0.0.1:8000/metrics",
    *,
    timeout_s: float = 2.0,
) -> VllmPrefixCacheMetrics:
    with urlopen(metrics_url, timeout=timeout_s) as response:  # nosec B310 - local metrics endpoint by default
        text = response.read().decode("utf-8", errors="replace")
    return parse_vllm_prefix_cache_metrics(text)


def _first_metric_value(values: dict[str, float], names: tuple[str, ...]) -> float:
    for name in names:
        if name in values:
            return values[name]
    return 0.0
