from __future__ import annotations

from dataclasses import dataclass
from urllib.request import urlopen


@dataclass(frozen=True)
class VllmPrefixCacheMetrics:
    queries_total: float = 0.0
    hits_total: float = 0.0
    hit_rate: float = 0.0
    raw_metric_names: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return {
            "queries_total": self.queries_total,
            "hits_total": self.hits_total,
            "hit_rate": self.hit_rate,
            "raw_metric_names": list(self.raw_metric_names),
            "schema_version": "statebus.vllm_prefix_cache_metrics.v1",
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
            values[name] = float(value_text)
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
