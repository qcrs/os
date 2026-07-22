from __future__ import annotations

from dataclasses import dataclass
import math
import re
import time
from urllib.request import urlopen

from v2.utils import sha256_digest


_QUERY_COUNTER_NAMES = (
    "vllm:gpu_prefix_cache_queries_total",
    "vllm_gpu_prefix_cache_queries_total",
    "vllm:prefix_cache_queries_total",
    "vllm_prefix_cache_queries_total",
)
_HIT_COUNTER_NAMES = (
    "vllm:gpu_prefix_cache_hits_total",
    "vllm_gpu_prefix_cache_hits_total",
    "vllm:prefix_cache_hits_total",
    "vllm_prefix_cache_hits_total",
)
_HIT_RATE_GAUGE_NAMES = (
    "vllm:gpu_prefix_cache_hit_rate",
    "vllm_gpu_prefix_cache_hit_rate",
    "vllm:prefix_cache_hit_rate",
    "vllm_prefix_cache_hit_rate",
)
_SAMPLE_RE = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[-+]?(?:Inf|NaN|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?))"
    r"(?:\s+\d+)?$"
)
_LABEL_RE = re.compile(r'(?P<name>[A-Za-z_][A-Za-z0-9_]*)="(?P<value>(?:\\.|[^"\\])*)"')


@dataclass(frozen=True)
class VllmPrefixCacheMetricSeries:
    metric_name: str
    labels: tuple[tuple[str, str], ...]
    value: float
    counter_role: str
    unit: str = "tokens"

    @property
    def series_key(self) -> tuple[tuple[str, str], ...]:
        return self.labels

    def canonical_payload(self) -> dict[str, object]:
        return {
            "metric_name": self.metric_name,
            "labels": dict(self.labels),
            "value": self.value,
            "counter_role": self.counter_role,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class VllmPrefixCacheMetrics:
    queries_total: float = 0.0
    hits_total: float = 0.0
    hit_rate: float = 0.0
    raw_metric_names: tuple[str, ...] = ()
    counter_metric_names: tuple[str, ...] = ()
    gauge_metric_names: tuple[str, ...] = ()
    query_series: tuple[VllmPrefixCacheMetricSeries, ...] = ()
    hit_series: tuple[VllmPrefixCacheMetricSeries, ...] = ()
    counter_unit: str = "tokens"
    metric_schema_valid: bool = True
    metric_schema_error: str = ""
    engine_instance_id: str = ""
    cache_epoch: str = ""
    sampled_at_ns: int = 0

    @property
    def has_query_hit_counters(self) -> bool:
        query_names = {name for name in self.counter_metric_names if "queries_total" in name}
        hit_names = {name for name in self.counter_metric_names if "hits_total" in name}
        return bool(self.metric_schema_valid and query_names and hit_names)

    @property
    def observation_kind(self) -> str:
        if self.has_query_hit_counters:
            return "query_hit_token_counters"
        if self.gauge_metric_names:
            return "service_lifetime_gauge_only"
        return "unavailable"

    @property
    def series_digest(self) -> str:
        if self.query_series or self.hit_series:
            payload = [
                series.canonical_payload()
                for series in (*self.query_series, *self.hit_series)
            ]
        else:
            payload = {
                "counter_metric_names": list(self.counter_metric_names),
                "legacy_unlabelled": True,
            }
        return sha256_digest(payload)

    def canonical_payload(self) -> dict[str, object]:
        return {
            "queries_total": self.queries_total,
            "hits_total": self.hits_total,
            "hit_rate": self.hit_rate,
            "service_lifetime_hit_rate": self.hit_rate,
            "raw_metric_names": list(self.raw_metric_names),
            "counter_metric_names": list(self.counter_metric_names),
            "gauge_metric_names": list(self.gauge_metric_names),
            "query_series": [series.canonical_payload() for series in self.query_series],
            "hit_series": [series.canonical_payload() for series in self.hit_series],
            "counter_unit": self.counter_unit,
            "metric_schema_valid": self.metric_schema_valid,
            "metric_schema_error": self.metric_schema_error,
            "engine_instance_id": self.engine_instance_id,
            "cache_epoch": self.cache_epoch,
            "sampled_at_ns": self.sampled_at_ns,
            "has_query_hit_counters": self.has_query_hit_counters,
            "observation_kind": self.observation_kind,
            "series_digest": self.series_digest,
            "schema_version": "statebus.vllm_prefix_cache_metrics.v3",
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
    counter_unit: str = "tokens"
    counter_series_digest: str = ""
    exclusive_interval: bool = False
    pollution_detected: bool = False
    request_count: int = 0
    retry_count: int = 0

    @property
    def observed_query_token_delta(self) -> float:
        return self.queries

    @property
    def observed_hit_token_delta(self) -> float:
        return self.hits

    @property
    def observed_token_hit_rate(self) -> float | None:
        return self.observed_hit_rate

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema_version": "statebus.vllm_prefix_cache_counter_delta.v2",
            "available": self.available,
            "valid": self.valid,
            "observed_query_token_delta": self.queries,
            "observed_hit_token_delta": self.hits,
            "observed_token_hit_rate": self.observed_hit_rate,
            "counter_unit": self.counter_unit,
            "counter_series_digest": self.counter_series_digest,
            "unavailable_reason": self.unavailable_reason,
            "service_lifetime_hit_rate_before": self.service_lifetime_hit_rate_before,
            "service_lifetime_hit_rate_after": self.service_lifetime_hit_rate_after,
            "sample_interval_ms": self.sample_interval_ms,
            "exclusive_interval": self.exclusive_interval,
            "pollution_detected": self.pollution_detected,
            "request_count": self.request_count,
            "retry_count": self.retry_count,
            "claim_boundary": (
                "request_local_token_hit_rate_only_for_matching_monotonic_labeled_counters_"
                "in_one_exclusive_retry_free_interval"
            ),
        }


def parse_vllm_prefix_cache_metrics(metrics_text: str) -> VllmPrefixCacheMetrics:
    samples: list[tuple[str, tuple[tuple[str, str], ...], float]] = []
    for raw_line in metrics_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if match is None:
            continue
        name = match.group("name")
        if name not in {*_QUERY_COUNTER_NAMES, *_HIT_COUNTER_NAMES, *_HIT_RATE_GAUGE_NAMES}:
            continue
        try:
            value = float(match.group("value"))
            labels = _parse_labels(match.group("labels") or "")
        except ValueError:
            continue
        samples.append((name, labels, value))

    query_samples = tuple(sample for sample in samples if sample[0] in _QUERY_COUNTER_NAMES)
    hit_samples = tuple(sample for sample in samples if sample[0] in _HIT_COUNTER_NAMES)
    gauge_samples = tuple(sample for sample in samples if sample[0] in _HIT_RATE_GAUGE_NAMES)
    schema_errors: list[str] = []
    query_names = {sample[0] for sample in query_samples}
    hit_names = {sample[0] for sample in hit_samples}
    if len(query_names) > 1 or len(hit_names) > 1:
        schema_errors.append("ambiguous_counter_aliases")
    if any(not math.isfinite(sample[2]) or sample[2] < 0 for sample in (*query_samples, *hit_samples)):
        schema_errors.append("non_finite_or_negative_counter")
    query_labels = [sample[1] for sample in query_samples]
    hit_labels = [sample[1] for sample in hit_samples]
    if len(set(query_labels)) != len(query_labels) or len(set(hit_labels)) != len(hit_labels):
        schema_errors.append("duplicate_counter_series")
    if query_samples and hit_samples and set(query_labels) != set(hit_labels):
        schema_errors.append("query_hit_label_mismatch")

    query_series = tuple(
        VllmPrefixCacheMetricSeries(
            metric_name=name,
            labels=labels,
            value=value,
            counter_role="queried_tokens",
        )
        for name, labels, value in query_samples
    )
    hit_series = tuple(
        VllmPrefixCacheMetricSeries(
            metric_name=name,
            labels=labels,
            value=value,
            counter_role="cached_hit_tokens",
        )
        for name, labels, value in hit_samples
    )
    queries_total = sum(series.value for series in query_series)
    hits_total = sum(series.value for series in hit_series)
    hit_rate = sum(sample[2] for sample in gauge_samples)
    if not gauge_samples and queries_total > 0:
        hit_rate = hits_total / queries_total
    return VllmPrefixCacheMetrics(
        queries_total=queries_total,
        hits_total=hits_total,
        hit_rate=hit_rate,
        raw_metric_names=tuple(sorted({sample[0] for sample in samples})),
        counter_metric_names=tuple(sorted(query_names | hit_names)),
        gauge_metric_names=tuple(sorted({sample[0] for sample in gauge_samples})),
        query_series=query_series,
        hit_series=hit_series,
        metric_schema_valid=not schema_errors,
        metric_schema_error=";".join(sorted(set(schema_errors))),
        sampled_at_ns=time.time_ns(),
    )


def compute_vllm_prefix_cache_counter_delta(
    before: VllmPrefixCacheMetrics,
    after: VllmPrefixCacheMetrics,
    *,
    exclusive_interval: bool = False,
    pollution_detected: bool = False,
    request_count: int = 1,
    retry_count: int = 0,
    expected_engine_instance_id: str = "",
    expected_cache_epoch: str = "",
) -> VllmPrefixCacheCounterDelta:
    interval_ms = (
        max(after.sampled_at_ns - before.sampled_at_ns, 0) / 1_000_000.0
        if before.sampled_at_ns and after.sampled_at_ns
        else 0.0
    )
    common = {
        "service_lifetime_hit_rate_before": before.hit_rate,
        "service_lifetime_hit_rate_after": after.hit_rate,
        "sample_interval_ms": interval_ms,
        "counter_unit": "tokens",
        "counter_series_digest": sha256_digest(
            {"before": before.series_digest, "after": after.series_digest}
        ),
        "exclusive_interval": exclusive_interval,
        "pollution_detected": pollution_detected,
        "request_count": request_count,
        "retry_count": retry_count,
    }
    if not before.metric_schema_valid or not after.metric_schema_valid:
        reason = before.metric_schema_error or after.metric_schema_error or "counter_schema_invalid"
        return VllmPrefixCacheCounterDelta(
            available=False,
            valid=False,
            unavailable_reason=reason,
            **common,
        )
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
            **common,
        )
    if set(before.counter_metric_names) != set(after.counter_metric_names):
        return VllmPrefixCacheCounterDelta(
            available=False,
            valid=False,
            unavailable_reason="counter_schema_changed_between_snapshots",
            **common,
        )
    if not _matching_series_labels(before, after):
        return VllmPrefixCacheCounterDelta(
            available=True,
            valid=False,
            unavailable_reason="counter_label_cardinality_changed",
            **common,
        )

    context_reason = _observation_context_error(
        before,
        after,
        exclusive_interval=exclusive_interval,
        pollution_detected=pollution_detected,
        request_count=request_count,
        retry_count=retry_count,
        expected_engine_instance_id=expected_engine_instance_id,
        expected_cache_epoch=expected_cache_epoch,
    )
    if context_reason:
        return VllmPrefixCacheCounterDelta(
            available=True,
            valid=False,
            unavailable_reason=context_reason,
            **common,
        )

    query_delta = after.queries_total - before.queries_total
    hit_delta = after.hits_total - before.hits_total
    if query_delta <= 0:
        reason = "counter_reset_or_no_queries"
    elif hit_delta < 0:
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
            **common,
        )
    return VllmPrefixCacheCounterDelta(
        available=True,
        valid=False,
        unavailable_reason=reason,
        **common,
    )


def fetch_vllm_prefix_cache_metrics(
    metrics_url: str = "http://127.0.0.1:8000/metrics",
    *,
    timeout_s: float = 2.0,
) -> VllmPrefixCacheMetrics:
    with urlopen(metrics_url, timeout=timeout_s) as response:  # nosec B310 - caller owns endpoint policy
        text = response.read().decode("utf-8", errors="replace")
    return parse_vllm_prefix_cache_metrics(text)


def _parse_labels(raw_labels: str) -> tuple[tuple[str, str], ...]:
    if not raw_labels:
        return ()
    labels: list[tuple[str, str]] = []
    cursor = 0
    for match in _LABEL_RE.finditer(raw_labels):
        separator = raw_labels[cursor : match.start()].strip()
        if separator not in {"", ","}:
            raise ValueError("invalid Prometheus label syntax")
        value = bytes(match.group("value"), "utf-8").decode("unicode_escape")
        labels.append((match.group("name"), value))
        cursor = match.end()
    if raw_labels[cursor:].strip():
        raise ValueError("invalid Prometheus label suffix")
    if len({name for name, _ in labels}) != len(labels):
        raise ValueError("duplicate Prometheus label")
    return tuple(sorted(labels))


def _matching_series_labels(
    before: VllmPrefixCacheMetrics,
    after: VllmPrefixCacheMetrics,
) -> bool:
    if not (before.query_series or before.hit_series or after.query_series or after.hit_series):
        return True
    before_query = {series.series_key for series in before.query_series}
    before_hit = {series.series_key for series in before.hit_series}
    after_query = {series.series_key for series in after.query_series}
    after_hit = {series.series_key for series in after.hit_series}
    return before_query == before_hit == after_query == after_hit


def _observation_context_error(
    before: VllmPrefixCacheMetrics,
    after: VllmPrefixCacheMetrics,
    *,
    exclusive_interval: bool,
    pollution_detected: bool,
    request_count: int,
    retry_count: int,
    expected_engine_instance_id: str,
    expected_cache_epoch: str,
) -> str:
    if not exclusive_interval:
        return "exclusive_interval_not_proven"
    if pollution_detected:
        return "counter_window_polluted"
    if request_count != 1:
        return "counter_window_request_count_not_one"
    if retry_count:
        return "counter_window_contains_retry"
    if before.sampled_at_ns and after.sampled_at_ns and after.sampled_at_ns < before.sampled_at_ns:
        return "snapshot_clock_reversed"
    before_engine = before.engine_instance_id
    after_engine = after.engine_instance_id
    if before_engine and after_engine and before_engine != after_engine:
        return "engine_instance_changed"
    if expected_engine_instance_id and (
        before_engine != expected_engine_instance_id or after_engine != expected_engine_instance_id
    ):
        return "engine_instance_mismatch"
    before_epoch = before.cache_epoch
    after_epoch = after.cache_epoch
    if before_epoch and after_epoch and before_epoch != after_epoch:
        return "cache_epoch_changed"
    if expected_cache_epoch and (
        before_epoch != expected_cache_epoch or after_epoch != expected_cache_epoch
    ):
        return "cache_epoch_mismatch"
    return ""
