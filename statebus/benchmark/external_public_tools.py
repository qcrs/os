from __future__ import annotations

import csv
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExternalPublicToolResult:
    execution_kind: str
    outputs: dict[str, object]
    source_paths: tuple[str, ...]


def supports_public_task(*, task_family: str, intent_op: str) -> bool:
    if task_family == "cross_period_financial_analysis":
        return intent_op in {"compare_metric", "compute_delta", "compute_trend"}
    if task_family == "continuous_csv_table_analysis":
        return intent_op in {
            "profile_table",
            "aggregate_and_extreme",
            "detect_outliers",
            "materialize_clean_table",
            "profile_and_mean",
            "groupby_aggregate",
        }
    return False


def execute_public_task(
    *,
    project_root: Path,
    task_family: str,
    intent_op: str,
    arguments: dict[str, object],
) -> ExternalPublicToolResult:
    if task_family == "cross_period_financial_analysis":
        return _execute_cross_period(
            project_root=project_root,
            intent_op=intent_op,
            arguments=arguments,
        )
    if task_family == "continuous_csv_table_analysis":
        return _execute_csv_task(
            project_root=project_root,
            intent_op=intent_op,
            arguments=arguments,
        )
    raise ValueError(f"unsupported external public task family: {task_family}")


def _resolve_public_path(project_root: Path, raw_path: str) -> Path:
    root = project_root.resolve()
    path = Path(raw_path)
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"public task path escapes project root: {raw_path}")
    if not resolved.is_file():
        raise FileNotFoundError(f"public task file is unavailable: {raw_path}")
    return resolved


def _parse_number(value: object) -> float | None:
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    match = re.match(r"^([-+]?\d+(?:\.\d+)?)", text)
    return float(match.group(1)) if match is not None else None


def _format_number(value: float, *, digits: int | None = None) -> str:
    if digits is None:
        if float(value).is_integer():
            return str(int(round(value)))
        return str(value)
    return f"{value:.{digits}f}"


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _numeric_series(rows: list[dict[str, str]], column: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _parse_number(row.get(column, ""))
        if value is not None:
            values.append(value)
    return values


def _iqr_outlier_mask(values: list[float]) -> list[bool]:
    if len(values) < 2:
        return [False for _ in values]
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return [value < low or value > high for value in values]


def _monthly_means(
    rows: list[dict[str, str]],
    *,
    date_column: str,
    value_column: str,
) -> dict[str, float]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        value = _parse_number(row.get(value_column, ""))
        if value is None:
            continue
        date_token = str(row.get(date_column, "")).strip().split()[0]
        parts = re.split(r"[-/]", date_token)
        if len(parts) < 2:
            continue
        month = int(parts[1]) if len(parts[0]) == 4 else int(parts[0])
        grouped[month].append(value)
    return {
        f"month_{month}": round(_mean(values), 2)
        for month, values in sorted(grouped.items())
    }


def _read_csv(path: Path) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, skipinitialspace=True)
        rows = [dict(row) for row in reader]
        return rows, tuple(reader.fieldnames or ())


def _execute_csv_task(
    *,
    project_root: Path,
    intent_op: str,
    arguments: dict[str, object],
) -> ExternalPublicToolResult:
    csv_path = _resolve_public_path(project_root, str(arguments.get("csv_path", "")))
    rows, fieldnames = _read_csv(csv_path)
    outputs: dict[str, object]

    if intent_op == "profile_table":
        columns = [str(item) for item in arguments.get("columns", [])]
        outputs = {
            f"percentage_{column.replace('No. of ', '').replace(' ', '_').lower()}": round(
                sum(1 for row in rows if not str(row.get(column, "")).strip())
                / max(len(rows), 1)
                * 100.0,
                2,
            )
            for column in columns
        }
        outputs["row_count"] = len(rows)
        outputs["fieldnames"] = list(fieldnames)
    elif intent_op == "aggregate_and_extreme":
        mean_column = str(arguments["mean_column"])
        max_column = str(arguments["max_column"])
        values = _numeric_series(rows, mean_column)
        candidate_rows = [
            row for row in rows if _parse_number(row.get(max_column, "")) is not None
        ]
        max_row = max(
            candidate_rows,
            key=lambda row: _parse_number(row.get(max_column, "")) or 0.0,
        )
        outputs = {
            "mean_cases": str(int(round(_mean(values)))),
            "max_deaths_country": str(max_row.get("Country", "")).strip(),
            "max_deaths_year": str(max_row.get("Year", "")).strip(),
        }
    elif intent_op == "profile_and_mean":
        values = _numeric_series(rows, str(arguments["column"]))
        outputs = {"mean_windspeed": _format_number(round(_mean(values), 3), digits=3)}
    elif intent_op == "groupby_aggregate":
        date_column = str(arguments["groupby"]).replace("month(", "").replace(")", "")
        outputs = {
            "monthly_avg_windspeed": _monthly_means(
                rows,
                date_column=date_column,
                value_column=str(arguments["value_column"]),
            )
        }
    elif intent_op == "detect_outliers":
        column = str(arguments["column"])
        method = str(arguments.get("method", "iqr")).strip().lower()
        if method != "iqr":
            raise ValueError(f"unsupported external outlier method: {method}")
        values = _numeric_series(rows, column)
        mask = _iqr_outlier_mask(values)
        kept = [value for value, is_outlier in zip(values, mask, strict=True) if not is_outlier]
        outlier_count = sum(1 for is_outlier in mask if is_outlier)
        outputs = {"outlier_count": str(outlier_count)}
        if column == "BARO":
            outputs["baro_outlier_count"] = str(outlier_count)
        if column == "No. of deaths_max":
            outputs.update(
                {
                    "mean_no_of_deaths_with_outliers": _format_number(
                        round(_mean(values), 2), digits=2
                    ),
                    "mean_no_of_deaths_without_outliers": _format_number(
                        round(_mean(kept), 2), digits=2
                    ),
                }
            )
    elif intent_op == "materialize_clean_table":
        outlier_column = str(arguments.get("outlier_column", "WINDSPEED"))
        impute_column = str(arguments.get("impute_column", "AT"))
        wind_values = _numeric_series(rows, outlier_column)
        wind_mean = _mean(wind_values)
        mask = _iqr_outlier_mask(wind_values)
        replaced = [
            wind_mean if is_outlier else value
            for value, is_outlier in zip(wind_values, mask, strict=True)
        ]
        temperature_values = _numeric_series(rows, impute_column)
        outputs = {
            "mean_wind_post": _format_number(round(_mean(replaced), 2), digits=2),
            "mean_atmos_temp_post": _format_number(
                round(_mean(temperature_values), 2), digits=2
            ),
            "cleaned_row_count": len(rows),
        }
    else:
        raise ValueError(f"unsupported external CSV intent: {intent_op}")

    return ExternalPublicToolResult(
        execution_kind=f"public_csv_{intent_op}",
        outputs=outputs,
        source_paths=(str(csv_path),),
    )


def _parse_cross_period_tables(document_text: str) -> dict[str, dict[str, float]]:
    series: dict[str, dict[str, float]] = {}
    current_ticker = ""
    for line in document_text.splitlines():
        stripped = line.strip()
        heading = re.match(r"^##\s+([A-Za-z0-9_-]+)\s+Revenue Table$", stripped)
        if heading is not None:
            current_ticker = heading.group(1).upper()
            series[current_ticker] = {}
            continue
        if not current_ticker or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"quarter", "---"} or set(cells[0]) == {"-"}:
            continue
        value = _parse_number(cells[1])
        if value is not None:
            series[current_ticker][cells[0]] = value
    return series


def _trend_direction(values: list[float]) -> str:
    if len(values) < 2:
        return "flat"
    if all(right > left for left, right in zip(values, values[1:])):
        return "increasing"
    if all(right < left for left, right in zip(values, values[1:])):
        return "decreasing"
    return "mixed"


def _execute_cross_period(
    *,
    project_root: Path,
    intent_op: str,
    arguments: dict[str, object],
) -> ExternalPublicToolResult:
    raw_path = str(arguments.get("document_path", "")).strip() or (
        "statebus/benchmark/samples/continuous_task_families/"
        "cross_period_financial/cross_period_financial_report.md"
    )
    document_path = _resolve_public_path(project_root, raw_path)
    tables = _parse_cross_period_tables(document_path.read_text(encoding="utf-8"))
    outputs: dict[str, object]

    if intent_op == "compute_delta":
        ticker = str(arguments["ticker"]).strip().upper()
        period_from = str(arguments["period_from"]).strip()
        period_to = str(arguments["period_to"]).strip()
        start = tables[ticker][period_from]
        end = tables[ticker][period_to]
        delta = end - start
        outputs = {
            "delta_value": _format_number(delta),
            "delta_pct": _format_number(round(delta / start * 100.0, 1), digits=1),
        }
    elif intent_op == "compute_trend":
        quarters = [str(item).strip() for item in arguments.get("quarters", [])]
        tickers = [str(item).strip().upper() for item in arguments.get("tickers", [])]
        if tickers:
            left = [tables[tickers[0]][quarter] for quarter in quarters]
            right = [tables[tickers[1]][quarter] for quarter in quarters]
            outputs = {
                "acme_trend_values": ",".join(_format_number(value) for value in left),
                "beta_trend_values": ",".join(_format_number(value) for value in right),
                "acme_trend_direction": _trend_direction(left),
                "beta_trend_direction": _trend_direction(right),
            }
        else:
            ticker = str(arguments["ticker"]).strip().upper()
            values = [tables[ticker][quarter] for quarter in quarters]
            outputs = {
                "trend_values": ",".join(_format_number(value) for value in values),
                "trend_direction": _trend_direction(values),
            }
    elif intent_op == "compare_metric":
        tickers = [str(item).strip().upper() for item in arguments.get("tickers", [])]
        quarter = str(arguments["quarter"]).strip()
        if len(tickers) < 2:
            raise ValueError("cross-period compare_metric requires two tickers")
        left = tables[tickers[0]][quarter]
        right = tables[tickers[1]][quarter]
        outputs = {
            "acme_revenue_value": _format_number(left),
            "beta_revenue_value": _format_number(right),
            "gap_value": _format_number(left - right),
        }
    else:
        raise ValueError(f"unsupported external cross-period intent: {intent_op}")

    return ExternalPublicToolResult(
        execution_kind=f"public_markdown_table_{intent_op}",
        outputs=outputs,
        source_paths=(str(document_path),),
    )
