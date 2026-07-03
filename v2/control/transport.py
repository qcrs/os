from __future__ import annotations

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
    RunStart,
    SuccessResult,
    TrapFatal,
    deframe_control_message,
    frame_control_message,
)


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
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
            server.listen(1)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                client.connect(str(self.socket_path))
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
            if self.socket_path.exists():
                self.socket_path.unlink()
        return echoed

    def exchange_sequence(self, message: ControlMessage) -> list[ControlMessage]:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        responses: list[ControlMessage] = []
        ready = threading.Event()

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(self.socket_path))
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
                if self.socket_path.exists():
                    self.socket_path.unlink()

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()
        ready.wait(timeout=2.0)

        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(self.socket_path))
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
        if not getattr(message, "workspace_root", "").strip():
            required_errors.append("workspace_root_missing")
        if not getattr(message, "input_manifest_hash", "").strip():
            required_errors.append("input_manifest_hash_missing")
        if not getattr(message, "output_contract_version", "").strip():
            required_errors.append("output_contract_version_missing")
        if not semantic_state_optional and not tuple(getattr(message, "state_refs", ())):
            required_errors.append("state_refs_missing")
        if not tuple(getattr(message, "artifact_refs", ())):
            required_errors.append("artifact_refs_missing")
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


@dataclass
class SubprocessExecutorTransport:
    """Launch a worker subprocess and communicate via UDS + typed Protobuf frames.

    The main process listens on ``socket_path``; the subprocess connects,
    receives one ``ExecRequest``, executes it, and returns a result frame.

    Protocol: main sends ExecRequest → worker sends AckReceived + RunStart +
    Heartbeat + SuccessResult (or ErrorResult) → connection closes.
    """

    socket_path: Path
    python_executable: str = sys.executable
    timeout_s: float = 30.0

    def execute(self, request: ExecRequest) -> Union[SuccessResult, ErrorResult]:
        """Start worker subprocess, exchange one ExecRequest/result pair."""
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            self.socket_path.unlink()

        result_holder: list[Union[SuccessResult, ErrorResult]] = []
        server_ready = threading.Event()

        def _serve() -> None:
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(self.socket_path))
                server.listen(1)
                server.settimeout(self.timeout_s)
                server_ready.set()
                conn, _ = server.accept()
                try:
                    send_control_message(conn, request)
                    # Drain intermediate frames (ACK, RUN_START, HEARTBEAT).
                    # For error responses the worker sends only one frame, so
                    # treat any SuccessResult/ErrorResult as the final message.
                    final = None
                    for _ in range(4):
                        try:
                            msg = recv_control_message(conn)
                        except (ConnectionError, ConnectionResetError):
                            break
                        if isinstance(msg, (SuccessResult, ErrorResult)):
                            final = msg
                            break
                    if final is not None and isinstance(final, (SuccessResult, ErrorResult)):
                        result_holder.append(final)
                except Exception:
                    pass
                finally:
                    conn.close()
            finally:
                server.close()
                if self.socket_path.exists():
                    self.socket_path.unlink()

        import os as _os

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        server_ready.wait(timeout=2.0)

        # Determine project root (parent of the v2/ package directory)
        _worker_file = Path(__file__).resolve().parent.parent.parent
        proc = subprocess.Popen(
            [
                self.python_executable,
                "-m",
                "v2.control.subprocess_worker",
                "--socket-path",
                str(self.socket_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_os.environ,
            cwd=str(_worker_file),
        )
        t.join(timeout=self.timeout_s)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

        if result_holder:
            return result_holder[0]
        return ErrorResult(
            header=replace(request.header, event_type=EventType.RES_ERR),
            error_code="subprocess_timeout",
            error_detail="worker subprocess did not return a result within timeout",
            failed_at_ns=time.time_ns(),
        )
