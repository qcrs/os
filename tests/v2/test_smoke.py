from __future__ import annotations

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
    assert result.response_sequence == ("ACK_RECV", "RUN_START", "RES_SUCC")
    assert result.replay_class == "exact_replay"
    assert result.artifact_state == "verified"
    assert result.reloaded_manifest_id == "manifest-smoke"
    assert result.reloaded_pack_id == "pack-smoke"
    assert result.telemetry_event_count == 4
