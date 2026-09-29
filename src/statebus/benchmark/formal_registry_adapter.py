from __future__ import annotations

import json
from pathlib import Path

from statebus.benchmark.fixed_answer_runner import FixedAnswerSample
from statebus.benchmark.minimal_runner import MinimalBenchmarkSample
from statebus.benchmark.task_registry import formal_family_specs
from statebus.contracts.models import CanonicalTaskSpec
from statebus.route_tool_catalog import build_route_tool_surface
from statebus.utils import stable_json_dumps


def _projection_value_text(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return stable_json_dumps(value)
    return str(value)


def _public_metric_projection_key(canonical_task_spec: CanonicalTaskSpec) -> str:
    for raw_check in canonical_task_spec.arguments.get("quality_checks", []):
        parts = str(raw_check).split(":")
        if len(parts) >= 2 and parts[0] in {"exact", "numeric_tolerance"}:
            metric_name = parts[1].strip()
            if metric_name:
                return metric_name
    return str(canonical_task_spec.arguments.get("metric", "")).strip()


def _expected_metric_projection(
    expected_facts: dict[str, object],
    *,
    canonical_task_spec: CanonicalTaskSpec,
) -> tuple[str, str]:
    public_metric_name = _public_metric_projection_key(canonical_task_spec)
    if public_metric_name and public_metric_name in expected_facts:
        return public_metric_name, _projection_value_text(expected_facts[public_metric_name])
    metric_name = str(expected_facts.get("metric_name", "")).strip()
    metric_value = str(
        expected_facts.get("metric_value", expected_facts.get("revenue_value", ""))
    ).strip()
    if metric_name and metric_value:
        return metric_name, metric_value
    for key, value in expected_facts.items():
        key_text = str(key).strip()
        if not key_text or key_text in {"selected_doc_hashes", "metric_name", "metric_value", "revenue_value"}:
            continue
        if key_text.endswith("_ref") or key_text.endswith("_artifact_ref"):
            continue
        return key_text, _projection_value_text(value)
    return metric_name, metric_value


def _route_tool_projection(sample: MinimalBenchmarkSample) -> tuple[str, str]:
    if sample.canonical_task_spec is None:
        return "compare_metric", "table_retriever"
    if sample.canonical_task_spec.task_family == "cross_period_financial_analysis":
        return "compare_metric", "table_retriever"
    candidates = build_route_tool_surface(
        sample.canonical_task_spec,
        query_text=sample.request_text,
    )
    exact_intent = tuple(
        candidate
        for candidate in candidates
        if candidate.route == sample.canonical_task_spec.intent_op
    )
    ranked = sorted(
        exact_intent or candidates,
        key=lambda candidate: (-candidate.score, candidate.helper_rank, candidate.route, candidate.tool_name),
    )
    if not ranked:
        return "compare_metric", "table_retriever"
    return ranked[0].route, ranked[0].tool_name


def adapt_minimal_formal_sample_to_fixed_answer(
    sample: MinimalBenchmarkSample,
) -> FixedAnswerSample:
    if sample.canonical_task_spec is None:
        raise ValueError(f"formal registry sample lacks canonical_task_spec: {sample.task_id}")
    expected_facts = dict(sample.expected_facts or {})
    metric_name, _metric_value = _expected_metric_projection(
        expected_facts,
        canonical_task_spec=sample.canonical_task_spec,
    )
    expected_route, expected_tool_name = _route_tool_projection(sample)
    return FixedAnswerSample(
        task_id=sample.task_id,
        request_text=sample.request_text,
        canonical_task_spec=sample.canonical_task_spec,
        task_family=sample.task_family,
        expected_facts=expected_facts,
        expected_route=expected_route,
        expected_tool_name=expected_tool_name,
        summary_hint=sample.request_text,
        scenario_tags=tuple(dict.fromkeys((*sample.scenario_tags, "formal-registry-adapted"))),
        metric_projection_key=metric_name,
    )


def _fixed_or_adapted_formal_sample(path: Path) -> FixedAnswerSample:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("expected_route") and payload.get("expected_tool_name"):
        return FixedAnswerSample.from_path(path)
    return adapt_minimal_formal_sample_to_fixed_answer(MinimalBenchmarkSample.from_path(path))


def load_registered_formal_fixed_answer_samples() -> list[FixedAnswerSample]:
    samples: list[FixedAnswerSample] = []
    legacy_additions = {
        "financial_report_analysis_v1": {f"benchmark-sample-{i}" for i in range(9, 13)},
        "multi_period_trend_analysis_v1": {f"formal-trend-{i:03d}" for i in range(6, 11)},
        "cross_table_join_analysis_v1": {f"formal-join-{i:03d}" for i in range(6, 11)},
        "conditional_aggregation_v1": {f"formal-agg-{i:03d}" for i in range(5, 9)},
        "anomaly_detection_v1": {f"formal-anomaly-{i:03d}" for i in range(4, 9)},
    }
    for family in formal_family_specs():
        paths = sorted(family.sample_dir.glob("*.json"))
        paths = [
            path
            for path in paths
            if MinimalBenchmarkSample.from_path(path).task_id
            not in legacy_additions[family.family_id]
        ]
        if len(paths) != family.expected_case_count:
            raise ValueError(
                f"formal family {family.family_id} expected {family.expected_case_count} cases, "
                f"found {len(paths)} in {family.sample_dir}"
            )
        samples.extend(_fixed_or_adapted_formal_sample(path) for path in paths)
    return samples


def public_formal_case_projection(sample: MinimalBenchmarkSample) -> dict[str, object]:
    """Project only provider-visible registration fields; gold stays sealed."""
    if sample.canonical_task_spec is None:
        raise ValueError(f"formal registry sample lacks canonical_task_spec: {sample.task_id}")
    spec_payload = sample.canonical_task_spec.canonical_payload()
    # CanonicalTaskSpec is public task identity, but benchmark-only assertions
    # can be carried in its arguments by fixtures.  Keep those fields in the
    # scorer/registry surface only; never expose them to role providers.
    arguments = {
        str(key): value
        for key, value in dict(spec_payload.get("arguments", {})).items()
        if not (
            str(key).lower() in {"gold", "gold_answer", "quality_checks", "expected_route", "expected_tool", "expected_tool_name", "expected_facts"}
            or str(key).lower().startswith(("expected_", "hidden_", "future_round"))
        )
    }
    public_spec = {**spec_payload, "arguments": arguments}
    return {
        "case_id": sample.task_id,
        "task_family": sample.task_family,
        "request_text": sample.request_text,
        "canonical_task_spec": public_spec,
        "dataset_id": sample.dataset_id,
        "dataset_version": sample.dataset_version,
        "dataset_split": sample.dataset_split,
        "dataset_hash": sample.dataset_hash,
        "scenario_tags": list(sample.scenario_tags),
    }


def load_c2b_formal_fixed_answer_samples() -> list[FixedAnswerSample]:
    """Adapt the frozen 48-case C2B registry without exposing sealed facts."""
    from statebus.benchmark.task_registry import c2b_formal_family_specs

    samples: list[FixedAnswerSample] = []
    for family in c2b_formal_family_specs():
        paths = sorted(family.sample_dir.glob("*.json"))
        if len(paths) != family.expected_case_count:
            raise ValueError(f"c2b_family_case_count:{family.family_id}:{len(paths)}")
        samples.extend(_fixed_or_adapted_formal_sample(path) for path in paths)
    if len(samples) != 48:
        raise ValueError(f"c2b_fixed_answer_case_count:{len(samples)}")
    return samples
