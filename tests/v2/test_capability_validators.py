from __future__ import annotations

import pytest

from v2.runtime.capability_validators import (
    CapabilityQualityContext,
    CapabilityValidatorError,
    default_capability_validator_registry,
)


def _context(*, output: tuple[dict[str, object], ...], validator_id: str = "metric_series") -> CapabilityQualityContext:
    return CapabilityQualityContext(
        capability_id="extract_metric_series_v1",
        validator_id=validator_id,
        input_rows=(({"quarter": "2026Q1", "revenue_musd": 120.0},),),
        output_rows=output,
        input_artifact_hashes=("input-hash",),
        output_artifact_hash="output-hash",
        required_fields=("quarter", "revenue_musd"),
        completion_criteria={"min_rows": 1},
        provenance_item_ids=("evidence-row",),
    )


def test_metric_series_validator_accepts_recomputed_provenanced_output() -> None:
    report = default_capability_validator_registry().validate(
        _context(output=({"quarter": "2026Q1", "revenue_musd": 120},))
    )
    assert report.verified
    assert report.recomputation_passed
    assert report.provenance_passed
    assert report.execution_verified
    assert report.semantic_verification_status == "verified"


def test_schema_correct_but_numerically_wrong_output_is_not_verified() -> None:
    report = default_capability_validator_registry().validate(
        _context(output=({"quarter": "2026Q1", "revenue_musd": 999.0},))
    )
    assert not report.verified
    assert "metric_series_value_not_from_input" in report.error_codes


def test_validator_registry_fails_closed_for_unregistered_validator() -> None:
    with pytest.raises(CapabilityValidatorError, match="unregistered"):
        default_capability_validator_registry().validate(
            _context(output=({"quarter": "2026Q1", "revenue_musd": 120.0},), validator_id="not-registered")
        )


def _semantic_context(
    *,
    capability_id: str,
    validator_id: str,
    inputs: tuple[dict[str, object], ...],
    output: tuple[dict[str, object], ...],
    semantics: dict[str, object],
) -> CapabilityQualityContext:
    return CapabilityQualityContext(
        capability_id=capability_id,
        validator_id=validator_id,
        input_rows=(inputs,),
        output_rows=output,
        input_artifact_hashes=("input-hash",),
        output_artifact_hash="output-hash",
        required_fields=tuple(output[0]) if output else (),
        completion_criteria={"min_rows": 1},
        operation_semantics=semantics,
        provenance_item_ids=("evidence-row",),
    )


def test_period_comparison_validator_recomputes_difference_ratio_and_growth() -> None:
    context = _semantic_context(
        capability_id="compare_periods_python_v1",
        validator_id="period_comparison",
        inputs=(
            {"quarter": "2026Q1", "revenue_musd": 100.0},
            {"quarter": "2026Q2", "revenue_musd": 125.0},
        ),
        output=({
            "baseline_period": "2026Q1", "comparison_period": "2026Q2",
            "baseline_value": 100.0, "comparison_value": 125.0,
            "difference": 25.0, "ratio": 1.25, "growth_pct": 25.0,
        },),
        semantics={"operation": "compare_periods", "period_field": "quarter", "value_field": "revenue_musd"},
    )
    registry = default_capability_validator_registry()
    assert registry.validate(context).verified
    tampered = context.__class__(**{**context.__dict__, "output_rows": ({**context.output_rows[0], "growth_pct": 24.0},)})
    report = registry.validate(tampered)
    assert not report.verified
    assert "comparison_recomputation_mismatch" in report.error_codes


def test_grouped_aggregation_and_anomaly_validators_reject_numerically_wrong_rows() -> None:
    registry = default_capability_validator_registry()
    aggregation = _semantic_context(
        capability_id="aggregate_metrics_python_v1",
        validator_id="aggregation",
        inputs=(
            {"segment": "enterprise", "revenue": 10.0},
            {"segment": "enterprise", "revenue": 30.0},
            {"segment": "consumer", "revenue": 5.0},
        ),
        output=(
            {"segment": "consumer", "sum": 5.0, "mean": 5.0, "min": 5.0, "max": 5.0, "count": 1},
            {"segment": "enterprise", "sum": 40.0, "mean": 20.0, "min": 10.0, "max": 30.0, "count": 2},
        ),
        semantics={"operation": "aggregate_metrics", "group_field": "segment", "value_field": "revenue"},
    )
    assert registry.validate(aggregation).verified
    bad_aggregation = aggregation.__class__(**{**aggregation.__dict__, "output_rows": (
        aggregation.output_rows[0], {**aggregation.output_rows[1], "sum": 41.0},
    )})
    assert not registry.validate(bad_aggregation).verified

    anomaly = _semantic_context(
        capability_id="detect_anomaly_python_v1",
        validator_id="anomaly",
        inputs=(
            {"quarter": "2026Q1", "revenue": 10.0},
            {"quarter": "2026Q2", "revenue": 10.0},
            {"quarter": "2026Q3", "revenue": 100.0},
        ),
        output=(
            {"quarter": "2026Q1", "revenue": 10.0, "baseline_mean": 40.0, "threshold": 63.63961030678928, "is_anomaly": False},
            {"quarter": "2026Q2", "revenue": 10.0, "baseline_mean": 40.0, "threshold": 63.63961030678928, "is_anomaly": False},
            {"quarter": "2026Q3", "revenue": 100.0, "baseline_mean": 40.0, "threshold": 63.63961030678928, "is_anomaly": False},
        ),
        semantics={"operation": "detect_anomaly", "period_field": "quarter", "value_field": "revenue", "z_threshold": 1.5},
    )
    assert registry.validate(anomaly).verified
    bad_anomaly = anomaly.__class__(**{**anomaly.__dict__, "output_rows": (
        anomaly.output_rows[0], anomaly.output_rows[1], {**anomaly.output_rows[2], "is_anomaly": True},
    )})
    assert not registry.validate(bad_anomaly).verified
