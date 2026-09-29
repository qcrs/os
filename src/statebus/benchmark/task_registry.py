from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from statebus.benchmark.minimal_runner import MinimalBenchmarkSample
from statebus.contracts import CanonicalTaskSpec


@dataclass(frozen=True)
class FormalFamilySpec:
    family_id: str
    sample_dir: Path
    expected_case_count: int
    reasoning_type: str


@dataclass(frozen=True)
class C2BControlSpec:
    """Pre-registered negative/control contract (gold remains scorer-only)."""

    case_id: str
    injected_authority: str
    expected_status: str
    expected_error_code: str
    applicable_lanes: tuple[str, ...]

    @property
    def case_identity(self) -> str:
        return f"c2b-control::{self.case_id}"


C2B_CONTROL_SPECS: tuple[C2BControlSpec, ...] = (
    C2BControlSpec("c2b_wrong_provider", "provider_binding", "policy_reject", "c2a.binding_mismatch", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_wrong_task", "grant_task_identity", "policy_reject", "c2a.task_identity_mismatch", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_wrong_step", "dependency_step_binding", "policy_reject", "c2a.step_identity_mismatch", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_wrong_scope", "corpus_artifact_scope", "policy_reject", "c2a.scope_mismatch", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_unregistered_artifact", "artifact_verifier", "runtime_fail", "c2a.artifact_unregistered", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_invalid_claimset", "claimset_validator", "runtime_fail", "c2a.claimset_invalid", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_late_attempt", "attempt_fencing", "runtime_fail", "c2a.late_attempt", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_state_lease_failure", "state_access_authority", "runtime_fail", "c2a.state_lease_failure", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_memory_incompatibility", "memory_compatibility", "policy_reject", "c2a.memory_incompatible", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_codeact_trap", "bounded_codeact", "policy_reject", "c2a.codeact_policy_violation", ("adaptive_routed",)),
    C2BControlSpec("c2b_planner_binding_mismatch", "planner_binding", "policy_reject", "planner_binding_mismatch", ("fixed_structured", "adaptive_routed")),
    C2BControlSpec("c2b_retriever_deadline", "retriever_deadline", "timeout", "retriever_timeout", ("fixed_structured", "adaptive_routed")),
)


def c2b_control_specs() -> tuple[C2BControlSpec, ...]:
    return tuple(sorted(C2B_CONTROL_SPECS, key=lambda item: item.case_id))


def c2b_positive_identity(family_id: str, registered_case_id: str) -> str:
    return f"c2b-positive::{family_id}::{registered_case_id}"


def c2b_holdout_identity(registered_case_id: str) -> str:
    return f"c2b-holdout::{registered_case_id}"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def c2b_formal_family_specs() -> tuple[FormalFamilySpec, ...]:
    """C2B extension of the legacy 25-case registry seam."""
    specs = formal_family_specs()
    additions = {
        "financial_report_analysis_v1": 4,
        "multi_period_trend_analysis_v1": 5,
        "cross_table_join_analysis_v1": 5,
        "conditional_aggregation_v1": 4,
        "anomaly_detection_v1": 5,
    }
    return tuple(
        FormalFamilySpec(
            family_id=spec.family_id,
            sample_dir=spec.sample_dir,
            expected_case_count=spec.expected_case_count + additions[spec.family_id],
            reasoning_type=spec.reasoning_type,
        )
        for spec in specs
    )


def load_registered_formal_samples() -> list[MinimalBenchmarkSample]:
    samples: list[MinimalBenchmarkSample] = []
    for family in formal_family_specs():
        paths = sorted(family.sample_dir.glob("*.json"))
        # Preserve the pre-C2B 25-case loader used by existing diagnostics;
        # the C2B extension is exposed through ``load_c2b_positive_samples``.
        addition_prefixes = {
            "financial_report_analysis_v1": ("benchmark-sample-9", "benchmark-sample-10", "benchmark-sample-11", "benchmark-sample-12"),
            "multi_period_trend_analysis_v1": tuple(f"formal-trend-{i:03d}" for i in range(6, 11)),
            "cross_table_join_analysis_v1": tuple(f"formal-join-{i:03d}" for i in range(6, 11)),
            "conditional_aggregation_v1": tuple(f"formal-agg-{i:03d}" for i in range(5, 9)),
            "anomaly_detection_v1": tuple(f"formal-anomaly-{i:03d}" for i in range(4, 9)),
        }[family.family_id]
        family_samples = [
            sample
            for path in paths
            if (sample := MinimalBenchmarkSample.from_path(path)).task_id not in addition_prefixes
        ]
        if len(family_samples) != family.expected_case_count:
            raise ValueError(
                f"formal family {family.family_id} expected {family.expected_case_count} cases, "
                f"found {len(family_samples)} in {family.sample_dir}"
            )
        samples.extend(family_samples)
    return samples


def load_c2b_positive_samples() -> list[MinimalBenchmarkSample]:
    """Return the complete, stable 48-case positive registration."""
    samples: list[MinimalBenchmarkSample] = []
    for family in c2b_formal_family_specs():
        paths = sorted(family.sample_dir.glob("*.json"))
        if len(paths) != family.expected_case_count:
            raise ValueError(
                f"c2b family {family.family_id} expected {family.expected_case_count} cases, found {len(paths)}"
            )
        samples.extend(MinimalBenchmarkSample.from_path(path) for path in paths)
    dataset_defaults = {
        "financial_report_analysis": ("statebus.internal.financial", "v1", "c2b_positive"),
        "multi_period_trend_analysis_v1": ("statebus.internal.trend", "v1", "c2b_positive"),
        "cross_table_join_analysis_v1": ("statebus.internal.join", "v1", "c2b_positive"),
        "conditional_aggregation_v1": ("statebus.internal.aggregation", "v1", "c2b_positive"),
        "anomaly_detection_v1": ("statebus.internal.anomaly", "v1", "c2b_positive"),
    }
    samples = [
        replace(sample, dataset_id=dataset_defaults.get(sample.task_family, (sample.dataset_id, sample.dataset_version, sample.dataset_split))[0], dataset_version=dataset_defaults.get(sample.task_family, (sample.dataset_id, sample.dataset_version, sample.dataset_split))[1], dataset_split=dataset_defaults.get(sample.task_family, (sample.dataset_id, sample.dataset_version, sample.dataset_split))[2])
        for sample in samples
    ]
    family_order = {spec.family_id: index for index, spec in enumerate(c2b_formal_family_specs())}
    def sort_key(sample: MinimalBenchmarkSample) -> tuple[int, int, str]:
        family_id = "financial_report_analysis_v1" if sample.task_family == "financial_report_analysis" else sample.task_family
        match = __import__("re").search(r"(\d+)$", sample.task_id)
        return family_order.get(family_id, 99), int(match.group(1)) if match else 0, sample.task_id
    samples.sort(key=sort_key)
    if len(samples) != 48 or len({item.task_id for item in samples}) != 48:
        raise ValueError(f"c2b_positive_registry_incomplete:{len(samples)}")
    return samples


def c2b_registry_matrix() -> dict[str, object]:
    positives = load_c2b_positive_samples()
    family_ids = {"financial_report_analysis": "financial_report_analysis_v1"}
    return {
        "schema_version": "statebus.c2b.registry.v1",
        "positive": [
            {
                "case_identity": c2b_positive_identity(
                    family_ids.get(sample.task_family, sample.task_family), sample.task_id
                ),
                "registered_case_id": sample.task_id,
                "family_id": family_ids.get(sample.task_family, sample.task_family),
                "dataset_id": sample.dataset_id,
                "dataset_version": sample.dataset_version,
                "dataset_split": sample.dataset_split,
                "dataset_hash": sample.dataset_hash,
                "task_contract_hash": sample.canonical_task_spec.spec_hash if sample.canonical_task_spec else "",
            }
            for sample in positives
        ],
        "controls": [
            {**spec.__dict__, "case_identity": spec.case_identity}
            for spec in c2b_control_specs()
        ],
        "holdout": {
            "count": 8,
            "case_identities": [c2b_holdout_identity(f"semantic-holdout-s{i}") for i in range(1, 9)],
        },
    }


def c2a_pilot_samples() -> list[MinimalBenchmarkSample]:
    """Return the fixed 5-positive/3-control C2A pilot registration."""
    root = _repo_root() / "statebus" / "benchmark" / "samples" / "formal_financial_family"
    positive_ids = (
        "compare_metric_acme_q1.json",
        "compare_metric_acme_q2.json",
        "compare_metric_acme_q3.json",
        "compare_metric_acme_q4_2025.json",
        "compare_metric_beta_q1_revenue.json",
    )
    samples = [MinimalBenchmarkSample.from_path(root / name) for name in positive_ids]
    controls = (
        ("control_planner_binding_mismatch", "planner binding mismatch"),
        ("control_retriever_deadline", "retriever deadline control"),
        ("control_invalid_candidate", "invalid candidate control"),
    )
    samples.extend(
        MinimalBenchmarkSample(
            task_id=case_id,
            request_text=request,
            canonical_task_spec=CanonicalTaskSpec(
                task_family="c2a_control",
                intent_op="control",
                required_outputs=("summary_text",),
                arguments={"control": case_id},
            ),
            task_family="c2a_control",
            dataset_id="c2a_internal_fixture",
            dataset_version="c2a-v1",
            dataset_split="c2a_control",
            scenario_tags=("control", case_id),
            dataset_hash=f"sha256:{case_id}",
        )
        for case_id, request in controls
    )
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
