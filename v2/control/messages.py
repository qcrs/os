from __future__ import annotations

from dataclasses import asdict
import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from v2.contracts import CONTROL_PLANE_SCHEMA_VERSION
from v2.control.schema import message_class
from v2.utils import sha256_digest


CONTROL_PROTOCOL_VERSION = "statebus.uds.protobuf.v2"
DEFAULT_WORKER_CAPABILITY_IDS = (
    "echo_refs_v1",
    "semantic_select_v1",
    "typed_numeric_summary_v1",
)


def worker_capability_registry_digest(
    capability_ids: tuple[str, ...] = DEFAULT_WORKER_CAPABILITY_IDS,
) -> str:
    return sha256_digest({
        "protocol_version": CONTROL_PROTOCOL_VERSION,
        "schema_version": CONTROL_PLANE_SCHEMA_VERSION,
        "capability_ids": sorted(set(capability_ids)),
    })


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
    HELLO = 10
    HELLO_ACK = 11


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
class Hello:
    header: ControlHeader
    protocol_versions: tuple[str, ...]
    schema_versions: tuple[str, ...]
    controller_registry_digest: str
    required_capability_ids: tuple[str, ...] = ()
    controller_pid: int = 0


@dataclass(frozen=True)
class HelloAck:
    header: ControlHeader
    accepted: bool
    accepted_protocol_version: str
    accepted_schema_version: str
    worker_registry_digest: str
    supported_capability_ids: tuple[str, ...] = ()
    error_detail: str = ""
    worker_pid: int = 0


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
    capability_grant_token: str = ""
    capability_grant_session_id: str = ""


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
class NumericSummaryResult:
    input_ref_id: str
    input_payload_hash: str
    row_count: int
    total: float
    mean: float
    minimum: float
    maximum: float
    schema_digest: str
    output_artifact_hash: str
    validator_receipt_hash: str
    worker_pid: int
    worker_compute_ns: int


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
    numeric_summary: NumericSummaryResult | None = None


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
    Hello
    | HelloAck
    | ExecRequest
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
    Hello: "hello",
    HelloAck: "hello_ack",
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


def _numeric_summary_to_pb(summary: NumericSummaryResult) -> Any:
    pb = message_class("NumericSummaryResult")()
    pb.input_ref_id = summary.input_ref_id
    pb.input_payload_hash = summary.input_payload_hash
    pb.row_count = summary.row_count
    pb.total = summary.total
    pb.mean = summary.mean
    pb.minimum = summary.minimum
    pb.maximum = summary.maximum
    pb.schema_digest = summary.schema_digest
    pb.output_artifact_hash = summary.output_artifact_hash
    pb.validator_receipt_hash = summary.validator_receipt_hash
    pb.worker_pid = summary.worker_pid
    pb.worker_compute_ns = summary.worker_compute_ns
    return pb


def _numeric_summary_from_pb(pb: Any) -> NumericSummaryResult:
    return NumericSummaryResult(
        input_ref_id=pb.input_ref_id,
        input_payload_hash=pb.input_payload_hash,
        row_count=int(pb.row_count),
        total=float(pb.total),
        mean=float(pb.mean),
        minimum=float(pb.minimum),
        maximum=float(pb.maximum),
        schema_digest=pb.schema_digest,
        output_artifact_hash=pb.output_artifact_hash,
        validator_receipt_hash=pb.validator_receipt_hash,
        worker_pid=int(pb.worker_pid),
        worker_compute_ns=int(pb.worker_compute_ns),
    )


def encode_control_message(message: ControlMessage) -> bytes:
    envelope = message_class("ControlEnvelope")()
    body_field = _BODY_FIELD_BY_TYPE[type(message)]
    body_pb = getattr(envelope, body_field)
    body_pb.header.CopyFrom(_header_to_pb(message.header))

    if isinstance(message, Hello):
        body_pb.protocol_versions.extend(message.protocol_versions)
        body_pb.schema_versions.extend(message.schema_versions)
        body_pb.controller_registry_digest = message.controller_registry_digest
        body_pb.required_capability_ids.extend(message.required_capability_ids)
        body_pb.controller_pid = message.controller_pid
    elif isinstance(message, HelloAck):
        body_pb.accepted = message.accepted
        body_pb.accepted_protocol_version = message.accepted_protocol_version
        body_pb.accepted_schema_version = message.accepted_schema_version
        body_pb.worker_registry_digest = message.worker_registry_digest
        body_pb.supported_capability_ids.extend(message.supported_capability_ids)
        body_pb.error_detail = message.error_detail
        body_pb.worker_pid = message.worker_pid
    elif isinstance(message, ExecRequest):
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
        body_pb.capability_grant_token = message.capability_grant_token
        body_pb.capability_grant_session_id = message.capability_grant_session_id
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
        if message.numeric_summary is not None:
            body_pb.numeric_summary.CopyFrom(
                _numeric_summary_to_pb(message.numeric_summary)
            )
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

    if body_field == "hello":
        return Hello(
            header=header,
            protocol_versions=tuple(body_pb.protocol_versions),
            schema_versions=tuple(body_pb.schema_versions),
            controller_registry_digest=body_pb.controller_registry_digest,
            required_capability_ids=tuple(body_pb.required_capability_ids),
            controller_pid=int(body_pb.controller_pid),
        )
    if body_field == "hello_ack":
        return HelloAck(
            header=header,
            accepted=bool(body_pb.accepted),
            accepted_protocol_version=body_pb.accepted_protocol_version,
            accepted_schema_version=body_pb.accepted_schema_version,
            worker_registry_digest=body_pb.worker_registry_digest,
            supported_capability_ids=tuple(body_pb.supported_capability_ids),
            error_detail=body_pb.error_detail,
            worker_pid=int(body_pb.worker_pid),
        )
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
            capability_grant_token=body_pb.capability_grant_token,
            capability_grant_session_id=body_pb.capability_grant_session_id,
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
            numeric_summary=(
                _numeric_summary_from_pb(body_pb.numeric_summary)
                if body_pb.HasField("numeric_summary")
                else None
            ),
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


def encode_text_control_message(message: ControlMessage) -> bytes:
    """Encode a control message as canonical UTF-8 JSON, without Protobuf."""

    payload = asdict(message)
    payload["message_type"] = _BODY_FIELD_BY_TYPE[type(message)]
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _text_header(payload: dict[str, Any]) -> ControlHeader:
    return ControlHeader(
        trace_id=str(payload["trace_id"]),
        task_id=str(payload["task_id"]),
        step_id=str(payload["step_id"]),
        attempt_id=str(payload["attempt_id"]),
        target_role=str(payload["target_role"]),
        timeout_ms=int(payload["timeout_ms"]),
        event_type=EventType(int(payload["event_type"])),
        schema_version=str(payload.get("schema_version", CONTROL_PLANE_SCHEMA_VERSION)),
    )


def _text_refs(payload: object) -> tuple[RefHandle, ...]:
    if not isinstance(payload, list):
        return ()
    return tuple(
        RefHandle(ref_id=str(item["ref_id"]), ref_kind=str(item["ref_kind"]))
        for item in payload
        if isinstance(item, dict)
    )


def decode_text_control_message(payload: bytes) -> ControlMessage:
    """Decode a canonical UTF-8 JSON control message into the typed model."""

    decoded = json.loads(payload.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("text control message must be a JSON object")
    message_type = str(decoded.get("message_type", ""))
    header_payload = decoded.get("header")
    if not isinstance(header_payload, dict):
        raise ValueError("text control message header is missing")
    header = _text_header(header_payload)

    if message_type == "hello":
        return Hello(
            header=header,
            protocol_versions=tuple(
                str(item) for item in decoded.get("protocol_versions", [])
            ),
            schema_versions=tuple(
                str(item) for item in decoded.get("schema_versions", [])
            ),
            controller_registry_digest=str(
                decoded.get("controller_registry_digest", "")
            ),
            required_capability_ids=tuple(
                str(item) for item in decoded.get("required_capability_ids", [])
            ),
            controller_pid=int(decoded.get("controller_pid", 0)),
        )
    if message_type == "hello_ack":
        return HelloAck(
            header=header,
            accepted=bool(decoded.get("accepted", False)),
            accepted_protocol_version=str(
                decoded.get("accepted_protocol_version", "")
            ),
            accepted_schema_version=str(
                decoded.get("accepted_schema_version", "")
            ),
            worker_registry_digest=str(
                decoded.get("worker_registry_digest", "")
            ),
            supported_capability_ids=tuple(
                str(item) for item in decoded.get("supported_capability_ids", [])
            ),
            error_detail=str(decoded.get("error_detail", "")),
            worker_pid=int(decoded.get("worker_pid", 0)),
        )
    if message_type == "req_exec":
        reuse_payload = decoded.get("reuse_policy", {})
        reuse = dict(reuse_payload) if isinstance(reuse_payload, dict) else {}
        return ExecRequest(
            header=header,
            reuse_policy=ReusePolicy(
                allow_assist=bool(reuse.get("allow_assist", True)),
                allow_validated_replay=bool(reuse.get("allow_validated_replay", False)),
                allow_exact_replay=bool(reuse.get("allow_exact_replay", False)),
            ),
            state_refs=_text_refs(decoded.get("state_refs")),
            artifact_refs=_text_refs(decoded.get("artifact_refs")),
            memory_refs=_text_refs(decoded.get("memory_refs")),
            runtime_reuse_contract=str(decoded.get("runtime_reuse_contract", "")),
            output_contract_version=str(decoded.get("output_contract_version", "")),
            workspace_root=str(decoded.get("workspace_root", "")),
            input_manifest_hash=str(decoded.get("input_manifest_hash", "")),
            operation=str(decoded.get("operation", "")),
            state_root=str(decoded.get("state_root", "")),
            hydrate_manifest_id=str(decoded.get("hydrate_manifest_id", "")),
            semantic_top_k=int(decoded.get("semantic_top_k", 0)),
            evidence_budget_bytes=int(decoded.get("evidence_budget_bytes", 0)),
            expected_encoder_signature=str(decoded.get("expected_encoder_signature", "")),
            capability_grant_hash=str(decoded.get("capability_grant_hash", "")),
            capability_grant_token=str(decoded.get("capability_grant_token", "")),
            capability_grant_session_id=str(decoded.get("capability_grant_session_id", "")),
        )
    if message_type == "ack_recv":
        return AckReceived(header=header, acked_at_ns=int(decoded.get("acked_at_ns", 0)))
    if message_type == "run_start":
        return RunStart(
            header=header,
            started_at_ns=int(decoded.get("started_at_ns", 0)),
            heartbeat_interval_ms=int(decoded.get("heartbeat_interval_ms", 0)),
            lease_timeout_ms=int(decoded.get("lease_timeout_ms", 0)),
        )
    if message_type == "heartbeat":
        return Heartbeat(
            header=header,
            sent_at_ns=int(decoded.get("sent_at_ns", 0)),
            worker_state=str(decoded.get("worker_state", "")),
        )
    if message_type == "res_succ":
        numeric_payload = decoded.get("numeric_summary")
        numeric_summary = None
        if isinstance(numeric_payload, dict):
            numeric_summary = NumericSummaryResult(
                input_ref_id=str(numeric_payload.get("input_ref_id", "")),
                input_payload_hash=str(numeric_payload.get("input_payload_hash", "")),
                row_count=int(numeric_payload.get("row_count", 0)),
                total=float(numeric_payload.get("total", 0.0)),
                mean=float(numeric_payload.get("mean", 0.0)),
                minimum=float(numeric_payload.get("minimum", 0.0)),
                maximum=float(numeric_payload.get("maximum", 0.0)),
                schema_digest=str(numeric_payload.get("schema_digest", "")),
                output_artifact_hash=str(numeric_payload.get("output_artifact_hash", "")),
                validator_receipt_hash=str(numeric_payload.get("validator_receipt_hash", "")),
                worker_pid=int(numeric_payload.get("worker_pid", 0)),
                worker_compute_ns=int(numeric_payload.get("worker_compute_ns", 0)),
            )
        return SuccessResult(
            header=header,
            state_refs=_text_refs(decoded.get("state_refs")),
            artifact_refs=_text_refs(decoded.get("artifact_refs")),
            output_contract_version=str(decoded.get("output_contract_version", "")),
            completed_at_ns=int(decoded.get("completed_at_ns", 0)),
            consumed_state_ref_id=str(decoded.get("consumed_state_ref_id", "")),
            selected_candidate_ids=tuple(str(item) for item in decoded.get("selected_candidate_ids", [])),
            selected_scores=tuple(float(item) for item in decoded.get("selected_scores", [])),
            selected_row_indices=tuple(int(item) for item in decoded.get("selected_row_indices", [])),
            selected_evidence_bytes=int(decoded.get("selected_evidence_bytes", 0)),
            consumer_pid=int(decoded.get("consumer_pid", 0)),
            producer_pid=int(decoded.get("producer_pid", 0)),
            encoder_signature=str(decoded.get("encoder_signature", "")),
            numeric_summary=numeric_summary,
        )
    if message_type == "res_err":
        return ErrorResult(
            header=header,
            error_code=str(decoded.get("error_code", "")),
            error_detail=str(decoded.get("error_detail", "")),
            failed_at_ns=int(decoded.get("failed_at_ns", 0)),
        )
    if message_type == "cmd_cancel":
        return CancelCommand(
            header=header,
            reason=str(decoded.get("reason", "")),
            issued_at_ns=int(decoded.get("issued_at_ns", 0)),
        )
    if message_type == "trap_fatal":
        return TrapFatal(
            header=header,
            trap_reason=str(decoded.get("trap_reason", "")),
            error_detail=str(decoded.get("error_detail", "")),
            trapped_at_ns=int(decoded.get("trapped_at_ns", 0)),
        )
    if message_type == "cmd_gc":
        return GarbageCollectCommand(
            header=header,
            ref_ids=tuple(str(item) for item in decoded.get("ref_ids", [])),
            issued_at_ns=int(decoded.get("issued_at_ns", 0)),
        )
    raise ValueError(f"unsupported text control message type: {message_type}")


def frame_text_control_message(message: ControlMessage) -> bytes:
    payload = encode_text_control_message(message)
    return struct.pack(">I", len(payload)) + payload


def deframe_text_control_message(frame: bytes) -> ControlMessage:
    if len(frame) < 4:
        raise ValueError("text control frame missing length prefix")
    (payload_len,) = struct.unpack(">I", frame[:4])
    payload = frame[4:]
    if len(payload) != payload_len:
        raise ValueError(
            f"text control frame payload length mismatch: expected {payload_len}, got {len(payload)}"
        )
    return decode_text_control_message(payload)
