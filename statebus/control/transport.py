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
        if socket_path.exists():
            socket_path.unlink()

        responses: list[ControlMessage] = []
        response_wire_bytes: list[int] = []
        server_ready = threading.Event()
        resolved_text_payload = text_payload or _default_text_exec_handoff(exec_request)
        request_wire_bytes = len(
            frame_text_message(resolved_text_payload)
            if normalized_carrier == "utf8_text"
            else frame_control_message(exec_request)
        )

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(socket_path))
                server.listen(1)
                server.settimeout(self.timeout_s)
                server_ready.set()
                conn, _ = server.accept()
                try:
                    if normalized_carrier == "utf8_text":
                        send_text_message(conn, resolved_text_payload)
                    else:
                        send_control_message(conn, exec_request)
                    while True:
                        try:
                            if normalized_carrier == "utf8_text":
                                text_response = recv_text_message(conn)
                                response_wire_bytes.append(
                                    len(frame_text_message(text_response))
                                )
                                msg = _text_response_to_control_message(
                                    text_response,
                                    request=exec_request,
                                )
                            else:
                                msg = recv_control_message(conn)
                                response_wire_bytes.append(
                                    len(frame_control_message(msg))
                                )
                        except (ConnectionError, ConnectionResetError, socket.timeout):
                            break
                        responses.append(msg)
                        if isinstance(msg, (SuccessResult, ErrorResult)):
                            break
                except Exception:
                    pass
                finally:
                    conn.close()
            finally:
                server.close()
                if socket_path.exists():
                    socket_path.unlink()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        server_ready.wait(timeout=2.0)

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
        t.join(timeout=self.timeout_s)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        completed_responses = responses
        if not any(isinstance(msg, (SuccessResult, ErrorResult)) for msg in responses):
            completed_responses = responses + [ErrorResult(
                header=replace(request.header, event_type=EventType.RES_ERR),
                error_code="subprocess_timeout",
                error_detail="worker subprocess did not return a result within timeout",
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
            request_frame_count=1,
            response_frame_count=len(completed_responses),
            request_wire_bytes=request_wire_bytes,
            response_wire_bytes=sum(response_wire_bytes),
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
