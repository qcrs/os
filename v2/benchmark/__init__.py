from __future__ import annotations

from typing import TYPE_CHECKING, Any

from v2.benchmark.models import (
    BenchmarkCaseReport,
    BenchmarkContinuousCollectionReport,
    BenchmarkComparatorModeReport,
    BenchmarkComparatorSuiteReport,
    BenchmarkFamilyReport,
    BenchmarkLayer,
    BenchmarkLayerProfile,
    BenchmarkRunReport,
    BenchmarkSuiteReport,
    QualityFloorResult,
)

if TYPE_CHECKING:
    from v2.benchmark.continuous_task_family import ContinuousTaskFamily
    from v2.benchmark.minimal_runner import MinimalBenchmarkSample

__all__ = [
    "BenchmarkLayer",
    "BenchmarkCaseReport",
    "BenchmarkContinuousCollectionReport",
    "BenchmarkComparatorModeReport",
    "BenchmarkComparatorSuiteReport",
    "BenchmarkFamilyReport",
    "BenchmarkLayerProfile",
    "BenchmarkRunReport",
    "BenchmarkSuiteReport",
    "ContinuousTaskFamily",
    "MinimalBenchmarkSample",
    "QualityFloorResult",
    "load_continuous_task_family",
    "run_continuous_benchmark_suite",
    "run_continuous_benchmark_collection",
    "run_continuous_text_semantic_selection_family",
    "load_sample_family",
    "load_fixed_answer_family",
    "load_registered_formal_fixed_answer_samples",
    "compare_fixed_answer_with_external",
    "main_live_runner",
    "run_external_text_case",
    "run_external_text_family",
    "run_external_text_suite",
    "run_fixed_answer_external_comparator_suite",
    "run_fixed_answer_benchmark_family",
    "run_fixed_answer_internal_carrier_compare_suite",
    "run_fixed_answer_text_semantic_selection_family",
    "run_fixed_answer_suite",
    "run_non_text_flagship_ablation_report",
    "run_minimal_benchmark_family",
    "run_minimal_benchmark",
    "run_minimal_benchmark_suite",
]


def __getattr__(name: str) -> Any:
    if name in {
        "ContinuousTaskFamily",
        "load_continuous_task_family",
        "run_continuous_benchmark_suite",
        "run_continuous_benchmark_collection",
        "run_continuous_text_semantic_selection_family",
        "MinimalBenchmarkSample",
        "load_fixed_answer_family",
        "load_registered_formal_fixed_answer_samples",
        "compare_fixed_answer_with_external",
        "main_live_runner",
        "run_external_text_case",
        "run_external_text_family",
        "run_external_text_suite",
        "run_fixed_answer_external_comparator_suite",
        "run_fixed_answer_benchmark_family",
        "run_fixed_answer_internal_carrier_compare_suite",
        "run_fixed_answer_text_semantic_selection_family",
        "run_fixed_answer_suite",
        "run_non_text_flagship_ablation_report",
        "run_minimal_benchmark",
        "load_sample_family",
        "run_minimal_benchmark_family",
        "run_minimal_benchmark_suite",
    }:
        from v2.benchmark.continuous_task_family import (
            ContinuousTaskFamily,
            load_continuous_task_family,
        )
        from v2.benchmark.continuous_runner import (
            run_continuous_benchmark_collection,
            run_continuous_benchmark_suite,
            run_continuous_text_semantic_selection_family,
        )
        from v2.benchmark.minimal_runner import (
            MinimalBenchmarkSample,
            load_sample_family,
            run_minimal_benchmark_family,
            run_minimal_benchmark,
            run_minimal_benchmark_suite,
        )
        from v2.benchmark.fixed_answer_runner import (
            load_fixed_answer_family,
            run_fixed_answer_benchmark_family,
            run_fixed_answer_internal_carrier_compare_suite,
            run_fixed_answer_text_semantic_selection_family,
            run_fixed_answer_suite,
        )
        from v2.benchmark.flagship_ablation import run_non_text_flagship_ablation_report
        from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples
        from v2.benchmark.external_text_baseline import (
            run_external_text_case,
            run_external_text_family,
            run_external_text_suite,
        )
        from v2.benchmark.comparator_runner import (
            compare_fixed_answer_with_external,
            run_fixed_answer_external_comparator_suite,
        )
        from v2.benchmark.live_runner import main as main_live_runner

        exports = {
            "ContinuousTaskFamily": ContinuousTaskFamily,
            "load_continuous_task_family": load_continuous_task_family,
            "run_continuous_benchmark_suite": run_continuous_benchmark_suite,
            "run_continuous_benchmark_collection": run_continuous_benchmark_collection,
            "run_continuous_text_semantic_selection_family": run_continuous_text_semantic_selection_family,
            "MinimalBenchmarkSample": MinimalBenchmarkSample,
            "load_sample_family": load_sample_family,
            "load_fixed_answer_family": load_fixed_answer_family,
            "load_registered_formal_fixed_answer_samples": load_registered_formal_fixed_answer_samples,
            "compare_fixed_answer_with_external": compare_fixed_answer_with_external,
            "main_live_runner": main_live_runner,
            "run_external_text_case": run_external_text_case,
            "run_external_text_family": run_external_text_family,
            "run_external_text_suite": run_external_text_suite,
            "run_fixed_answer_external_comparator_suite": run_fixed_answer_external_comparator_suite,
            "run_fixed_answer_benchmark_family": run_fixed_answer_benchmark_family,
            "run_fixed_answer_internal_carrier_compare_suite": run_fixed_answer_internal_carrier_compare_suite,
            "run_fixed_answer_text_semantic_selection_family": run_fixed_answer_text_semantic_selection_family,
            "run_fixed_answer_suite": run_fixed_answer_suite,
            "run_non_text_flagship_ablation_report": run_non_text_flagship_ablation_report,
            "run_minimal_benchmark_family": run_minimal_benchmark_family,
            "run_minimal_benchmark": run_minimal_benchmark,
            "run_minimal_benchmark_suite": run_minimal_benchmark_suite,
        }
        return exports[name]
    raise AttributeError(name)
