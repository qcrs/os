from __future__ import annotations

from dataclasses import dataclass
import csv
from math import floor, isclose, isfinite
from pathlib import Path
import re
from typing import Callable

from v2.benchmark.minimal_runner import MinimalBenchmarkSample
from v2.contracts import CapabilityQualityReport, CanonicalTaskSpec
from v2.runtime.capability_validators import CapabilityQualityContext
from v2.utils import sha256_digest


_CROSS_PERIOD_DOCUMENT = Path(
    "v2/benchmark/samples/continuous_task_families/"
    "cross_period_financial/cross_period_financial_report.md"
)


@dataclass(frozen=True)
class FormalAdaptiveCase:
    sample: MinimalBenchmarkSample
    operation: str
    capability_id: str
    output_contract_version: str
    source_rows: tuple[dict[str, object], ...]
    source_schema: dict[str, str]
    output_schema: dict[str, str]
    expected_output_shape: str
    operation_semantics: dict[str, object]
    report_capability_ids: tuple[str, ...]

    @property
    def task_id(self) -> str:
        return self.sample.task_id

    @property
    def spec(self) -> CanonicalTaskSpec:
        if self.sample.canonical_task_spec is None:
            raise ValueError(f"formal_sample_missing_canonical_task_spec:{self.task_id}")
        return self.sample.canonical_task_spec

    @property
    def source_ref_id(self) -> str:
        return f"formal-source:{self.task_id}"

    @property
    def expected_rows(self) -> tuple[dict[str, object], ...]:
        return recompute_formal_rows(self.operation, self.spec.arguments, self.source_rows)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_repo_file(raw_path: str | Path) -> Path:
    root = _project_root().resolve()
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"formal_source_path_escape:{raw_path}")
    if not resolved.is_file():
        raise FileNotFoundError(f"formal_source_missing:{raw_path}")
    return resolved


def _parse_number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if isfinite(float(value)) else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.match(r"^([-+]?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match is not None else None


def _required_number(row: dict[str, object], field: str) -> float:
    value = _parse_number(row.get(field))
    if value is None:
        raise ValueError(f"formal_numeric_field_missing:{field}")
    return value


def _source_schema(rows: tuple[dict[str, object], ...]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            kind = (
                "boolean"
                if isinstance(value, bool)
                else "number"
                if isinstance(value, (int, float))
                else "string"
            )
            prior = schema.get(key)
            if prior is not None and prior != kind:
                kind = "string"
            schema[key] = kind
    if not schema:
        raise ValueError("formal_source_rows_empty")
    return dict(sorted(schema.items()))


def build_non_answer_source_profile(
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    """Describe input shape and encodings without exposing source values."""
    profile: dict[str, dict[str, object]] = {}
    schema = _source_schema(rows)
    for column, kind in schema.items():
        values = [row.get(column) for row in rows]
        texts = [str(value).strip() for value in values if str(value).strip()]
        formats: list[str] = []
        if texts and all(re.fullmatch(r"\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2})?", text) for text in texts):
            formats.append("MM/DD/YYYY HH:MM" if any(" " in text for text in texts) else "MM/DD/YYYY")
        if texts and all(re.fullmatch(r"\d{4}Q[1-4]", text, re.IGNORECASE) for text in texts):
            formats.append("YYYYQn")
        if any(re.fullmatch(r"[-+]?\d+(?:\.\d+)?\[[-+]?\d+(?:\.\d+)?-[-+]?\d+(?:\.\d+)?\]", text) for text in texts):
            formats.append(
                "leading numeric token with optional [lower-upper] range; parse only the leading token as the value"
            )
        numeric_string_count = sum(
            1 for value in values
            if isinstance(value, str) and _parse_number(value) is not None
        )
        profile[column] = {
            "declared_type": kind,
            "missing_count": sum(1 for value in values if not str(value).strip()),
            "numeric_string_count": numeric_string_count,
            "formats": formats,
        }
    return {
        "row_count": len(rows),
        "columns": dict(sorted(profile.items())),
        "contains_values": False,
    }


def execution_task_parameters(case: FormalAdaptiveCase) -> dict[str, object]:
    """Expose user/task constraints while excluding benchmark-only metadata."""
    excluded = {"csv_path", "dataset_id", "quality_checks"}
    return {
        str(key): value
        for key, value in case.spec.arguments.items()
        if str(key) not in excluded
    }


def _financial_source_rows(spec: CanonicalTaskSpec) -> tuple[dict[str, object], ...]:
    from v2.retrieval.corpus import OfflineFinancialReportCorpus

    ticker = str(spec.arguments.get("ticker", "")).upper()
    quarter = str(spec.arguments.get("quarter", "")).upper()
    metric = str(spec.arguments.get("metric", "")).strip().lower()
    document = OfflineFinancialReportCorpus().resolve(ticker=ticker, quarter=quarter)
    matching = [
        row
        for row in document.table_rows
        if row.metric_name.strip().lower().split(":", 1)[0] == metric
    ]
    if len(matching) != 1:
        raise ValueError(
            f"formal_financial_metric_row_count:{ticker}:{quarter}:{metric}:{len(matching)}"
        )
    value = _parse_number(matching[0].value)
    if value is None:
        raise ValueError(f"formal_financial_metric_not_numeric:{metric}")
    return ({"ticker": ticker, "quarter": quarter, "metric": metric, "value": value},)


def _cross_period_source_rows() -> tuple[dict[str, object], ...]:
    text = _resolve_repo_file(_CROSS_PERIOD_DOCUMENT).read_text(encoding="utf-8")
    rows: list[dict[str, object]] = []
    for match in re.finditer(
        r"(?ms)^## ([A-Za-z0-9_-]+) Revenue Table\s*(.*?)(?=^## |\Z)", text
    ):
        ticker = match.group(1).upper()
        for line in match.group(2).splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) != 2 or not re.fullmatch(r"\d{4}Q[1-4]", cells[0]):
                continue
            value = _parse_number(cells[1])
            if value is None:
                raise ValueError(f"formal_cross_period_value_invalid:{ticker}:{cells[0]}")
            rows.append(
                {"ticker": ticker, "quarter": cells[0], "metric": "revenue", "value": value}
            )
    if len(rows) != 6:
        raise ValueError(f"formal_cross_period_row_count:{len(rows)}")
    return tuple(rows)


def _csv_source_rows(spec: CanonicalTaskSpec) -> tuple[dict[str, object], ...]:
    path = _resolve_repo_file(str(spec.arguments.get("csv_path", "")))
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        rows = tuple(dict(row) for row in reader)
    if not rows:
        raise ValueError(f"formal_csv_source_empty:{path.name}")
    return rows


def _operation_for_spec(spec: CanonicalTaskSpec) -> str:
    if spec.task_family == "financial_report_analysis" and spec.intent_op == "compare_metric":
        return "lookup_metric"
    if spec.task_family == "cross_period_financial_analysis" and spec.intent_op in {
        "compare_metric",
        "compute_delta",
        "compute_trend",
    }:
        return spec.intent_op
    if spec.task_family == "continuous_csv_table_analysis" and spec.intent_op in {
        "profile_table",
        "aggregate_and_extreme",
        "profile_and_mean",
        "groupby_aggregate",
        "detect_outliers",
        "materialize_clean_table",
    }:
        return spec.intent_op
    raise ValueError(f"formal_adaptive_operation_unsupported:{spec.task_family}:{spec.intent_op}")


def _output_contract(operation: str) -> str:
    del operation
    return "statebus.analysis_result.v2"


def _capability_id(operation: str) -> str:
    del operation
    return "execute_bounded_python_v2"


def _output_schema(operation: str, arguments: dict[str, object]) -> tuple[dict[str, str], str]:
    if operation == "lookup_metric":
        return {"metric_name": "string", "metric_value": "number"}, "object"
    if operation == "compute_delta":
        return {
            "ticker": "string",
            "period_from": "string",
            "period_to": "string",
            "value_from": "number",
            "value_to": "number",
            "delta_value": "number",
            "delta_pct": "number",
        }, "object"
    if operation == "compute_trend":
        return {
            "ticker": "string",
            "quarter": "string",
            "metric_value": "number",
            "trend_direction": "string",
        }, "array"
    if operation == "compare_metric":
        return {
            "quarter": "string",
            "acme_revenue_value": "number",
            "beta_revenue_value": "number",
            "gap_value": "number",
        }, "object"
    if operation == "profile_table":
        return {
            "percentage_cases_min": "number",
            "percentage_deaths_max": "number",
        }, "object"
    if operation == "aggregate_and_extreme":
        return {
            "mean_cases": "number",
            "max_deaths_country": "string",
            "max_deaths_year": "string",
        }, "object"
    if operation == "profile_and_mean":
        return {"mean_windspeed": "number"}, "object"
    if operation == "groupby_aggregate":
        return {"month": "integer", "monthly_avg_windspeed": "number"}, "array"
    if operation == "detect_outliers":
        column = str(arguments.get("column", ""))
        if column == "BARO":
            return {"baro_outlier_count": "integer"}, "object"
        return {
            "mean_no_of_deaths_with_outliers": "number",
            "mean_no_of_deaths_without_outliers": "number",
        }, "object"
    if operation == "materialize_clean_table":
        return {
            "mean_wind_post": "number",
            "mean_atmos_temp_post": "number",
            "cleaned_row_count": "integer",
        }, "object"
    raise ValueError(f"formal_output_schema_unsupported:{operation}")


def _operation_semantics(operation: str, arguments: dict[str, object]) -> dict[str, object]:
    semantics: dict[str, object] = {
        "operation": operation,
        "input_contract": "Read the complete JSON object array from inputs/task.json.",
        "numeric_parser": (
            "Trim whitespace and remove comma characters in memory; str.replace(',', '') is allowed, while "
            "Path.replace and filesystem rename/replace operations remain forbidden. Ignore an empty or "
            "non-numeric cell."
        ),
        "output_contract": "Write only the requested JSON object or object array to outputs/result.json.",
    }
    if operation == "lookup_metric":
        semantics.update(
            ticker=str(arguments["ticker"]).upper(),
            quarter=str(arguments["quarter"]).upper(),
            metric=str(arguments["metric"]).lower(),
            formula="Select the unique matching ticker, quarter, and metric row; emit its metric and numeric value.",
        )
    elif operation == "compute_delta":
        semantics.update(
            ticker=str(arguments["ticker"]).upper(),
            metric=str(arguments["metric"]),
            period_from=str(arguments["period_from"]),
            period_to=str(arguments["period_to"]),
            formula="delta_value=value_to-value_from; delta_pct=delta_value/value_from*100.",
        )
    elif operation == "compute_trend":
        tickers = arguments.get("tickers", [arguments.get("ticker", "")])
        semantics.update(
            tickers=[str(item).upper() for item in tickers if str(item).strip()],
            quarters=[str(item) for item in arguments["quarters"]],
            metric=str(arguments["metric"]),
            formula=(
                "Emit one row per requested ticker and quarter in ticker-list then quarter-list order. "
                "Direction is increasing when every adjacent value rises, decreasing when every adjacent value falls, "
                "flat when all are equal, otherwise mixed; repeat that ticker direction on its rows."
            ),
        )
    elif operation == "compare_metric":
        semantics.update(
            tickers=[str(item).upper() for item in arguments["tickers"]],
            quarter=str(arguments["quarter"]),
            metric=str(arguments["metric"]),
            formula="Select ACME and BETA at the requested quarter; gap_value=ACME-BETA.",
        )
    elif operation == "profile_table":
        semantics.update(
            columns=[str(item) for item in arguments["columns"]],
            formula=(
                "For each authorized column, missing percentage is empty-or-whitespace cell count divided by total row count "
                "times 100, rounded to two decimals. Emit percentage_cases_min and percentage_deaths_max."
            ),
        )
    elif operation == "aggregate_and_extreme":
        semantics.update(
            mean_column=str(arguments["mean_column"]),
            max_column=str(arguments["max_column"]),
            formula=(
                "mean_cases is the arithmetic mean of non-missing mean_column values rounded to the nearest integer. "
                "Find the row with maximum non-missing max_column and emit its Country and Year strings."
            ),
        )
    elif operation == "profile_and_mean":
        semantics.update(
            column=str(arguments["column"]),
            formula="Arithmetic mean of non-missing numeric column values, rounded to three decimals.",
        )
    elif operation == "groupby_aggregate":
        semantics.update(
            date_column=str(arguments["groupby"]).removeprefix("month(").removesuffix(")"),
            value_column=str(arguments["value_column"]),
            date_format=(
                "MM/DD/YYYY HH:MM; the month is the leading two-digit MM component, "
                "for example 01/31/2015 23:00 has month 1"
            ),
            formula=(
                "Parse the documented date format, compute mean of non-missing values by month, round to two decimals, "
                "and emit ascending month rows."
            ),
        )
    elif operation == "detect_outliers":
        semantics.update(
            column=str(arguments["column"]),
            method="iqr",
            inclusive_quantile_definition=(
                "Sort the non-missing numeric values. For probability p, use zero-based position (n-1)*p and linearly "
                "interpolate between the floor and ceiling positions; use p=0.25 for Q1 and p=0.75 for Q3."
            ),
            formula=(
                "Use inclusive linear-interpolation Q1 and Q3; outliers are below Q1-1.5*IQR or above Q3+1.5*IQR. "
                "For BARO emit integer outlier count. For deaths emit means before and after removing outliers, rounded to two decimals."
            ),
        )
    elif operation == "materialize_clean_table":
        semantics.update(
            outlier_column=str(arguments["outlier_column"]),
            impute_column=str(arguments["impute_column"]),
            inclusive_quantile_definition=(
                "Sort the non-missing numeric values. For probability p, use zero-based position (n-1)*p and linearly "
                "interpolate between the floor and ceiling positions; use p=0.25 for Q1 and p=0.75 for Q3."
            ),
            formula=(
                "Detect outlier_column values with inclusive Q1/Q3 and 1.5*IQR, replace each outlier with the pre-replacement "
                "non-missing column mean, and mean-impute missing impute_column cells. Emit both post means rounded to two "
                "decimals and the original row count."
            ),
        )
    else:
        raise ValueError(f"formal_operation_semantics_unsupported:{operation}")
    return semantics


def adapt_formal_sample(sample: MinimalBenchmarkSample) -> FormalAdaptiveCase:
    if sample.canonical_task_spec is None:
        raise ValueError(f"formal_sample_missing_canonical_task_spec:{sample.task_id}")
    spec = sample.canonical_task_spec
    operation = _operation_for_spec(spec)
    if spec.task_family == "financial_report_analysis":
        source_rows = _financial_source_rows(spec)
    elif spec.task_family == "cross_period_financial_analysis":
        source_rows = _cross_period_source_rows()
    else:
        source_rows = _csv_source_rows(spec)
    output_schema, shape = _output_schema(operation, spec.arguments)
    report_capabilities = ("compose_risk_memo_v1", "compose_claim_set_v2")
    return FormalAdaptiveCase(
        sample=sample,
        operation=operation,
        capability_id=_capability_id(operation),
        output_contract_version=_output_contract(operation),
        source_rows=source_rows,
        source_schema=_source_schema(source_rows),
        output_schema=output_schema,
        expected_output_shape=shape,
        operation_semantics=_operation_semantics(operation, spec.arguments),
        report_capability_ids=report_capabilities,
    )


def _mean(values: list[float]) -> float:
    if not values:
        raise ValueError("formal_numeric_series_empty")
    return sum(values) / len(values)


def _numeric_series(rows: tuple[dict[str, object], ...], field: str) -> list[float]:
    return [value for row in rows if (value := _parse_number(row.get(field))) is not None]


def _inclusive_quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) < 2:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    left = floor(position)
    fraction = position - left
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * fraction


def _iqr_mask(values: list[float]) -> list[bool]:
    if len(values) < 2:
        return [False] * len(values)
    q1 = _inclusive_quantile(values, 0.25)
    q3 = _inclusive_quantile(values, 0.75)
    spread = q3 - q1
    low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
    return [value < low or value > high for value in values]


def _trend_direction(values: list[float]) -> str:
    deltas = [right - left for left, right in zip(values, values[1:], strict=False)]
    if deltas and all(delta > 0 for delta in deltas):
        return "increasing"
    if deltas and all(delta < 0 for delta in deltas):
        return "decreasing"
    if not deltas or all(isclose(delta, 0.0, abs_tol=1e-12) for delta in deltas):
        return "flat"
    return "mixed"


def _date_month(value: object) -> int:
    token = str(value).strip().split()[0]
    parts = re.split(r"[-/]", token)
    if len(parts) < 2:
        raise ValueError(f"formal_date_month_invalid:{value}")
    return int(parts[1]) if len(parts[0]) == 4 else int(parts[0])


def recompute_formal_rows(
    operation: str,
    arguments: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    if operation == "lookup_metric":
        ticker = str(arguments["ticker"]).upper()
        quarter = str(arguments["quarter"]).upper()
        metric = str(arguments["metric"]).lower()
        selected = [
            row
            for row in rows
            if str(row.get("ticker", "")).upper() == ticker
            and str(row.get("quarter", "")).upper() == quarter
            and str(row.get("metric", "")).lower() == metric
        ]
        if len(selected) != 1:
            raise ValueError(f"formal_lookup_match_count:{len(selected)}")
        return ({"metric_name": metric, "metric_value": _required_number(selected[0], "value")},)
    if operation == "compute_delta":
        ticker = str(arguments["ticker"]).upper()
        period_from, period_to = str(arguments["period_from"]), str(arguments["period_to"])
        selected = {
            str(row.get("quarter")): _required_number(row, "value")
            for row in rows
            if str(row.get("ticker", "")).upper() == ticker
        }
        before, after = selected[period_from], selected[period_to]
        if before == 0:
            raise ValueError("formal_delta_zero_baseline")
        delta = after - before
        return ({
            "ticker": ticker,
            "period_from": period_from,
            "period_to": period_to,
            "value_from": before,
            "value_to": after,
            "delta_value": delta,
            "delta_pct": delta / before * 100.0,
        },)
    if operation == "compute_trend":
        tickers_raw = arguments.get("tickers", [arguments.get("ticker", "")])
        tickers = [str(item).upper() for item in tickers_raw if str(item).strip()]
        quarters = [str(item) for item in arguments["quarters"]]
        output: list[dict[str, object]] = []
        for ticker in tickers:
            values_by_quarter = {
                str(row.get("quarter")): _required_number(row, "value")
                for row in rows
                if str(row.get("ticker", "")).upper() == ticker
            }
            values = [values_by_quarter[quarter] for quarter in quarters]
            direction = _trend_direction(values)
            output.extend(
                {
                    "ticker": ticker,
                    "quarter": quarter,
                    "metric_value": value,
                    "trend_direction": direction,
                }
                for quarter, value in zip(quarters, values, strict=True)
            )
        return tuple(output)
    if operation == "compare_metric":
        quarter = str(arguments["quarter"])
        selected = {
            str(row.get("ticker", "")).upper(): _required_number(row, "value")
            for row in rows
            if str(row.get("quarter")) == quarter
        }
        acme, beta = selected["ACME"], selected["BETA"]
        return ({
            "quarter": quarter,
            "acme_revenue_value": acme,
            "beta_revenue_value": beta,
            "gap_value": acme - beta,
        },)
    if operation == "profile_table":
        columns = [str(item) for item in arguments["columns"]]
        percentages = [
            round(sum(1 for row in rows if not str(row.get(column, "")).strip()) / len(rows) * 100.0, 2)
            for column in columns
        ]
        return ({
            "percentage_cases_min": percentages[0],
            "percentage_deaths_max": percentages[1],
        },)
    if operation == "aggregate_and_extreme":
        mean_column = str(arguments["mean_column"])
        max_column = str(arguments["max_column"])
        candidates = [row for row in rows if _parse_number(row.get(max_column)) is not None]
        extreme = max(candidates, key=lambda row: _required_number(row, max_column))
        return ({
            "mean_cases": round(_mean(_numeric_series(rows, mean_column))),
            "max_deaths_country": str(extreme.get("Country", "")).strip(),
            "max_deaths_year": str(extreme.get("Year", "")).strip(),
        },)
    if operation == "profile_and_mean":
        return ({
            "mean_windspeed": round(_mean(_numeric_series(rows, str(arguments["column"]))), 3)
        },)
    if operation == "groupby_aggregate":
        date_column = str(arguments["groupby"]).removeprefix("month(").removesuffix(")")
        value_column = str(arguments["value_column"])
        grouped: dict[int, list[float]] = {}
        for row in rows:
            value = _parse_number(row.get(value_column))
            if value is None:
                continue
            grouped.setdefault(_date_month(row.get(date_column)), []).append(value)
        return tuple(
            {"month": month, "monthly_avg_windspeed": round(_mean(values), 2)}
            for month, values in sorted(grouped.items())
        )
    if operation == "detect_outliers":
        column = str(arguments["column"])
        values = _numeric_series(rows, column)
        mask = _iqr_mask(values)
        kept = [value for value, is_outlier in zip(values, mask, strict=True) if not is_outlier]
        if column == "BARO":
            return ({"baro_outlier_count": sum(mask)},)
        return ({
            "mean_no_of_deaths_with_outliers": round(_mean(values), 2),
            "mean_no_of_deaths_without_outliers": round(_mean(kept), 2),
        },)
    if operation == "materialize_clean_table":
        wind_field = str(arguments["outlier_column"])
        temperature_field = str(arguments["impute_column"])
        winds = _numeric_series(rows, wind_field)
        wind_mean = _mean(winds)
        mask = _iqr_mask(winds)
        cleaned_winds = [wind_mean if flag else value for value, flag in zip(winds, mask, strict=True)]
        temperatures = _numeric_series(rows, temperature_field)
        temperature_mean = _mean(temperatures)
        return ({
            "mean_wind_post": round(_mean(cleaned_winds), 2),
            "mean_atmos_temp_post": round(temperature_mean, 2),
            "cleaned_row_count": len(rows),
        },)
    raise ValueError(f"formal_recompute_unsupported:{operation}")


def _rows_equal(
    actual: tuple[dict[str, object], ...],
    expected: tuple[dict[str, object], ...],
) -> bool:
    if len(actual) != len(expected):
        return False
    for left, right in zip(actual, expected, strict=True):
        if set(left) != set(right):
            return False
        for key, expected_value in right.items():
            actual_value = left[key]
            if (
                isinstance(actual_value, (int, float))
                and not isinstance(actual_value, bool)
                and isinstance(expected_value, (int, float))
                and not isinstance(expected_value, bool)
            ):
                if not isclose(float(actual_value), float(expected_value), rel_tol=1e-9, abs_tol=1e-9):
                    return False
            elif actual_value != expected_value:
                return False
    return True


def build_formal_quality_validator(
    case: FormalAdaptiveCase,
) -> Callable[[CapabilityQualityContext], CapabilityQualityReport]:
    def validate(context: CapabilityQualityContext) -> CapabilityQualityReport:
        errors: list[str] = []
        if not context.input_artifact_hashes:
            errors.append("missing_input_artifact_hash")
        if not context.provenance_item_ids:
            errors.append("missing_provenance")
        if len(context.input_rows) != 1 or not context.input_rows[0]:
            errors.append("formal_input_rows_missing")
            expected: tuple[dict[str, object], ...] = ()
        else:
            try:
                expected = recompute_formal_rows(
                    case.operation,
                    case.spec.arguments,
                    context.input_rows[0],
                )
            except (KeyError, TypeError, ValueError) as exc:
                expected = ()
                errors.append(f"formal_recomputation_failed:{type(exc).__name__}")
        if not context.output_rows:
            errors.append("empty_output")
        if any(set(row) != set(case.output_schema) for row in context.output_rows):
            errors.append("required_fields_missing")
        if expected and not _rows_equal(context.output_rows, expected):
            errors.append("formal_recomputation_mismatch")
        minimum = context.completion_criteria.get("min_rows")
        if isinstance(minimum, int) and len(context.output_rows) < minimum:
            errors.append("completion_min_rows_failed")
        errors = sorted(set(errors))
        return CapabilityQualityReport(
            capability_id=context.capability_id,
            validator_id=context.validator_id,
            input_artifact_hashes=context.input_artifact_hashes,
            output_artifact_hash=context.output_artifact_hash,
            schema_passed=not any(error in {"empty_output", "required_fields_missing"} for error in errors),
            recomputation_passed=not any(error.startswith("formal_recomputation") for error in errors),
            provenance_passed=not any(error.startswith("missing_") for error in errors),
            completion_criteria_passed="completion_min_rows_failed" not in errors,
            verified=not errors,
            error_codes=tuple(errors),
        )

    return validate


def flatten_formal_output(case: FormalAdaptiveCase, rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    if case.operation == "lookup_metric":
        row = rows[0]
        return {
            "metric_name": row["metric_name"],
            "metric_value": row["metric_value"],
            "revenue_value": row["metric_value"],
        }
    if case.operation == "compute_trend":
        directions = {
            str(row["ticker"]).lower(): row["trend_direction"]
            for row in rows
        }
        if len(directions) == 1:
            return {"trend_direction": next(iter(directions.values()))}
        return {
            f"{ticker}_trend_direction": direction
            for ticker, direction in sorted(directions.items())
        }
    if case.operation == "groupby_aggregate":
        return {
            f"monthly_avg_windspeed.month_{int(row['month'])}": row["monthly_avg_windspeed"]
            for row in rows
        }
    return dict(rows[0])


def expected_facts_report(case: FormalAdaptiveCase, rows: tuple[dict[str, object], ...]) -> dict[str, object]:
    actual = flatten_formal_output(case, rows)
    expected = dict(case.sample.expected_facts or {})
    checks: dict[str, bool] = {}
    for key, expected_value in expected.items():
        if key == "selected_doc_hashes":
            # This is a retrieval-provenance check, not a CodeAct output
            # field.  The live runner verifies it against EvidencePack source
            # hashes after retrieval.
            continue
        if key not in actual:
            checks[key] = False
            continue
        observed = actual[key]
        observed_number = _parse_number(observed)
        expected_number = _parse_number(expected_value)
        if observed_number is not None and expected_number is not None:
            checks[key] = isclose(observed_number, expected_number, rel_tol=1e-9, abs_tol=0.011)
        else:
            checks[key] = str(observed) == str(expected_value)
    return {
        "passed": bool(checks) and all(checks.values()),
        "checks": dict(sorted(checks.items())),
        "actual": dict(sorted(actual.items())),
        "expected": dict(sorted(expected.items())),
        "deferred_provenance_keys": [
            key for key in expected if key == "selected_doc_hashes"
        ],
        "contract_hash": sha256_digest({"actual": actual, "expected": expected}),
    }
