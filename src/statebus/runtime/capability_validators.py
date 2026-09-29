from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose, isfinite
from typing import Callable

from statebus.contracts import CapabilityQualityReport


class CapabilityValidatorError(ValueError):
    pass


@dataclass(frozen=True)
class CapabilityQualityContext:
    capability_id: str
    validator_id: str
    input_rows: tuple[tuple[dict[str, object], ...], ...]
    output_rows: tuple[dict[str, object], ...]
    input_artifact_hashes: tuple[str, ...]
    output_artifact_hash: str
    expected_rows: tuple[dict[str, object], ...] = ()
    required_fields: tuple[str, ...] = ()
    completion_criteria: dict[str, object] = field(default_factory=dict)
    operation_semantics: dict[str, object] = field(default_factory=dict)
    provenance_item_ids: tuple[str, ...] = ()


CapabilityValidator = Callable[[CapabilityQualityContext], CapabilityQualityReport]


class CapabilityValidatorRegistry:
    """Controller-owned business validators for both DSL and LLM Python output."""

    def __init__(self) -> None:
        self._validators: dict[str, CapabilityValidator] = {}

    def register(self, validator_id: str, validator: CapabilityValidator) -> None:
        if not validator_id or validator_id in self._validators:
            raise CapabilityValidatorError(f"duplicate_or_empty_validator:{validator_id}")
        self._validators[validator_id] = validator

    def contains(self, validator_id: str) -> bool:
        return validator_id in self._validators

    def validate(self, context: CapabilityQualityContext) -> CapabilityQualityReport:
        try:
            validator = self._validators[context.validator_id]
        except KeyError as exc:
            raise CapabilityValidatorError(f"unregistered_capability_validator:{context.validator_id}") from exc
        report = validator(context)
        if report.validator_id != context.validator_id or report.capability_id != context.capability_id:
            raise CapabilityValidatorError("capability_validator_identity_mismatch")
        return report


def default_capability_validator_registry() -> CapabilityValidatorRegistry:
    registry = CapabilityValidatorRegistry()
    registry.register("metric_series", _validate_metric_series)
    registry.register("period_comparison", _validate_period_comparison)
    registry.register("aggregation", _validate_aggregation)
    registry.register("join", _validate_recomputed_rows)
    registry.register("anomaly", _validate_anomaly)
    registry.register("conflict", _validate_recomputed_rows)
    registry.register("cited_report", _validate_recomputed_rows)
    registry.register("generic_analysis", _validate_generic_analysis)
    return registry


def _validate_metric_series(context: CapabilityQualityContext) -> CapabilityQualityReport:
    source_rows = tuple(row for rows in context.input_rows for row in rows)
    errors = _common_errors(context)
    for row in context.output_rows:
        if not any(_rows_equal((row,), (source_row,)) for source_row in source_rows):
            errors.append("metric_series_value_not_from_input")
            break
    return _report(context, errors)


def _validate_recomputed_rows(context: CapabilityQualityContext) -> CapabilityQualityReport:
    errors = _common_errors(context)
    if not context.expected_rows:
        errors.append("missing_independent_recomputation")
    elif not _rows_equal(context.output_rows, context.expected_rows):
        errors.append("recomputation_mismatch")
    return _report(context, errors)


def _validate_generic_analysis(context: CapabilityQualityContext) -> CapabilityQualityReport:
    """Validate a model-authored analysis without using benchmark answers.

    Formal benchmark oracles run after Runtime completion.  This validator is
    deliberately limited to generic properties that are meaningful in the
    product path: provenance, non-empty rows, declared fields, finite numeric
    values and the requested row budget.  It must not recompute a task-specific
    operation from hidden benchmark arguments.
    """
    errors = _common_errors(context)
    if not context.output_rows:
        errors.append("empty_output")
    required_fields = set(context.required_fields)
    for row in context.output_rows:
        if required_fields and not required_fields <= set(row):
            errors.append("required_fields_missing")
        for value in row.values():
            if isinstance(value, float) and not isfinite(value):
                errors.append("non_finite_output")
    errors = sorted(set(errors))
    return CapabilityQualityReport(
        capability_id=context.capability_id,
        validator_id=context.validator_id,
        input_artifact_hashes=context.input_artifact_hashes,
        output_artifact_hash=context.output_artifact_hash,
        schema_passed=not any(
            error in {"required_fields_missing", "non_finite_output", "empty_output"}
            for error in errors
        ),
        # A generic sandbox/schema validator cannot honestly claim that it
        # independently recomputed an arbitrary model-selected analysis.
        recomputation_passed=False,
        provenance_passed=(
            "missing_provenance" not in errors
            and "missing_input_artifact_hash" not in errors
        ),
        completion_criteria_passed=not any(
            error.startswith("completion_") for error in errors
        ),
        verified=not errors,
        recomputation_evaluated=False,
        error_codes=tuple(errors),
    )


def _validate_period_comparison(context: CapabilityQualityContext) -> CapabilityQualityReport:
    errors = _common_errors(context)
    expected = _comparison_rows(context)
    if expected is None:
        if not context.expected_rows:
            errors.append("comparison_input_not_recomputable")
        elif not _rows_equal(context.output_rows, context.expected_rows):
            errors.append("recomputation_mismatch")
    elif not _rows_equal(context.output_rows, expected):
        errors.append("comparison_recomputation_mismatch")
    return _report(context, errors)


def _validate_aggregation(context: CapabilityQualityContext) -> CapabilityQualityReport:
    errors = _common_errors(context)
    expected = _aggregation_rows(context)
    if expected is None:
        if not context.expected_rows:
            errors.append("aggregation_input_not_recomputable")
        elif not _rows_equal(context.output_rows, context.expected_rows):
            errors.append("recomputation_mismatch")
    elif not _rows_equal(context.output_rows, expected):
        errors.append("aggregation_recomputation_mismatch")
    return _report(context, errors)


def _validate_anomaly(context: CapabilityQualityContext) -> CapabilityQualityReport:
    errors = _common_errors(context)
    expected = _anomaly_rows(context)
    if expected is None:
        if not context.expected_rows:
            errors.append("anomaly_input_not_recomputable")
        elif not _rows_equal(context.output_rows, context.expected_rows):
            errors.append("recomputation_mismatch")
    elif not _rows_equal(context.output_rows, expected):
        errors.append("anomaly_recomputation_mismatch")
    return _report(context, errors)


def _input_rows(context: CapabilityQualityContext) -> tuple[dict[str, object], ...]:
    return tuple(dict(row) for rows in context.input_rows for row in rows)


def _comparison_rows(context: CapabilityQualityContext) -> tuple[dict[str, object], ...] | None:
    semantics = context.operation_semantics
    if semantics.get("operation") != "compare_periods":
        return None
    rows = _input_rows(context)
    period_field = str(semantics.get("period_field", "period"))
    value_field = str(semantics.get("value_field", "value"))
    ordered = sorted(rows, key=lambda row: str(row.get(period_field, "")))
    if len(ordered) < 2:
        return ()
    baseline, comparison = ordered[0], ordered[-1]
    if not isinstance(baseline.get(value_field), (int, float)) or isinstance(baseline.get(value_field), bool):
        return ()
    if not isinstance(comparison.get(value_field), (int, float)) or isinstance(comparison.get(value_field), bool):
        return ()
    before, after = float(baseline[value_field]), float(comparison[value_field])
    if before == 0:
        return ()
    return ({
        str(semantics.get("baseline_period_output", "baseline_period")): baseline.get(period_field),
        str(semantics.get("comparison_period_output", "comparison_period")): comparison.get(period_field),
        str(semantics.get("baseline_value_output", "baseline_value")): before,
        str(semantics.get("comparison_value_output", "comparison_value")): after,
        str(semantics.get("difference_output", "difference")): after - before,
        str(semantics.get("ratio_output", "ratio")): after / before,
        str(semantics.get("growth_pct_output", "growth_pct")): ((after - before) / before) * 100.0,
    },)


def _aggregation_rows(context: CapabilityQualityContext) -> tuple[dict[str, object], ...] | None:
    semantics = context.operation_semantics
    if semantics.get("operation") != "aggregate_metrics":
        return None
    group_field = str(semantics.get("group_field", "group"))
    value_field = str(semantics.get("value_field", "value"))
    groups: dict[object, list[float]] = {}
    for row in _input_rows(context):
        value = row.get(value_field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ()
        groups.setdefault(row.get(group_field), []).append(float(value))
    if not groups:
        return ()
    output_names = {
        "group": str(semantics.get("group_output", group_field)),
        "sum": str(semantics.get("sum_output", "sum")),
        "mean": str(semantics.get("mean_output", "mean")),
        "min": str(semantics.get("min_output", "min")),
        "max": str(semantics.get("max_output", "max")),
        "count": str(semantics.get("count_output", "count")),
    }
    expected: list[dict[str, object]] = []
    for group in sorted(groups, key=lambda item: str(item)):
        values = groups[group]
        expected.append({
            output_names["group"]: group,
            output_names["sum"]: sum(values),
            output_names["mean"]: sum(values) / len(values),
            output_names["min"]: min(values),
            output_names["max"]: max(values),
            output_names["count"]: len(values),
        })
    return tuple(expected)


def _anomaly_rows(context: CapabilityQualityContext) -> tuple[dict[str, object], ...] | None:
    semantics = context.operation_semantics
    if semantics.get("operation") != "detect_anomaly":
        return None
    period_field = str(semantics.get("period_field", "period"))
    value_field = str(semantics.get("value_field", "value"))
    rows = sorted(_input_rows(context), key=lambda row: str(row.get(period_field, "")))
    values = [float(row[value_field]) for row in rows if isinstance(row.get(value_field), (int, float)) and not isinstance(row.get(value_field), bool)]
    if len(values) != len(rows) or not values:
        return ()
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    threshold = float(semantics.get("z_threshold", 1.5)) * variance ** 0.5
    baseline_name = str(semantics.get("baseline_output", "baseline_mean"))
    threshold_name = str(semantics.get("threshold_output", "threshold"))
    flag_name = str(semantics.get("flag_output", "is_anomaly"))
    return tuple({
        period_field: row.get(period_field),
        value_field: float(row[value_field]),
        baseline_name: mean,
        threshold_name: threshold,
        flag_name: abs(float(row[value_field]) - mean) > threshold,
    } for row in rows)


def _common_errors(context: CapabilityQualityContext) -> list[str]:
    errors: list[str] = []
    if not context.input_artifact_hashes:
        errors.append("missing_input_artifact_hash")
    if not context.provenance_item_ids:
        errors.append("missing_provenance")
    if not context.output_rows:
        errors.append("empty_output")
    required_fields = set(context.required_fields)
    min_rows = context.completion_criteria.get("min_rows")
    if isinstance(min_rows, int) and len(context.output_rows) < min_rows:
        errors.append("completion_min_rows_failed")
    for row in context.output_rows:
        if required_fields and not required_fields <= set(row):
            errors.append("required_fields_missing")
        for value in row.values():
            if isinstance(value, float) and not isfinite(value):
                errors.append("non_finite_output")
    return sorted(set(errors))


def _rows_equal(actual: tuple[dict[str, object], ...], expected: tuple[dict[str, object], ...]) -> bool:
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected):
        if set(left) != set(right):
            return False
        for key in left:
            a, b = left[key], right[key]
            if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
                if not isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9):
                    return False
            elif a != b:
                return False
    return True


def _report(context: CapabilityQualityContext, errors: list[str]) -> CapabilityQualityReport:
    verified = not errors
    return CapabilityQualityReport(
        capability_id=context.capability_id,
        validator_id=context.validator_id,
        input_artifact_hashes=context.input_artifact_hashes,
        output_artifact_hash=context.output_artifact_hash,
        schema_passed=not any(error in {"required_fields_missing", "non_finite_output", "empty_output"} for error in errors),
        recomputation_passed=not any("recomputation" in error or "value_not_from_input" in error or "not_recomputable" in error for error in errors),
        provenance_passed="missing_provenance" not in errors and "missing_input_artifact_hash" not in errors,
        completion_criteria_passed=not any(error.startswith("completion_") for error in errors),
        verified=verified,
        error_codes=tuple(errors),
    )
