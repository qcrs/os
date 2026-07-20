from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from v2.contracts import CONTROL_PLANE_SCHEMA_VERSION
from v2.control.schema import message_class


class EventType(IntEnum):
    EVENT_TYPE_UNSPECIFIED = 0
    REQ_EXEC = 1
    ACK_RECV = 2
    RUN_START = 3
    HEARTBEAT = 4
    RES_SUCC = 5
    RES_ERR = 6
    CMD_CANCEL = 7
    TRAP_FATAL = 8
    CMD_GC = 9


@dataclass(frozen=True)
class ControlHeader:
    trace_id: str
    task_id: str
    step_id: str
    attempt_id: str
    target_role: str
    timeout_ms: int
    event_type: EventType
    schema_version: str = CONTROL_PLANE_SCHEMA_VERSION


@dataclass(frozen=True)
class RefHandle:
    ref_id: str
    ref_kind: str


@dataclass(frozen=True)
class ReusePolicy:
    allow_assist: bool = True
    allow_validated_replay: bool = False
    allow_exact_replay: bool = False


@dataclass(frozen=True)
class ExecRequest:
    header: ControlHeader
    reuse_policy: ReusePolicy = field(default_factory=ReusePolicy)
    state_refs: tuple[RefHandle, ...] = ()
    artifact_refs: tuple[RefHandle, ...] = ()
    memory_refs: tuple[RefHandle, ...] = ()
    runtime_reuse_contract: str = ""
    output_contract_version: str = ""
    workspace_root: str = ""
    input_manifest_hash: str = ""
    operation: str = ""
    state_root: str = ""
    hydrate_manifest_id: str = ""
    semantic_top_k: int = 0
    evidence_budget_bytes: int = 0
    expected_encoder_signature: str = ""
    capability_grant_hash: str = ""


@dataclass(frozen=True)
class AckReceived:
    header: ControlHeader
    acked_at_ns: int


@dataclass(frozen=True)
class RunStart:
    header: ControlHeader
    started_at_ns: int
    heartbeat_interval_ms: int
    lease_timeout_ms: int


@dataclass(frozen=True)
class Heartbeat:
    header: ControlHeader
    sent_at_ns: int
    worker_state: str = ""


@dataclass(frozen=True)
class SuccessResult:
    header: ControlHeader
    state_refs: tuple[RefHandle, ...] = ()
    artifact_refs: tuple[RefHandle, ...] = ()
    output_contract_version: str = ""
    completed_at_ns: int = 0
    consumed_state_ref_id: str = ""
    selected_candidate_ids: tuple[str, ...] = ()
    selected_scores: tuple[float, ...] = ()
    selected_row_indices: tuple[int, ...] = ()
    selected_evidence_bytes: int = 0
    consumer_pid: int = 0
    producer_pid: int = 0
    encoder_signature: str = ""


@dataclass(frozen=True)
class ErrorResult:
    header: ControlHeader
    error_code: str
    error_detail: str
    failed_at_ns: int


@dataclass(frozen=True)
class CancelCommand:
    header: ControlHeader
    reason: str
    issued_at_ns: int


@dataclass(frozen=True)
class TrapFatal:
    header: ControlHeader
    trap_reason: str
    error_detail: str
    trapped_at_ns: int


@dataclass(frozen=True)
class GarbageCollectCommand:
    header: ControlHeader
    ref_ids: tuple[str, ...]
    issued_at_ns: int


ControlMessage = (
    ExecRequest
    | AckReceived
    | RunStart
    | Heartbeat
    | SuccessResult
    | ErrorResult
    | CancelCommand
    | TrapFatal
    | GarbageCollectCommand
)


_BODY_FIELD_BY_TYPE: dict[type, str] = {
    ExecRequest: "req_exec",
    AckReceived: "ack_recv",
    RunStart: "run_start",
    Heartbeat: "heartbeat",
    SuccessResult: "res_succ",
    ErrorResult: "res_err",
    CancelCommand: "cmd_cancel",
    TrapFatal: "trap_fatal",
    GarbageCollectCommand: "cmd_gc",
}

_TYPE_BY_BODY_FIELD = {value: key for key, value in _BODY_FIELD_BY_TYPE.items()}


def _header_to_pb(header: ControlHeader) -> Any:
    pb = message_class("ControlHeader")()
    pb.trace_id = header.trace_id
    pb.task_id = header.task_id
    pb.step_id = header.step_id
    pb.attempt_id = header.attempt_id
    pb.target_role = header.target_role
    pb.timeout_ms = header.timeout_ms
    pb.schema_version = header.schema_version
    pb.event_type = int(header.event_type)
    return pb


def _header_from_pb(pb: Any) -> ControlHeader:
    return ControlHeader(
        trace_id=pb.trace_id,
        task_id=pb.task_id,
        step_id=pb.step_id,
        attempt_id=pb.attempt_id,
        target_role=pb.target_role,
        timeout_ms=int(pb.timeout_ms),
        schema_version=pb.schema_version or CONTROL_PLANE_SCHEMA_VERSION,
        event_type=EventType(pb.event_type),
    )


def _ref_to_pb(handle: RefHandle) -> Any:
    pb = message_class("RefHandle")()
    pb.ref_id = handle.ref_id
    pb.ref_kind = handle.ref_kind
    return pb


def _ref_from_pb(pb: Any) -> RefHandle:
    return RefHandle(ref_id=pb.ref_id, ref_kind=pb.ref_kind)


def encode_control_message(message: ControlMessage) -> bytes:
    envelope = message_class("ControlEnvelope")()
    body_field = _BODY_FIELD_BY_TYPE[type(message)]
    body_pb = getattr(envelope, body_field)
    body_pb.header.CopyFrom(_header_to_pb(message.header))

    if isinstance(message, ExecRequest):
        reuse_pb = message_class("ReusePolicy")()
        reuse_pb.allow_assist = message.reuse_policy.allow_assist
        reuse_pb.allow_validated_replay = message.reuse_policy.allow_validated_replay
        reuse_pb.allow_exact_replay = message.reuse_policy.allow_exact_replay
        body_pb.reuse_policy.CopyFrom(reuse_pb)
        body_pb.state_refs.extend(_ref_to_pb(ref) for ref in message.state_refs)
        body_pb.artifact_refs.extend(_ref_to_pb(ref) for ref in message.artifact_refs)
        body_pb.memory_refs.extend(_ref_to_pb(ref) for ref in message.memory_refs)
        body_pb.runtime_reuse_contract = message.runtime_reuse_contract
        body_pb.output_contract_version = message.output_contract_version
        body_pb.workspace_root = message.workspace_root
        body_pb.input_manifest_hash = message.input_manifest_hash
        body_pb.operation = message.operation
        body_pb.state_root = message.state_root
        body_pb.hydrate_manifest_id = message.hydrate_manifest_id
        body_pb.semantic_top_k = message.semantic_top_k
        body_pb.evidence_budget_bytes = message.evidence_budget_bytes
        body_pb.expected_encoder_signature = message.expected_encoder_signature
        body_pb.capability_grant_hash = message.capability_grant_hash
    elif isinstance(message, AckReceived):
        body_pb.acked_at_ns = message.acked_at_ns
    elif isinstance(message, RunStart):
        body_pb.started_at_ns = message.started_at_ns
        body_pb.heartbeat_interval_ms = message.heartbeat_interval_ms
        body_pb.lease_timeout_ms = message.lease_timeout_ms
    elif isinstance(message, Heartbeat):
        body_pb.sent_at_ns = message.sent_at_ns
        body_pb.worker_state = message.worker_state
    elif isinstance(message, SuccessResult):
        body_pb.state_refs.extend(_ref_to_pb(ref) for ref in message.state_refs)
        body_pb.artifact_refs.extend(_ref_to_pb(ref) for ref in message.artifact_refs)
        body_pb.output_contract_version = message.output_contract_version
        body_pb.completed_at_ns = message.completed_at_ns
        body_pb.consumed_state_ref_id = message.consumed_state_ref_id
        body_pb.selected_candidate_ids.extend(message.selected_candidate_ids)
        body_pb.selected_scores.extend(message.selected_scores)
        body_pb.selected_row_indices.extend(message.selected_row_indices)
        body_pb.selected_evidence_bytes = message.selected_evidence_bytes
        body_pb.consumer_pid = message.consumer_pid
        body_pb.producer_pid = message.producer_pid
        body_pb.encoder_signature = message.encoder_signature
    elif isinstance(message, ErrorResult):
        body_pb.error_code = message.error_code
        body_pb.error_detail = message.error_detail
        body_pb.failed_at_ns = message.failed_at_ns
    elif isinstance(message, CancelCommand):
        body_pb.reason = message.reason
        body_pb.issued_at_ns = message.issued_at_ns
    elif isinstance(message, TrapFatal):
        body_pb.trap_reason = message.trap_reason
        body_pb.error_detail = message.error_detail
        body_pb.trapped_at_ns = message.trapped_at_ns
    elif isinstance(message, GarbageCollectCommand):
        body_pb.ref_ids.extend(message.ref_ids)
        body_pb.issued_at_ns = message.issued_at_ns
    else:
        raise TypeError(f"unsupported control message type: {type(message)!r}")
    return envelope.SerializeToString()


def decode_control_message(payload: bytes) -> ControlMessage:
    envelope = message_class("ControlEnvelope")()
    envelope.ParseFromString(payload)
    body_field = envelope.WhichOneof("body")
    if not body_field:
        raise ValueError("control envelope body is missing")
    body_pb = getattr(envelope, body_field)
    header = _header_from_pb(body_pb.header)

    if body_field == "req_exec":
        reuse = body_pb.reuse_policy
        return ExecRequest(
            header=header,
            reuse_policy=ReusePolicy(
                allow_assist=bool(reuse.allow_assist),
                allow_validated_replay=bool(reuse.allow_validated_replay),
                allow_exact_replay=bool(reuse.allow_exact_replay),
            ),
            state_refs=tuple(_ref_from_pb(ref) for ref in body_pb.state_refs),
            artifact_refs=tuple(_ref_from_pb(ref) for ref in body_pb.artifact_refs),
            memory_refs=tuple(_ref_from_pb(ref) for ref in body_pb.memory_refs),
            runtime_reuse_contract=body_pb.runtime_reuse_contract,
            output_contract_version=body_pb.output_contract_version,
            workspace_root=body_pb.workspace_root,
            input_manifest_hash=body_pb.input_manifest_hash,
            operation=body_pb.operation,
            state_root=body_pb.state_root,
            hydrate_manifest_id=body_pb.hydrate_manifest_id,
            semantic_top_k=int(body_pb.semantic_top_k),
            evidence_budget_bytes=int(body_pb.evidence_budget_bytes),
            expected_encoder_signature=body_pb.expected_encoder_signature,
            capability_grant_hash=body_pb.capability_grant_hash,
        )
    if body_field == "ack_recv":
        return AckReceived(header=header, acked_at_ns=int(body_pb.acked_at_ns))
    if body_field == "run_start":
        return RunStart(
            header=header,
            started_at_ns=int(body_pb.started_at_ns),
            heartbeat_interval_ms=int(body_pb.heartbeat_interval_ms),
            lease_timeout_ms=int(body_pb.lease_timeout_ms),
        )
    if body_field == "heartbeat":
        return Heartbeat(
            header=header,
            sent_at_ns=int(body_pb.sent_at_ns),
            worker_state=body_pb.worker_state,
        )
    if body_field == "res_succ":
        return SuccessResult(
            header=header,
            state_refs=tuple(_ref_from_pb(ref) for ref in body_pb.state_refs),
            artifact_refs=tuple(_ref_from_pb(ref) for ref in body_pb.artifact_refs),
            output_contract_version=body_pb.output_contract_version,
            completed_at_ns=int(body_pb.completed_at_ns),
            consumed_state_ref_id=body_pb.consumed_state_ref_id,
            selected_candidate_ids=tuple(body_pb.selected_candidate_ids),
            selected_scores=tuple(float(value) for value in body_pb.selected_scores),
            selected_row_indices=tuple(int(value) for value in body_pb.selected_row_indices),
            selected_evidence_bytes=int(body_pb.selected_evidence_bytes),
            consumer_pid=int(body_pb.consumer_pid),
            producer_pid=int(body_pb.producer_pid),
            encoder_signature=body_pb.encoder_signature,
        )
    if body_field == "res_err":
        return ErrorResult(
            header=header,
            error_code=body_pb.error_code,
            error_detail=body_pb.error_detail,
            failed_at_ns=int(body_pb.failed_at_ns),
        )
    if body_field == "cmd_cancel":
        return CancelCommand(
            header=header,
            reason=body_pb.reason,
            issued_at_ns=int(body_pb.issued_at_ns),
        )
    if body_field == "trap_fatal":
        return TrapFatal(
            header=header,
            trap_reason=body_pb.trap_reason,
            error_detail=body_pb.error_detail,
            trapped_at_ns=int(body_pb.trapped_at_ns),
        )
    if body_field == "cmd_gc":
        return GarbageCollectCommand(
            header=header,
            ref_ids=tuple(body_pb.ref_ids),
            issued_at_ns=int(body_pb.issued_at_ns),
        )
    raise ValueError(f"unsupported control envelope body: {body_field}")


def frame_control_message(message: ControlMessage) -> bytes:
    payload = encode_control_message(message)
    return struct.pack(">I", len(payload)) + payload


def deframe_control_message(frame: bytes) -> ControlMessage:
    if len(frame) < 4:
        raise ValueError("control frame missing length prefix")
    (payload_len,) = struct.unpack(">I", frame[:4])
    payload = frame[4:]
    if len(payload) != payload_len:
        raise ValueError(
            f"control frame payload length mismatch: expected {payload_len}, got {len(payload)}"
        )
    return decode_control_message(payload)
