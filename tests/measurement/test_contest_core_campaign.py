from pathlib import Path

from statebus.benchmark.contest_core_campaign import (
    DEFAULT_STAGE2_FAMILIES,
    P11_FEATURE_VARIANTS,
    STAGE2_FAMILY_CASE_COUNTS,
    STAGE2_FAMILY_IDS,
    _feature_flags,
    build_campaign_manifest,
)


def test_campaign_planner_writes_reproducible_manifest_and_commands(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    manifest = build_campaign_manifest(
        output_root=root,
        seed=17,
        profile="test-profile",
        case_ids=("case-a",),
        families=("family-a",),
        dry_run=True,
        skip_live=True,
    )

    assert manifest["schema_version"] == "statebus.contest_core_campaign_manifest.v1"
    assert manifest["formal_campaign_executed"] is False
    assert manifest["lane_order"] == build_campaign_manifest(
        output_root=tmp_path / "campaign-2",
        seed=17,
        profile="test-profile",
        case_ids=("case-a",),
        families=("family-a",),
        dry_run=True,
        skip_live=True,
    )["lane_order"]
    assert set(manifest["stages"]) == {
        "P0", "P1", "P2", "P3", "P4", "P4_live", "P5", "P5_live", "P11"
    }
    assert manifest["stages"]["P3"]["enabled"] is False
    assert manifest["stages"]["P4_live"]["enabled"] is False
    assert manifest["stages"]["P5_live"]["enabled"] is False
    assert manifest["stages"]["P11"]["enabled"] is False
    assert len(manifest["p11_feature_matrix"]) == len(P11_FEATURE_VARIANTS)
    assert (root / "campaign_manifest.json").is_file()
    assert (root / "commands.sh").is_file()
    commands = (root / "commands.sh").read_text(encoding="utf-8")
    assert "enabled=False" in commands
    assert "# scripts/run_g6b2_os_container.sh" in commands
    assert commands.startswith("#!/usr/bin/env bash\nset -euo pipefail")
    assert "cd /home/qcrs/statebus/os" in commands
    assert "source ./deploy/activate_statebus_host.sh" in commands


def test_p11_feature_variants_only_disable_the_named_mechanism() -> None:
    assert _feature_flags("without_semantic_state") == {
        "semantic_state": False,
        "memory": True,
        "adaptive_routing": True,
        "codeact": True,
        "cross_text_semantic_state": False,
        "engine_local_kv": False,
        "hidden_latent": False,
        "apc_prefix": False,
    }
    assert _feature_flags("without_memory")["semantic_state"] is True
    assert _feature_flags("without_memory")["memory"] is False
    assert _feature_flags("without_adaptive_routing")["codeact"] is True


def test_live_campaign_bootstraps_profile_and_passes_stage2_families(tmp_path: Path) -> None:
    root = tmp_path / "live-campaign"
    manifest = build_campaign_manifest(
        output_root=root,
        seed=20260921,
        profile="qwen3-32b-gpu2-u050",
        case_ids=(),
        families=("cross_period_financial", "incident_diagnosis"),
        stage2_family_ids=STAGE2_FAMILY_IDS,
        dry_run=False,
        skip_live=False,
    )

    command_text = (root / "commands.sh").read_text(encoding="utf-8")
    assert manifest["p1_selection"]["mode"] == "family"
    assert manifest["stage2_families"] == list(STAGE2_FAMILY_IDS)
    assert "--print-env" in command_text
    assert "scripts/start_statebus.sh qwen3-32b-gpu2-u050" in command_text
    assert "CONTAINER_P1_ROOT=\"$(scripts/run_g6b2_os_container.sh map-path \"$HOST_P1_ROOT\")\"" in command_text
    assert "scripts/run_g6b2_os_container.sh exec python3 -m statebus.benchmark.stage2_pilot" in command_text
    assert "--embedding-device cuda:0" in command_text
    assert "--max-cases-per-family 1" in command_text
    assert all(
        f"--family-id {family_id}" in str(manifest["stages"]["P1"]["command"])
        for family_id in STAGE2_FAMILY_IDS
    )


def test_stage2_family_selection_is_the_cli_default(tmp_path: Path) -> None:
    root = tmp_path / "default-live-campaign"
    manifest = build_campaign_manifest(
        output_root=root,
        seed=20260921,
        profile="qwen3-32b-gpu2-u050",
        families=("cross_period_financial", "incident_diagnosis"),
        dry_run=False,
        skip_live=False,
    )

    assert manifest["stage2_families"] == list(DEFAULT_STAGE2_FAMILIES)
    assert manifest["p1_selection"]["mode"] == "family"


def test_full_registry_expands_to_48_cases_and_192_rows(tmp_path: Path) -> None:
    root = tmp_path / "full-campaign"
    manifest = build_campaign_manifest(
        output_root=root,
        seed=20260922,
        profile="qwen3-32b-gpu2-u050",
        families=("cross_period_financial", "incident_diagnosis"),
        stage2_family_ids=STAGE2_FAMILY_IDS,
        dry_run=False,
        skip_live=False,
        full_registry=True,
    )

    command_text = (root / "commands.sh").read_text(encoding="utf-8")
    assert manifest["p1_selection"] == {
        "mode": "family",
        "scope": "full_registry",
        "case_ids": [],
        "family_ids": list(STAGE2_FAMILY_IDS),
        "family_case_counts": STAGE2_FAMILY_CASE_COUNTS,
        "max_cases_per_family": 0,
        "independent_case_count": 48,
        "repeat_count": 1,
        "timeout_s": 900,
        "lane_count": 4,
        "planned_rows": 192,
        "denominator_fields": [
            "planned",
            "started",
            "settled",
            "observed",
            "success",
            "failed",
        ],
    }
    assert "--max-cases-per-family 0" in command_text
    assert "--embedding-gpu 1" in command_text
    assert "--container-name statebus-runtime" in command_text
    assert "scripts/run_g6b2_os_container.sh verify" in command_text
    assert "scripts/run_g6b2_os_container.sh smoke" in command_text
    assert "scripts/run_local_vllm_container_check.sh" in command_text
    p3_scope = manifest["stage_scopes"]["P3"]
    assert p3_scope["scope"] == "formal_full"
    assert p3_scope["available_case_count"] == 8
    assert len(p3_scope["case_ids"]) == 8
    assert all(f"--case-id semantic-holdout-s{i}" in command_text for i in range(1, 9))
