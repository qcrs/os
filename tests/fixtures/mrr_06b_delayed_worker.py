from __future__ import annotations

import argparse
from dataclasses import replace
import socket
import time

from statebus.control.messages import (
    AckReceived,
    EventType,
    ExecRequest,
    Heartbeat,
    RunStart,
    SuccessResult,
)
from statebus.control.transport import recv_control_message, send_control_message


def _connect(socket_path: str) -> socket.socket:
    deadline = time.monotonic() + 5.0
    while True:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(socket_path)
            return sock
        except OSError:
            sock.close()
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket-path", required=True)
    parser.add_argument("--carrier", default="protobuf")
    args = parser.parse_args()
    if args.carrier != "protobuf":
        raise ValueError("mrr_06b_fixture_requires_protobuf")

    sock = _connect(args.socket_path)
    try:
        request = recv_control_message(sock)
        if not isinstance(request, ExecRequest):
            raise TypeError("mrr_06b_fixture_expected_exec_request")
        header = request.header
        send_control_message(
            sock,
            AckReceived(
                header=replace(header, event_type=EventType.ACK_RECV),
                acked_at_ns=time.time_ns(),
            ),
        )
        send_control_message(
            sock,
            RunStart(
                header=replace(header, event_type=EventType.RUN_START),
                started_at_ns=time.time_ns(),
                heartbeat_interval_ms=50,
                lease_timeout_ms=5_000,
            ),
        )
        send_control_message(
            sock,
            Heartbeat(
                header=replace(header, event_type=EventType.HEARTBEAT),
                sent_at_ns=time.time_ns(),
                worker_state="running",
            ),
        )
        time.sleep(1.0)
        send_control_message(
            sock,
            SuccessResult(
                header=replace(header, event_type=EventType.RES_SUCC),
                artifact_refs=request.artifact_refs,
                output_contract_version=request.output_contract_version,
                completed_at_ns=time.time_ns(),
            ),
        )
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
