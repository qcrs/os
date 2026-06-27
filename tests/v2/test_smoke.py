from __future__ import annotations

import json
from pathlib import Path

from v2.runtime.smoke import run_smoke


def test_v2_smoke_runs_vertical_slice(tmp_path: Path) -> None:
    result = run_smoke(
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert result.compiler_status == "compiled"
    assert result.supervisor_state == "GC_DONE"
    assert result.response_sequence == ("ACK_RECV", "RUN_START", "HEARTBEAT", "RES_SUCC")
    assert result.replay_class == "exact_replay"
    assert result.artifact_state == "verified"
    assert result.reloaded_manifest_id == "manifest-smoke"
    assert result.reloaded_pack_id == "pack-smoke"
    assert result.reloaded_input_manifest_hash
    assert result.canonical_task_spec_path
    assert result.output_artifact_hash
    assert result.telemetry_event_count == 6
    assert Path(result.canonical_task_spec_path).exists()
    assert Path(result.input_manifest_path).exists()
    assert Path(result.artifact_manifest_path).exists()
    assert Path(result.evidence_pack_path).exists()
    assert Path(result.hydrate_manifest_path).exists()
    assert Path(result.output_artifact_path).exists()
    assert Path(result.telemetry_path).exists()
    assert result.session_state == "GC_DONE"
    assert result.task_metrics["heartbeat_count"] == 1.0

    output_payload = json.loads(Path(result.output_artifact_path).read_text(encoding="utf-8"))
    assert output_payload["task_id"] == "smoke-task"
    assert output_payload["summary_text"].endswith("summary ready")
