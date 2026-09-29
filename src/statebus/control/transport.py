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

from statebus.control.admission import (
    ControlResponseAdmissionError,
    ControlResponseAdmissionReceipt,
    ControlResponseOrigin,
    admit_control_response_sequence,
)
from statebus.control.messages import (
    AckReceived,
    CancelCommand,
    ControlMessage,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
    TrapFatal,
    decode_text_control_message,
    deframe_control_message,
    frame_control_message,
    frame_text_control_message,
    control_frame_metadata,
    MAX_CONTROL_FRAME_PAYLOAD_BYTES,
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
    return Path("/tmp") / f"statebus-uds-{uid}" / f"{digest}.sock"


def _recv_exact(sock: socket.socket, length: int) -> bytes:
    if length < 0:
        raise ValueError("frame_length_invalid")
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("socket closed before frame payload was fully received")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _recv_framed(sock: socket.socket) -> bytes:
    """Receive one bounded frame and retain the exact bytes observed."""
    try:
        header = _recv_exact(sock, 4)
    except ConnectionError as exc:
        raise ConnectionError("frame_header_truncated") from exc
    payload_len = int.from_bytes(header, byteorder="big", signed=False)
    if payload_len <= 0:
        raise ValueError("frame_length_invalid")
    if payload_len > MAX_CONTROL_FRAME_PAYLOAD_BYTES:
        raise ValueError("frame_oversized")
    try:
        payload = _recv_exact(sock, payload_len)
    except ConnectionError as exc:
        raise ConnectionError("frame_payload_truncated") from exc
    return header + payload


def _ensure_socket_available(path: Path) -> None:
    """Never unlink an existing row/foreign socket implicitly."""
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"socket_path_occupied:{path}")


def send_control_message(sock: socket.socket, message: ControlMessage) -> None:
    sock.sendall(frame_control_message(message))


def recv_control_message(sock: socket.socket) -> ControlMessage:
    return deframe_control_message(_recv_framed(sock))


def frame_text_message(message: str) -> bytes:
    payload = message.encode("utf-8")
    if not payload:
        raise ValueError("frame_length_invalid")
    if len(payload) > MAX_CONTROL_FRAME_PAYLOAD_BYTES:
        raise ValueError("frame_oversized")
    return len(payload).to_bytes(4, byteorder="big", signed=False) + payload


def send_text_message(sock: socket.socket, message: str) -> None:
    sock.sendall(frame_text_message(message))


def recv_text_message(sock: socket.socket) -> str:
    header = _recv_exact(sock, 4)
    payload_len = int.from_bytes(header, byteorder="big", signed=False)
    if payload_len <= 0:
        raise ValueError("frame_length_invalid")
    if payload_len > MAX_CONTROL_FRAME_PAYLOAD_BYTES:
        raise ValueError("frame_oversized")
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
        _ensure_socket_available(socket_path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound_inode: int | None = None
        try:
            server.bind(str(socket_path))
            bound_inode = socket_path.stat().st_ino
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
            if socket_path.exists() and bound_inode is not None:
                try:
                    if socket_path.stat().st_ino == bound_inode:
                        socket_path.unlink()
                except OSError:
                    pass
        return echoed

    def exchange_sequence(self, message: ControlMessage) -> list[ControlMessage]:
        socket_path = effective_unix_socket_path(self.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensure_socket_available(socket_path)

        responses: list[ControlMessage] = []
        ready = threading.Event()

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            bound_inode: int | None = None
            try:
                server.bind(str(socket_path))
                bound_inode = socket_path.stat().st_ino
                server.listen(1)
                ready.set()
                conn, _ = server.accept()
                try:
                    request = recv_control_message(conn)
                    for response in self._worker_harness_sequence(request):
                        send_control_message(conn, response)
                finally:
                    conn.close()
            finally:
                server.close()
                if socket_path.exists() and bound_inode is not None:
                    try:
                        if socket_path.stat().st_ino == bound_inode:
                            socket_path.unlink()
                    except OSError:
                        pass

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
        logit_gate = getattr(message, "operation", "") == "logit_gate_v1"
        if not getattr(message, "workspace_root", "").strip():
            required_errors.append("workspace_root_missing")
        if not getattr(message, "input_manifest_hash", "").strip():
            required_errors.append("input_manifest_hash_missing")
        if not getattr(message, "output_contract_version", "").strip():
            required_errors.append("output_contract_version_missing")
        if not semantic_state_optional and not tuple(getattr(message, "state_refs", ())):
            required_errors.append("state_refs_missing")
        if not semantic_selection and not logit_gate and not tuple(getattr(message, "artifact_refs", ())):
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
        if logit_gate:
            if not getattr(message, "state_root", "").strip():
                required_errors.append("state_root_missing")
            if len(tuple(getattr(message, "state_refs", ()))) != 1:
                required_errors.append("logit_state_ref_count_invalid")
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
    socket_path_requested: str = ""
    socket_path_effective: str = ""
    socket_inode: int | None = None
    session_id: str = ""
    request_frame_metadata: tuple[dict[str, object], ...] = ()
    response_frame_metadata: tuple[dict[str, object], ...] = ()
    failure_stage: str = ""
    error_code: str = ""
    task_id: str = ""
    step_id: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    execution_binding_hash: str = ""
    capability_grant_hash: str = ""

    def canonical_payload(self) -> dict[str, object]:
        diagnostic = {
            "request_total": self.request_wire_bytes,
            "response_total": self.response_wire_bytes,
            "per_frame": [
                int(item.get("framed_length_observed", 0))
                for item in (*self.request_frame_metadata, *self.response_frame_metadata)
                if isinstance(item, dict) and item.get("framed_length_observed") is not None
            ],
            "source": "raw_send_or_recv_frame_observation",
        }
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
            "diagnostic_control_frame_bytes": diagnostic,
            "topology": self.topology,
            "socket_path_requested": self.socket_path_requested,
            "socket_path_effective": self.socket_path_effective,
            "socket_inode": self.socket_inode,
            "session_id": self.session_id,
            "request_frame_metadata": list(self.request_frame_metadata),
            "response_frame_metadata": list(self.response_frame_metadata),
            "failure_stage": self.failure_stage,
            "error_code": self.error_code,
            "task_id": self.task_id,
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "invocation_id": self.invocation_id,
            "execution_binding_hash": self.execution_binding_hash,
            "capability_grant_hash": self.capability_grant_hash,
        }


class SubprocessTransportTimeout(TimeoutError):
    """A locally observed deadline with an independently running worker."""

    origin = "LOCAL_TRANSPORT"

    def __init__(
        self,
        *,
        transport: "SubprocessExecutorTransport",
        request: ExecRequest,
        thread: threading.Thread,
        process: subprocess.Popen[bytes],
        responses: list[ControlMessage],
        response_wire_bytes: list[int],
        carrier: str,
        request_wire_bytes: int,
    ) -> None:
        self.transport = transport
        self.request = request
        self.thread = thread
        self.process = process
        self._responses = responses
        self._response_wire_bytes = response_wire_bytes
        self.carrier = carrier
        self.request_wire_bytes = request_wire_bytes
        self.termination_attempted = False
        self.termination_succeeded = False
        self.termination_outcome = "not_attempted"
        super().__init__(
            "subprocess_transport_timeout:"
            f"{request.header.step_id}:{request.header.attempt_id}:"
            f"{request.header.invocation_id}"
        )

    def terminate(self, *, grace_s: float = 1.0) -> bool:
        """Best-effort physical termination after Runtime semantic settlement."""
        self.termination_attempted = True
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=max(float(grace_s), 0.0))
                    self.termination_outcome = "terminated"
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=max(float(grace_s), 0.1))
                    self.termination_outcome = "killed_after_grace"
            else:
                self.termination_outcome = "already_exited"
            self.termination_succeeded = self.process.poll() is not None
        except (OSError, subprocess.SubprocessError) as exc:
            self.termination_outcome = f"termination_failed:{type(exc).__name__}"
            self.termination_succeeded = False
        self.thread.join(timeout=max(float(grace_s), 0.0))
        return self.termination_succeeded

    def wait_for_admitted_sequence(
        self,
        *,
        timeout_s: float = 5.0,
    ) -> list[ControlMessage]:
        """Wait for and admit a physical response that outlived the deadline."""
        timeout_s = max(float(timeout_s), 0.0)
        self.thread.join(timeout=timeout_s)
        if self.thread.is_alive():
            raise TimeoutError("late_subprocess_response_not_ready")
        try:
            self.process.wait(timeout=max(timeout_s, 0.1))
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("late_subprocess_worker_not_reaped") from exc
        return self.transport._admit_completed_responses(
            request=self.request,
            responses=self._responses,
            response_wire_bytes=self._response_wire_bytes,
            carrier=self.carrier,
            request_wire_bytes=self.request_wire_bytes,
            worker_pid=self.process.pid,
        )

    def canonical_payload(self) -> dict[str, object]:
        header = self.request.header
        return {
            "origin": self.origin,
            "step_id": header.step_id,
            "attempt_id": header.attempt_id,
            "invocation_id": header.invocation_id,
            "worker_pid": self.process.pid,
            "observed_response_types": [
                type(response).__name__ for response in self._responses
            ],
            "termination_attempted": self.termination_attempted,
            "termination_succeeded": self.termination_succeeded,
            "termination_outcome": self.termination_outcome,
        }


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
    receives one ``ExecRequest``, executes it, and returns a result frame.

    Protocol: main sends ExecRequest → worker sends AckReceived + RunStart +
    Heartbeat + SuccessResult (or ErrorResult) → connection closes.

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
    last_exchange_audit: ExecutorTransportAudit | None = field(
        default=None,
        init=False,
    )
    last_admission_receipts: tuple[ControlResponseAdmissionReceipt, ...] = field(
        default=(),
        init=False,
    )
    last_control_frames: tuple[dict[str, object], ...] = field(default=(), init=False)
    last_response_messages: tuple[ControlMessage, ...] = field(default=(), init=False)
    last_failure_propagation: dict[str, object] = field(default_factory=dict, init=False)

    def _record_exchange_audit(
        self,
        *,
        carrier: str,
        worker_pid: int,
        request_wire_bytes: int,
        responses: list[ControlMessage],
        response_wire_bytes: list[int],
        socket_path_requested: Path | None = None,
        socket_path_effective: Path | None = None,
        socket_inode: int | None = None,
        request_frame_metadata: tuple[dict[str, object], ...] = (),
        response_frame_metadata: tuple[dict[str, object], ...] = (),
        failure_stage: str = "",
        error_code: str = "",
    ) -> None:
        request_header = getattr(getattr(self, "_last_request", None), "header", None)
        observed_header = responses[0].header if responses else request_header
        self.last_exchange_audit = ExecutorTransportAudit(
            carrier="utf8_text" if carrier == "utf8_text" else "typed_protobuf",
            backend="uds_subprocess",
            driver_pid=os.getpid(),
            worker_pid=worker_pid,
            request_frame_count=1,
            response_frame_count=len(responses),
            request_wire_bytes=request_wire_bytes,
            response_wire_bytes=sum(response_wire_bytes),
            socket_path_requested=str(self.socket_path),
            socket_path_effective=str(socket_path_effective or self.socket_path),
            socket_inode=socket_inode,
            session_id=responses[0].header.session_id if responses else "",
            request_frame_metadata=request_frame_metadata,
            response_frame_metadata=response_frame_metadata,
            failure_stage=failure_stage,
            error_code=error_code,
            task_id=getattr(observed_header, "task_id", ""),
            step_id=getattr(observed_header, "step_id", ""),
            attempt_id=getattr(observed_header, "attempt_id", ""),
            invocation_id=getattr(observed_header, "invocation_id", ""),
            execution_binding_hash=getattr(observed_header, "execution_binding_hash", ""),
            capability_grant_hash=getattr(observed_header, "capability_grant_hash", ""),
        )
        self.last_control_frames = request_frame_metadata + response_frame_metadata

    def _admit_completed_responses(
        self,
        *,
        request: ExecRequest,
        responses: list[ControlMessage],
        response_wire_bytes: list[int],
        carrier: str,
        request_wire_bytes: int,
        worker_pid: int,
    ) -> list[ControlMessage]:
        self._record_exchange_audit(
            carrier=carrier,
            worker_pid=worker_pid,
            request_wire_bytes=request_wire_bytes,
            responses=responses,
            response_wire_bytes=response_wire_bytes,
            socket_path_effective=getattr(self, "_last_effective_socket_path", None),
            socket_inode=getattr(self, "_last_socket_inode", None),
            request_frame_metadata=getattr(self, "_request_frame_metadata", ()),
            response_frame_metadata=getattr(self, "_response_frame_metadata", ()),
        )
        if not any(
            isinstance(message, (SuccessResult, ErrorResult, TrapFatal))
            for message in responses
        ):
            error = getattr(self, "_transport_error", None)
            error_code, failure_stage, terminal_status = self._stable_transport_failure(error)
            error_detail = "worker_closed_without_terminal"
            if error is not None:
                error_detail = str(error) or type(error).__name__
            responses.append(
                ErrorResult(
                    header=replace(request.header, event_type=EventType.RES_ERR),
                    error_code=error_code,
                    error_detail=error_detail,
                    failed_at_ns=time.time_ns(),
                )
            )
            self.last_failure_propagation = {
                "stage": failure_stage,
                "error_code": error_code,
                "terminal_status": terminal_status,
                "evidence": {
                    "exception_type": type(error).__name__ if error is not None else "",
                    "socket_path_requested": str(self.socket_path),
                    "socket_path_effective": str(getattr(self, "_last_effective_socket_path", self.socket_path)),
                    "socket_inode": getattr(self, "_last_socket_inode", None),
                },
            }

        canonical_scope_fields = (
            request.header.run_id,
            request.header.session_id,
            request.header.invocation_id,
            request.header.execution_binding_hash,
            request.header.capability_grant_hash,
        )
        origin = (
            ControlResponseOrigin.ADAPTER_DERIVED
            if carrier == "utf8_text"
            else (
                ControlResponseOrigin.NATIVE_TYPED_WORKER
                if all(str(value).strip() for value in canonical_scope_fields)
                else ControlResponseOrigin.LEGACY_COMPATIBILITY
            )
        )
        admitted, receipts = admit_control_response_sequence(
            request,
            responses,
            origin=origin,
        )
        self.last_admission_receipts = receipts
        self.last_response_messages = tuple(responses)

        # The legacy admission helper intentionally tolerates a bare
        # ErrorResult for compatibility.  A physical typed sequence is
        # stricter: ACK -> RUN -> HEARTBEAT* -> exactly one terminal.
        phase = "initial"
        strict_reason: str | None = None
        terminal_seen = False
        for response in responses:
            if terminal_seen:
                if isinstance(response, (SuccessResult, ErrorResult, TrapFatal)):
                    strict_reason = (
                        "late_result_fenced"
                        if response.header.attempt_id != request.header.attempt_id
                        else "duplicate_terminal"
                    )
                else:
                    strict_reason = "event_after_terminal"
                break
            if isinstance(response, AckReceived):
                if phase != "initial":
                    strict_reason = "illegal_event_order"
                    break
                phase = "acked"
            elif isinstance(response, RunStart):
                if phase != "acked":
                    strict_reason = "illegal_event_order"
                    break
                phase = "running"
            elif isinstance(response, Heartbeat):
                if phase != "running":
                    strict_reason = "illegal_event_order"
                    break
            elif isinstance(response, (SuccessResult, ErrorResult, TrapFatal)):
                if not isinstance(response, ErrorResult) and phase != "running":
                    strict_reason = "illegal_event_order"
                    break
                if isinstance(response, ErrorResult) and phase == "terminal":
                    strict_reason = "illegal_event_order"
                    break
                terminal_seen = True
                phase = "terminal"
        if strict_reason is not None:
            self.last_failure_propagation = {
                "stage": "response_order",
                "error_code": strict_reason,
                "terminal_status": "runtime_fail",
                "evidence": {
                    "terminal_count": sum(isinstance(item, (SuccessResult, ErrorResult, TrapFatal)) for item in responses),
                    "response_types": [type(item).__name__ for item in responses],
                },
            }
            raise ControlResponseAdmissionError(
                tuple(
                    replace(receipt, admitted=False, reason_code=strict_reason)
                    if index == len(receipts) - 1
                    else receipt
                    for index, receipt in enumerate(receipts)
                )
            )
        if not admitted:
            reason = self.last_admission_receipts[-1].reason_code if self.last_admission_receipts else "response_not_admitted"
            self.last_failure_propagation = {
                "stage": "response_admission",
                "error_code": reason,
                "terminal_status": "policy_reject" if reason.startswith(("scope_mismatch:", "expected_scope_missing:", "capability_grant", "execution_binding", "attempt_scope")) else "runtime_fail",
            }
            raise ControlResponseAdmissionError(receipts)
        return list(admitted)

    def _stable_transport_failure(
        self,
        error: BaseException | None,
    ) -> tuple[str, str, str]:
        """Map physical transport failures to the frozen stage/code vocabulary."""
        stage = str(getattr(self, "_transport_error_stage", "transport_receive"))
        if isinstance(error, PermissionError):
            return "socket_permission_denied", stage or "transport_bind", "environment_fail"
        if isinstance(error, FileNotFoundError):
            return "socket_missing", stage or "transport_connect", "environment_fail"
        if isinstance(error, ConnectionRefusedError):
            return "socket_connection_refused", stage or "transport_connect", "environment_fail"
        if isinstance(error, socket.timeout):
            return "socket_accept_timeout", stage or "transport_accept", "environment_fail"
        if isinstance(error, ValueError):
            detail = str(error)
            if detail in {"frame_oversized", "frame_payload_truncated", "frame_header_truncated", "frame_length_invalid"}:
                return detail, stage or "framing", "runtime_fail"
            return "transport_decode_failed", stage or "transport_receive", "runtime_fail"
        if error is None:
            return "subprocess_terminal_response_missing", stage or "transport_receive", "runtime_fail"
        return "transport_exception", stage or "transport_receive", "environment_fail"

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

        self.last_admission_receipts = ()
        self.last_response_messages = ()
        self.last_failure_propagation = {}
        self._last_request = request
        normalized_carrier = carrier.strip().lower()
        if normalized_carrier not in {"protobuf", "utf8_text"}:
            raise ValueError(f"unsupported subprocess carrier: {carrier}")
        pass_fds: tuple[int, ...] = ()
        exec_request = request
        if memfd_refs:
            new_state_refs = []
            fds_to_pass: list[int] = []
            for ref in request.state_refs:
                entry = memfd_refs.get(ref.ref_id)
                if entry is not None:
                    fd, length = entry
                    new_state_refs.append(
                        encode_memfd_ref(fd=fd, length=length, state_id=ref.ref_id, ref_kind=ref.ref_kind)
                    )
                    fds_to_pass.append(fd)
                else:
                    new_state_refs.append(ref)
            existing_ids = {ref.ref_id for ref in request.state_refs}
            for state_id, (fd, length) in memfd_refs.items():
                if state_id not in existing_ids:
                    new_state_refs.append(encode_memfd_ref(fd=fd, length=length, state_id=state_id))
                    fds_to_pass.append(fd)
            exec_request = replace(request, state_refs=tuple(new_state_refs))
            pass_fds = tuple(sorted(set(fds_to_pass)))

        socket_path = effective_unix_socket_path(self.socket_path)
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _ensure_socket_available(socket_path)
        self._last_effective_socket_path = socket_path
        self._last_socket_inode = None
        self._request_frame_metadata = ()
        self._response_frame_metadata = ()
        self._transport_error = None
        self._transport_error_stage = ""

        responses: list[ControlMessage] = []
        response_wire_bytes: list[int] = []
        server_ready = threading.Event()
        request_sent = threading.Event()
        resolved_text_payload = text_payload or _default_text_exec_handoff(exec_request)
        request_frame = (
            frame_text_message(resolved_text_payload)
            if normalized_carrier == "utf8_text"
            else frame_control_message(exec_request)
        )
        request_wire_bytes = len(request_frame)
        request_metadata = control_frame_metadata(request_frame, ordinal=0, direction="send") if normalized_carrier != "utf8_text" else {"frame_ordinal": 0, "direction": "send", "framed_length_observed": len(request_frame), "payload_length_observed": len(request_frame) - 4, "frame_digest": hashlib.sha256(request_frame).hexdigest()}
        request_metadata.update({
            "message_type": type(exec_request).__name__,
            "event_type": exec_request.header.event_type.name,
            "schema_version": exec_request.header.schema_version,
            "task_id": exec_request.header.task_id,
            "session_id": exec_request.header.session_id,
            "step_id": exec_request.header.step_id,
            "attempt_id": exec_request.header.attempt_id,
            "invocation_id": exec_request.header.invocation_id,
            "execution_binding_hash": exec_request.header.execution_binding_hash,
            "capability_grant_hash": exec_request.header.capability_grant_hash,
        })
        self._request_frame_metadata = (request_metadata,)

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            bound_inode: int | None = None
            try:
                try:
                    server.bind(str(socket_path))
                except Exception as exc:
                    self._transport_error = exc
                    self._transport_error_stage = "transport_bind"
                    return
                bound_inode = socket_path.stat().st_ino
                self._last_socket_inode = bound_inode
                server.listen(1)
                server.settimeout(max(self.timeout_s, 2.0))
                server_ready.set()
                try:
                    conn, _ = server.accept()
                except Exception as exc:
                    self._transport_error = exc
                    self._transport_error_stage = "transport_accept"
                    return
                try:
                    # The Runtime deadline is owned by the waiting thread. Once
                    # connected, keep receiving so a late physical result can
                    # still be correlated and fenced after semantic timeout.
                    conn.settimeout(None)
                    conn.sendall(request_frame)
                    request_sent.set()
                    while True:
                        try:
                            if normalized_carrier == "utf8_text":
                                raw_response = _recv_framed(conn)
                                response_wire_bytes.append(len(raw_response))
                                metadata = {"frame_ordinal": len(self._response_frame_metadata), "direction": "recv", "framed_length_observed": len(raw_response), "payload_length_observed": len(raw_response) - 4, "frame_digest": hashlib.sha256(raw_response).hexdigest()}
                                text_response = raw_response[4:].decode("utf-8")
                                msg = _text_response_to_control_message(
                                    text_response,
                                    request=exec_request,
                                )
                            else:
                                raw_response = _recv_framed(conn)
                                response_wire_bytes.append(len(raw_response))
                                metadata = control_frame_metadata(raw_response, ordinal=len(self._response_frame_metadata), direction="recv")
                                msg = deframe_control_message(raw_response)
                            metadata.update({
                                "message_type": type(msg).__name__,
                                "event_type": msg.header.event_type.name,
                                "schema_version": msg.header.schema_version,
                                "task_id": msg.header.task_id,
                                "session_id": msg.header.session_id,
                                "step_id": msg.header.step_id,
                                "attempt_id": msg.header.attempt_id,
                                "invocation_id": msg.header.invocation_id,
                                "execution_binding_hash": msg.header.execution_binding_hash,
                                "capability_grant_hash": msg.header.capability_grant_hash,
                            })
                            self._response_frame_metadata += (metadata,)
                        except (ConnectionError, ConnectionResetError, socket.timeout):
                            break
                        responses.append(msg)
                except Exception as exc:
                    self._transport_error = exc
                    self._transport_error_stage = "transport_receive"
                finally:
                    conn.close()
            finally:
                server.close()
                if socket_path.exists() and bound_inode is not None:
                    try:
                        if socket_path.stat().st_ino == bound_inode:
                            socket_path.unlink()
                    except OSError:
                        pass

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        server_ready.wait(timeout=2.0)

        # A bind/accept failure is already a terminal environment observation;
        # do not launch a worker that could connect to a foreign residue.
        if not server_ready.is_set() and not t.is_alive():
            return [self._admit_completed_responses(
                request=exec_request,
                responses=responses,
                response_wire_bytes=response_wire_bytes,
                carrier=normalized_carrier,
                request_wire_bytes=request_wire_bytes,
                worker_pid=0,
            )[0]]

        worker_root = Path(__file__).resolve().parent.parent.parent
        proc = subprocess.Popen(
            [
                self.python_executable,
                "-m",
                "statebus.control.subprocess_worker",
                "--socket-path",
                str(socket_path),
                "--carrier",
                normalized_carrier,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_os.environ,
            cwd=str(worker_root),
            close_fds=True,
            pass_fds=pass_fds,
        )
        request_sent.wait(timeout=max(self.timeout_s, 2.0))
        t.join(timeout=self.timeout_s)
        if t.is_alive():
            self._record_exchange_audit(
                carrier=normalized_carrier,
                worker_pid=proc.pid,
                request_wire_bytes=request_wire_bytes,
                responses=responses,
                response_wire_bytes=response_wire_bytes,
                socket_path_effective=socket_path,
                socket_inode=self._last_socket_inode,
                request_frame_metadata=self._request_frame_metadata,
                response_frame_metadata=self._response_frame_metadata,
                failure_stage="transport_timeout",
                error_code="subprocess_transport_timeout",
            )
            raise SubprocessTransportTimeout(
                transport=self,
                request=exec_request,
                thread=t,
                process=proc,
                responses=responses,
                response_wire_bytes=response_wire_bytes,
                carrier=normalized_carrier,
                request_wire_bytes=request_wire_bytes,
            )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)

        return self._admit_completed_responses(
            request=exec_request,
            responses=responses,
            response_wire_bytes=response_wire_bytes,
            carrier=normalized_carrier,
            request_wire_bytes=request_wire_bytes,
            worker_pid=proc.pid,
        )

    def execute(
        self,
        request: ExecRequest,
        *,
        memfd_refs: dict[str, tuple[int, int]] | None = None,
        carrier: str = "protobuf",
        text_payload: str = "",
    ) -> Union[SuccessResult, ErrorResult, TrapFatal]:
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
            if isinstance(response, (SuccessResult, ErrorResult, TrapFatal)):
                return response
        raise RuntimeError("admitted_control_terminal_missing")
