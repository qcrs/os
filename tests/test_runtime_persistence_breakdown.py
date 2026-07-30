from __future__ import annotations

import json
from pathlib import Path

from scripts.diagnostics.runtime_persistence_breakdown import (
    build_runtime_persistence_breakdown_bundle,
    main as runtime_persistence_breakdown_main,
)


def test_runtime_persistence_breakdown_bundle_writes_summary_and_csv(tmp_path: Path) -> None:
    bundle_dir = build_runtime_persistence_breakdown_bundle(
        output_root=tmp_path / "diagnostics",
        suite_id="statebus-runtime-persistence-breakdown",
        task_id="smoke-task",
        layer_name="L3-cold-start",
        handoff_mode="structured_collaboration",
        structured_control_enabled=True,
        semantic_pruning_enabled=True,
        replay_enabled=False,
        multi_attempt_enabled=False,
        force_first_attempt_trap=False,
        role_path_mode="deterministic",
        embedding_mode="deterministic",
        seed_replay_memory=False,
    )

    summary = json.loads((bundle_dir / "summary.json").read_text(encoding="utf-8"))
    assert Path(summary["runtime_root"]).exists()
    assert Path(summary["workspace_root"]).exists()
    assert summary["persist"]["persist_bundle_write_stage_ms"] >= 0.0
    assert summary["persist"]["persist_and_reload_stage_ms"] >= 0.0
    assert summary["sidecar_totals"]
    assert summary["top_sidecars"]
    assert [profile["profile"] for profile in summary["persistence_profiles"]] == [
        "audit_full",
        "benchmark_balanced",
        "fast_runtime",
    ]
    assert summary["persistence_profiles"][0]["included_size_ratio"] >= summary["persistence_profiles"][-1]["included_size_ratio"]
    assert (bundle_dir / "summary.md").exists()
    assert (bundle_dir / "file_sizes.csv").exists()
    assert (bundle_dir / "sidecar_sizes.csv").exists()
    assert (bundle_dir / "manifest_sizes.csv").exists()


def test_runtime_persistence_breakdown_cli_prints_bundle_paths(tmp_path: Path, capsys) -> None:
    bundle_dir = runtime_persistence_breakdown_main(
        [
            "--output-root",
            str(tmp_path / "diagnostics"),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert Path(payload["bundle_dir"]) == bundle_dir
    assert Path(payload["summary_json"]).exists()
    assert Path(payload["summary_markdown"]).exists()
    assert Path(payload["sidecar_sizes_csv"]).exists()
