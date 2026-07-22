"""Tests for SubprocessExecutorTransport and subprocess_worker."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from v2.control import (
    AckReceived,
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    ReusePolicy,
    RunStart,
    SuccessResult,
)
from v2.control.transport import (
    SubprocessExecutorTransport,
    _validate_numeric_worker_response,
    recv_control_message,
    send_control_message,
)
from v2.control.worker_operations import (
    TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION,
    compute_typed_numeric_summary,
    encode_typed_numeric_input,
)


def _make_exec_request(*, valid: bool = True) -> ExecRequest:
    header = ControlHeader(
        trace_id="trace-test",
        task_id="task-test",
        step_id="step-test",
        attempt_id="attempt-test",
        target_role="executor",
        timeout_ms=30_000,
        event_type=EventType.REQ_EXEC,
    )
    if valid:
        return ExecRequest(
            header=header,
            workspace_root="/tmp/workspace-test",
            input_manifest_hash="sha256:input",
            output_contract_version="output-v1",
            runtime_reuse_contract="no_semantic_state",
            artifact_refs=(
                RefHandle(ref_id="artifact-1", ref_kind="artifact"),
            ),
        )
    # Missing required fields -> should produce ErrorResult.
    return ExecRequest(
        header=header,
        workspace_root="",
        input_manifest_hash="",
        output_contract_version="",
        runtime_reuse_contract="no_semantic_state",
        artifact_refs=(),
    )


def _make_numeric_request(
    *,
    input_ref_id: str = "numeric-input-1",
    artifact_refs: tuple[RefHandle, ...] = (),
) -> ExecRequest:
    return ExecRequest(
        header=ControlHeader(
            trace_id="trace-numeric",
            task_id="task-numeric",
            step_id="numeric-summary",
            attempt_id="attempt-numeric",
            target_role="executor",
            timeout_ms=30_000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(RefHandle(ref_id=input_ref_id, ref_kind="numeric_vector"),),
        artifact_refs=artifact_refs,
        runtime_reuse_contract="typed_numeric_state_required",
        output_contract_version=TYPED_NUMERIC_OUTPUT_CONTRACT_VERSION,
        workspace_root="/tmp/workspace-numeric",
        input_manifest_hash="sha256:numeric-input",
        operation="typed_numeric_summary_v1",
    )


def _memfd_payload(payload: bytes) -> int:
    fd = os.memfd_create("statebus-numeric-test", flags=0)
    os.write(fd, payload)
    os.lseek(fd, 0, os.SEEK_SET)
    return fd


def test_subprocess_executor_valid_round_trip(tmp_path: Path) -> None:
    """A valid ExecRequest round-trips through the subprocess and returns SuccessResult."""
    sock_path = tmp_path / "exec.sock"
    transport = SubprocessExecutorTransport(socket_path=sock_path, timeout_s=20.0)
    request = _make_exec_request(valid=True)

    result = transport.execute(request)

    assert isinstance(result, SuccessResult), (
        f"Expected SuccessResult but got {type(result).__name__}: {result}"
    )
    assert result.output_contract_version == "output-v1"
    assert result.artifact_refs == request.artifact_refs
    audit = transport.last_exchange_audit
    assert audit is not None
    assert audit.negotiation_performed is True
    assert audit.negotiation_accepted is True
    assert audit.controller_registry_digest == audit.worker_registry_digest
    assert audit.required_capability_ids == ("echo_refs_v1",)
    assert "echo_refs_v1" in audit.supported_capability_ids
    assert audit.negotiation_request_frame_count == 1
    assert audit.negotiation_response_frame_count == 1
    assert audit.execution_request_frame_count == 1
    assert audit.execution_response_frame_count == 4
    assert audit.request_frame_count == 2
    assert audit.response_frame_count == 5


def test_subprocess_executor_utf8_text_round_trip(tmp_path: Path) -> None:
    sock_path = tmp_path / "exec-text.sock"
    transport = SubprocessExecutorTransport(socket_path=sock_path, timeout_s=20.0)
    request = _make_exec_request(valid=True)

    result = transport.execute(request, carrier="utf8_text")

    assert isinstance(result, SuccessResult)
    assert result.output_contract_version == "output-v1"
    assert result.artifact_refs == ()
    assert transport.last_exchange_audit is not None
    assert transport.last_exchange_audit.carrier == "utf8_text"
    assert transport.last_exchange_audit.backend == "uds_subprocess"
    assert transport.last_exchange_audit.driver_pid != transport.last_exchange_audit.worker_pid
    assert transport.last_exchange_audit.request_wire_bytes > 0
    assert transport.last_exchange_audit.negotiation_performed is False
    assert transport.last_exchange_audit.negotiation_request_frame_count == 0
    assert transport.last_exchange_audit.execution_request_frame_count == 1


def test_subprocess_executor_invalid_request_returns_error(tmp_path: Path) -> None:
    """An ExecRequest missing required fields returns ErrorResult from the worker."""
    sock_path = tmp_path / "exec-err.sock"
    transport = SubprocessExecutorTransport(socket_path=sock_path, timeout_s=20.0)
    request = _make_exec_request(valid=False)

    result = transport.execute(request)

    assert isinstance(result, ErrorResult), (
        f"Expected ErrorResult but got {type(result).__name__}: {result}"
    )
    assert result.error_code == "invalid_exec_request"
    assert "workspace_root_missing" in result.error_detail
    assert "input_manifest_hash_missing" in result.error_detail
    assert "output_contract_version_missing" in result.error_detail
    assert "artifact_refs_missing" in result.error_detail


@pytest.mark.parametrize(
    ("transport_options", "expected_error"),
    [
        ({"offered_protocol_versions": ("statebus.uds.protobuf.v999",)}, "protocol_version_mismatch"),
        ({"offered_schema_versions": ("statebus.control.v999",)}, "schema_version_mismatch"),
        ({"controller_registry_digest": "sha256:wrong-registry"}, "capability_registry_digest_mismatch"),
        ({"required_capability_ids": ("unknown_worker_capability_v1",)}, "missing_required_capability"),
    ],
)
def test_subprocess_executor_rejects_incompatible_handshake_before_exec(
    tmp_path: Path,
    transport_options: dict[str, object],
    expected_error: str,
) -> None:
    transport = SubprocessExecutorTransport(
        socket_path=tmp_path / f"{expected_error}.sock",
        timeout_s=20.0,
        **transport_options,
    )

    result = transport.execute(_make_exec_request(valid=True))

    assert isinstance(result, ErrorResult)
    assert result.error_code == expected_error
    audit = transport.last_exchange_audit
    assert audit is not None
    assert audit.negotiation_performed is True
    assert audit.negotiation_accepted is False
    assert expected_error in audit.negotiation_error
    assert audit.negotiation_request_frame_count == 1
    assert audit.negotiation_response_frame_count == 1
    assert audit.execution_request_frame_count == 0
    assert audit.execution_response_frame_count == 0
    assert audit.request_frame_count == 1
    assert audit.response_frame_count == 1


def test_subprocess_worker_rejects_exec_request_before_hello(tmp_path: Path) -> None:
    socket_path = tmp_path / "pre-hello.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(socket_path))
    server.listen(1)
    server.settimeout(20.0)
    worker_root = Path(__file__).resolve().parent.parent.parent
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "v2.control.subprocess_worker",
            "--socket-path",
            str(socket_path),
        ],
        cwd=str(worker_root),
        env={
            key: value
            for key, value in os.environ.items()
            if key in {"PATH", "PYTHONPATH", "PYTHONHOME", "LANG", "LC_ALL", "LD_LIBRARY_PATH"}
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        conn, _ = server.accept()
        try:
            send_control_message(conn, _make_exec_request(valid=True))
            result = recv_control_message(conn)
        finally:
            conn.close()
        proc.wait(timeout=10.0)
    finally:
        server.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)

    assert isinstance(result, ErrorResult)
    assert result.error_code == "hello_required_before_exec"
    assert proc.returncode == 1


@pytest.mark.skipif(not hasattr(os, "memfd_create"), reason="memfd_create is Linux-only")
def test_typed_numeric_summary_is_worker_owned_hash_validated_and_input_bound(
    tmp_path: Path,
) -> None:
    output_hashes: list[str] = []
    for index, values in enumerate(((1.0, 2.0, 7.0), (1.0, 2.0, 8.0)), start=1):
        payload = encode_typed_numeric_input(values)
        fd = _memfd_payload(payload)
        try:
            request = _make_numeric_request()
            transport = SubprocessExecutorTransport(
                socket_path=tmp_path / f"numeric-{index}.sock",
                timeout_s=20.0,
            )
            result = transport.execute(
                request,
                memfd_refs={"numeric-input-1": (fd, len(payload))},
            )
        finally:
            os.close(fd)

        assert isinstance(result, SuccessResult)
        assert result.numeric_summary is not None
        assert result.numeric_summary.row_count == 3
        assert result.numeric_summary.total == sum(values)
        assert result.numeric_summary.mean == sum(values) / 3
        assert result.numeric_summary.minimum == 1.0
        assert result.numeric_summary.maximum == values[-1]
        assert result.numeric_summary.worker_pid != os.getpid()
        assert result.numeric_summary.worker_compute_ns > 0
        assert result.consumed_state_ref_id == "numeric-input-1"
        output_hashes.append(result.numeric_summary.output_artifact_hash)
        audit = transport.last_exchange_audit
        assert audit is not None
        assert audit.required_capability_ids == ("typed_numeric_summary_v1",)
        assert audit.negotiation_accepted is True

    assert output_hashes[0] != output_hashes[1]


@pytest.mark.skipif(not hasattr(os, "memfd_create"), reason="memfd_create is Linux-only")
def test_typed_numeric_summary_rejects_additional_ref_scope(tmp_path: Path) -> None:
    payload = encode_typed_numeric_input((2.0, 4.0))
    fd = _memfd_payload(payload)
    try:
        request = _make_numeric_request(
            artifact_refs=(RefHandle(ref_id="unauthorized-artifact", ref_kind="artifact"),)
        )
        result = SubprocessExecutorTransport(
            socket_path=tmp_path / "numeric-scope.sock",
            timeout_s=20.0,
        ).execute(
            request,
            memfd_refs={"numeric-input-1": (fd, len(payload))},
        )
    finally:
        os.close(fd)

    assert isinstance(result, ErrorResult)
    assert result.error_code == "invalid_exec_request"
    assert "typed_numeric_scope_violation" in result.error_detail


def test_typed_numeric_summary_rejects_non_fd_input(tmp_path: Path) -> None:
    result = SubprocessExecutorTransport(
        socket_path=tmp_path / "numeric-no-fd.sock",
        timeout_s=20.0,
    ).execute(_make_numeric_request())

    assert isinstance(result, ErrorResult)
    assert result.error_code == "invalid_exec_request"
    assert "typed_numeric_input_fd_required" in result.error_detail


@pytest.mark.skipif(not hasattr(os, "memfd_create"), reason="memfd_create is Linux-only")
def test_controller_rejects_tampered_numeric_worker_hash() -> None:
    payload = encode_typed_numeric_input((3.0, 5.0))
    fd = _memfd_payload(payload)
    try:
        summary = compute_typed_numeric_summary(
            payload,
            input_ref_id="numeric-input-1",
            worker_pid=12345,
            worker_compute_ns=100,
        )
        result = SuccessResult(
            header=replace(_make_numeric_request().header, event_type=EventType.RES_SUCC),
            numeric_summary=replace(summary, output_artifact_hash="tampered"),
        )
        error = _validate_numeric_worker_response(
            result,
            request=_make_numeric_request(),
            memfd_refs={"numeric-input-1": (fd, len(payload))},
            negotiated_worker_pid=12345,
        )
    finally:
        os.close(fd)

    assert error == "numeric_summary_content_or_hash_mismatch"
