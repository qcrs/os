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
    document = OfflineFinancialReportCorpus().resolve(ticker=ticker, quarter=quarter)
    rows: list[dict[str, object]] = []
    for row in document.table_rows:
        value = _parse_number(row.value)
        if value is None:
            raise ValueError(
                f"formal_financial_metric_not_numeric:{ticker}:{quarter}:{row.metric_name}"
            )
        rows.append({
            "ticker": ticker,
            "quarter": quarter,
            "metric": row.metric_name.strip().lower().split(":", 1)[0],
            "value": value,
            "source_doc_hash": row.source_doc_hash,
            "table_id": row.table_id,
            "sheet_name": row.sheet_name,
            "row_idx": row.row_idx,
            "col_idx": row.col_idx,
            "extractor_version": row.extractor_version,
            "rendered_text": row.rendered_text,
        })
    if len(rows) < 2:
        raise ValueError(
            f"formal_financial_full_table_required:{ticker}:{quarter}:{len(rows)}"
        )
    return tuple(rows)


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


def _markdown_section_rows(path: Path) -> tuple[dict[str, object], ...]:
    """Return every markdown section intact with stable, source-local locators."""

    text = path.read_text(encoding="utf-8")
    heading_matches = tuple(re.finditer(r"(?m)^##\s+(.+?)\s*$", text))
    rows: list[dict[str, object]] = []
    for index, match in enumerate(heading_matches):
        body_start = match.end()
        body_end = (
            heading_matches[index + 1].start()
            if index + 1 < len(heading_matches)
            else len(text)
        )
        body = text[body_start:body_end].strip()
        rows.append({
            "row_kind": "narrative_section",
            "section": match.group(1).strip(),
            "text": body,
            "locator": f"{path.name}#section-{index + 1}",
        })
    if not rows:
        raise ValueError(f"formal_markdown_sections_missing:{path.name}")
    return tuple(rows)


def _markdown_table_rows(path: Path) -> tuple[dict[str, object], ...]:
    """Parse all ordinary markdown tables without selecting task-relevant rows."""

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    rows: list[dict[str, object]] = []
    table_index = 0
    index = 0
    while index + 2 < len(lines):
        header_line = lines[index].strip()
        divider_line = lines[index + 1].strip()
        if not header_line.startswith("|") or not divider_line.startswith("|"):
            index += 1
            continue
        headers = [cell.strip() for cell in header_line.strip("|").split("|")]
        divider = [cell.strip() for cell in divider_line.strip("|").split("|")]
        if (
            len(headers) < 2
            or len(headers) != len(divider)
            or any(not cell or set(cell) - {"-", ":"} for cell in divider)
        ):
            index += 1
            continue
        table_index += 1
        data_index = 0
        index += 2
        while index < len(lines) and lines[index].strip().startswith("|"):
            cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
            if len(cells) != len(headers):
                break
            data_index += 1
            row: dict[str, object] = {
                "row_kind": "table_row",
                "locator": f"{path.name}#table-{table_index}-row-{data_index}",
            }
            for header, cell in zip(headers, cells, strict=True):
                parsed = _parse_number(cell)
                row[header] = parsed if parsed is not None and re.fullmatch(
                    r"[-+]?\d+(?:\.\d+)?", cell.replace(",", "")
                ) else cell
            rows.append(row)
            index += 1
    return tuple(rows)


def _holdout_source_rows(spec: CanonicalTaskSpec) -> tuple[dict[str, object], ...]:
    source_path = _resolve_repo_file(str(spec.arguments.get("source_path", "")))
    source_kind = str(spec.arguments.get("source_kind", "")).strip()
    if source_kind == "narrative_markdown":
        rows = _markdown_section_rows(source_path)
    elif source_kind == "csv_table":
        with source_path.open("r", encoding="utf-8", newline="") as handle:
            rows = tuple(dict(row) for row in csv.DictReader(handle))
        if not rows:
            raise ValueError(f"formal_holdout_csv_empty:{source_path.name}")
    elif source_kind == "mixed_markdown":
        rows = (*_markdown_section_rows(source_path), *_markdown_table_rows(source_path))
        if not any(row.get("row_kind") == "table_row" for row in rows):
            raise ValueError(f"formal_holdout_mixed_table_missing:{source_path.name}")
    else:
        raise ValueError(f"formal_holdout_source_kind_unsupported:{source_kind}")

    output_schema = spec.arguments.get("output_schema", {})
    if not isinstance(output_schema, dict):
        raise ValueError(f"formal_holdout_output_schema_invalid:{source_path.name}")
    normalized: list[dict[str, object]] = []
    for raw_row in rows:
        row = dict(raw_row)
        for raw_field, raw_kind in output_schema.items():
            field = str(raw_field)
            kind = str(raw_kind)
            if field not in row or kind not in {"integer", "number"}:
                continue
            parsed = _parse_number(row[field])
            if parsed is None:
                raise ValueError(f"formal_holdout_numeric_value_invalid:{field}")
            if kind == "integer":
                if not parsed.is_integer():
                    raise ValueError(f"formal_holdout_integer_value_invalid:{field}")
                row[field] = int(parsed)
            else:
                row[field] = float(parsed)
        normalized.append(row)
    return tuple(normalized)


def _operation_for_spec(spec: CanonicalTaskSpec) -> str:
    if spec.task_family in {
        "continuous_long_doc_table_analysis",
        "continuous_csv_table_analysis",
    } and spec.intent_op in {
        "extract_narrative_facts",
        "synthesize_narrative_risk",
        "lookup_table_record",
        "lookup_table_with_qualifier",
    }:
        return spec.intent_op
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
    if operation in {
        "extract_narrative_facts",
        "synthesize_narrative_risk",
        "lookup_table_record",
        "lookup_table_with_qualifier",
    }:
        raw_schema = arguments.get("output_schema")
        if not isinstance(raw_schema, dict) or not raw_schema:
            raise ValueError(f"formal_output_schema_missing:{operation}")
        schema = {str(key): str(value) for key, value in raw_schema.items()}
        if any(value not in {"string", "number", "integer", "boolean"} for value in schema.values()):
            raise ValueError(f"formal_output_schema_type_unsupported:{operation}")
        return schema, "object"
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


def _labeled_fact_semantics(arguments: dict[str, object]) -> dict[str, object]:
    return {
        "fact_selectors": arguments.get("fact_selectors", []),
        "labeled_fact_algorithm": {
            "row_selection": (
                "For each selector, select exactly one row whose row_kind is narrative_section "
                "and whose section equals selector.section."
            ),
            "sentence_selection": (
                "Within that row's text, find the sentence that starts at the beginning of the text "
                "or immediately after a . ! or ? terminator plus whitespace, then matches "
                "selector.label case-insensitively, followed by was or is."
            ),
            "value_extraction": (
                "Set selector.output_field to only the minimal phrase after was/is and before the "
                "next . ! or ? sentence terminator, trimmed of surrounding whitespace. Do not split "
                "the whole section on was/is and do not copy the complete sentence or section."
            ),
            "locator_output": (
                "When selector.locator_field is present, set it to selector.section exactly. Do not "
                "emit the row locator, source path, TextSpanLocator, section id, or section body."
            ),
            "python_regex_template": (
                "label = str(selector['label']); pattern = rf'(?i)(?:^|[.!?]\\s+)\\s*"
                "{re.escape(label)}\\s+(?:was|is)\\s+(.+?)(?=[.!?](?:\\s|$)|$)'; "
                "match = re.search(pattern, text); use match.group(1).strip(). This pattern intentionally "
                "uses a consuming non-capturing prefix; do not replace it with lookbehind."
            ),
        },
    }


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
    if operation in {"extract_narrative_facts", "synthesize_narrative_risk"}:
        semantics.update(
            **_labeled_fact_semantics(arguments),
            formula=(
                "Apply labeled_fact_algorithm literally to every public selector and emit exactly the declared "
                "fields. Do not infer a value from benchmark gold."
            ),
        )
    elif operation == "lookup_table_record":
        semantics.update(
            filters=arguments.get("filters", {}),
            value_fields=arguments.get("value_fields", []),
            formula=(
                "Select the unique authorized table row matching every public filter and emit only the declared "
                "output fields, preserving strings and parsing numeric cells as numbers."
            ),
        )
    elif operation == "lookup_table_with_qualifier":
        semantics.update(
            filters=arguments.get("filters", {}),
            value_fields=arguments.get("value_fields", []),
            **_labeled_fact_semantics(arguments),
            formula=(
                "Select the unique authorized table row matching every public filter, then extract each requested "
                "qualifier by applying labeled_fact_algorithm literally. Merge only the declared fields into one "
                "output object."
            ),
        )
    elif operation == "lookup_metric":
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
            numeric_cell_encoding=(
                "The mean and maximum columns may encode a point estimate as a leading numeric token followed by "
                "an optional [lower-upper] range. Remove commas, keep only the text before the first [, trim it, "
                "and parse that complete leading token as the value. Never delete punctuation from the full cell or "
                "concatenate digits from the bracketed range into the point estimate."
            ),
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
            outlier_column_missing_policy=(
                "Preserve missing outlier_column cells as missing. Exclude them from quartiles, the pre-replacement "
                "mean, and the post-replacement mean; do not impute them."
            ),
            impute_column_missing_policy=(
                "Mean-impute only missing impute_column cells using that column's non-missing mean."
            ),
            inclusive_quantile_definition=(
                "Sort the non-missing numeric values. For probability p, use zero-based position (n-1)*p and linearly "
                "interpolate between the floor and ceiling positions; use p=0.25 for Q1 and p=0.75 for Q3."
            ),
            formula=(
                "Detect outlier_column values with inclusive Q1/Q3 and 1.5*IQR, replace each outlier with the pre-replacement "
                "non-missing column mean, preserve but exclude missing outlier_column cells from its statistics, and "
                "mean-impute missing impute_column cells. Emit both post means rounded to two decimals and the original "
                "row count."
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
    if operation in {
        "extract_narrative_facts",
        "synthesize_narrative_risk",
        "lookup_table_record",
        "lookup_table_with_qualifier",
    }:
        source_rows = _holdout_source_rows(spec)
    elif spec.task_family == "financial_report_analysis":
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


def _extract_labeled_fact(
    rows: tuple[dict[str, object], ...],
    selector: dict[str, object],
) -> tuple[str, str]:
    section = str(selector.get("section", "")).strip()
    label = str(selector.get("label", "")).strip()
    candidates = [
        row
        for row in rows
        if str(row.get("row_kind", "")) == "narrative_section"
        and str(row.get("section", "")) == section
    ]
    if len(candidates) != 1 or not label:
        raise ValueError(f"formal_narrative_selector_invalid:{section}:{label}")
    text = str(candidates[0].get("text", ""))
    match = re.search(
        rf"(?i)(?:^|[.!?]\s+)\s*{re.escape(label)}\s+(?:was|is)\s+(.+?)(?=[.!?](?:\s|$)|$)",
        text,
    )
    if match is None:
        raise ValueError(f"formal_narrative_fact_missing:{section}:{label}")
    return match.group(1).strip(), section


def _recompute_public_fact_fields(
    arguments: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    selectors = arguments.get("fact_selectors", [])
    if not isinstance(selectors, list) or not selectors:
        raise ValueError("formal_fact_selectors_missing")
    output: dict[str, object] = {}
    for raw_selector in selectors:
        if not isinstance(raw_selector, dict):
            raise ValueError("formal_fact_selector_invalid")
        field = str(raw_selector.get("output_field", "")).strip()
        locator_field = str(raw_selector.get("locator_field", "")).strip()
        if not field:
            raise ValueError("formal_fact_output_field_missing")
        value, section = _extract_labeled_fact(rows, raw_selector)
        output[field] = value
        if locator_field:
            output[locator_field] = section
    return output


def _select_public_table_row(
    arguments: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> dict[str, object]:
    filters = arguments.get("filters", {})
    if not isinstance(filters, dict) or not filters:
        raise ValueError("formal_table_filters_missing")
    selected = [
        row
        for row in rows
        if str(row.get("row_kind", "table_row")) == "table_row"
        and all(str(row.get(str(key), "")) == str(value) for key, value in filters.items())
    ]
    if len(selected) != 1:
        raise ValueError(f"formal_table_match_count:{len(selected)}")
    value_fields = arguments.get("value_fields", [])
    if not isinstance(value_fields, list) or not value_fields:
        raise ValueError("formal_table_value_fields_missing")
    output_schema = arguments.get("output_schema", {})
    if not isinstance(output_schema, dict):
        raise ValueError("formal_table_output_schema_missing")
    output: dict[str, object] = {}
    for raw_field in value_fields:
        field = str(raw_field)
        value = selected[0][field]
        if output_schema.get(field) in {"number", "integer"}:
            parsed = _parse_number(value)
            if parsed is None:
                raise ValueError(f"formal_table_numeric_value_invalid:{field}")
            value = int(parsed) if output_schema.get(field) == "integer" else parsed
        output[field] = value
    return output


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
    if operation in {"extract_narrative_facts", "synthesize_narrative_risk"}:
        return (_recompute_public_fact_fields(arguments, rows),)
    if operation == "lookup_table_record":
        return (_select_public_table_row(arguments, rows),)
    if operation == "lookup_table_with_qualifier":
        return ({
            **_select_public_table_row(arguments, rows),
            **_recompute_public_fact_fields(arguments, rows),
        },)
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
    # Deliberately retain only the public execution contract.  Expected facts
    # remain outside Runtime and are evaluated by the benchmark gate later.
    operation = case.operation
    arguments = dict(case.spec.arguments)
    formal_output_fields = frozenset(case.output_schema)

    def validate(context: CapabilityQualityContext) -> CapabilityQualityReport:
        errors: list[str] = []
        if not context.input_artifact_hashes:
            errors.append("missing_input_artifact_hash")
        if not context.provenance_item_ids:
            errors.append("missing_provenance")
        if not context.output_rows:
            errors.append("empty_output")
        required_fields = frozenset(context.required_fields)
        if any(required_fields and set(row) != required_fields for row in context.output_rows):
            errors.append("required_fields_missing")

        # Intermediate model-selected stages use their declared schema and the
        # generic safety checks above.  The final formal result is independently
        # recomputed from each authorized input artifact that can satisfy the
        # public operation contract.  No benchmark expected value is consulted.
        recomputation_evaluated = required_fields == formal_output_fields
        if recomputation_evaluated:
            candidates: list[tuple[dict[str, object], ...]] = []
            failures: list[Exception] = []
            for rows in context.input_rows:
                if not rows:
                    continue
                try:
                    candidates.append(recompute_formal_rows(operation, arguments, rows))
                except (KeyError, TypeError, ValueError) as exc:
                    failures.append(exc)
            if not candidates:
                if not context.input_rows or not any(context.input_rows):
                    errors.append("formal_input_rows_missing")
                else:
                    failure_type = type(failures[-1]).__name__ if failures else "ValueError"
                    errors.append(f"formal_recomputation_failed:{failure_type}")
            elif not any(_rows_equal(context.output_rows, expected) for expected in candidates):
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
            recomputation_passed=(
                recomputation_evaluated
                and not any(error.startswith("formal_recomputation") for error in errors)
            ),
            provenance_passed=not any(error.startswith("missing_") for error in errors),
            completion_criteria_passed="completion_min_rows_failed" not in errors,
            verified=not errors,
            recomputation_evaluated=recomputation_evaluated,
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
