from __future__ import annotations

from collections import defaultdict
from math import ceil, isfinite
from typing import Any

from statebus.contracts import TransformProgram, TransformStep


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
    if step.op == "rank":
        metric = str(args["metric"])
        output = str(args["output"])
        descending = bool(args.get("descending", False))
        tie_break = tuple(str(field) for field in args.get("tie_break_columns", ()))
        if any(
            not isinstance(row.get(metric), (int, float))
            or isinstance(row.get(metric), bool)
            or not isfinite(float(row[metric]))
            for row in rows
        ):
            raise CapabilityRecomputeError("recompute_rank_metric_not_numeric")
        ranked = sorted(
            rows,
            key=lambda row: (
                -row[metric] if descending else row[metric],
                tuple(row.get(field) for field in tie_break),
            ),
        )
        positions = {id(row): index for index, row in enumerate(ranked, 1)}
        return [{**row, output: positions[id(row)]} for row in rows]
    if step.op == "percentile_nearest_rank":
        value_field = str(args["value_field"])
        output = str(args["output"])
        percentile = float(args["percentile"])
        group_fields = tuple(str(field) for field in args.get("group_fields", ()))
        groups: dict[tuple[object, ...], list[int | float]] = defaultdict(list)
        for row in rows:
            value = row.get(value_field)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
                raise CapabilityRecomputeError("recompute_percentile_value_not_numeric")
            groups[tuple(row[field] for field in group_fields)].append(value)
        output_rows: list[dict[str, object]] = []
        for key, values in sorted(groups.items(), key=lambda item: tuple(str(part) for part in item[0])):
            ordered = sorted(values)
            index = max(1, ceil(percentile * len(ordered) / 100.0)) - 1
            output_row = {**dict(zip(group_fields, key)), output: ordered[index]}
            if "sample_count_output" in args:
                output_row[str(args["sample_count_output"])] = len(values)
            output_rows.append(output_row)
        return output_rows
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
        if "group_fields" in args:
            grouping = list(args["group_fields"])
            group_outputs = grouping
            reductions = list(zip(args["value_fields"], args["functions"], args["outputs"], strict=True))
        else:
            grouping = [str(args["group_field"])]
            group_outputs = [str(args.get("group_output", grouping[0]))]
            reductions = [(str(args["value_field"]), function, str(args.get(f"{function}_output", function)))
                          for function in ("sum", "mean", "min", "max", "count")]
        groups: dict[tuple[object, ...], list[dict[str, object]]] = {}
        for row in rows:
            key = tuple(row[field] for field in grouping)
            groups.setdefault(key, []).append(row)
        reduced: list[dict[str, object]] = []
        for key in sorted(groups, key=lambda key: tuple(str(item) for item in key)):
            record = dict(zip(group_outputs, key, strict=True))
            members = groups[key]
            for field, function, output in reductions:
                values = []
                for member in members:
                    value = member[field]
                    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
                        raise CapabilityRecomputeError("recompute_aggregate_value_not_numeric")
                    values.append(value)
                if function == "count":
                    answer = len(members)
                elif function == "sum":
                    answer = sum(values)
                elif function == "mean":
                    answer = sum(values) / len(members)
                elif function == "min":
                    answer = min(values)
                else:
                    answer = max(values)
                if isinstance(answer, float) and not isfinite(answer):
                    raise CapabilityRecomputeError("recompute_non_finite")
                record[output] = answer
            reduced.append(record)
        return reduced
    if step.op == "derive_safe":
        calculations = args.get("calculations", [])
        if "calculations" not in args:
            calculations = [[args["output"], args["kind"], args["numerator"], args["denominator"]]]
        derived: list[dict[str, object]] = []
        for original in rows:
            row = dict(original)
            for calculation in calculations:
                output, operation, lhs, rhs = calculation[:4]
                left = row[lhs]
                right = row[rhs] if isinstance(rhs, str) else rhs
                if operation == "boolean_change":
                    if type(left) is not bool or (right is not None and type(right) is not bool):
                        raise CapabilityRecomputeError("recompute_derive_boolean_operand_invalid")
                    transitions = {(False, False): "still_clear", (False, True): "resolved",
                                   (True, False): "new", (True, True): "still_risk"}
                    answer = "initial" if right is None else transitions[(left, right)]
                else:
                    for operand in (left, right):
                        if type(operand) not in (int, float) or not isfinite(float(operand)):
                            raise CapabilityRecomputeError("recompute_derive_operand_not_numeric")
                    if operation in {"ratio", "pct_change"} and right == 0:
                        raise CapabilityRecomputeError("recompute_derive_zero_denominator")
                    if operation == "difference":
                        answer = left - right
                    elif operation == "ratio":
                        answer = left / right
                    elif operation == "pct_change":
                        answer = (left - right) / right * 100.0
                    elif operation == "less_than":
                        answer = left < right
                    elif operation == "greater_than":
                        answer = left > right
                    else:
                        raise CapabilityRecomputeError("recompute_unknown_derive_kind")
                    if len(calculation) >= 5:
                        answer = answer * calculation[4]
                    if len(calculation) == 6 and calculation[5] is not None:
                        answer = round(answer, calculation[5])
                    if isinstance(answer, float) and not isfinite(answer):
                        raise CapabilityRecomputeError("recompute_non_finite")
                row[output] = answer
            derived.append(row)
        return derived
    if step.op == "compare_periods":
        period_field, value_field = str(args["period_field"]), str(args["value_field"])
        carry_fields = tuple(str(field) for field in args.get("carry_fields", ()))
        grouping = tuple(args.get("group_fields", ()))
        partitions: dict[tuple[object, ...], list[dict[str, object]]] = {}
        for row in rows:
            partitions.setdefault(tuple(row[field] for field in grouping), []).append(row)
        if not rows:
            raise CapabilityRecomputeError("recompute_comparison_requires_two_rows")
        output_rows = []
        for key in sorted(partitions, key=lambda key: tuple(str(item) for item in key)):
            ordered = sorted(partitions[key], key=lambda row: str(row[period_field]))
            if len(ordered) < 2:
                raise CapabilityRecomputeError("recompute_comparison_requires_two_rows")
            if "group_fields" in args and (len(ordered) != 2 or ordered[0][period_field] == ordered[1][period_field]):
                raise CapabilityRecomputeError("recompute_comparison_period_rows_invalid")
            first, last = ordered[0], ordered[-1]
            baseline, current = first[value_field], last[value_field]
            if any(type(value) not in (int, float) or not isfinite(float(value)) for value in (baseline, current)) or baseline == 0:
                raise CapabilityRecomputeError("recompute_comparison_values_invalid")
            result = dict(zip(grouping, key, strict=True))
            for field in carry_fields:
                if any(member[field] != first[field] for member in ordered):
                    raise CapabilityRecomputeError("recompute_comparison_carry_field_not_invariant")
                result[field] = first[field]
            result.update({
                str(args.get("baseline_period_output", "baseline_period")): first[period_field],
                str(args.get("comparison_period_output", "comparison_period")): last[period_field],
                str(args.get("baseline_value_output", "baseline_value")): baseline,
                str(args.get("comparison_value_output", "comparison_value")): current,
                str(args.get("difference_output", "difference")): current - baseline,
                str(args.get("ratio_output", "ratio")): current / baseline,
                str(args.get("growth_pct_output", "growth_pct")): (current - baseline) / baseline * 100.0,
            })
            output_rows.append(result)
        return output_rows
    if step.op == "compare_metric":
        ticker_field = str(args["ticker_field"])
        period_field = str(args["period_field"])
        metric_field = str(args["metric_field"])
        value_field = str(args["value_field"])
        left_ticker = str(args["left_ticker"]).upper()
        right_ticker = str(args["right_ticker"]).upper()
        period = str(args["period"])
        metric = str(args["metric"]).lower()

        def select_value(ticker: str) -> float:
            matches = [
                row
                for row in rows
                if str(row.get(ticker_field, "")).upper() == ticker
                and str(row.get(period_field, "")) == period
                and str(row.get(metric_field, "")).lower() == metric
            ]
            if len(matches) != 1:
                raise CapabilityRecomputeError("recompute_compare_metric_match_count_invalid")
            value = matches[0].get(value_field)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not isfinite(float(value))
            ):
                raise CapabilityRecomputeError("recompute_compare_metric_value_invalid")
            return float(value)

        left = select_value(left_ticker)
        right = select_value(right_ticker)
        return [{
            str(args["period_output"]): period,
            str(args["left_output"]): left,
            str(args["right_output"]): right,
            str(args["gap_output"]): left - right,
        }]
    if step.op == "trend_series":
        ticker_field = str(args["ticker_field"])
        period_field = str(args["period_field"])
        metric_field = str(args["metric_field"])
        value_field = str(args["value_field"])
        tickers = tuple(str(item) for item in args["tickers"])
        periods = tuple(str(item) for item in args["periods"])
        metric = str(args["metric"])
        ticker_output = str(args["ticker_output"])
        period_output = str(args["period_output"])
        value_output = str(args["value_output"])
        direction_output = str(args["direction_output"])
        output: list[dict[str, object]] = []
        for ticker in tickers:
            values: list[float] = []
            for period in periods:
                matches = [
                    row
                    for row in rows
                    if str(row.get(ticker_field, "")).upper() == ticker.upper()
                    and str(row.get(period_field, "")) == period
                    and str(row.get(metric_field, "")).lower() == metric.lower()
                ]
                if len(matches) != 1:
                    raise CapabilityRecomputeError("recompute_trend_series_match_count_invalid")
                value = matches[0].get(value_field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise CapabilityRecomputeError("recompute_trend_series_value_invalid")
                values.append(float(value))
            deltas = [right - left for left, right in zip(values, values[1:], strict=False)]
            if all(delta > 0 for delta in deltas):
                direction = "increasing"
            elif all(delta < 0 for delta in deltas):
                direction = "decreasing"
            elif all(delta == 0 for delta in deltas):
                direction = "flat"
            else:
                direction = "mixed"
            output.extend(
                {
                    ticker_output: ticker,
                    period_output: period,
                    value_output: value,
                    direction_output: direction,
                }
                for period, value in zip(periods, values, strict=True)
            )
        return output
    if step.op == "join_by_key":
        right_rows = inputs[str(args["right_ref"])]
        left_columns = args["left_keys"] if "left_keys" in args else [args["left_key"]]
        right_columns = args["right_keys"] if "right_keys" in args else [args["right_key"]]
        prefix = str(args.get("right_prefix", ""))
        # Deliberately use a scan rather than the interpreter's indexed join.
        joined: list[dict[str, object]] = []
        for left in rows:
            for right in right_rows:
                if all(left[lkey] == right[rkey] for lkey, rkey in zip(left_columns, right_columns, strict=True)):
                    joined.append({**left, **{prefix + key: value for key, value in right.items()}})
        return joined
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
