from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Union

from v2.contracts import CONTROL_PLANE_SCHEMA_VERSION
from v2.control.messages import (
    AckReceived,
    CancelCommand,
    CONTROL_PROTOCOL_VERSION,
    ControlMessage,
    DEFAULT_WORKER_CAPABILITY_IDS,
    ErrorResult,
    EventType,
    ExecRequest,
    Hello,
    HelloAck,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
    TrapFatal,
    decode_text_control_message,
    deframe_control_message,
    frame_control_message,
    frame_text_control_message,
    worker_capability_registry_digest,
)


# Linux allows 107 pathname bytes plus the trailing NUL.  Keeping a few bytes
# of headroom also makes the fallback usable on platforms with a 104-byte
# sockaddr_un.sun_path field.
_UNIX_SOCKET_PATH_BUDGET_BYTES = 103


def effective_unix_socket_path(socket_path: Path) -> Path:
    """Return a deterministic, bounded path for a filesystem Unix socket."""
    if len(os.fsencode(socket_path)) <= _UNIX_SOCKET_PATH_BUDGET_BYTES:
        return socket_path

    digest = hashlib.sha256(os.fsencode(socket_path.absolute())).hexdigest()[:24]
    sibling = socket_path.with_name(f".statebus-{digest}.sock")
    if len(os.fsencode(sibling)) <= _UNIX_SOCKET_PATH_BUDGET_BYTES:
        return sibling

    uid = os.getuid() if hasattr(os, "getuid") else 0
    return Path("/tmp") / f"statebus-v2-uds-{uid}" / f"{digest}.sock"


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before frame payload was fully received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def send_control_message(sock: socket.socket, message: ControlMessage) -> None:
    sock.sendall(frame_control_message(message))


def recv_control_message(sock: socket.socket) -> ControlMessage:
    header = _recv_exact(sock, 4)
    payload_len = int.from_bytes(header, byteorder="big", signed=False)
    payload = _recv_exact(sock, payload_len)
    return deframe_control_message(header + payload)


def frame_text_message(message: str) -> bytes:
    payload = message.encode("utf-8")
    return len(payload).to_bytes(4, byteorder="big", signed=False) + payload


def send_text_message(sock: socket.socket, message: str) -> None:
    sock.sendall(frame_text_message(message))


def recv_text_message(sock: socket.socket) -> str:
    header = _recv_exact(sock, 4)
    payload_len = int.from_bytes(header, byteorder="big", signed=False)
    payload = _recv_exact(sock, payload_len)
    return payload.decode("utf-8")


def send_text_control_message(sock: socket.socket, message: ControlMessage) -> None:
    sock.sendall(frame_text_control_message(message))


def recv_text_control_message(sock: socket.socket) -> ControlMessage:
    header = _recv_exact(sock, 4)
    payload_len = int.from_bytes(header, byteorder="big", signed=False)
    payload = _recv_exact(sock, payload_len)
    return decode_text_control_message(payload)


@dataclass
class ControlPlaneLoopbackServer:
    socket_path: Path

    def round_trip(self, message: ControlMessage) -> ControlMessage:
        socket_path = effective_unix_socket_path(self.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if socket_path.exists():
            socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(socket_path))
            server.listen(1)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(socket_path))
                conn, _ = server.accept()
                try:
                    send_control_message(client, message)
                    received = recv_control_message(conn)
                    send_control_message(conn, received)
                    echoed = recv_control_message(client)
                finally:
                    conn.close()
            finally:
                client.close()
        finally:
            server.close()
            if socket_path.exists():
                socket_path.unlink()
        return echoed

    def exchange_sequence(self, message: ControlMessage) -> list[ControlMessage]:
        socket_path = effective_unix_socket_path(self.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if socket_path.exists():
            socket_path.unlink()

        responses: list[ControlMessage] = []
        ready = threading.Event()

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(socket_path))
                server.listen(1)
                ready.set()
                conn, _ = server.accept()
                try:
                    request = recv_control_message(conn)
                    for response in self._worker_harness_sequence(request):
                        send_control_message(conn, response)
                finally:
                    conn.close()
            except (OSError, TimeoutError):
                # The parent adds a deterministic timeout result when no
                # worker connected; avoid leaking an unhandled thread error.
                return
            finally:
                server.close()
                if socket_path.exists():
                    socket_path.unlink()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        ready.wait(timeout=2.0)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(socket_path))
            send_control_message(client, message)
            while True:
                try:
                    responses.append(recv_control_message(client))
                except ConnectionError:
                    break
        finally:
            client.close()
        thread.join(timeout=2.0)
        return responses

    def drive_session(
        self,
        message: ControlMessage,
        *,
        command: ControlMessage | None = None,
    ) -> list[ControlMessage]:
        responses = self.exchange_sequence(message)
        if command is None:
            return responses
        if isinstance(command, CancelCommand):
            responses.append(
                ErrorResult(
                    header=replace(command.header, event_type=EventType.RES_ERR),
                    error_code="cancelled_by_supervisor",
                    error_detail=command.reason,
                    failed_at_ns=command.issued_at_ns,
                )
            )
            return responses
        if isinstance(command, Heartbeat):
            responses.append(command)
            return responses
        raise TypeError(f"unsupported command for loopback session: {type(command)!r}")

    def exchange_sequence_by_contract(self, message: ControlMessage) -> list[ControlMessage]:
        if not hasattr(message, "runtime_reuse_contract"):
            return self.exchange_sequence(message)
        contract = getattr(message, "runtime_reuse_contract", "")
        header = message.header
        if "drop_ack" in contract:
            return [
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="ack_timeout_simulated",
                    error_detail="worker_harness_withheld_ack",
                    failed_at_ns=0,
                )
            ]
        if "lease_timeout" in contract:
            return [
                AckReceived(header=replace(header, event_type=EventType.ACK_RECV), acked_at_ns=1),
                RunStart(
                    header=replace(header, event_type=EventType.RUN_START),
                    started_at_ns=2,
                    heartbeat_interval_ms=2000,
                    lease_timeout_ms=6000,
                ),
            ]
        return self.exchange_sequence(message)

    def _worker_harness_sequence(self, message: ControlMessage) -> list[ControlMessage]:
        header = message.header
        if header.event_type != EventType.REQ_EXEC:
            return [
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="unsupported_event_type",
                    error_detail=f"expected REQ_EXEC, got {header.event_type.name}",
                    failed_at_ns=0,
                )
            ]

        required_errors: list[str] = []
        runtime_reuse_contract = getattr(message, "runtime_reuse_contract", "")
        semantic_state_optional = "no_semantic_state" in runtime_reuse_contract
        semantic_selection = getattr(message, "operation", "") == "semantic_select_v1"
        if not getattr(message, "workspace_root", "").strip():
            required_errors.append("workspace_root_missing")
        if not getattr(message, "input_manifest_hash", "").strip():
            required_errors.append("input_manifest_hash_missing")
        if not getattr(message, "output_contract_version", "").strip():
            required_errors.append("output_contract_version_missing")
        if not semantic_state_optional and not tuple(getattr(message, "state_refs", ())):
            required_errors.append("state_refs_missing")
        if not semantic_selection and not tuple(getattr(message, "artifact_refs", ())):
            required_errors.append("artifact_refs_missing")
        if semantic_selection:
            if not getattr(message, "state_root", "").strip():
                required_errors.append("state_root_missing")
            if not getattr(message, "hydrate_manifest_id", "").strip():
                required_errors.append("hydrate_manifest_id_missing")
            if int(getattr(message, "semantic_top_k", 0)) <= 0:
                required_errors.append("semantic_top_k_missing")
            if not getattr(message, "capability_grant_hash", "").strip():
                required_errors.append("capability_grant_hash_missing")
        if required_errors:
            return [
                ErrorResult(
                    header=replace(header, event_type=EventType.RES_ERR),
                    error_code="invalid_exec_request",
                    error_detail=",".join(required_errors),
                    failed_at_ns=0,
                )
            ]

        if "force_trap" in runtime_reuse_contract:
            return [
                AckReceived(header=replace(header, event_type=EventType.ACK_RECV), acked_at_ns=1),
                RunStart(
                    header=replace(header, event_type=EventType.RUN_START),
                    started_at_ns=2,
                    heartbeat_interval_ms=2000,
                    lease_timeout_ms=6000,
                ),
                Heartbeat(
                    header=replace(header, event_type=EventType.HEARTBEAT),
                    sent_at_ns=3,
                    worker_state="running",
                ),
                TrapFatal(
                    header=replace(header, event_type=EventType.TRAP_FATAL),
                    trap_reason="worker_harness_forced_trap",
                    error_detail="runtime_reuse_contract requested trap",
                    trapped_at_ns=4,
                ),
            ]

        state_refs = tuple(getattr(message, "state_refs", ()))
        artifact_refs = tuple(getattr(message, "artifact_refs", ()))
        return [
            AckReceived(header=replace(header, event_type=EventType.ACK_RECV), acked_at_ns=1),
            RunStart(
                header=replace(header, event_type=EventType.RUN_START),
                started_at_ns=2,
                heartbeat_interval_ms=2000,
                lease_timeout_ms=6000,
            ),
            Heartbeat(
                header=replace(header, event_type=EventType.HEARTBEAT),
                sent_at_ns=3,
                worker_state="running",
            ),
            SuccessResult(
                header=replace(header, event_type=EventType.RES_SUCC),
                state_refs=state_refs,
                artifact_refs=artifact_refs,
                output_contract_version=getattr(message, "output_contract_version", "") or "output-v1",
                completed_at_ns=4,
            ),
        ]


def encode_memfd_ref(*, fd: int, length: int, state_id: str, ref_kind: str = "embedding") -> "RefHandle":
    """Encode a memfd file descriptor into a RefHandle for subprocess transfer.

    The ref_id format is ``memfd_fd:{fd}:{length}:{state_id}``.  The caller
    must pass the fd number to the subprocess via ``pass_fds`` so that the
    worker can read it with ``os.read(fd, length)``.
    """
    return RefHandle(ref_id=f"memfd_fd:{fd}:{length}:{state_id}", ref_kind=ref_kind)


def decode_memfd_ref(ref: "RefHandle") -> tuple[int, int, str] | None:
    """Parse a memfd RefHandle back to (fd, length, state_id), or None."""
    if not ref.ref_id.startswith("memfd_fd:"):
        return None
    parts = ref.ref_id.split(":", 3)
    if len(parts) != 4:
        return None
    try:
        return int(parts[1]), int(parts[2]), parts[3]
    except ValueError:
        return None


@dataclass(frozen=True)
class ExecutorTransportAudit:
    carrier: str
    backend: str
    driver_pid: int
    worker_pid: int
    request_frame_count: int
    response_frame_count: int
    request_wire_bytes: int
    response_wire_bytes: int
    topology: str = "driver_uds_executor_subprocess"
    negotiation_performed: bool = False
    negotiation_accepted: bool = False
    negotiated_protocol_version: str = ""
    negotiated_schema_version: str = ""
    controller_registry_digest: str = ""
    worker_registry_digest: str = ""
    required_capability_ids: tuple[str, ...] = ()
    supported_capability_ids: tuple[str, ...] = ()
    negotiation_error: str = ""
    negotiation_request_frame_count: int = 0
    negotiation_response_frame_count: int = 0
    negotiation_request_wire_bytes: int = 0
    negotiation_response_wire_bytes: int = 0
    execution_request_frame_count: int = 0
    execution_response_frame_count: int = 0
    execution_request_wire_bytes: int = 0
    execution_response_wire_bytes: int = 0

    def canonical_payload(self) -> dict[str, object]:
        return {
            "carrier": self.carrier,
            "backend": self.backend,
            "driver_pid": self.driver_pid,
            "worker_pid": self.worker_pid,
            "request_frame_count": self.request_frame_count,
            "response_frame_count": self.response_frame_count,
            "request_wire_bytes": self.request_wire_bytes,
            "response_wire_bytes": self.response_wire_bytes,
            "total_wire_bytes": self.request_wire_bytes + self.response_wire_bytes,
            "topology": self.topology,
            "negotiation_performed": self.negotiation_performed,
            "negotiation_accepted": self.negotiation_accepted,
            "negotiated_protocol_version": self.negotiated_protocol_version,
            "negotiated_schema_version": self.negotiated_schema_version,
            "controller_registry_digest": self.controller_registry_digest,
            "worker_registry_digest": self.worker_registry_digest,
            "required_capability_ids": list(self.required_capability_ids),
            "supported_capability_ids": list(self.supported_capability_ids),
            "negotiation_error": self.negotiation_error,
            "negotiation_request_frame_count": self.negotiation_request_frame_count,
            "negotiation_response_frame_count": self.negotiation_response_frame_count,
            "negotiation_request_wire_bytes": self.negotiation_request_wire_bytes,
            "negotiation_response_wire_bytes": self.negotiation_response_wire_bytes,
            "execution_request_frame_count": self.execution_request_frame_count,
            "execution_response_frame_count": self.execution_response_frame_count,
            "execution_request_wire_bytes": self.execution_request_wire_bytes,
            "execution_response_wire_bytes": self.execution_response_wire_bytes,
        }


def _wire_capability_for_request(request: ExecRequest) -> str:
    return request.operation.strip() or "echo_refs_v1"


def _validate_hello_ack(
    ack: HelloAck,
    *,
    offered_protocol_versions: tuple[str, ...],
    offered_schema_versions: tuple[str, ...],
    expected_registry_digest: str,
    required_capability_ids: tuple[str, ...],
) -> tuple[str, str]:
    if not ack.accepted:
        detail = ack.error_detail or "worker_rejected_negotiation"
        first_error = detail.split(",", 1)[0]
        return first_error.split(":", 1)[0], detail
    if ack.accepted_protocol_version not in offered_protocol_versions:
        return "protocol_version_mismatch", ack.accepted_protocol_version
    if ack.accepted_schema_version not in offered_schema_versions:
        return "schema_version_mismatch", ack.accepted_schema_version
    if ack.worker_registry_digest != expected_registry_digest:
        return "capability_registry_digest_mismatch", ack.worker_registry_digest
    missing = sorted(set(required_capability_ids) - set(ack.supported_capability_ids))
    if missing:
        return "missing_required_capability", ",".join(missing)
    return "", ""


def _validate_numeric_worker_response(
    result: SuccessResult,
    *,
    request: ExecRequest,
    memfd_refs: dict[str, tuple[int, int]] | None,
    negotiated_worker_pid: int,
) -> str:
    from v2.control.worker_operations import validate_typed_numeric_summary

    if result.numeric_summary is None:
        return "numeric_summary_result_missing"
    if len(request.state_refs) != 1 or not memfd_refs:
        return "numeric_summary_controller_input_missing"
    input_ref_id = request.state_refs[0].ref_id
    entry = memfd_refs.get(input_ref_id)
    if entry is None:
        return "numeric_summary_controller_fd_missing"
    fd, length = entry
    try:
        payload = os.pread(fd, length, 0)
    except OSError:
        return "numeric_summary_controller_fd_read_failed"
    if len(payload) != length:
        return "numeric_summary_controller_fd_short_read"
    return validate_typed_numeric_summary(
        result.numeric_summary,
        payload=payload,
        expected_input_ref_id=input_ref_id,
        expected_worker_pid=negotiated_worker_pid,
    )


def _text_response_to_control_message(
    payload: str,
    *,
    request: ExecRequest,
) -> ControlMessage:
    normalized = payload.strip()
    now = time.time_ns()
    if normalized == "ACK RECEIVED":
        return AckReceived(
            header=replace(request.header, event_type=EventType.ACK_RECV),
            acked_at_ns=now,
        )
    if normalized == "RUN START":
        return RunStart(
            header=replace(request.header, event_type=EventType.RUN_START),
            started_at_ns=now,
            heartbeat_interval_ms=2000,
            lease_timeout_ms=30_000,
        )
    if normalized == "HEARTBEAT running":
        return Heartbeat(
            header=replace(request.header, event_type=EventType.HEARTBEAT),
            sent_at_ns=now,
            worker_state="running",
        )
    if normalized == "RESULT SUCCESS":
        return SuccessResult(
            header=replace(request.header, event_type=EventType.RES_SUCC),
            output_contract_version=request.output_contract_version,
            completed_at_ns=now,
        )
    if normalized.startswith("RESULT ERROR "):
        detail = normalized.removeprefix("RESULT ERROR ").strip()
        code, _, message = detail.partition(" ")
        return ErrorResult(
            header=replace(request.header, event_type=EventType.RES_ERR),
            error_code=code or "text_worker_error",
            error_detail=message or code or "text worker error",
            failed_at_ns=now,
        )
    raise ValueError(f"unsupported text worker response: {normalized!r}")


def _default_text_exec_handoff(request: ExecRequest) -> str:
    return "\n".join(
        (
            "StateBus matched pure-text executor handoff.",
            f"Trace: {request.header.trace_id}",
            f"Task: {request.header.task_id}",
            f"Step: {request.header.step_id}",
            f"Attempt: {request.header.attempt_id}",
            f"Output contract: {request.output_contract_version}",
            f"Workspace: {request.workspace_root}",
            f"Input manifest: {request.input_manifest_hash}",
            f"Runtime contract: {request.runtime_reuse_contract}",
            "Current evidence:\nNo inline evidence was supplied by this transport test.",
            "Verified prior context:\nNo prior context was supplied.",
        )
    )


@dataclass
class SubprocessExecutorTransport:
    """Launch a worker subprocess and communicate via UDS + typed Protobuf frames.

    The main process listens on ``socket_path``; the subprocess connects,
    negotiates the typed protocol, receives one ``ExecRequest``, executes it,
    and returns result frames. The matched UTF-8 carrier skips negotiation.

    Typed protocol: main sends Hello -> worker sends HelloAck -> main sends
    ExecRequest -> worker sends AckReceived + RunStart + Heartbeat +
    SuccessResult (or ErrorResult) -> connection closes.

    memfd support
    -------------
    Pass ``memfd_refs={state_id: (fd, length)}`` to forward anonymous
    memfd file descriptors to the worker subprocess via ``pass_fds``.
    The state_refs in the request are rewritten to ``memfd_fd:{fd}:{length}:{state_id}``
    so the worker can call ``os.read(fd, length)`` directly — no filesystem
    path needed, embedding bytes never touch disk.
    """

    socket_path: Path
    python_executable: str = sys.executable
    timeout_s: float = 30.0
    capability_grant_secret: bytes = field(default=b"", repr=False)
    offered_protocol_versions: tuple[str, ...] = (CONTROL_PROTOCOL_VERSION,)
    offered_schema_versions: tuple[str, ...] = (CONTROL_PLANE_SCHEMA_VERSION,)
    controller_registry_digest: str = ""
    required_capability_ids: tuple[str, ...] = ()
    last_exchange_audit: ExecutorTransportAudit | None = field(
        default=None,
        init=False,
    )

    def exchange_sequence(
        self,
        request: ExecRequest,
        *,
        memfd_refs: dict[str, tuple[int, int]] | None = None,
        carrier: str = "protobuf",
        text_payload: str = "",
    ) -> list[ControlMessage]:
        """Start a worker subprocess and return the full response frame sequence."""
        import os as _os

        normalized_carrier = carrier.strip().lower()
        if normalized_carrier not in {"protobuf", "utf8_text"}:
            raise ValueError(f"unsupported subprocess carrier: {carrier}")
        pass_fds: tuple[int, ...] = ()
        exec_request = request
        grant_secret = self.capability_grant_secret
        if (
            normalized_carrier == "protobuf"
            and request.operation in {
                "logit_gate_v1",
                "semantic_select_v1",
                "typed_numeric_summary_v1",
            }
            and not request.capability_grant_token
        ):
            # Compatibility for trusted Controller call sites that predate the
            # authenticated token field.  The Controller transport issues a
            # one-shot wire grant; the worker still rejects an unsigned random
            # non-empty hash.
            import secrets as _secrets

            from v2.contracts import CapabilityGrant
            from v2.runtime.capability_grants import CapabilityGrantAuthenticator

            issued_at_ns = time.time_ns()
            wire_grant = CapabilityGrant(
                grant_id=f"wire-{request.header.task_id}-{request.header.attempt_id}",
                task_id=request.header.task_id,
                session_id=request.header.trace_id,
                step_id=request.header.step_id,
                attempt_id=request.header.attempt_id,
                capability_id=request.operation,
                capability_version="wire-v1",
                input_ref_ids=tuple(
                    ref.ref_id
                    for ref in (*request.state_refs, *request.artifact_refs, *request.memory_refs)
                ),
                output_contract_version=request.output_contract_version,
                workspace_root_id=request.workspace_root,
                max_runtime_ms=request.header.timeout_ms,
                expires_at_ns=issued_at_ns + max(request.header.timeout_ms, 1_000) * 1_000_000,
                approved_plan_hash="wire-controller-issued",
                grant_nonce=_secrets.token_urlsafe(18),
                issued_at_ns=issued_at_ns,
            )
            grant_secret = grant_secret or _secrets.token_bytes(32)
            authenticator = CapabilityGrantAuthenticator(secret=grant_secret)
            exec_request = replace(
                request,
                capability_grant_hash=wire_grant.grant_hash,
                capability_grant_token=authenticator.issue(
                    wire_grant,
                    bound_ref_ids=wire_grant.input_ref_ids,
                    bound_output_contract=request.output_contract_version,
                ),
                capability_grant_session_id=wire_grant.session_id,
            )
        if memfd_refs:
            new_state_refs = []
            fds_to_pass: list[int] = []
            for ref in exec_request.state_refs:
                entry = memfd_refs.get(ref.ref_id)
                if entry is not None:
                    fd, length = entry
                    new_state_refs.append(
                        encode_memfd_ref(fd=fd, length=length, state_id=ref.ref_id, ref_kind=ref.ref_kind)
                    )
                    fds_to_pass.append(fd)
                else:
                    new_state_refs.append(ref)
            existing_ids = {ref.ref_id for ref in exec_request.state_refs}
            for state_id, (fd, length) in memfd_refs.items():
                if state_id not in existing_ids:
                    new_state_refs.append(encode_memfd_ref(fd=fd, length=length, state_id=state_id))
                    fds_to_pass.append(fd)
            exec_request = replace(exec_request, state_refs=tuple(new_state_refs))
            pass_fds = tuple(sorted(set(fds_to_pass)))

        registry_digest = (
            self.controller_registry_digest
            or worker_capability_registry_digest(DEFAULT_WORKER_CAPABILITY_IDS)
        )
        required_capability_ids = tuple(dict.fromkeys((
            *self.required_capability_ids,
            _wire_capability_for_request(exec_request),
        )))
        hello = Hello(
            header=replace(
                exec_request.header,
                event_type=EventType.HELLO,
                target_role="executor_worker",
            ),
            protocol_versions=self.offered_protocol_versions,
            schema_versions=self.offered_schema_versions,
            controller_registry_digest=registry_digest,
            required_capability_ids=required_capability_ids,
            controller_pid=_os.getpid(),
        )

        socket_path = effective_unix_socket_path(self.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if socket_path.exists():
            socket_path.unlink()

        responses: list[ControlMessage] = []
        request_wire_frames: list[int] = []
        response_wire_frames: list[int] = []
        negotiation_request_wire_frames: list[int] = []
        negotiation_response_wire_frames: list[int] = []
        execution_request_wire_frames: list[int] = []
        execution_response_wire_frames: list[int] = []
        negotiation_state: dict[str, object] = {
            "performed": False,
            "accepted": False,
            "protocol_version": "",
            "schema_version": "",
            "worker_registry_digest": "",
            "supported_capability_ids": (),
            "worker_pid": 0,
            "error": "",
        }
        server_ready = threading.Event()
        resolved_text_payload = text_payload or _default_text_exec_handoff(exec_request)

        def _serve() -> None:
            nonlocal exec_request
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            conn: socket.socket | None = None
            try:
                server.bind(str(socket_path))
                server.listen(1)
                server.settimeout(self.timeout_s)
                server_ready.set()
                conn, _ = server.accept()
                try:
                    if exec_request.capability_grant_token:
                        from v2.runtime.capability_grants import require_peer_uid

                        require_peer_uid(conn, _os.getuid())
                    if normalized_carrier == "utf8_text":
                        request_size = len(frame_text_message(resolved_text_payload))
                        send_text_message(conn, resolved_text_payload)
                        request_wire_frames.append(request_size)
                        execution_request_wire_frames.append(request_size)
                    else:
                        negotiation_state["performed"] = True
                        hello_size = len(frame_control_message(hello))
                        send_control_message(conn, hello)
                        request_wire_frames.append(hello_size)
                        negotiation_request_wire_frames.append(hello_size)
                        hello_response = recv_control_message(conn)
                        hello_response_size = len(frame_control_message(hello_response))
                        response_wire_frames.append(hello_response_size)
                        negotiation_response_wire_frames.append(hello_response_size)
                        if not isinstance(hello_response, HelloAck):
                            error_code = "hello_ack_required"
                            error_detail = type(hello_response).__name__
                        else:
                            negotiation_state.update({
                                "accepted": hello_response.accepted,
                                "protocol_version": hello_response.accepted_protocol_version,
                                "schema_version": hello_response.accepted_schema_version,
                                "worker_registry_digest": hello_response.worker_registry_digest,
                                "supported_capability_ids": hello_response.supported_capability_ids,
                                "worker_pid": hello_response.worker_pid,
                            })
                            error_code, error_detail = _validate_hello_ack(
                                hello_response,
                                offered_protocol_versions=self.offered_protocol_versions,
                                offered_schema_versions=self.offered_schema_versions,
                                expected_registry_digest=registry_digest,
                                required_capability_ids=required_capability_ids,
                            )
                        if error_code:
                            negotiation_state["accepted"] = False
                            negotiation_state["error"] = error_detail or error_code
                            responses.append(ErrorResult(
                                header=replace(exec_request.header, event_type=EventType.RES_ERR),
                                error_code=error_code,
                                error_detail=error_detail or error_code,
                                failed_at_ns=time.time_ns(),
                            ))
                            return
                        negotiation_state["accepted"] = True
                        if exec_request.operation == "logit_gate_v1":
                            from v2.runtime.confidence_gate import (
                                logit_control_grant_from_domain,
                                logit_control_ref_from_domain,
                            )
                            from v2.state.logit_state import (
                                LogitStateGrant,
                                logit_ref_from_sidecar,
                            )

                            worker_pid = int(negotiation_state.get("worker_pid", 0))
                            if worker_pid <= 0:
                                raise ValueError("logit_gate_worker_pid_missing")
                            domain_ref = logit_ref_from_sidecar(
                                Path(exec_request.state_root),
                                exec_request.state_refs[0].ref_id,
                            )
                            typed_ref = logit_control_ref_from_domain(domain_ref)
                            if (
                                exec_request.logit_state_ref is not None
                                and exec_request.logit_state_ref != typed_ref
                            ):
                                raise ValueError("logit_gate_control_ref_mismatch")
                            grant = LogitStateGrant.issue(
                                domain_ref,
                                consumer_pid=worker_pid,
                            )
                            exec_request = replace(
                                exec_request,
                                logit_state_ref=typed_ref,
                                logit_state_grant=logit_control_grant_from_domain(grant),
                            )
                        exec_size = len(frame_control_message(exec_request))
                        send_control_message(conn, exec_request)
                        request_wire_frames.append(exec_size)
                        execution_request_wire_frames.append(exec_size)
                    while True:
                        try:
                            if normalized_carrier == "utf8_text":
                                text_response = recv_text_message(conn)
                                response_size = len(frame_text_message(text_response))
                                msg = _text_response_to_control_message(
                                    text_response,
                                    request=exec_request,
                                )
                            else:
                                msg = recv_control_message(conn)
                                response_size = len(frame_control_message(msg))
                        except (ConnectionError, ConnectionResetError, socket.timeout):
                            break
                        response_wire_frames.append(response_size)
                        execution_response_wire_frames.append(response_size)
                        if (
                            isinstance(msg, SuccessResult)
                            and exec_request.operation == "typed_numeric_summary_v1"
                        ):
                            validation_error = _validate_numeric_worker_response(
                                msg,
                                request=request,
                                memfd_refs=memfd_refs,
                                negotiated_worker_pid=int(
                                    negotiation_state.get("worker_pid", 0)
                                ),
                            )
                            if validation_error:
                                msg = ErrorResult(
                                    header=replace(
                                        exec_request.header,
                                        event_type=EventType.RES_ERR,
                                    ),
                                    error_code="worker_result_validation_failed",
                                    error_detail=validation_error,
                                    failed_at_ns=time.time_ns(),
                                )
                        responses.append(msg)
                        if isinstance(msg, (SuccessResult, ErrorResult)):
                            break
                except Exception as exc:
                    # Do not turn an authentication or framing failure into a
                    # parent-side timeout.  Return a typed, fail-closed error
                    # while the connection is still available.
                    error_code = str(getattr(exc, "code", "transport_server_error"))
                    error_detail = str(exc) or error_code
                    error = ErrorResult(
                        header=replace(exec_request.header, event_type=EventType.RES_ERR),
                        error_code=error_code,
                        error_detail=error_detail,
                        failed_at_ns=time.time_ns(),
                    )
                    try:
                        if normalized_carrier == "utf8_text":
                            send_text_message(
                                conn,
                                f"RESULT ERROR {error_code} {error_detail}",
                            )
                        else:
                            send_control_message(conn, error)
                            response_size = len(frame_control_message(error))
                            response_wire_frames.append(response_size)
                            execution_response_wire_frames.append(response_size)
                        responses.append(error)
                    except (ConnectionError, OSError):
                        pass
                finally:
                    if conn is not None:
                        conn.close()
            except (OSError, TimeoutError):
                # The parent adds a deterministic timeout result when no
                # worker connected; avoid leaking an unhandled thread error.
                return
            finally:
                server.close()
                if socket_path.exists():
                    socket_path.unlink()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        server_ready.wait(timeout=2.0)

        worker_root = Path(__file__).resolve().parent.parent.parent
        # Only carry the process settings needed to import/run the worker.
        # Capability material is added below for this one-shot process only.
        worker_env = {
            key: value
            for key, value in _os.environ.items()
            if key in {
                "PATH",
                "PYTHONPATH",
                "PYTHONHOME",
                "LANG",
                "LC_ALL",
                "LD_LIBRARY_PATH",
                "TMPDIR",
                "OPENBLAS_NUM_THREADS",
                "OMP_NUM_THREADS",
                "MKL_NUM_THREADS",
            }
        }
        if exec_request.capability_grant_token:
            if not grant_secret:
                raise ValueError("capability_grant_secret_required")
            # The secret is inherited only by the one-shot worker.  It never
            # appears in argv, a wire frame, an artifact, or a log line.
            worker_env["STATEBUS_CAPABILITY_GRANT_SECRET_HEX"] = grant_secret.hex()
            nonce_dir = socket_path.parent / ".statebus_grant_nonces"
            nonce_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            worker_env["STATEBUS_CAPABILITY_GRANT_NONCE_DIR"] = str(nonce_dir)
        proc = subprocess.Popen(
            [
                self.python_executable,
                "-m",
                "v2.control.subprocess_worker",
                "--socket-path",
                str(socket_path),
                "--carrier",
                normalized_carrier,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=worker_env,
            cwd=str(worker_root),
            close_fds=True,
            pass_fds=pass_fds,
            start_new_session=True,
        )
        t.join(timeout=self.timeout_s)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        worker_stderr = ""
        if proc.stderr is not None:
            try:
                worker_stderr = proc.stderr.read().decode("utf-8", errors="replace").strip()
            except OSError:
                worker_stderr = ""

        completed_responses = responses
        if not any(isinstance(msg, (SuccessResult, ErrorResult)) for msg in responses):
            completed_responses = responses + [ErrorResult(
                header=replace(request.header, event_type=EventType.RES_ERR),
                error_code="subprocess_timeout",
                error_detail=(
                    "worker subprocess did not return a result within timeout"
                    f";returncode={proc.returncode}"
                    + (f";stderr={worker_stderr[-500:]}" if worker_stderr else "")
                ),
                failed_at_ns=time.time_ns(),
            )]
        self.last_exchange_audit = ExecutorTransportAudit(
            carrier=(
                "utf8_text"
                if normalized_carrier == "utf8_text"
                else "typed_protobuf"
            ),
            backend="uds_subprocess",
            driver_pid=_os.getpid(),
            worker_pid=proc.pid,
            request_frame_count=len(request_wire_frames),
            response_frame_count=len(response_wire_frames),
            request_wire_bytes=sum(request_wire_frames),
            response_wire_bytes=sum(response_wire_frames),
            negotiation_performed=bool(negotiation_state["performed"]),
            negotiation_accepted=bool(negotiation_state["accepted"]),
            negotiated_protocol_version=str(negotiation_state["protocol_version"]),
            negotiated_schema_version=str(negotiation_state["schema_version"]),
            controller_registry_digest=(
                registry_digest if normalized_carrier == "protobuf" else ""
            ),
            worker_registry_digest=str(negotiation_state["worker_registry_digest"]),
            required_capability_ids=(
                required_capability_ids if normalized_carrier == "protobuf" else ()
            ),
            supported_capability_ids=tuple(
                str(value)
                for value in negotiation_state["supported_capability_ids"]
            ),
            negotiation_error=str(negotiation_state["error"]),
            negotiation_request_frame_count=len(negotiation_request_wire_frames),
            negotiation_response_frame_count=len(negotiation_response_wire_frames),
            negotiation_request_wire_bytes=sum(negotiation_request_wire_frames),
            negotiation_response_wire_bytes=sum(negotiation_response_wire_frames),
            execution_request_frame_count=len(execution_request_wire_frames),
            execution_response_frame_count=len(execution_response_wire_frames),
            execution_request_wire_bytes=sum(execution_request_wire_frames),
            execution_response_wire_bytes=sum(execution_response_wire_frames),
        )
        return completed_responses

    def execute(
        self,
        request: ExecRequest,
        *,
        memfd_refs: dict[str, tuple[int, int]] | None = None,
        carrier: str = "protobuf",
        text_payload: str = "",
    ) -> Union[SuccessResult, ErrorResult]:
        """Start worker subprocess, exchange one ExecRequest/result pair.

        Args:
            request: The execution request.
            memfd_refs: Optional mapping of ``{state_id: (fd, length)}``.
                When provided the corresponding state_refs are rewritten to
                ``memfd_fd:`` handles and the FDs are inherited by the
                subprocess via ``pass_fds``.
        """
        for response in self.exchange_sequence(
            request,
            memfd_refs=memfd_refs,
            carrier=carrier,
            text_payload=text_payload,
        ):
            if isinstance(response, (SuccessResult, ErrorResult)):
                return response
        return ErrorResult(
            header=replace(request.header, event_type=EventType.RES_ERR),
            error_code="subprocess_timeout",
            error_detail="worker subprocess did not return a result within timeout",
            failed_at_ns=time.time_ns(),
        )
