from __future__ import annotations

from typing import TYPE_CHECKING, Any

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkRunReport,
    QualityFloorResult,
)

if TYPE_CHECKING:
    from v2.benchmark.minimal_runner import MinimalBenchmarkSample

__all__ = [
    "BenchmarkLayer",
    "BenchmarkCaseReport",
    "BenchmarkFamilyReport",
    "BenchmarkRunReport",
    "MinimalBenchmarkSample",
    "QualityFloorResult",
    "load_sample_family",
    "run_minimal_benchmark_family",
    "run_minimal_benchmark",
]


def __getattr__(name: str) -> Any:
    if name in {
        "MinimalBenchmarkSample",
        "run_minimal_benchmark",
        "load_sample_family",
        "run_minimal_benchmark_family",
    }:
        from v2.benchmark.minimal_runner import (
            MinimalBenchmarkSample,
            load_sample_family,
            run_minimal_benchmark_family,
            run_minimal_benchmark,
        )

        exports = {
            "MinimalBenchmarkSample": MinimalBenchmarkSample,
            "load_sample_family": load_sample_family,
            "run_minimal_benchmark_family": run_minimal_benchmark_family,
            "run_minimal_benchmark": run_minimal_benchmark,
        }
        return exports[name]
    raise AttributeError(name)
