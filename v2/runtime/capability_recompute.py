from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any

from v2.contracts import TransformProgram, TransformStep


class CapabilityRecomputeError(ValueError):
    pass


def recompute_transform_program(
    program: TransformProgram,
    *,
    inputs: dict[str, list[dict[str, object]]],
) -> tuple[dict[str, object], ...]:
    """Independently recompute a validated DSL program for the quality gate.

    This deliberately does not share TransformDslInterpreter execution helpers.
    Program syntax and resource limits are enforced before this function runs.
    """
    try:
        rows = [dict(row) for row in inputs[program.input_artifact_refs[0]]]
    except (IndexError, KeyError) as exc:
        raise CapabilityRecomputeError("recompute_input_missing") from exc
    for step in program.operations:
        rows = _apply(rows, step, inputs)
    return tuple({key: row[key] for key in sorted(row)} for row in rows)


def _apply(
    rows: list[dict[str, object]],
    step: TransformStep,
    inputs: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    args = step.arguments
    if step.op in {"select", "project_claim_fields"}:
        return [{column: row.get(column) for column in args["columns"]} for row in rows]
    if step.op == "rename":
        source, target = str(args["source"]), str(args["target"])
        renamed_rows: list[dict[str, object]] = []
        for row in rows:
            renamed = dict(row)
            renamed[target] = renamed.pop(source, None)
            renamed_rows.append(renamed)
        return renamed_rows
    if step.op == "filter_eq":
        return [row for row in rows if row.get(args["column"]) == args.get("value")]
    if step.op == "filter_contains":
        needle = str(args.get("value", "")).lower()
        return [row for row in rows if needle in str(row.get(args["column"], "")).lower()]
    if step.op == "filter_in":
        values = set(args.get("values", ()))
        return [row for row in rows if row.get(args["column"]) in values]
    if step.op == "filter_range":
        lower, upper = args.get("min"), args.get("max")
        return [
            row
            for row in rows
            if (lower is None or row.get(args["column"]) >= lower)
            and (upper is None or row.get(args["column"]) <= upper)
        ]
    if step.op == "sort":
        columns = tuple(args.get("columns", (args.get("column"),)))
        return sorted(rows, key=lambda row: tuple((row.get(column) is None, row.get(column)) for column in columns))
    if step.op == "limit":
        return rows[: int(args["count"])]
    if step.op == "group_by":
        columns = tuple(args["columns"])
        return [dict(row) for row in sorted(rows, key=lambda row: tuple(row.get(column) for column in columns))]
    if step.op == "aggregate":
        column = str(args["column"])
        function = str(args["function"])
        output = str(args.get("output", f"{function}_{column}"))
        values = [row[column] for row in rows if row.get(column) is not None]
        if function == "count":
            value: object = len(rows)
        elif not values:
            value = None
        elif function == "sum":
            value = sum(values)
        elif function == "mean":
            value = sum(values) / len(values)
        elif function == "min":
            value = min(values)
        elif function == "max":
            value = max(values)
        else:
            raise CapabilityRecomputeError("recompute_unknown_aggregate")
        return [{output: value}]
    if step.op == "aggregate_grouped":
        group_field, value_field = str(args["group_field"]), str(args["value_field"])
        groups: dict[object, list[float]] = defaultdict(list)
        for row in rows:
            value = row.get(value_field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise CapabilityRecomputeError("recompute_aggregate_value_not_numeric")
            groups[row.get(group_field)].append(float(value))
        return [{
            str(args.get("group_output", group_field)): group,
            str(args.get("sum_output", "sum")): sum(values),
            str(args.get("mean_output", "mean")): sum(values) / len(values),
            str(args.get("min_output", "min")): min(values),
            str(args.get("max_output", "max")): max(values),
            str(args.get("count_output", "count")): len(values),
        } for group, values in sorted(groups.items(), key=lambda item: str(item[0]))]
    if step.op == "derive_safe":
        numerator, denominator = str(args["numerator"]), str(args["denominator"])
        output, kind = str(args["output"]), str(args["kind"])
        derived: list[dict[str, object]] = []
        for row in rows:
            left, right = row.get(numerator), row.get(denominator)
            value: object = None
            if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
                if kind == "difference":
                    value = left - right
                elif kind == "ratio" and right != 0:
                    value = left / right
                elif kind == "pct_change" and right != 0:
                    value = ((left - right) / right) * 100.0
            if isinstance(value, float) and not isfinite(value):
                raise CapabilityRecomputeError("recompute_non_finite")
            derived.append({**row, output: value})
        return derived
    if step.op == "compare_periods":
        period_field, value_field = str(args["period_field"]), str(args["value_field"])
        carry_fields = tuple(str(field) for field in args.get("carry_fields", ()))
        ordered = sorted(rows, key=lambda row: str(row.get(period_field, "")))
        if len(ordered) < 2:
            raise CapabilityRecomputeError("recompute_comparison_requires_two_rows")
        before, after = ordered[0], ordered[-1]
        base, current = before.get(value_field), after.get(value_field)
        if not isinstance(base, (int, float)) or isinstance(base, bool) or not isinstance(current, (int, float)) or isinstance(current, bool) or base == 0:
            raise CapabilityRecomputeError("recompute_comparison_values_invalid")
        carried: dict[str, object] = {}
        for field in carry_fields:
            value = ordered[0].get(field)
            if any(row.get(field) != value for row in ordered[1:]):
                raise CapabilityRecomputeError("recompute_comparison_carry_field_not_invariant")
            carried[field] = value
        return [{
            **carried,
            str(args.get("baseline_period_output", "baseline_period")): before.get(period_field),
            str(args.get("comparison_period_output", "comparison_period")): after.get(period_field),
            str(args.get("baseline_value_output", "baseline_value")): float(base),
            str(args.get("comparison_value_output", "comparison_value")): float(current),
            str(args.get("difference_output", "difference")): float(current) - float(base),
            str(args.get("ratio_output", "ratio")): float(current) / float(base),
            str(args.get("growth_pct_output", "growth_pct")): ((float(current) - float(base)) / float(base)) * 100.0,
        }]
    if step.op == "join_by_key":
        right_rows = inputs[str(args["right_ref"])]
        left_key, right_key = str(args["left_key"]), str(args["right_key"])
        lookup: dict[object, list[dict[str, object]]] = defaultdict(list)
        for right in right_rows:
            lookup[right.get(right_key)].append(right)
        return [{**left, **right} for left in rows for right in lookup.get(left.get(left_key), ())]
    if step.op == "anomaly_check":
        column, output = str(args["column"]), str(args.get("output", "is_anomaly"))
        values = sorted(
            float(row[column])
            for row in rows
            if isinstance(row.get(column), (int, float)) and not isinstance(row.get(column), bool)
        )
        if not values:
            return [{**row, output: False} for row in rows]
        q1, q3 = values[len(values) // 4], values[(len(values) * 3) // 4]
        lower, upper = q1 - 1.5 * (q3 - q1), q3 + 1.5 * (q3 - q1)
        return [
            {**row, output: isinstance(row.get(column), (int, float)) and not isinstance(row.get(column), bool) and not lower <= float(row[column]) <= upper}
            for row in rows
        ]
    if step.op == "anomaly_zscore":
        period_field, value_field = str(args["period_field"]), str(args["value_field"])
        ordered = sorted(rows, key=lambda row: str(row.get(period_field, "")))
        numeric = [row.get(value_field) for row in ordered]
        if not numeric or any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in numeric):
            raise CapabilityRecomputeError("recompute_anomaly_values_invalid")
        values = [float(value) for value in numeric]
        mean = sum(values) / len(values)
        threshold = float(args.get("z_threshold", 1.5)) * (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5
        return [{
            period_field: row.get(period_field), value_field: float(row[value_field]),
            str(args.get("baseline_output", "baseline_mean")): mean,
            str(args.get("threshold_output", "threshold")): threshold,
            str(args.get("flag_output", "is_anomaly")): abs(float(row[value_field]) - mean) > threshold,
        } for row in ordered]
    raise CapabilityRecomputeError(f"recompute_unknown_operation:{step.op}")
