from __future__ import annotations

from v2.control import (
    ControlHeader,
    EventType,
    ExecRequest,
    RefHandle,
    ReusePolicy,
    deframe_control_message,
    frame_control_message,
)


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
        runtime_reuse_contract="benchmark_strict:exact_replay_allowed",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-1",
        input_manifest_hash="sha256:manifest",
    )

    parsed = deframe_control_message(frame_control_message(message))
    assert isinstance(parsed, ExecRequest)
    assert parsed.header.event_type == EventType.REQ_EXEC
    assert parsed.state_refs[0].ref_kind == "semantic_state"
    assert parsed.artifact_refs[0].ref_kind == "execution_artifact"
    assert parsed.reuse_policy.allow_validated_replay is True
    assert parsed.runtime_reuse_contract == "benchmark_strict:exact_replay_allowed"
    assert parsed.workspace_root == "/statebus/workspaces/task-1"
