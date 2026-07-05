"""Executor subprocess worker entry point for StateBus v2 control plane.

The worker is launched by SubprocessExecutorTransport and communicates
with the main process over a Unix Domain Socket using typed Protobuf frames.

Protocol (worker-side):
  1. Connect to the UDS path supplied via --socket-path.
  2. Receive one ExecRequest frame from the main process.
  3. Validate required fields; send ErrorResult on failure.
  4. Read any memfd state refs (``memfd_fd:{fd}:{length}:{state_id}``).
  5. On success: send AckReceived → RunStart → Heartbeat → SuccessResult.
  6. Close connection and exit.

memfd refs
----------
When the ExecRequest contains state_refs with ``memfd_fd:`` prefixed
ref_ids the worker reads the embedding bytes directly from the inherited
file descriptor using ``os.read(fd, length)``.  The bytes never touch the
filesystem; the FD was created with ``memfd_create`` in the main process
and forwarded via ``pass_fds`` in ``subprocess.Popen``.

Usage:
  python -m v2.control.subprocess_worker --socket-path /tmp/statebus-exec.sock
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from dataclasses import replace

from v2.control.messages import (
    AckReceived,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    RunStart,
    SuccessResult,
)
from v2.control.transport import decode_memfd_ref, recv_control_message, send_control_message


def _read_memfd_refs(state_refs: tuple[RefHandle, ...]) -> dict[str, bytes]:
    """Read bytes from any inherited memfd FDs in state_refs.

    Returns {state_id: payload_bytes} for each successfully read memfd ref.
    Non-memfd refs are silently skipped.
    """
    result: dict[str, bytes] = {}
    for ref in state_refs:
        parsed = decode_memfd_ref(ref)
        if parsed is None:
            continue
        fd, length, state_id = parsed
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            data = os.read(fd, length)
        except OSError as exc:
            print(
                f"subprocess_worker: failed to read memfd fd={fd} state_id={state_id}: {exc}",
                file=sys.stderr,
            )
            continue
        result[state_id] = data
    return result


def run(socket_path: str) -> int:
    """Connect to supervisor, process one ExecRequest, return exit code."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(socket_path)
    except OSError as exc:
        print(f"subprocess_worker: connect failed: {exc}", file=sys.stderr)
        return 1

    try:
        message = recv_control_message(sock)
    except Exception as exc:
        print(f"subprocess_worker: recv failed: {exc}", file=sys.stderr)
        sock.close()
        return 1

    if not isinstance(message, ExecRequest):
        print(
            f"subprocess_worker: expected ExecRequest, got {type(message).__name__}",
            file=sys.stderr,
        )
        sock.close()
        return 1

    header = message.header
    runtime_reuse_contract = message.runtime_reuse_contract or ""
    semantic_optional = "no_semantic_state" in runtime_reuse_contract

    errors: list[str] = []
    if not message.workspace_root.strip():
        errors.append("workspace_root_missing")
    if not message.input_manifest_hash.strip():
        errors.append("input_manifest_hash_missing")
    if not message.output_contract_version.strip():
        errors.append("output_contract_version_missing")
    if not semantic_optional and not message.state_refs:
        errors.append("state_refs_missing")
    if not message.artifact_refs:
        errors.append("artifact_refs_missing")

    if errors:
        send_control_message(
            sock,
            ErrorResult(
                header=replace(header, event_type=EventType.RES_ERR),
                error_code="invalid_exec_request",
                error_detail=",".join(errors),
                failed_at_ns=0,
            ),
        )
        sock.close()
        return 1

    # Read any memfd state refs passed by the main process.
    memfd_payloads = _read_memfd_refs(message.state_refs)
    if memfd_payloads:
        total_bytes = sum(len(v) for v in memfd_payloads.values())
        print(
            f"subprocess_worker: read {len(memfd_payloads)} memfd ref(s), "
            f"{total_bytes} bytes total: {list(memfd_payloads)}",
            file=sys.stderr,
        )

    now = time.time_ns()
    send_control_message(
        sock,
        AckReceived(
            header=replace(header, event_type=EventType.ACK_RECV),
            acked_at_ns=now,
        ),
    )
    send_control_message(
        sock,
        RunStart(
            header=replace(header, event_type=EventType.RUN_START),
            started_at_ns=now + 1,
            heartbeat_interval_ms=2000,
            lease_timeout_ms=30_000,
        ),
    )
    send_control_message(
        sock,
        Heartbeat(
            header=replace(header, event_type=EventType.HEARTBEAT),
            sent_at_ns=now + 2,
            worker_state="running",
        ),
    )
    send_control_message(
        sock,
        SuccessResult(
            header=replace(header, event_type=EventType.RES_SUCC),
            state_refs=message.state_refs,
            artifact_refs=message.artifact_refs,
            output_contract_version=message.output_contract_version,
            completed_at_ns=time.time_ns(),
        ),
    )
    sock.close()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="StateBus v2 Executor subprocess worker")
    parser.add_argument("--socket-path", required=True, help="UDS path to connect to")
    args = parser.parse_args()
    sys.exit(run(args.socket_path))


if __name__ == "__main__":
    main()
