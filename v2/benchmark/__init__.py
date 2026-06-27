from __future__ import annotations

from typing import TYPE_CHECKING, Any

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkRunReport,
    BenchmarkSuiteReport,
    QualityFloorResult,
)

if TYPE_CHECKING:
    from v2.benchmark.minimal_runner import MinimalBenchmarkSample

__all__ = [
    "BenchmarkLayer",
    "BenchmarkCaseReport",
    "BenchmarkFamilyReport",
    "BenchmarkLayerProfile",
    "BenchmarkRunReport",
    "BenchmarkSuiteReport",
    "MinimalBenchmarkSample",
    "QualityFloorResult",
    "load_sample_family",
    "run_minimal_benchmark_family",
    "run_minimal_benchmark",
    "run_minimal_benchmark_suite",
]


def __getattr__(name: str) -> Any:
    if name in {
        "MinimalBenchmarkSample",
        "run_minimal_benchmark",
        "load_sample_family",
        "run_minimal_benchmark_family",
        "run_minimal_benchmark_suite",
    }:
        from v2.benchmark.minimal_runner import (
            MinimalBenchmarkSample,
            load_sample_family,
            run_minimal_benchmark_family,
            run_minimal_benchmark,
            run_minimal_benchmark_suite,
        )

        exports = {
            "MinimalBenchmarkSample": MinimalBenchmarkSample,
            "load_sample_family": load_sample_family,
            "run_minimal_benchmark_family": run_minimal_benchmark_family,
            "run_minimal_benchmark": run_minimal_benchmark,
            "run_minimal_benchmark_suite": run_minimal_benchmark_suite,
        }
        return exports[name]
    raise AttributeError(name)
