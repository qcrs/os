from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import replace
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from v2.control.messages import (
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
    deframe_control_message,
    frame_control_message,
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

    def exchange_sequence(
        self,
        request: ExecRequest,
        *,
        memfd_refs: dict[str, tuple[int, int]] | None = None,
    ) -> list[ControlMessage]:
        """Start a worker subprocess and return the full response frame sequence."""
        import os as _os

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
        server_ready = threading.Event()

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(socket_path))
                server.listen(1)
                server.settimeout(self.timeout_s)
                server_ready.set()
                conn, _ = server.accept()
                try:
                    send_control_message(conn, exec_request)
                    while True:
                        try:
                            msg = recv_control_message(conn)
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
                "v2.control.subprocess_worker",
                "--socket-path",
                str(socket_path),
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

        if any(isinstance(msg, (SuccessResult, ErrorResult)) for msg in responses):
            return responses
        return responses + [
            ErrorResult(
                header=replace(request.header, event_type=EventType.RES_ERR),
                error_code="subprocess_timeout",
                error_detail="worker subprocess did not return a result within timeout",
                failed_at_ns=time.time_ns(),
            )
        ]

    def execute(
        self,
        request: ExecRequest,
        *,
        memfd_refs: dict[str, tuple[int, int]] | None = None,
    ) -> Union[SuccessResult, ErrorResult]:
        """Start worker subprocess, exchange one ExecRequest/result pair.

        Args:
            request: The execution request.
            memfd_refs: Optional mapping of ``{state_id: (fd, length)}``.
                When provided the corresponding state_refs are rewritten to
                ``memfd_fd:`` handles and the FDs are inherited by the
                subprocess via ``pass_fds``.
        """
        for response in self.exchange_sequence(request, memfd_refs=memfd_refs):
            if isinstance(response, (SuccessResult, ErrorResult)):
                return response
        return ErrorResult(
            header=replace(request.header, event_type=EventType.RES_ERR),
            error_code="subprocess_timeout",
            error_detail="worker subprocess did not return a result within timeout",
            failed_at_ns=time.time_ns(),
        )
