from __future__ import annotations

import json
from pathlib import Path


MANIFEST_ROOT = Path("v2/benchmark/samples/continuous_task_families")


def _load_manifest(family: str) -> dict[str, object]:
    return json.loads((MANIFEST_ROOT / family / "manifest.json").read_text(encoding="utf-8"))


def test_continuous_task_family_manifests_have_ten_ordered_rounds() -> None:
    for family in (
        "csv_table_profile",
        "csv_correlation_replay",
        "long_doc_table",
        "long_doc_metric_replay",
        "gridops_world",
    ):
        manifest = _load_manifest(family)
        rounds = manifest["rounds"]
        assert manifest["schema_version"] == "statebus.continuous_task_family.v1"
        assert manifest["round_count"] >= 10
        assert len(rounds) >= 10
        assert [round_payload["round"] for round_payload in rounds] == list(range(1, len(rounds) + 1))


def test_continuous_task_family_dependencies_only_point_backward() -> None:
    for family in (
        "csv_table_profile",
        "csv_correlation_replay",
        "long_doc_table",
        "long_doc_metric_replay",
        "gridops_world",
    ):
        manifest = _load_manifest(family)
        for round_payload in manifest["rounds"]:
            round_number = int(round_payload["round"])
            assert all(int(dep) < round_number for dep in round_payload["depends_on_rounds"])


def test_continuous_task_family_rounds_declare_reuse_and_quality_contracts() -> None:
    for family in (
        "csv_table_profile",
        "csv_correlation_replay",
        "long_doc_table",
        "long_doc_metric_replay",
        "gridops_world",
    ):
        manifest = _load_manifest(family)
        for round_payload in manifest["rounds"]:
            spec = round_payload["canonical_task_spec"]
            reuse_contract = round_payload["reuse_contract"]
            assert spec["task_family"]
            assert spec["intent_op"]
            assert spec["required_outputs"]
            assert spec["required_tools"]
            assert reuse_contract["produces"]
            assert "minimum_reuse_class" in reuse_contract
            assert round_payload["quality_checks"]
            assert round_payload["expected_metric_effects"] is not None


def test_continuous_task_families_cover_formal_and_demo_tracks() -> None:
    tiers = {
        _load_manifest(family)["claim_tier"]
        for family in (
            "csv_table_profile",
            "csv_correlation_replay",
            "long_doc_table",
            "long_doc_metric_replay",
            "gridops_world",
        )
    }
    assert "formal_primary" in tiers
    assert "formal_secondary" in tiers
    assert "demo_secondary" in tiers
