"""Small, side-effect free contracts used by the bounded Stage 2 runner.

This module deliberately contains measurement projections only.  It does not
create Runtime objects, provider receipts, retries, or terminal events.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


LANES = (
    "direct_single_agent",
    "pure_text_mas",
    "fixed_structured",
    "adaptive_routed",
)
TERMINAL_CLASSES = (
    "success",
    "quality_fail",
    "timeout",
    "unsupported",
    "runtime_fail",
    "policy_reject",
    "environment_fail",
)
# Lifecycle accounting is deliberately separate from terminal outcome.  A
# planned slot which was never started, or whose terminal state is unknown
# after an interrupted worker, must remain in the denominator without being
# reported as a successful/failed business result.
ACCOUNTING_CLASSES = (*TERMINAL_CLASSES, "not_started", "unknown")
LIFECYCLE_STATES = (
    "planned",
    "started",
    "provider_started",
    "settled",
    "interrupted",
    "unknown",
    "not_started",
)
_GOLD_KEYS = {
    "expected",
    "expected_facts",
    "quality_checks",
    "summary_hint",
    "gold",
    "oracle_answer",
    "hidden",
    "future",
    "correctness_hint",
}
_PROVENANCE_KEYS = {
    "selected_doc_ids",
    "selected_doc_hashes",
    "supporting_doc_ids",
    "public_sources",
    "public_tool_execution",
    "public_tool_outputs",
    "source_paths",
    "source_document",
    "source_ref_id",
    "provenance",
}


def _forbidden_paths(value: Any, *, path: str = "") -> list[str]:
    """Find scorer/oracle fields structurally, including nested rows."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            lowered = key.lower()
            if lowered in _GOLD_KEYS or any(
                token in lowered for token in ("gold", "expected", "oracle", "hidden", "future")
            ):
                found.append(child_path)
            found.extend(_forbidden_paths(raw_value, path=child_path))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(_forbidden_paths(item, path=f"{path}[{index}]"))
    return found


def _public_value(value: Any, *, key: str = "") -> Any:
    """Remove scorer/oracle metadata from a mapping without changing evidence."""
    lowered = key.lower()
    if lowered in _GOLD_KEYS or any(token in lowered for token in ("gold", "expected", "oracle", "hidden", "future")):
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            child_key = str(raw_key)
            projected = _public_value(raw_value, key=child_key)
            if projected is not None:
                result[child_key] = projected
        return result
    if isinstance(value, (list, tuple)):
        return [_public_value(item, key=key) for item in value]
    return value


def public_case_projection(sample: Any) -> dict[str, Any]:
    """Build the single public case shared by all four lanes.

    Only task/request and explicitly public source descriptors are included.
    The returned object is suitable for provider prompts; it intentionally
    excludes expected facts and scorer metadata.
    """
    spec = getattr(sample, "canonical_task_spec", None)
    arguments = dict(getattr(spec, "arguments", {}) or {})
    public_arguments: dict[str, Any] = {}
    allowed_argument_keys = {
        "ticker", "quarter", "metric", "document_path", "csv_path", "log_path",
        "source_ids", "public_doc_ids", "public_sources", "table", "text",
        "source_document", "source_path", "tickers", "quarters",
        "task_family", "dataset_id", "dataset_version", "dataset_split",
    }
    for key, value in arguments.items():
        if str(key) in allowed_argument_keys:
            projected = _public_value(value, key=str(key))
            if projected is not None:
                public_arguments[str(key)] = projected
    public_sources = public_arguments.get("public_sources")
    if public_sources is None:
        public_sources = []
        for key in ("public_doc_ids", "source_ids"):
            value = public_arguments.get(key)
            if isinstance(value, list):
                public_sources.extend(str(item) for item in value if str(item).strip())
        for key in ("document_path", "csv_path", "log_path", "source_document", "source_path"):
            value = public_arguments.get(key)
            if isinstance(value, str) and value.strip():
                public_sources.append(value)
    public_spec = {
        "task_family": str(getattr(spec, "task_family", "")),
        "intent_op": str(getattr(spec, "intent_op", "")),
        "required_outputs": [str(item) for item in getattr(spec, "required_outputs", ())],
        "arguments": public_arguments,
    }
    # Preserve public dataset identity, but never copy the full canonical spec.
    return {
        "case_id": str(getattr(sample, "task_id", "")),
        "family": str(getattr(sample, "task_family", getattr(spec, "task_family", ""))),
        "dataset_id": str(getattr(sample, "dataset_id", "")),
        "dataset_version": str(getattr(sample, "dataset_version", "")),
        "split": str(getattr(sample, "dataset_split", "")),
        "request": str(getattr(sample, "request_text", "")),
        "task_spec": public_spec,
        "public_sources": list(dict.fromkeys(str(item) for item in public_sources if str(item).strip())),
    }


def validate_public_case(case: Mapping[str, Any]) -> tuple[str, ...]:
    errors: list[str] = []
    for forbidden_path in _forbidden_paths(case):
        errors.append(f"forbidden_public_field:{forbidden_path}")
    case_id = str(case.get("case_id", "")).strip()
    if not case_id:
        errors.append("missing_case_id")
    sources = case.get("public_sources", ())
    if not isinstance(sources, list) or any(not str(item).strip() for item in sources):
        errors.append("invalid_public_sources")
    if len(set(str(item) for item in sources)) != len(sources):
        errors.append("duplicate_public_source_id")
    task_spec = case.get("task_spec", {})
    if not isinstance(task_spec, Mapping):
        errors.append("invalid_task_spec")
    elif not str(task_spec.get("task_family", "")).strip():
        errors.append("missing_task_family")
    return tuple(errors)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def canonical_output_projection(
    payload: Mapping[str, Any],
    *,
    observed_metric_name: str = "",
    observed_metric_value: Any = None,
    selected_doc_ids: Iterable[str] = (),
    allowed_doc_ids: Iterable[str] | None = None,
    required_outputs: Iterable[str] = (),
    output_path: str = "",
    report_path: str = "",
) -> dict[str, Any]:
    """Return the business-output projection plus non-blocking provenance diagnostics."""
    # Project recursively before validating.  Top-level ``pop`` alone lets
    # nested oracle fields in rows or public-tool payloads leak into the
    # provider/output surface.
    output = _public_value(dict(payload))
    if not isinstance(output, dict):
        output = {}
    errors: list[str] = []
    provenance_errors: list[str] = []
    raw_doc_ids = [str(item).strip() for item in selected_doc_ids if str(item).strip()]
    if len(set(raw_doc_ids)) != len(raw_doc_ids):
        provenance_errors.append("duplicate_doc_id")
    output["selected_doc_ids"] = list(dict.fromkeys(raw_doc_ids))
    if allowed_doc_ids is not None:
        allowed = {str(item) for item in allowed_doc_ids}
        unknown = sorted(set(output["selected_doc_ids"]) - allowed)
        if unknown:
            provenance_errors.append(f"unknown_doc_id:{','.join(unknown)}")
    output["output_path"] = output_path
    output["report_path"] = report_path
    if output_path and report_path and output_path == report_path:
        errors.append("output_report_path_must_differ")
    for field in required_outputs:
        value = output.get(str(field))
        if value is None and isinstance(output.get("rows"), list):
            rows = output["rows"]
            if rows and all(
                isinstance(row, Mapping)
                and row.get(str(field)) is not None
                and not (isinstance(row.get(str(field)), str) and not str(row.get(str(field))).strip())
                for row in rows
            ):
                value = rows
        if value is None or (isinstance(value, str) and not value.strip()):
            errors.append(f"missing_required_output:{field}")
    metric_name = str(observed_metric_name or output.get("metric_name", "")).strip()
    metric_value = observed_metric_value if observed_metric_value is not None else output.get("metric_value")
    if metric_name:
        output["metric_name"] = metric_name
    if metric_value is not None:
        output["metric_value"] = metric_value
    if metric_name == "revenue" and metric_value is not None:
        output["revenue_value"] = metric_value
    else:
        output.pop("revenue_value", None)
    if metric_value is not None:
        if isinstance(metric_value, (int, float)) and not _finite_number(metric_value):
            errors.append("metric_value_not_finite")
        elif isinstance(metric_value, str) and metric_value.strip().lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
            errors.append("metric_value_not_finite")
    rows = output.get("rows")
    if isinstance(rows, list):
        seen: set[str] = set()
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                errors.append(f"row_not_object:{index}")
                continue
            identity = str(row.get("row_id", row.get("period", index)))
            if identity in seen:
                errors.append(f"duplicate_row_identity:{identity}")
            seen.add(identity)
    output["projection_errors"] = errors
    output["projection_valid"] = not errors
    output["provenance_errors"] = provenance_errors
    output["provenance_valid"] = not provenance_errors
    # Keep compatibility aliases at the top level for existing scorers, while
    # making the output/provenance boundary explicit and auditable.
    provenance = output.get("provenance")
    if not isinstance(provenance, Mapping):
        provenance = {}
    provenance_payload = dict(provenance)
    for key in _PROVENANCE_KEYS:
        if key in output and key != "provenance":
            provenance_payload.setdefault(key, output[key])
    output["provenance"] = provenance_payload
    output["projection_domains"] = {
        "output": sorted(key for key in output if key not in _PROVENANCE_KEYS),
        "provenance": sorted(provenance_payload),
    }
    return output


@dataclass(frozen=True)
class SlotIdentity:
    run_id: str
    case_id: str
    split: str
    round: int
    repeat: int
    seed: int | str
    profile_id: str
    regime: str
    lane: str

    @property
    def pair_id(self) -> str:
        return "::".join((self.run_id, self.case_id, self.split, str(self.round), str(self.repeat), str(self.seed), self.profile_id, self.regime))

    @property
    def slot_id(self) -> str:
        return f"{self.pair_id}::{self.lane}"


def compare_slot_sets(planned: Iterable[str], observed: Iterable[str]) -> dict[str, list[str] | bool]:
    planned_list = list(planned)
    observed_list = list(observed)
    planned_set = set(planned_list)
    observed_set = set(observed_list)
    duplicates = sorted({item for item in observed_list if observed_list.count(item) > 1})
    missing = sorted(planned_set - observed_set)
    extra = sorted(observed_set - planned_set)
    return {"closed": not missing and not extra and not duplicates and len(planned_set) == len(planned_list), "missing": missing, "extra": extra, "duplicate": duplicates}


def metric_status(value: Any, *, source_ref: str | None = None, reason: str | None = None) -> dict[str, Any]:
    if value is None:
        return {"status": "missing", "value": None, "unit": "ms", "source_ref": source_ref, "reason": reason or "not_observed"}
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
        return {"status": "observed", "value": value, "unit": "ms", "source_ref": source_ref, "reason": None}
    return {"status": "invalid", "value": None, "unit": "ms", "source_ref": source_ref, "reason": reason or "non_finite_or_non_numeric"}
