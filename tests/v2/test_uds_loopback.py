from __future__ import annotations

from pathlib import Path

from v2.control import ControlHeader, ControlPlaneLoopbackServer, EventType, ExecRequest, RefHandle


def test_control_plane_uds_worker_harness_sequence(tmp_path: Path) -> None:
    message = ExecRequest(
        header=ControlHeader(
            trace_id="trace-uds",
            task_id="task-uds",
            step_id="step-uds",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=1000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(RefHandle(ref_id="state-1", ref_kind="semantic_state"),),
        artifact_refs=(RefHandle(ref_id="artifact-1", ref_kind="execution_artifact"),),
        runtime_reuse_contract="benchmark_strict:exact_replay_allowed",
        output_contract_version="output-v1",
        workspace_root="/statebus/workspaces/task-uds",
        input_manifest_hash="sha256:artifact-manifest",
    )

    responses = ControlPlaneLoopbackServer(tmp_path / "control.sock").exchange_sequence(message)
    assert [response.header.event_type.name for response in responses] == [
        "ACK_RECV",
        "RUN_START",
        "RES_SUCC",
    ]
    assert responses[-1].artifact_refs[0].ref_kind == "execution_artifact"
    assert responses[-1].output_contract_version == "output-v1"
