from __future__ import annotations

from typing import TYPE_CHECKING, Any

from v2.benchmark.models import BenchmarkLayer, BenchmarkRunReport, QualityFloorResult

if TYPE_CHECKING:
    from v2.benchmark.minimal_runner import MinimalBenchmarkSample

__all__ = [
    "BenchmarkLayer",
    "BenchmarkRunReport",
    "MinimalBenchmarkSample",
    "QualityFloorResult",
    "run_minimal_benchmark",
]


def __getattr__(name: str) -> Any:
    if name in {"MinimalBenchmarkSample", "run_minimal_benchmark"}:
        from v2.benchmark.minimal_runner import MinimalBenchmarkSample, run_minimal_benchmark

        exports = {
            "MinimalBenchmarkSample": MinimalBenchmarkSample,
            "run_minimal_benchmark": run_minimal_benchmark,
        }
        return exports[name]
    raise AttributeError(name)
