from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from statebus.control.messages import (
    AckReceived,
    ControlMessage,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RunStart,
    SuccessResult,
    TrapFatal,
)


class ControlResponseOrigin(str, Enum):
    NATIVE_TYPED_WORKER = "NATIVE_TYPED_WORKER"
    ADAPTER_DERIVED = "ADAPTER_DERIVED"
    LEGACY_COMPATIBILITY = "LEGACY_COMPATIBILITY"


_SCOPE_FIELDS = (
    "trace_id",
    "task_id",
    "run_id",
    "session_id",
    "step_id",
    "attempt_id",
    "invocation_id",
    "target_role",
    "timeout_ms",
    "execution_binding_hash",
    "capability_grant_hash",
    "schema_version",
)

_EXPECTED_EVENT_BY_TYPE = {
    AckReceived: EventType.ACK_RECV,
    RunStart: EventType.RUN_START,
    Heartbeat: EventType.HEARTBEAT,
    SuccessResult: EventType.RES_SUCC,
    ErrorResult: EventType.RES_ERR,
    TrapFatal: EventType.TRAP_FATAL,
}

_TERMINAL_TYPES = (SuccessResult, ErrorResult, TrapFatal)

_CANONICAL_SCOPE_FIELDS = (
    "run_id",
    "session_id",
    "invocation_id",
    "execution_binding_hash",
    "capability_grant_hash",
)


def _scope_items(header: object) -> tuple[tuple[str, str | int], ...]:
    return tuple((field_name, getattr(header, field_name)) for field_name in _SCOPE_FIELDS)


@dataclass(frozen=True)
class ControlResponseAdmissionReceipt:
    invocation_id: str
    attempt_id: str
    execution_binding_hash: str
    capability_grant_hash: str
    event_type: str
    admitted: bool
    reason_code: str
    terminal: bool
    origin: ControlResponseOrigin
    expected_scope: tuple[tuple[str, str | int], ...]
    observed_scope: tuple[tuple[str, str | int], ...]
    terminal_count: int
    output_contract_decision: str

    def canonical_payload(self) -> dict[str, object]:
        return {
            "invocation_id": self.invocation_id,
            "attempt_id": self.attempt_id,
            "execution_binding_hash": self.execution_binding_hash,
            "capability_grant_hash": self.capability_grant_hash,
            "event_type": self.event_type,
            "admitted": self.admitted,
            "reason_code": self.reason_code,
            "terminal": self.terminal,
            "origin": self.origin.value,
            "expected_scope": dict(self.expected_scope),
            "observed_scope": dict(self.observed_scope),
            "terminal_count": self.terminal_count,
            "output_contract_decision": self.output_contract_decision,
        }


class ControlResponseAdmissionError(ValueError):
    def __init__(self, receipts: Iterable[ControlResponseAdmissionReceipt]) -> None:
        self.receipts = tuple(receipts)
        rejected = tuple(receipt for receipt in self.receipts if not receipt.admitted)
        reason = rejected[0].reason_code if rejected else "response_not_admitted"
        super().__init__(f"control_response_admission_rejected:{reason}")


def _scope_mismatch_reason(
    expected_scope: tuple[tuple[str, str | int], ...],
    observed_scope: tuple[tuple[str, str | int], ...],
) -> str | None:
    for (field_name, expected), (_, observed) in zip(expected_scope, observed_scope):
        if observed != expected:
            return f"scope_mismatch:{field_name}"
    return None


def _expected_scope_reason(request: ExecRequest) -> str | None:
    values = tuple(
        str(getattr(request.header, field_name)).strip()
        for field_name in _CANONICAL_SCOPE_FIELDS
    )
    if not any(values):
        return None
    for field_name, value in zip(_CANONICAL_SCOPE_FIELDS, values):
        if not value:
            return f"expected_scope_missing:{field_name}"
    return None


def _event_order_reason(message: ControlMessage, phase: str) -> str | None:
    if phase == "terminal":
        return "event_after_terminal"
    if isinstance(message, AckReceived):
        return None if phase == "initial" else "illegal_event_order"
    if isinstance(message, RunStart):
        return None if phase == "acked" else "illegal_event_order"
    if isinstance(message, Heartbeat):
        return None if phase == "running" else "illegal_event_order"
    if isinstance(message, SuccessResult):
        return None if phase == "running" else "illegal_event_order"
    if isinstance(message, ErrorResult):
        return None
    if isinstance(message, TrapFatal):
        return None if phase == "running" else "illegal_event_order"
    return "illegal_message_type"


def _next_phase(message: ControlMessage, phase: str) -> str:
    if isinstance(message, AckReceived):
        return "acked"
    if isinstance(message, RunStart):
        return "running"
    if isinstance(message, _TERMINAL_TYPES):
        return "terminal"
    return phase


def _semantic_result_reason(request: ExecRequest, response: SuccessResult) -> str | None:
    if len(request.state_refs) != 1:
        return "semantic_request_state_ref_count_invalid"
    if request.state_refs[0].ref_kind != "semantic_state":
        return "semantic_request_state_ref_kind_invalid"
    if len(response.state_refs) != 1:
        return "semantic_response_state_ref_count_invalid"
    expected_ref = request.state_refs[0]
    if response.state_refs[0] != expected_ref:
        return "semantic_state_ref_mismatch"
    if response.consumed_state_ref_id != expected_ref.ref_id:
        return "semantic_consumed_state_ref_mismatch"
    cardinalities = {
        len(response.selected_candidate_ids),
        len(response.selected_scores),
        len(response.selected_row_indices),
    }
    if len(cardinalities) != 1:
        return "semantic_result_cardinality_mismatch"
    if len(response.selected_candidate_ids) > request.semantic_top_k:
        return "semantic_result_top_k_exceeded"
    return None


def admit_control_response_sequence(
    request: ExecRequest,
    responses: Iterable[ControlMessage],
    *,
    origin: ControlResponseOrigin,
) -> tuple[tuple[ControlMessage, ...], tuple[ControlResponseAdmissionReceipt, ...]]:
    """Atomically admit a physical response sequence against one request."""
    candidates = tuple(responses)
    expected_scope = _scope_items(request.header)
    expected_scope_reason = _expected_scope_reason(request)
    receipts: list[ControlResponseAdmissionReceipt] = []
    phase = "initial"
    terminal_count = 0

    for message in candidates:
        header = message.header
        observed_scope = _scope_items(header)
        terminal = isinstance(message, _TERMINAL_TYPES)
        if terminal:
            terminal_count += 1

        expected_event = _EXPECTED_EVENT_BY_TYPE.get(type(message))
        reason_code = "admitted"
        output_contract_decision = "not_applicable"
        request_rejection = (
            isinstance(message, ErrorResult)
            and message.error_code == "invalid_exec_request"
        )
        if expected_scope_reason is not None and not request_rejection:
            reason_code = expected_scope_reason
        elif expected_event is None:
            reason_code = "illegal_message_type"
        elif header.event_type != expected_event:
            reason_code = "event_type_mismatch"
        else:
            reason_code = _scope_mismatch_reason(expected_scope, observed_scope) or "admitted"

        if reason_code == "admitted" and terminal_count > 1:
            reason_code = "duplicate_terminal"
        if reason_code == "admitted":
            reason_code = _event_order_reason(message, phase) or "admitted"

        if isinstance(message, SuccessResult):
            if message.output_contract_version == request.output_contract_version:
                output_contract_decision = "matched"
            else:
                output_contract_decision = "mismatch"
                if reason_code == "admitted":
                    reason_code = "output_contract_mismatch"
            if reason_code == "admitted" and request.operation == "semantic_select_v1":
                reason_code = _semantic_result_reason(request, message) or "admitted"

        receipt = ControlResponseAdmissionReceipt(
            invocation_id=header.invocation_id,
            attempt_id=header.attempt_id,
            execution_binding_hash=header.execution_binding_hash,
            capability_grant_hash=header.capability_grant_hash,
            event_type=header.event_type.name,
            admitted=reason_code == "admitted",
            reason_code=reason_code,
            terminal=terminal,
            origin=origin,
            expected_scope=expected_scope,
            observed_scope=observed_scope,
            terminal_count=terminal_count,
            output_contract_decision=output_contract_decision,
        )
        receipts.append(receipt)

        if expected_event is not None and header.event_type == expected_event:
            phase = _next_phase(message, phase)

    admitted = (
        tuple(candidates)
        if candidates and all(receipt.admitted for receipt in receipts)
        else ()
    )
    return admitted, tuple(receipts)
