from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from statebus.contracts import (
    CandidateSurfaceV2,
    LogitGateAction,
    LogitGateReceipt,
)
from statebus.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from statebus.runtime.logit_state import ExactChoiceLogitResult
from statebus.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    publish_logit_state,
    release_logit_state,
)
from statebus.utils import sha256_digest


class LogitGateError(RuntimeError):
    pass


class LogitGateMode(StrEnum):
    OFF = "off"
    TELEMETRY = "telemetry"
    RETRY_ONCE = "retry_once"


def normalize_logit_gate_mode(value: str) -> LogitGateMode:
    normalized = str(value).strip().lower() or LogitGateMode.OFF.value
    try:
        return LogitGateMode(normalized)
    except ValueError as exc:
        raise ValueError(
            "STATEBUS_LOGIT_GATE_MODE must be off, telemetry, or retry_once"
        ) from exc


@dataclass(frozen=True)
class LogitGateAttempt:
    attempt_index: int
    state_id: str
    storage_kind: str
    state_bytes: int
    producer_receipt: dict[str, Any]
    gate_receipt: LogitGateReceipt
    transport_audit: dict[str, Any]
    tombstone_path: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "attempt_index": self.attempt_index,
            "state_id": self.state_id,
            "storage_kind": self.storage_kind,
            "state_bytes": self.state_bytes,
            "producer_receipt": self.producer_receipt,
            "gate_receipt": self.gate_receipt.canonical_payload(),
            "transport_audit": self.transport_audit,
            "tombstone_path": self.tombstone_path,
        }


def make_logit_state_store(root: Path) -> LayeredStateStore:
    return LayeredStateStore(
        root=Path(root),
        policy=LayeredStoragePolicy.for_state_pool_mode("shared_memory"),
    )


def evaluate_logit_gate_in_subprocess(
    *,
    state_root: Path,
    state_id: str,
    task_id: str,
    trace_id: str,
    attempt_id: str,
    input_manifest_hash: str,
    timeout_s: float = 20.0,
) -> tuple[LogitGateReceipt, dict[str, Any]]:
    transport = SubprocessExecutorTransport(
        socket_path=Path(state_root) / f".{state_id}.gate.sock",
        timeout_s=timeout_s,
    )
    response = transport.execute(
        ExecRequest(
            header=ControlHeader(
                trace_id=trace_id,
                task_id=task_id,
                step_id="logit.gate",
                attempt_id=attempt_id,
                target_role="logit_gate",
                timeout_ms=max(1, int(timeout_s * 1000)),
                event_type=EventType.REQ_EXEC,
            ),
            state_refs=(RefHandle(ref_id=state_id, ref_kind="logit_state"),),
            artifact_refs=(),
            runtime_reuse_contract="logit_state_required",
            output_contract_version="statebus.logit_gate_receipt.v1",
            workspace_root=str(state_root),
            input_manifest_hash=input_manifest_hash,
            operation="logit_gate_v1",
            state_root=str(state_root),
        )
    )
    if isinstance(response, ErrorResult):
        raise LogitGateError(response.error_detail or response.error_code)
    if not isinstance(response, SuccessResult):
        raise LogitGateError("logit_gate_result_missing")
    if response.consumed_state_ref_id != state_id:
        raise LogitGateError("logit_gate_consumed_ref_mismatch")
    audit = transport.last_exchange_audit
    if audit is None or audit.worker_pid <= 0:
        raise LogitGateError("logit_gate_transport_audit_missing")
    if response.consumer_pid != audit.worker_pid:
        raise LogitGateError("logit_gate_consumer_pid_mismatch")
    try:
        receipt = LogitGateReceipt(
            state_id=state_id,
            decision_id=response.decision_id,
            action=LogitGateAction(response.gate_action),
            reason=response.gate_reason,
            selected_alias=response.selected_alias,
            selected_candidate_id=response.selected_candidate_id,
            top1_alias=response.top1_alias,
            selected_probability=response.selected_probability,
            top_margin=response.top_margin,
            normalized_entropy=response.normalized_entropy,
            other_mass=response.other_mass,
            candidate_count=response.gate_candidate_count,
            producer_pid=response.producer_pid,
            consumer_pid=response.consumer_pid,
            margin_threshold=response.margin_threshold,
        )
    except (TypeError, ValueError) as exc:
        raise LogitGateError(str(exc) or "logit_gate_receipt_invalid") from exc
    return receipt, audit.canonical_payload()


def run_logit_gate_attempt(
    *,
    store: LayeredStateStore,
    extraction: ExactChoiceLogitResult,
    candidate_surface: CandidateSurfaceV2,
    task_id: str,
    trace_id: str,
    attempt_index: int,
    timeout_s: float = 20.0,
) -> LogitGateAttempt:
    identity = {
        "task_id": task_id,
        "trace_id": trace_id,
        "attempt_id": extraction.receipt.attempt_id,
        "candidate_surface_digest": candidate_surface.candidate_surface_digest,
    }
    state_id = f"logit-{sha256_digest(identity)[:24]}"
    publication = publish_logit_state(
        store=store,
        extraction=extraction,
        candidate_surface=candidate_surface,
        task_id=task_id,
        trace_id=trace_id,
        state_id=state_id,
    )
    gate_receipt: LogitGateReceipt | None = None
    transport_audit: dict[str, Any] = {}
    tombstone_path = ""
    try:
        gate_receipt, transport_audit = evaluate_logit_gate_in_subprocess(
            state_root=store.root,
            state_id=publication.ref.state_id,
            task_id=task_id,
            trace_id=trace_id,
            attempt_id=extraction.receipt.attempt_id,
            input_manifest_hash=publication.ref.blob_hash,
            timeout_s=timeout_s,
        )
        if gate_receipt.producer_pid != publication.contract.producer_pid:
            raise LogitGateError("logit_gate_producer_pid_mismatch")
        if gate_receipt.selected_alias != extraction.selected_alias:
            raise LogitGateError("logit_gate_selected_alias_mismatch")
        if gate_receipt.selected_candidate_id != extraction.selected_candidate_id:
            raise LogitGateError("logit_gate_selected_candidate_mismatch")
    finally:
        tombstone_path = str(
            release_logit_state(
                store=store,
                publication=publication,
                reason="consumed" if gate_receipt is not None else "rejected",
                consumer_pid=0 if gate_receipt is None else gate_receipt.consumer_pid,
            )
        )
    if gate_receipt is None:
        raise LogitGateError("logit_gate_result_missing")
    return LogitGateAttempt(
        attempt_index=attempt_index,
        state_id=publication.ref.state_id,
        storage_kind=publication.ref.storage_kind.value,
        state_bytes=publication.ref.length,
        producer_receipt=extraction.receipt.canonical_payload(),
        gate_receipt=gate_receipt,
        transport_audit=transport_audit,
        tombstone_path=tombstone_path,
    )
