from __future__ import annotations

from dataclasses import dataclass
import csv
from math import ceil, floor, isclose, isfinite
from pathlib import Path
import re
from typing import Callable

from statebus.benchmark.minimal_runner import MinimalBenchmarkSample
from statebus.contracts import CapabilityQualityReport, CanonicalTaskSpec
from statebus.runtime.capability_validators import CapabilityQualityContext
from statebus.utils import sha256_digest


_CROSS_PERIOD_DOCUMENT = Path(
    "statebus/benchmark/samples/continuous_task_families/"
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
    from statebus.retrieval.corpus import OfflineFinancialReportCorpus

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
        "finance_monthly_review",
        "service_weekly_review",
        "finance_v2_monthly_review",
        "service_v2_weekly_review",
        "finance_quarterly_review",
        "finance_period_delta",
        "finance_budget_review",
        "finance_budget_status_review",
        "finance_budget_delta_review",
        "finance_half_year_review",
        "service_sequence_review",
        "service_error_delta",
        "service_p95_review",
        "service_multiweek_review",
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
    if operation in {"finance_monthly_review", "finance_v2_monthly_review"}:
        return {
            "unit_id": "string", "net_revenue_cny": "integer", "cost_cny": "integer",
            "profit_cny": "integer", "margin_pct": "number", "below_20_pct": "boolean",
            "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation in {"service_weekly_review", "service_v2_weekly_review"}:
        return {
            "site_id": "string", "request_count": "integer", "failed_request_count": "integer",
            "error_rate_pct": "number", "mean_latency_ms": "number", "exceeds_slo": "boolean",
            "risk_change": "string", "event_locator": "string",
        }, "array"
    if operation == "finance_quarterly_review":
        schema, shape = _output_schema("finance_monthly_review", arguments)
        schema.update({f"m{period[-2:]}_margin_pct": "number" for period in arguments["periods"]})
        return schema, shape
    if operation == "finance_period_delta":
        return {
            "unit_id": "string", "period_from": "string", "period_to": "string",
            "revenue_from_cny": "integer", "revenue_to_cny": "integer", "delta_cny": "integer",
            "growth_pct": "number", "decline_rank": "integer", "below_20_pct": "boolean",
            "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation == "finance_budget_review":
        return {
            "unit_id": "string", "actual_net_revenue_cny": "integer", "budget_net_revenue_cny": "integer",
            "variance_cny": "integer", "variance_pct": "number", "attainment_pct": "number",
            "under_budget": "boolean", "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation == "finance_budget_status_review":
        return {
            "unit_id": "string", "actual_net_revenue_cny": "integer", "budget_net_revenue_cny": "integer",
            "variance_cny": "integer", "under_budget": "boolean", "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation == "finance_budget_delta_review":
        return {
            "unit_id": "string", "current_actual_net_revenue_cny": "integer", "prior_actual_net_revenue_cny": "integer",
            "current_budget_net_revenue_cny": "integer", "prior_budget_net_revenue_cny": "integer",
            "current_variance_cny": "integer", "prior_variance_cny": "integer",
            "current_under_budget": "boolean", "prior_under_budget": "boolean",
            "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation == "finance_half_year_review":
        return {
            "unit_id": "string", "half_year_net_revenue_cny": "integer", "half_year_cost_cny": "integer",
            "half_year_profit_cny": "integer", "half_year_margin_pct": "number",
            **{f"m{period[-2:]}_{metric}": kind for period in arguments["periods"]
               for metric, kind in (("net_revenue_cny", "integer"), ("profit_cny", "integer"), ("margin_pct", "number"))},
            **{f"q{q}_{metric}": "integer" for q in (1, 2) for metric in ("net_revenue_cny", "profit_cny")},
            "m05_attainment_pct": "number", "m06_attainment_pct": "number",
            "m05_under_budget": "boolean", "m06_under_budget": "boolean", "budget_risk_change": "string",
            "below_20_pct": "boolean", "risk_change": "string", "note_locator": "string",
        }, "array"
    if operation == "service_sequence_review":
        schema, shape = _output_schema("service_weekly_review", arguments)
        schema.update({f"{period.lower()}_error_rate_pct": "number" for period in arguments["periods"]})
        return schema, shape
    if operation == "service_error_delta":
        return {
            "site_id": "string", "period_from": "string", "period_to": "string",
            "error_rate_from_pct": "number", "error_rate_to_pct": "number", "error_rate_delta_pp": "number",
            "deterioration_rank": "integer", "exceeds_slo": "boolean", "risk_change": "string", "event_locator": "string",
        }, "array"
    if operation == "service_p95_review":
        return {
            "site_id": "string", "period": "string", "sample_count": "integer",
            "p95_latency_ms": "integer", "exceeds_slo": "boolean", "risk_change": "string",
            "event_locator": "string",
        }, "array"
    if operation == "service_multiweek_review":
        return {
            "site_id": "string", "weeks_included": "integer", "request_count": "integer",
            "failed_request_count": "integer", "error_rate_pct": "number", "mean_latency_ms": "number",
            **{f"{period.lower()}_error_rate_pct": "number" for period in arguments["periods"]},
            "w07_p95_latency_ms": "integer", "w08_p95_latency_ms": "integer",
            "w07_p95_exceeds_slo": "boolean", "w08_p95_exceeds_slo": "boolean", "p95_risk_change": "string",
            "exceeds_slo": "boolean", "risk_change": "string", "event_locator": "string",
        }, "array"
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
        columns = tuple(str(item) for item in arguments.get("columns", ()))
        schema = {"percentage_cases_min": "number"}
        if len(columns) > 1:
            schema["percentage_deaths_max"] = "number"
        return schema, "object"
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


def formal_output_contract(spec: CanonicalTaskSpec) -> tuple[str, dict[str, str], str]:
    """Return the controller-owned operation and output types without loading sources."""

    operation = _operation_for_spec(spec)
    output_schema, shape = _output_schema(operation, spec.arguments)
    return operation, output_schema, shape


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


def _period_review_guidance(operation: str) -> str:
    """Public period-review invariants shared by both Executor paths.

    The formal operation contract is authoritative, but both lanes benefit
    from an imperative checklist at both generation and repair time.  This is
    parameterized by the operation rather than by task IDs so the same rules
    apply to every current/previous aggregate review.
    """
    if operation in {"finance_monthly_review", "finance_v2_monthly_review"}:
        entity = "unit_id"
        values = (
            "net_revenue_cny and cost_cny"
            if operation == "finance_monthly_review"
            else "booked_revenue_cny, refund_cny, and cost_cny"
        )
        threshold = "(revenue - cost) / revenue < 0.20"
        threshold_source = "the fixed 0.20 margin threshold from the public formula, not a nonexistent threshold input field"
        risk = "below_20_pct"
        locator = "note_locator"
    elif operation in {"service_weekly_review", "service_v2_weekly_review"}:
        entity = "site_id"
        values = (
            "request_count, failed_request_count, and latency_sum_ms"
            if operation == "service_weekly_review"
            else "completed_request_count, final_failed_request_count, and request_latency_sum_ms"
        )
        threshold = (
            "failed / request_count > the current row's slo_error_rate"
            if operation == "service_weekly_review"
            else "final_failed / completed_request_count > the current row's slo_error_rate"
        )
        threshold_source = "the same site's current input slo_error_rate for BOTH current and prior risk comparisons; bind this threshold once and reuse it, rather than reading an uninitialized prior accumulator field"
        risk = "exceeds_slo"
        locator = "event_locator"
    else:
        return ""
    return (
        "\nExecutor invariants for this period review (apply literally):\n"
        "- All released CSV, SLO, and locator metadata needed for the calculation is already bound in "
        "inputs/task.json. Do not read any other released file, infer a path, or use the filesystem to obtain a "
        "previous period; use is_current and the bound rows only.\n"
        f"- Group ALL raw rows by {entity} and the boolean is_current before calculating any derived field; "
        f"sum {values} within each group and emit exactly one current row per {entity}. Never emit one row per raw row.\n"
        "- Keep period presence separate from a false risk value. A missing previous group is not an all-clear "
        "previous group: test whether previous rows exist before reading or creating a prior aggregate. "
        "Only if no previous raw rows exist for the review, set risk_change='initial' for every current entity.\n"
        f"- Only when previous rows exist, compute prior {risk} from the complete prior aggregate using {threshold}; "
        "then compare current and prior booleans to choose new, resolved, still_risk, or still_clear. Never read a "
        "missing derived risk key as false. A missing accumulator threshold or derived field is a code defect, not evidence that previous rows are absent; do not substitute initial, false, zero, or an empty group to hide it.\n"
        f"- Use {threshold_source}; do not use a stale row variable left over from an earlier loop, and do not "
        f"invent an entity-specific threshold. Read {locator} from the grouped current rows for that same entity.\n"
        "- Initialize each accumulator once per entity and period, then add every row's amounts or counts. "
        "Test prior-group membership before an indexed defaultdict lookup can create a synthetic prior group.\n"
        f"- Sort all current output rows by {entity}, then write only outputs/result.json. The row count comes from "
        "the current entities present in the bound input, not from a fixed literal."
    )


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
        "period_binding": "Use exact period strings from input rows and declared operation arguments; never invent or normalize their case.",
    }
    if operation in {"finance_monthly_review", "finance_v2_monthly_review"}:
        semantics.update(
            executor_invariants=_period_review_guidance(operation),
            numeric_parser="Input amounts are JSON integers, not formatted strings. Use them directly; do not call string methods on numbers.",
            period_selection="Rows with is_current true are current; false rows are previous. Do not hardcode periods.",
            formula=(
                (
                    "For each unit_id sum net_revenue_cny and cost_cny separately over its rows in each period; "
                    if operation == "finance_monthly_review"
                    else "For each unit_id compute row_net_revenue=booked_revenue_cny-refund_cny, then sum row_net_revenue and cost_cny separately over its rows in each period; "
                )
                + "profit_cny=revenue-cost; margin_pct=round(100*profit/revenue,4). "
                "below_20_pct is (revenue-cost)/revenue < 0.20 BEFORE rounding. Previous-period risk uses that period's sums, not "
                "a derived risk field (raw input rows do not contain below_20_pct); recompute the prior risk from the "
                "prior raw rows with the same formula. Never read a missing derived field as no prior risk. "
                "risk_change='initial' for EVERY entity if no prior rows exist; "
                "otherwise 'new' if current risk and not prior risk, 'resolved' if prior risk and not current risk, "
                "'still_risk' if both true, 'still_clear' if both false. Notes never determine risk_change. "
                "Emit one current-period row per unit_id present in the bound current input, sorted by unit_id. "
                "Take note_locator from the current-period rows for the same unit_id."
            ),
        )
    elif operation in {
        "finance_quarterly_review", "finance_period_delta", "finance_budget_review",
        "finance_budget_status_review",
        "finance_budget_delta_review",
        "finance_half_year_review", "service_sequence_review", "service_error_delta",
        "service_p95_review", "service_multiweek_review",
    }:
        formulas = {
            "finance_quarterly_review": "This is a multi-period report with separate scopes. First group by unit_id and month. For each output row, compute net_revenue_cny, cost_cny, profit_cny, margin_pct, below_20_pct, and note_locator ONLY from the rows whose month equals current_period. Compute mMM_margin_pct separately from each listed month and use those fields only for the corresponding month. Never use a single all-period accumulator for current-month fields and never emit a quarterly total in the current-month fields. The current-month numeric fields must exactly match the current_period aggregate. risk_change compares current_period risk against previous_period risk.",
            "finance_period_delta": "Aggregate period_from and period_to separately by unit_id. revenue_from_cny/revenue_to_cny are their totals; delta_cny=to-from; growth_pct=round(100*delta/from,4). decline_rank is 1-based ascending UNROUNDED growth, ties by unit_id. below_20_pct and risk_change compare the two periods' margins. Emit rows sorted by unit_id, not rank.",
            "finance_budget_review": "For each unit_id set actual_net_revenue_cny=sum(booked_revenue_cny-refund_cny) over current rows; NEVER subtract cost_cny from this field (cost is not part of net revenue). The joined budget_net_revenue_cny repeats on every raw row: read ONCE per entity/period, never sum repeated budgets. variance_cny=actual-budget; variance_pct=round(100*variance/budget,4); attainment_pct=round(100*actual/budget,4). under_budget is actual<budget (not above budget). risk_change compares current/prior under_budget, or initial if no prior period.",
            "finance_budget_status_review": "For each unit_id set actual_net_revenue_cny=sum(booked_revenue_cny-refund_cny) over current rows; NEVER subtract cost_cny from this field. Read the joined budget_net_revenue_cny once per entity/period. Emit variance_cny=actual-budget, under_budget=actual<budget, and risk_change from current versus prior under_budget; do not emit percentage fields.",
            "finance_budget_delta_review": "Compare the current and prior budget periods per unit_id. For each period sum booked_revenue_cny-refund_cny, read one budget_net_revenue_cny, and emit actual revenue, budget, variance_cny, and under_budget for both periods. risk_change compares current_under_budget with prior_under_budget. Emit no percentage fields.",
            "finance_half_year_review": "Emit each listed month's mMM_net_revenue_cny, mMM_profit_cny and mMM_margin_pct. q1_net_revenue_cny/q1_profit_cny cover months 01-03; q2 equivalents cover 04-06. half_year_net_revenue_cny/cost_cny/profit_cny/margin_pct cover all six months. below_20_pct and risk_change compare current versus previous MONTH margins. For months 05/06, read one budget per entity/month, emit m05/m06_attainment_pct and m05/m06_under_budget; budget_risk_change compares June versus May under_budget. Do not add monthly percentages or count repeated budget values more than once.",
            "service_sequence_review": "This is a multi-period report with separate scopes. First group by site_id and week. For each output row, compute request_count, failed_request_count, error_rate_pct, mean_latency_ms, exceeds_slo, and event_locator ONLY from rows whose week equals current_period. Compute wNN_error_rate_pct separately from each listed week. Never use a single all-period accumulator for current-week fields and never put multiweek totals or rates in the current-week fields. risk_change compares current_period risk against previous_period risk. Preserve the exact case and type of input period keys when initializing and accessing accumulators.",
            "service_error_delta": "Aggregate each site in period_from/period_to. Each error rate is round(100*sum(failures)/sum(requests),4); error_rate_delta_pp=round(error_rate_to_pct-error_rate_from_pct,4). deterioration_rank is 1-based descending error_rate_delta_pp, ties by site_id; output sorted by site_id. exceeds_slo/risk_change compare UNROUNDED current/prior error ratios.",
            "service_p95_review": "Rows are individual request latency samples, not hourly means. For each site/week sort latency_ms; nearest-rank index=(95*n+99)//100-1 (zero-based), p95_latency_ms=sorted_values[index]. sample_count is current site's sample count. exceeds_slo uses p95_latency_ms>sample_p95_latency_ms; risk_change compares previous sample P95 when present. Never compute P95 from hourly latency_sum/request_count.",
            "service_multiweek_review": "Separate row_kind=hourly from row_kind=latency_sample. For hourly rows emit each week's wNN_error_rate_pct and full-period summed request_count/failed_request_count; error_rate_pct=round(100*all_failures/all_requests,4); mean_latency_ms=round(all_latency_sum/all_requests,4). weeks_included=len(periods). exceeds_slo/risk_change compare current/previous WEEK error ratios. For latency_sample rows independently compute nearest-rank request-sample P95 for W07/W08, emit w07/w08_p95_latency_ms and w07/w08_p95_exceeds_slo; p95_risk_change compares those booleans. Never average weekly rates or weekly P95s.",
        }
        semantics.update(
            periods=arguments.get("periods", []),
            current_period=str(arguments.get("current_period", "")),
            previous_period=str(arguments.get("previous_period", "")),
            period_from=arguments.get("period_from", ""), period_to=arguments.get("period_to", ""),
            formula=formulas[operation],
            numeric_parser="All numeric inputs are JSON numbers. Do not use string parsing on them.",
            finance_definition="For v1 rows use net_revenue_cny; for v2 rows compute booked_revenue_cny-refund_cny. Sum cost_cny. profit=revenue-cost; margin_pct=round(100*profit/revenue,4); margin risk uses UNROUNDED profit/revenue < 0.20.",
            service_definition="v1 hourly counts are request_count/failed_request_count/latency_sum_ms; v2 are completed_request_count/final_failed_request_count/request_latency_sum_ms. failed_attempt_count is NEVER the error numerator. Ratios use sums, error rate multiplies by 100, mean latency does not. Error risk uses UNROUNDED failures/requests > slo_error_rate.",
            risk_change_definition=(
                "initial is allowed ONLY when previous_period is empty/no prior rows exist. "
                "When a previous period exists, use the complete (prior_risk,current_risk) truth table: "
                "(false,false)=still_clear; (false,true)=new; (true,false)=resolved; (true,true)=still_risk. "
                "A false prior risk is NOT a missing prior period. Raw rows never contain derived risk fields."
            ),
            executor_invariants=(
                "All inputs are bound in inputs/task.json. Do not open any other path. Group by entity AND month/week; "
                "is_current only marks provenance, not input eligibility. Keep every declared period and accumulate ALL raw rows; "
                "never overwrite an accumulator with the last row. Follow the operation's per-field period scope: current-period fields "
                "use only the current_period group, while historical fields are computed independently per declared period. "
                "Derive period keys from the exact values in the bound rows and the declared periods; do not invent, lowercase, or hardcode period tokens. For period-delta operations, use the two declared period_from/period_to values exactly. Initialize every accumulated field before addition. "
                "Round ALL percentage/rate/margin/mean outputs to FOUR decimal places, not two and not unrounded. "
                "Emit one row per entity sorted by entity key. Use that entity's current note_locator/event_locator. Null is invalid. Derive period keys from the exact values present in the bound rows and declared periods; preserve case and type."
            ),
        )
    elif operation in {"service_weekly_review", "service_v2_weekly_review"}:
        semantics.update(
            executor_invariants=_period_review_guidance(operation),
            numeric_parser=(
                "Counts and latency_sum_ms are JSON integers; slo_error_rate is a JSON number read from each site's rows. Never invent a threshold or call string methods on numbers."
                if operation == "service_weekly_review"
                else "Counts, final_failed_request_count, failed_attempt_count and request_latency_sum_ms are JSON integers; slo_error_rate is a JSON number read from each site's rows. Never use failed_attempt_count as the error numerator."
            ),
            period_selection="Rows with is_current true are current; false rows are previous. Do not hardcode periods.",
            formula=(
                (
                    "For each site_id separately sum request_count, failed_request_count, latency_sum_ms "
                    if operation == "service_weekly_review"
                    else "For each site_id separately sum completed_request_count, final_failed_request_count, request_latency_sum_ms "
                )
                + "in each period. error_rate_pct=round(100*failed/request,4); "
                + (
                    "mean_latency_ms=round(latency_sum_ms/request,4), never average hourly means. "
                    if operation == "service_weekly_review"
                    else "mean_latency_ms=round(request_latency_sum_ms/completed_request_count,4), never use failed_attempt_count for error_rate or denominator. "
                )
                + (
                    "exceeds_slo is failed/request > slo_error_rate BEFORE rounding. Prior risk uses "
                    if operation == "service_weekly_review"
                    else "exceeds_slo is final_failed/completed_request_count > slo_error_rate BEFORE rounding. Prior risk uses "
                )
                + "prior raw rows and the SAME site's CURRENT input slo_error_rate for both periods, not an uninitialized "
                "prior accumulator threshold; raw input rows do not contain exceeds_slo, so recompute the "
                "prior risk from the prior raw aggregates instead of reading a derived field. "
                "risk_change='initial' for EVERY site if no prior rows exist; "
                "otherwise 'new' if current risk and not prior risk, 'resolved' if prior risk and not current risk, "
                "'still_risk' if both true, 'still_clear' if both false. Events never determine risk_change. "
                "Emit one current-period row per site_id present in the bound current input, sorted by site_id. "
                "Take event_locator from current-period rows for that site_id."
            ),
        )
    elif operation in {"extract_narrative_facts", "synthesize_narrative_risk"}:
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
        normalized_tickers = [str(item).upper() for item in tickers if str(item).strip()]
        normalized_quarters = [str(item) for item in arguments["quarters"]]
        metric = str(arguments["metric"])
        semantics.update(
            tickers=normalized_tickers,
            quarters=normalized_quarters,
            metric=metric,
            dsl_operation="trend_series",
            dsl_arguments={
                "ticker_field": "ticker",
                "period_field": "quarter",
                "metric_field": "metric",
                "value_field": "value",
                "tickers": normalized_tickers,
                "periods": normalized_quarters,
                "metric": metric,
                "ticker_output": "ticker",
                "period_output": "quarter",
                "value_output": "metric_value",
                "direction_output": "trend_direction",
            },
            formula=(
                "Emit one row per requested ticker and quarter in ticker-list then quarter-list order. "
                "Direction is increasing when every adjacent value rises, decreasing when every adjacent value falls, "
                "flat when all are equal, otherwise mixed; repeat that ticker direction on its rows."
            ),
        )
    elif operation == "compare_metric":
        tickers = [str(item).upper() for item in arguments["tickers"]]
        if tickers != ["ACME", "BETA"]:
            raise ValueError(f"formal_compare_metric_tickers_unsupported:{tickers}")
        quarter = str(arguments["quarter"])
        metric = str(arguments["metric"]).lower()
        semantics.update(
            tickers=tickers,
            quarter=quarter,
            metric=metric,
            dsl_operation="compare_metric",
            dsl_arguments={
                "ticker_field": "ticker",
                "period_field": "quarter",
                "metric_field": "metric",
                "value_field": "value",
                "left_ticker": "ACME",
                "right_ticker": "BETA",
                "period": quarter,
                "metric": metric,
                "period_output": "quarter",
                "left_output": "acme_revenue_value",
                "right_output": "beta_revenue_value",
                "gap_output": "gap_value",
            },
            formula="Select exactly one ACME and one BETA revenue row at the requested quarter; gap_value=ACME-BETA.",
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
        selected_months = [int(item) for item in arguments.get("selected_months", [])]
        semantics.update(
            date_column=str(arguments["groupby"]).removeprefix("month(").removesuffix(")"),
            value_column=str(arguments["value_column"]),
            selected_months=selected_months,
            date_format=(
                "MM/DD/YYYY HH:MM; the month is the leading two-digit MM component, "
                "for example 01/31/2015 23:00 has month 1"
            ),
            formula=(
                "Parse the documented date format, compute mean of non-missing values by month, round to two decimals, "
                + (
                    f"and emit only selected_months {selected_months} in ascending order."
                    if selected_months
                    else "and emit all month rows in ascending order."
                )
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
    operation, output_schema, shape = formal_output_contract(spec)
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


def load_c2b_formal_cases() -> tuple[FormalAdaptiveCase, ...]:
    """Adapt the registered 48 positive cases through the existing validator seam."""
    from statebus.benchmark.task_registry import load_c2b_positive_samples

    return tuple(adapt_formal_sample(sample) for sample in load_c2b_positive_samples())


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


_CONTEST_EXTENDED_OPERATIONS = frozenset({
    "finance_quarterly_review", "finance_period_delta", "finance_budget_review", "finance_budget_status_review", "finance_budget_delta_review",
    "finance_half_year_review", "service_sequence_review", "service_error_delta",
    "service_p95_review", "service_multiweek_review",
})


def _contest_periods(arguments: dict[str, object], rows: tuple[dict[str, object], ...]) -> tuple[str, ...]:
    declared = tuple(str(item) for item in arguments.get("periods", ()) if str(item))
    if declared:
        return declared
    return tuple(dict.fromkeys(str(row.get("month", row.get("week", ""))) for row in rows))


def _contest_finance_amount(row: dict[str, object]) -> tuple[int, int]:
    if "booked_revenue_cny" in row:
        return int(row["booked_revenue_cny"]) - int(row["refund_cny"]), int(row["cost_cny"])
    return int(row["net_revenue_cny"]), int(row["cost_cny"])


def _contest_finance_aggregate(batch: list[dict[str, object]]) -> tuple[int, int, float, bool]:
    revenue = sum(_contest_finance_amount(row)[0] for row in batch)
    cost = sum(_contest_finance_amount(row)[1] for row in batch)
    if revenue <= 0:
        raise ValueError("contest_zero_finance_revenue")
    margin = round(100 * (revenue - cost) / revenue, 4)
    return revenue, cost, margin, (revenue - cost) / revenue < 0.20


def _contest_service_amount(row: dict[str, object]) -> tuple[int, int, int]:
    if "completed_request_count" in row:
        return int(row["completed_request_count"]), int(row["final_failed_request_count"]), int(row["request_latency_sum_ms"])
    return int(row["request_count"]), int(row["failed_request_count"]), int(row["latency_sum_ms"])


def _contest_service_aggregate(batch: list[dict[str, object]]) -> tuple[int, int, int, float, float, bool]:
    requests = sum(_contest_service_amount(row)[0] for row in batch)
    failures = sum(_contest_service_amount(row)[1] for row in batch)
    latency = sum(_contest_service_amount(row)[2] for row in batch)
    if requests <= 0:
        raise ValueError("contest_zero_service_requests")
    threshold = float(batch[0]["slo_error_rate"])
    error = round(100 * failures / requests, 4)
    mean_latency = round(latency / requests, 4)
    return requests, failures, latency, error, mean_latency, failures / requests > threshold


def _contest_latency_values(batch: list[dict[str, object]]) -> list[int]:
    return [int(row["latency_ms"]) for row in batch]


def _contest_nearest_rank(values: list[float], percentile: float = 0.95) -> float:
    if not values:
        raise ValueError("contest_empty_percentile")
    ordered = sorted(values)
    rank = max(1, int(ceil(len(ordered) * percentile)))
    return ordered[rank - 1]


def _contest_risk_change(current: bool, previous: bool | None) -> str:
    return _review_change(current, previous)


def _recompute_contest_extended(
    operation: str,
    arguments: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    periods = _contest_periods(arguments, rows)
    current = str(arguments.get("current_period", periods[-1] if periods else ""))
    previous = str(arguments.get("previous_period", ""))
    field = "month" if operation.startswith("finance_") else "week"
    entity_field = "unit_id" if operation.startswith("finance_") else "site_id"
    grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
    for row in rows:
        period = str(row.get(field, ""))
        if period in periods:
            grouped.setdefault(str(row[entity_field]), {}).setdefault(period, []).append(row)
    entities = sorted(grouped)
    out: list[dict[str, object]] = []
    for entity in entities:
        batches = grouped[entity]
        now = batches.get(current, [])
        if not now:
            continue
        before = batches.get(previous, []) if previous else []
        if operation == "finance_quarterly_review":
            revenue, cost, margin, risk = _contest_finance_aggregate(now)
            out.append({"unit_id": entity, "net_revenue_cny": revenue, "cost_cny": cost,
                        "profit_cny": revenue-cost, "margin_pct": margin, "below_20_pct": risk,
                        "risk_change": _contest_risk_change(risk, _contest_finance_aggregate(before)[3] if before else None),
                        **{f"m{p[-2:]}_margin_pct": _contest_finance_aggregate(batches[p])[2] for p in periods},
                        "note_locator": str(now[0]["note_locator"])})
        elif operation == "finance_half_year_review":
            total_rev, total_cost, total_margin, _ = _contest_finance_aggregate([r for p in periods for r in batches[p]])
            month = {p: _contest_finance_aggregate(batches[p]) for p in periods}
            result = {"unit_id": entity, "half_year_net_revenue_cny": total_rev, "half_year_cost_cny": total_cost,
                      "half_year_profit_cny": total_rev-total_cost, "half_year_margin_pct": total_margin,
                      "below_20_pct": month[current][3], "risk_change": _contest_risk_change(month[current][3], month[previous][3]),
                      "note_locator": str(now[0]["note_locator"])}
            for p, (revenue, cost, margin, _) in month.items():
                result.update({f"m{p[-2:]}_net_revenue_cny": revenue, f"m{p[-2:]}_profit_cny": revenue-cost, f"m{p[-2:]}_margin_pct": margin})
            for q, batch_periods in ((1, periods[:3]), (2, periods[3:])):
                revenue, cost, _, _ = _contest_finance_aggregate([r for p in batch_periods for r in batches[p]])
                result.update({f"q{q}_net_revenue_cny": revenue, f"q{q}_profit_cny": revenue-cost})
            for p in periods[-2:]:
                budget = int(batches[p][0]["budget_net_revenue_cny"])
                result[f"m{p[-2:]}_attainment_pct"] = round(100*month[p][0]/budget, 4)
                result[f"m{p[-2:]}_under_budget"] = month[p][0] < budget
            result["budget_risk_change"] = _contest_risk_change(result["m06_under_budget"], result["m05_under_budget"])
            out.append(result)
        elif operation == "finance_period_delta":
            from_rev, _, _, from_risk = _contest_finance_aggregate(before)
            to_rev, _, _, to_risk = _contest_finance_aggregate(now)
            out.append({"unit_id": entity, "period_from": str(arguments["period_from"]), "period_to": str(arguments["period_to"]),
                        "revenue_from_cny": from_rev, "revenue_to_cny": to_rev, "delta_cny": to_rev-from_rev,
                        "growth_pct": round((to_rev-from_rev)/from_rev*100, 4), "below_20_pct": to_risk,
                        "risk_change": _contest_risk_change(to_risk, from_risk), "note_locator": str(now[0]["note_locator"])})
        elif operation in {"finance_budget_review", "finance_budget_status_review"}:
            # Budget review is a revenue-to-budget join. Cost remains in the
            # published source for other operations but is not part of the
            # actual net revenue compared with budget.
            actual = sum(_contest_finance_amount(row)[0] for row in now)
            budget = int(now[0]["budget_net_revenue_cny"])
            under = actual < budget
            prior = (sum(_contest_finance_amount(row)[0] for row in before)
                     < int(before[0]["budget_net_revenue_cny"])) if before else None
            result = {"unit_id": entity, "actual_net_revenue_cny": actual, "budget_net_revenue_cny": budget,
                      "variance_cny": actual-budget, "under_budget": under,
                      "risk_change": _contest_risk_change(under, prior), "note_locator": str(now[0]["note_locator"])}
            if operation == "finance_budget_review":
                result.update({"variance_pct": round(100*(actual-budget)/budget, 4),
                               "attainment_pct": round(100*actual/budget, 4)})
            out.append(result)
        elif operation == "finance_budget_delta_review":
            current_actual = sum(_contest_finance_amount(row)[0] for row in now)
            prior_actual = sum(_contest_finance_amount(row)[0] for row in before)
            current_budget = int(now[0]["budget_net_revenue_cny"])
            prior_budget = int(before[0]["budget_net_revenue_cny"])
            current_under = current_actual < current_budget
            prior_under = prior_actual < prior_budget
            out.append({"unit_id": entity, "current_actual_net_revenue_cny": current_actual,
                        "prior_actual_net_revenue_cny": prior_actual,
                        "current_budget_net_revenue_cny": current_budget,
                        "prior_budget_net_revenue_cny": prior_budget,
                        "current_variance_cny": current_actual-current_budget,
                        "prior_variance_cny": prior_actual-prior_budget,
                        "current_under_budget": current_under, "prior_under_budget": prior_under,
                        "risk_change": _contest_risk_change(current_under, prior_under),
                        "note_locator": str(now[0]["note_locator"])})
        elif operation in {"service_sequence_review", "service_multiweek_review"}:
            hourly = {p: [r for r in batches[p] if r.get("row_kind", "hourly") == "hourly"] for p in periods}
            weeks = {p: _contest_service_aggregate(hourly[p]) for p in periods}
            total = weeks[current] if operation == "service_sequence_review" else _contest_service_aggregate([r for p in periods for r in hourly[p]])
            result = {"site_id": entity, "request_count": total[0], "failed_request_count": total[1],
                      "error_rate_pct": total[3], "mean_latency_ms": total[4],
                      **{f"{p.lower()}_error_rate_pct": weeks[p][3] for p in periods},
                      "exceeds_slo": weeks[current][5], "risk_change": _contest_risk_change(weeks[current][5], weeks[previous][5]),
                      "event_locator": str(now[0]["event_locator"])}
            if operation == "service_multiweek_review":
                result["weeks_included"] = len(periods)
                for p in periods[-2:]:
                    samples = [r for r in batches[p] if r["row_kind"] == "latency_sample"]
                    p95 = int(_contest_nearest_rank(_contest_latency_values(samples)))
                    result[f"{p.lower()}_p95_latency_ms"] = p95
                    result[f"{p.lower()}_p95_exceeds_slo"] = p95 > float(samples[0]["sample_p95_latency_ms"])
                result["p95_risk_change"] = _contest_risk_change(result["w08_p95_exceeds_slo"], result["w07_p95_exceeds_slo"])
            out.append(result)
        elif operation == "service_error_delta":
            left = _contest_service_aggregate(before); right = _contest_service_aggregate(now)
            out.append({"site_id": entity, "period_from": str(arguments["period_from"]), "period_to": str(arguments["period_to"]),
                        "error_rate_from_pct": left[3], "error_rate_to_pct": right[3], "error_rate_delta_pp": round(right[3]-left[3],4),
                        "exceeds_slo": right[5], "risk_change": _contest_risk_change(right[5],left[5]), "event_locator": str(now[0]["event_locator"])})
        elif operation == "service_p95_review":
            p95 = int(_contest_nearest_rank(_contest_latency_values(now)))
            threshold = float(now[0]["sample_p95_latency_ms"]); risk = p95 > threshold
            prior = _contest_nearest_rank(_contest_latency_values(before)) > threshold if before else None
            out.append({"site_id": entity, "period": current, "sample_count": len(now), "p95_latency_ms": p95,
                        "exceeds_slo": risk, "risk_change": _contest_risk_change(risk,prior), "event_locator": str(now[0]["event_locator"])})
    if operation == "finance_period_delta":
        for rank, row in enumerate(sorted(out, key=lambda r: (r["delta_cny"]/r["revenue_from_cny"], r["unit_id"])), 1):
            row["decline_rank"] = rank
    if operation == "service_error_delta":
        for rank, row in enumerate(sorted(out, key=lambda r: (-r["error_rate_delta_pp"], r["site_id"])), 1):
            row["deterioration_rank"] = rank

    return tuple(out)


def recompute_formal_rows(
    operation: str,
    arguments: dict[str, object],
    rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    if operation in _CONTEST_EXTENDED_OPERATIONS:
        return _recompute_contest_extended(operation, arguments, rows)
    if operation in {"finance_monthly_review", "service_weekly_review",
                     "finance_v2_monthly_review", "service_v2_weekly_review"}:
        finance = operation in {"finance_monthly_review", "finance_v2_monthly_review"}
        v2 = operation in {"finance_v2_monthly_review", "service_v2_weekly_review"}
        current = str(arguments["current_period"])
        previous = str(arguments.get("previous_period", ""))
        period_key = "month" if finance else "week"
        group_key = "unit_id" if finance else "site_id"
        grouped: dict[str, dict[str, list[dict[str, object]]]] = {}
        for row in rows:
            period = str(row[period_key])
            if period in {current, previous}:
                grouped.setdefault(str(row[group_key]), {}).setdefault(period, []).append(row)
        current_keys = tuple(sorted(key for key, periods in grouped.items() if current in periods))
        if not current_keys:
            raise ValueError(f"formal_review_group_count:{len(grouped)}")
        output: list[dict[str, object]] = []
        for key in current_keys:
            periods = grouped[key]
            now = periods[current]
            before = periods.get(previous, ()) if previous else ()
            if finance:
                def calculate(batch):
                    revenue = sum(
                        int(row["booked_revenue_cny"]) - int(row["refund_cny"])
                        if v2 else int(row["net_revenue_cny"])
                        for row in batch
                    )
                    cost = sum(int(row["cost_cny"]) for row in batch)
                    if revenue <= 0:
                        raise ValueError("formal_review_zero_revenue")
                    return revenue, cost, round(100 * (revenue - cost) / revenue, 4)
                revenue, cost, margin = calculate(now)
                risk = (revenue - cost) * 5 < revenue
                prior_risk = ((calculate(before)[0] - calculate(before)[1]) * 5 < calculate(before)[0]) if before else None
                item = {
                    "unit_id": key, "net_revenue_cny": revenue, "cost_cny": cost,
                    "profit_cny": revenue - cost, "margin_pct": margin,
                    "below_20_pct": risk, "risk_change": _review_change(risk, prior_risk),
                    "note_locator": str(now[0]["note_locator"]),
                }
            else:
                def calculate(batch):
                    requests = sum(int(row["completed_request_count" if v2 else "request_count"]) for row in batch)
                    failed = sum(int(row["final_failed_request_count" if v2 else "failed_request_count"]) for row in batch)
                    latency = sum(int(row["request_latency_sum_ms" if v2 else "latency_sum_ms"]) for row in batch)
                    if requests <= 0:
                        raise ValueError("formal_review_zero_requests")
                    return requests, failed, round(100 * failed / requests, 4), round(latency / requests, 4)
                requests, failed, error, latency = calculate(now)
                threshold = float(now[0]["slo_error_rate"])
                risk = failed / requests > threshold
                prior_risk = (calculate(before)[1] / calculate(before)[0] > threshold) if before else None
                item = {
                    "site_id": key, "request_count": requests, "failed_request_count": failed,
                    "error_rate_pct": error, "mean_latency_ms": latency,
                    "exceeds_slo": risk, "risk_change": _review_change(risk, prior_risk),
                    "event_locator": str(now[0]["event_locator"]),
                }
            output.append(item)
        return tuple(output)
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
        output = {"percentage_cases_min": percentages[0]}
        if len(percentages) > 1:
            output["percentage_deaths_max"] = percentages[1]
        return (output,)
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
        raw_selected_months = arguments.get("selected_months")
        selected_months = (
            {int(item) for item in raw_selected_months}
            if raw_selected_months is not None
            else None
        )
        grouped: dict[int, list[float]] = {}
        for row in rows:
            value = _parse_number(row.get(value_column))
            if value is None:
                continue
            month = _date_month(row.get(date_column))
            if selected_months is not None and month not in selected_months:
                continue
            grouped.setdefault(month, []).append(value)
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


def _review_change(current: bool, previous: bool | None) -> str:
    if previous is None:
        return "initial"
    if current and not previous:
        return "new"
    if previous and not current:
        return "resolved"
    return "still_risk" if current else "still_clear"


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


def _mismatched_row_fields(
    actual: tuple[dict[str, object], ...],
    expected: tuple[dict[str, object], ...],
) -> tuple[str, ...]:
    """Name discrepant public fields without disclosing identities or expected values."""
    if len(actual) != len(expected) or any(set(left) != set(right) for left, right in zip(actual, expected)):
        return ()
    return tuple(sorted({
        field
        for left, right in zip(actual, expected)
        for field in right
        if not _rows_equal(({field: left[field]},), ({field: right[field]},))
    }))


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
                if len(candidates) == 1:
                    errors.extend(
                        f"formal_recomputation_field_mismatch:{field}"
                        for field in _mismatched_row_fields(context.output_rows, candidates[0])
                    )
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
