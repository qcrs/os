from __future__ import annotations

import json
import math
from typing import Iterable

from v2.control.messages import NumericSummaryResult
from v2.utils import sha256_digest, stable_json_dumps


TYPED_NUMERIC_INPUT_SCHEMA_VERSION = "statebus.numeric_vector.v1"
TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION = "statebus.numeric_summary.v1"
TYPED_NUMERIC_VALIDATOR_VERSION = "statebus.numeric_summary_validator.v1"


class TypedNumericOperationError(ValueError):
    pass


def encode_typed_numeric_input(values: Iterable[float]) -> bytes:
    normalized = [_numeric_value(value) for value in values]
    if not normalized:
        raise TypedNumericOperationError("numeric_input_empty")
    return stable_json_dumps({
        "schema_version": TYPED_NUMERIC_INPUT_SCHEMA_VERSION,
        "values": normalized,
    }).encode("utf-8")


def _numeric_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypedNumericOperationError("numeric_input_value_invalid")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise TypedNumericOperationError("numeric_input_value_not_finite")
    return normalized


def _decode_typed_numeric_input(payload: bytes) -> tuple[float, ...]:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TypedNumericOperationError("numeric_input_json_invalid") from exc
    if not isinstance(decoded, dict):
        raise TypedNumericOperationError("numeric_input_object_required")
    if set(decoded) != {"schema_version", "values"}:
        raise TypedNumericOperationError("numeric_input_fields_invalid")
    if decoded.get("schema_version") != TYPED_NUMERIC_INPUT_SCHEMA_VERSION:
        raise TypedNumericOperationError("numeric_input_schema_mismatch")
    raw_values = decoded.get("values")
    if not isinstance(raw_values, list) or not raw_values:
        raise TypedNumericOperationError("numeric_input_values_missing")
    return tuple(_numeric_value(value) for value in raw_values)


def _schema_digest() -> str:
    return sha256_digest({
        "schema_version": TYPED_NUMERIC_INPUT_SCHEMA_VERSION,
        "fields": [{"name": "value", "type": "finite_number"}],
    })


def _output_payload(
    *,
    input_ref_id: str,
    input_payload_hash: str,
    row_count: int,
    total: float,
    mean: float,
    minimum: float,
    maximum: float,
    schema_digest: str,
) -> dict[str, object]:
    return {
        "contract_version": TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION,
        "input_ref_id": input_ref_id,
        "input_payload_hash": input_payload_hash,
        "row_count": row_count,
        "total": total,
        "mean": mean,
        "minimum": minimum,
        "maximum": maximum,
        "schema_digest": schema_digest,
    }


def compute_typed_numeric_summary(
    payload: bytes,
    *,
    input_ref_id: str,
    worker_pid: int,
    worker_compute_ns: int = 0,
) -> NumericSummaryResult:
    values = _decode_typed_numeric_input(payload)
    row_count = len(values)
    total = math.fsum(values)
    mean = total / row_count
    minimum = min(values)
    maximum = max(values)
    input_payload_hash = sha256_digest(payload)
    schema_digest = _schema_digest()
    output_artifact_hash = sha256_digest(_output_payload(
        input_ref_id=input_ref_id,
        input_payload_hash=input_payload_hash,
        row_count=row_count,
        total=total,
        mean=mean,
        minimum=minimum,
        maximum=maximum,
        schema_digest=schema_digest,
    ))
    validator_receipt_hash = sha256_digest({
        "validator_version": TYPED_NUMERIC_VALIDATOR_VERSION,
        "operation": "typed_numeric_summary_v1",
        "input_ref_id": input_ref_id,
        "output_artifact_hash": output_artifact_hash,
        "schema_digest": schema_digest,
        "row_count": row_count,
        "worker_pid": worker_pid,
    })
    return NumericSummaryResult(
        input_ref_id=input_ref_id,
        input_payload_hash=input_payload_hash,
        row_count=row_count,
        total=total,
        mean=mean,
        minimum=minimum,
        maximum=maximum,
        schema_digest=schema_digest,
        output_artifact_hash=output_artifact_hash,
        validator_receipt_hash=validator_receipt_hash,
        worker_pid=worker_pid,
        worker_compute_ns=max(int(worker_compute_ns), 0),
    )


def validate_typed_numeric_summary(
    summary: NumericSummaryResult,
    *,
    payload: bytes,
    expected_input_ref_id: str,
    expected_worker_pid: int,
) -> str:
    if summary.input_ref_id != expected_input_ref_id:
        return "numeric_summary_input_ref_mismatch"
    if summary.worker_pid != expected_worker_pid or summary.worker_pid <= 0:
        return "numeric_summary_worker_pid_mismatch"
    try:
        expected = compute_typed_numeric_summary(
            payload,
            input_ref_id=expected_input_ref_id,
            worker_pid=expected_worker_pid,
            worker_compute_ns=summary.worker_compute_ns,
        )
    except TypedNumericOperationError as exc:
        return str(exc)
    if summary != expected:
        return "numeric_summary_content_or_hash_mismatch"
    return ""
