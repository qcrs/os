from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from statebus.benchmark.minimal_runner import MinimalBenchmarkSample


@dataclass(frozen=True)
class FormalFamilySpec:
    family_id: str
    sample_dir: Path
    expected_case_count: int
    reasoning_type: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def formal_family_specs() -> tuple[FormalFamilySpec, ...]:
    root = _repo_root()
    return (
        FormalFamilySpec(
            family_id="financial_report_analysis_v1",
            sample_dir=root / "statebus" / "benchmark" / "samples" / "formal_financial_family",
            expected_case_count=8,
            reasoning_type="single_metric_extraction",
        ),
        FormalFamilySpec(
            family_id="multi_period_trend_analysis_v1",
            sample_dir=root / "tasks" / "formal" / "multi_period_trend_analysis_v1" / "samples",
            expected_case_count=5,
            reasoning_type="multi_period_trend",
        ),
        FormalFamilySpec(
            family_id="cross_table_join_analysis_v1",
            sample_dir=root / "tasks" / "formal" / "cross_table_join_analysis_v1" / "samples",
            expected_case_count=5,
            reasoning_type="cross_table_relation",
        ),
        FormalFamilySpec(
            family_id="conditional_aggregation_v1",
            sample_dir=root / "tasks" / "formal" / "conditional_aggregation_v1" / "samples",
            expected_case_count=4,
            reasoning_type="conditional_aggregation",
        ),
        FormalFamilySpec(
            family_id="anomaly_detection_v1",
            sample_dir=root / "tasks" / "formal" / "anomaly_detection_v1" / "samples",
            expected_case_count=3,
            reasoning_type="anomaly_detection",
        ),
    )


def load_registered_formal_samples() -> list[MinimalBenchmarkSample]:
    samples: list[MinimalBenchmarkSample] = []
    for family in formal_family_specs():
        family_samples = [
            MinimalBenchmarkSample.from_path(path)
            for path in sorted(family.sample_dir.glob("*.json"))
        ]
        if len(family_samples) != family.expected_case_count:
            raise ValueError(
                f"formal family {family.family_id} expected {family.expected_case_count} cases, "
                f"found {len(family_samples)} in {family.sample_dir}"
            )
        samples.extend(family_samples)
    return samples


def formal_family_payload() -> list[dict[str, object]]:
    return [
        {
            "family_id": family.family_id,
            "sample_dir": str(family.sample_dir),
            "expected_case_count": family.expected_case_count,
            "reasoning_type": family.reasoning_type,
        }
        for family in formal_family_specs()
    ]
