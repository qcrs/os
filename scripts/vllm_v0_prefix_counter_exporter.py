from __future__ import annotations

from functools import wraps
import os
from typing import Any


SUPPORTED_VLLM_VERSION = "0.7.3"


def cache_metric_totals(metric_data: Any) -> tuple[int, int]:
    """Recover exact cumulative block queries/hits from vLLM V0 state."""
    completed_blocks = int(getattr(metric_data, "num_completed_blocks", 0))
    block_size = int(getattr(metric_data, "block_size", 1000))
    incomplete_queries = int(
        getattr(metric_data, "num_incompleted_block_queries", 0)
    )
    incomplete_hits = int(getattr(metric_data, "num_incompleted_block_hit", 0))
    completed_hit_rate = float(
        getattr(metric_data, "completed_block_cache_hit_rate", 0.0)
    )
    completed_queries = completed_blocks * block_size
    completed_hits = round(completed_hit_rate * completed_queries)
    queries = completed_queries + incomplete_queries
    hits = completed_hits + incomplete_hits
    if queries < 0 or hits < 0 or hits > queries:
        raise ValueError(
            f"invalid vLLM prefix cache metric state: queries={queries}, hits={hits}"
        )
    return queries, hits


def _engine_prefix_totals(engine: Any, device: Any) -> tuple[int, int] | None:
    schedulers = getattr(engine, "scheduler", ())
    if not schedulers:
        return None
    block_manager = getattr(schedulers[0], "block_manager", None)
    block_allocator = getattr(block_manager, "block_allocator", None)
    device_allocators = getattr(block_allocator, "_allocators", {})
    allocator = device_allocators.get(device)
    metric_data = getattr(allocator, "metric_data", None)
    if metric_data is None:
        return None
    return cache_metric_totals(metric_data)


def install() -> bool:
    """Expose V0 allocator counters without changing cache or scheduling behavior."""
    import vllm

    if os.getenv("VLLM_USE_V1", "0").strip().lower() not in {"0", "false"}:
        return False
    if str(vllm.__version__) != SUPPORTED_VLLM_VERSION:
        raise RuntimeError(
            "StateBus prefix counter exporter supports only "
            f"vLLM {SUPPORTED_VLLM_VERSION}; found {vllm.__version__}"
        )

    from vllm.engine.llm_engine import LLMEngine
    from vllm.engine import metrics as metrics_module
    from vllm.utils import Device

    if getattr(metrics_module, "_statebus_prefix_counter_exporter_installed", False):
        return True

    original_get_stats = LLMEngine._get_stats

    @wraps(original_get_stats)
    def get_stats_with_prefix_totals(self, *args, **kwargs):
        stats = original_get_stats(self, *args, **kwargs)
        for name, device in (("gpu", Device.GPU), ("cpu", Device.CPU)):
            totals = _engine_prefix_totals(self, device)
            if totals is None:
                continue
            queries, hits = totals
            setattr(stats, f"{name}_prefix_cache_queries_total_raw", queries)
            setattr(stats, f"{name}_prefix_cache_hits_total_raw", hits)
        return stats

    LLMEngine._get_stats = get_stats_with_prefix_totals

    original_metrics_init = metrics_module.Metrics.__init__

    @wraps(original_metrics_init)
    def metrics_init_with_prefix_counters(self, labelnames, vllm_config):
        original_metrics_init(self, labelnames, vllm_config)
        for name in ("gpu", "cpu"):
            setattr(
                self,
                f"counter_{name}_prefix_cache_queries",
                self._counter_cls(
                    name=f"vllm:{name}_prefix_cache_queries",
                    documentation=(
                        f"{name.upper()} prefix cache queries in queried prompt blocks."
                    ),
                    labelnames=labelnames,
                ),
            )
            setattr(
                self,
                f"counter_{name}_prefix_cache_hits",
                self._counter_cls(
                    name=f"vllm:{name}_prefix_cache_hits",
                    documentation=(
                        f"{name.upper()} prefix cache hits in cached prompt blocks."
                    ),
                    labelnames=labelnames,
                ),
            )

    metrics_module.Metrics.__init__ = metrics_init_with_prefix_counters

    original_logger_init = metrics_module.PrometheusStatLogger.__init__

    @wraps(original_logger_init)
    def logger_init_with_prefix_counters(self, *args, **kwargs):
        original_logger_init(self, *args, **kwargs)
        self._statebus_prefix_counter_last = {
            "gpu_queries": 0,
            "gpu_hits": 0,
            "cpu_queries": 0,
            "cpu_hits": 0,
        }

    metrics_module.PrometheusStatLogger.__init__ = logger_init_with_prefix_counters

    original_log_prometheus = metrics_module.PrometheusStatLogger._log_prometheus

    @wraps(original_log_prometheus)
    def log_prometheus_with_prefix_counters(self, stats):
        original_log_prometheus(self, stats)
        for device_name in ("gpu", "cpu"):
            for metric_name in ("queries", "hits"):
                raw_name = (
                    f"{device_name}_prefix_cache_{metric_name}_total_raw"
                )
                current = getattr(stats, raw_name, None)
                if current is None:
                    continue
                state_key = f"{device_name}_{metric_name}"
                current = int(current)
                previous = int(self._statebus_prefix_counter_last[state_key])
                # A prefix-cache reset restarts allocator-local totals. The
                # exported Prometheus counter remains monotonic across it.
                delta = current - previous if current >= previous else current
                counter = getattr(
                    self.metrics,
                    f"counter_{device_name}_prefix_cache_{metric_name}",
                )
                # Calling inc(0) is intentional: prometheus_client does not
                # expose a labelled zero-valued Counter until labels() is
                # touched at least once. Both query and hit series must exist
                # in the before snapshot for a task-local delta to be valid.
                self._log_counter(counter, delta)
                self._statebus_prefix_counter_last[state_key] = current

    metrics_module.PrometheusStatLogger._log_prometheus = (
        log_prometheus_with_prefix_counters
    )
    metrics_module._statebus_prefix_counter_exporter_installed = True
    return True
