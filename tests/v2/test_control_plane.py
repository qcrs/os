from __future__ import annotations

import os
import platform
import sys
import tempfile
from pathlib import Path

import pytest

from v2.contracts import CONTROL_PLANE_SCHEMA_VERSION
from v2.control import (
    CONTROL_PROTOCOL_VERSION,
    ControlHeader,
    EventType,
    ExecRequest,
    Hello,
    LogitGateResult,
    LogitStateGrantControl,
    LogitStateRefControl,
    NumericSummaryResult,
    RefHandle,
    ReusePolicy,
    deframe_control_message,
    frame_control_message,
    worker_capability_registry_digest,
)
from v2.control.transport import (
    ControlPlaneLoopbackServer,
    SubprocessExecutorTransport,
    decode_memfd_ref,
    encode_memfd_ref,
)
from v2.control.messages import SuccessResult


def test_control_plane_frame_round_trip_preserves_typed_refs() -> None:
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-1",
            task_id="task-1",
            step_id="step-1",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        ),
        reuse_policy=ReusePolicy(
            allow_assist=True,
            allow_validated_replay=True,
            allow_exact_replay=False,
        ),
        state_refs=(RefHandle(ref_id="state-1", ref_kind="semantic_state"),),
        artifact_refs=(RefHandle(ref_id="artifact-1", ref_kind="execution_artifact"),),
        memory_refs=(RefHandle(ref_id="memory-1", ref_kind="memory"),),
        runtime_reuse_contract="benchmark_strict:exact_replay_allowed",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-1",
        input_manifest_hash="sha256:manifest",
        operation="semantic_select_v1",
        state_root="/statebus/work/statepool/task-1",
        hydrate_manifest_id="manifest-1",
        semantic_top_k=3,
        evidence_budget_bytes=4096,
        expected_encoder_signature="encoder-signature",
        capability_grant_hash="grant-hash",
    )

    parsed = deframe_control_message(frame_control_message(message))
    assert isinstance(parsed, ExecRequest)
    assert parsed.header.event_type == EventType.REQ_EXEC
    assert parsed.state_refs[0].ref_kind == "semantic_state"
    assert parsed.artifact_refs[0].ref_kind == "execution_artifact"
    assert parsed.memory_refs[0].ref_kind == "memory"
    assert parsed.reuse_policy.allow_validated_replay is True
    assert parsed.runtime_reuse_contract == "benchmark_strict:exact_replay_allowed"
    assert parsed.workspace_root == "/statebus/workspaces/task-1"
    assert parsed.operation == "semantic_select_v1"
    assert parsed.state_root == "/statebus/work/statepool/task-1"
    assert parsed.hydrate_manifest_id == "manifest-1"
    assert parsed.semantic_top_k == 3
    assert parsed.evidence_budget_bytes == 4096
    assert parsed.expected_encoder_signature == "encoder-signature"
    assert parsed.capability_grant_hash == "grant-hash"


def test_control_plane_frame_round_trip_preserves_hello_negotiation() -> None:
    message = Hello(
        header=ControlHeader(
            trace_id="trace-hello",
            task_id="task-hello",
            step_id="control-handshake",
            attempt_id="attempt-1",
            target_role="executor_worker",
            timeout_ms=5000,
            event_type=EventType.HELLO,
        ),
        protocol_versions=(CONTROL_PROTOCOL_VERSION,),
        schema_versions=(CONTROL_PLANE_SCHEMA_VERSION,),
        controller_registry_digest=worker_capability_registry_digest(),
        required_capability_ids=("echo_refs_v1",),
        controller_pid=os.getpid(),
    )

    parsed = deframe_control_message(frame_control_message(message))

    assert parsed == message


def test_control_plane_frame_round_trip_preserves_typed_numeric_result() -> None:
    summary = NumericSummaryResult(
        input_ref_id="numeric-1",
        input_payload_hash="input-hash",
        row_count=2,
        total=4.0,
        mean=2.0,
        minimum=1.0,
        maximum=3.0,
        schema_digest="schema-hash",
        output_artifact_hash="output-hash",
        validator_receipt_hash="receipt-hash",
        worker_pid=42,
        worker_compute_ns=100,
    )
    message = SuccessResult(
        header=ControlHeader(
            trace_id="trace-numeric",
            task_id="task-numeric",
            step_id="numeric-summary",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.RES_SUCC,
        ),
        output_contract_version="statebus.numeric_summary.v1",
        numeric_summary=summary,
    )

    parsed = deframe_control_message(frame_control_message(message))

    assert parsed == message


def test_control_plane_frame_round_trip_preserves_typed_logit_request() -> None:
    logit_ref = LogitStateRefControl(
        ref_id="logit-state-1",
        schema_version="statebus.logit_state.v2",
        task_id="task-logit",
        session_id="session-logit",
        trace_id="trace-logit",
        step_id="execute",
        request_id="request-logit",
        attempt_id="attempt-logit",
        storage_kind="shared_memory",
        shared_memory_name="statebus-logit-state-1",
        mmap_relpath="",
        blob_hash="logit-blob-hash",
        size_bytes=12,
        candidate_surface_digest="candidate-surface-digest",
        alias_mapping_digest="alias-mapping-digest",
        candidate_count=2,
        producer_pid=41,
        lease_expires_at_ns=123_456_789,
        model_id="model-logit",
        tokenizer_id="tokenizer-logit",
        chat_template_sha256="chat-template-digest",
        template_kwargs_sha256="template-kwargs-digest",
        response_schema_digest="response-schema-digest",
        calibration_version="calibration-version",
        threshold_policy_version="threshold-policy-version",
        gate_budget_version="gate-budget-version",
        policy="gated",
        decision_type="executor_tool_recipe_choice_v1",
        dtype="<f4",
        byte_order="little",
    )
    logit_grant = LogitStateGrantControl(
        schema_version="statebus.logit_state_grant.v1",
        ref_id=logit_ref.ref_id,
        task_id=logit_ref.task_id,
        session_id=logit_ref.session_id,
        trace_id=logit_ref.trace_id,
        step_id=logit_ref.step_id,
        request_id=logit_ref.request_id,
        attempt_id=logit_ref.attempt_id,
        consumer_component="confidence_gate",
        consumer_pid=42,
        candidate_surface_digest=logit_ref.candidate_surface_digest,
        alias_mapping_digest=logit_ref.alias_mapping_digest,
        calibration_version=logit_ref.calibration_version,
        threshold_policy_version=logit_ref.threshold_policy_version,
        gate_budget_version=logit_ref.gate_budget_version,
        model_id=logit_ref.model_id,
        tokenizer_id=logit_ref.tokenizer_id,
        chat_template_sha256=logit_ref.chat_template_sha256,
        template_kwargs_sha256=logit_ref.template_kwargs_sha256,
        response_schema_digest=logit_ref.response_schema_digest,
        expires_at_ns=123_456_000,
        grant_token="grant-token",
    )
    message = ExecRequest(
        header=ControlHeader(
            trace_id=logit_ref.trace_id,
            task_id=logit_ref.task_id,
            step_id=logit_ref.step_id,
            attempt_id=logit_ref.attempt_id,
            target_role="confidence_gate",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(RefHandle(ref_id=logit_ref.ref_id, ref_kind="logit_state"),),
        runtime_reuse_contract="logit_state_required",
        output_contract_version="statebus.gate_decision.v1",
        workspace_root="/statebus/state/logit",
        input_manifest_hash="logit-ref-digest",
        operation="logit_gate_v1",
        state_root="/statebus/state/logit",
        logit_state_ref=logit_ref,
        logit_state_grant=logit_grant,
        logit_gate_policy_json='{"schema_version":"statebus.logit_gate_policy.v1"}',
    )

    parsed = deframe_control_message(frame_control_message(message))

    assert parsed == message


def test_control_plane_frame_round_trip_preserves_typed_logit_gate_result() -> None:
    gate_result = LogitGateResult(
        schema_version="statebus.gate_decision.v1",
        decision_id="decision-1",
        action_token="action-token-1",
        ref_id="logit-state-1",
        task_id="task-logit",
        request_id="request-logit",
        consumer_pid=42,
        producer_pid=41,
        action="verify_once",
        selected_candidate_probability=0.61,
        entropy=0.79,
        normalized_entropy=0.72,
        top_margin=0.18,
        other_mass=0.03,
        candidate_count=2,
        calibration_version="calibration-version",
        threshold_policy_version="threshold-policy-version",
        gate_budget_version="gate-budget-version",
        reason="selected_probability_verify_band",
    )
    message = SuccessResult(
        header=ControlHeader(
            trace_id="trace-logit",
            task_id=gate_result.task_id,
            step_id="execute",
            attempt_id="attempt-logit",
            target_role="confidence_gate",
            timeout_ms=5000,
            event_type=EventType.RES_SUCC,
        ),
        output_contract_version="statebus.gate_decision.v1",
        consumed_state_ref_id=gate_result.ref_id,
        logit_gate_result=gate_result,
        logit_grant_hash="grant-hash",
        logit_action_reused=True,
    )

    parsed = deframe_control_message(frame_control_message(message))

    assert parsed == message


def test_loopback_transport_shortens_overlong_unix_socket_path(tmp_path: Path) -> None:
    requested_socket = tmp_path / ("nested-" + "x" * 80) / "control.sock"
    assert len(os.fsencode(requested_socket)) > 107
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-overlong-socket",
            task_id="task-overlong-socket",
            step_id="step-1",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        ),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-overlong-socket",
        input_manifest_hash="sha256:manifest",
        artifact_refs=(RefHandle(ref_id="artifact-1", ref_kind="execution_artifact"),),
    )

    echoed = ControlPlaneLoopbackServer(requested_socket).round_trip(message)

    assert echoed == message
    assert not requested_socket.exists()


def test_encode_decode_memfd_ref_round_trip() -> None:
    """encode_memfd_ref / decode_memfd_ref must be lossless."""
    ref = encode_memfd_ref(fd=7, length=64, state_id="emb-001", ref_kind="embedding")
    assert ref.ref_id == "memfd_fd:7:64:emb-001"
    assert ref.ref_kind == "embedding"

    parsed = decode_memfd_ref(ref)
    assert parsed == (7, 64, "emb-001")


def test_decode_memfd_ref_returns_none_for_plain_ref() -> None:
    ref = RefHandle(ref_id="plain-state-id", ref_kind="semantic_state")
    assert decode_memfd_ref(ref) is None


def _make_header(task_id: str = "task-memfd") -> ControlHeader:
    return ControlHeader(
        trace_id="trace-memfd",
        task_id=task_id,
        step_id="step-1",
        attempt_id="attempt-1",
        target_role="executor",
        timeout_ms=15000,
        event_type=EventType.REQ_EXEC,
    )


@pytest.mark.skipif(
    platform.system() != "Linux",
    reason="memfd_create is Linux-only",
)
def test_subprocess_transport_memfd_e2e(tmp_path: Path) -> None:
    """SubprocessExecutorTransport must forward memfd FDs to the worker subprocess.

    Flow:
      1. Main process writes test bytes to a memfd.
      2. SubprocessExecutorTransport rewrites state_refs to memfd_fd: handles
         and passes the FD via pass_fds.
      3. subprocess_worker reads the bytes from the inherited FD.
      4. Worker returns SuccessResult — proves the subprocess received and
         accepted the ExecRequest with memfd refs.
    """
    from statepool.store import MemfdStatePool

    pool = MemfdStatePool(root=tmp_path / "memfd-pool")
    payload = b"query_embedding_f32_bytes_" + bytes(range(32))
    ref = pool.put_bytes("emb-subprocess-test", "embedding", payload)

    # Retrieve the FD that MemfdStatePool owns for this state.
    fd = pool.owned_fds["emb-subprocess-test"]
    length = ref.length
    assert length == len(payload)

    socket_path = tmp_path / "memfd-test.sock"
    transport = SubprocessExecutorTransport(
        socket_path=socket_path,
        timeout_s=20.0,
    )
    request = ExecRequest(
        header=_make_header(),
        state_refs=(RefHandle(ref_id="emb-subprocess-test", ref_kind="embedding"),),
        artifact_refs=(RefHandle(ref_id="art-1", ref_kind="execution_artifact"),),
        runtime_reuse_contract="no_semantic_state",
        output_contract_version="output-v1",
        workspace_root=str(tmp_path / "ws"),
        input_manifest_hash="sha256:test",
    )
    result = transport.execute(request, memfd_refs={"emb-subprocess-test": (fd, length)})

    assert isinstance(result, SuccessResult), (
        f"expected SuccessResult, got {type(result).__name__}: "
        f"{getattr(result, 'error_detail', '')}"
    )
    assert result.output_contract_version == "output-v1"
    # Worker echoes state_refs back — they should carry the memfd_fd: encoded ref.
    assert len(result.state_refs) == 1
    assert result.state_refs[0].ref_id.startswith("memfd_fd:")
    decoded = decode_memfd_ref(result.state_refs[0])
    assert decoded is not None
    _, echoed_length, echoed_state_id = decoded
    assert echoed_state_id == "emb-subprocess-test"
    assert echoed_length == length
