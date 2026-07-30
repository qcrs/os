"""Tests for SubprocessExecutorTransport and subprocess_worker."""
from __future__ import annotations

import tempfile
from pathlib import Path

from statebus.control import (
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
from statebus.control.transport import SubprocessExecutorTransport


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
    # Missing required fields → should produce ErrorResult
    return ExecRequest(
        header=header,
        workspace_root="",
        input_manifest_hash="",
        output_contract_version="",
        runtime_reuse_contract="no_semantic_state",
        artifact_refs=(),
    )


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
