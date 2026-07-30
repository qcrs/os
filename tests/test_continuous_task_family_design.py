from __future__ import annotations

import json
from pathlib import Path


MANIFEST_ROOT = Path("statebus/benchmark/samples/continuous_task_families")
FAMILIES = (
    "cross_period_financial",
    "csv_table_profile",
    "csv_correlation_replay",
    "incident_diagnosis",
    "long_doc_table",
    "long_doc_metric_replay",
    "gridops_world",
    "formal_operating_metrics",
    "formal_financial_reports",
)


def _load_manifest(family: str) -> dict[str, object]:
    return json.loads((MANIFEST_ROOT / family / "manifest.json").read_text(encoding="utf-8"))


def test_continuous_task_family_manifests_have_ordered_related_rounds() -> None:
    for family in FAMILIES:
        manifest = _load_manifest(family)
        rounds = manifest["rounds"]
        assert manifest["schema_version"] == "statebus.continuous_task_family.v1"
        assert manifest["round_count"] >= 2
        assert len(rounds) == manifest["round_count"]
        assert [round_payload["round"] for round_payload in rounds] == list(range(1, len(rounds) + 1))


def test_continuous_task_family_dependencies_only_point_backward() -> None:
    for family in FAMILIES:
        manifest = _load_manifest(family)
        for round_payload in manifest["rounds"]:
            round_number = int(round_payload["round"])
            assert all(int(dep) < round_number for dep in round_payload["depends_on_rounds"])


def test_continuous_task_family_rounds_declare_reuse_and_quality_contracts() -> None:
    for family in FAMILIES:
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
    tiers = {_load_manifest(family)["claim_tier"] for family in FAMILIES}
    assert "formal_primary" in tiers
    assert "formal_secondary" in tiers
    assert "demo_secondary" in tiers


def test_cross_period_financial_manifest_targets_strategy_reuse_not_answer_restore() -> None:
    manifest = _load_manifest("cross_period_financial")
    rounds_by_number = {round_payload["round"]: round_payload for round_payload in manifest["rounds"]}

    assert rounds_by_number[2]["reuse_contract"]["minimum_reuse_class"] == "validated_replay"
    assert rounds_by_number[4]["reuse_contract"]["minimum_reuse_class"] == "validated_replay"
    assert rounds_by_number[6]["canonical_task_spec"]["arguments"]["ticker"] == "BETA"
    assert rounds_by_number[6]["reuse_contract"]["minimum_reuse_class"] == "validated_replay"
    assert rounds_by_number[8]["canonical_task_spec"]["arguments"]["ticker"] == "BETA"
    assert rounds_by_number[8]["reuse_contract"]["minimum_reuse_class"] == "validated_replay"
    assert rounds_by_number[7]["reuse_contract"]["minimum_reuse_class"] == "assist"
    assert rounds_by_number[10]["reuse_contract"]["minimum_reuse_class"] == "assist"


def test_formal_views_are_dependency_closed_and_r9_fixture_is_not_prompted() -> None:
    for family_name in ("formal_financial_reports", "formal_operating_metrics"):
        manifest = _load_manifest(family_name)
        rounds_by_number = {
            int(round_payload["round"]): round_payload
            for round_payload in manifest["rounds"]
        }
        for view_name, selected_rounds in manifest["experiment_views"].items():
            selected_prefix: set[int] = set()
            for round_number in selected_rounds:
                assert set(rounds_by_number[round_number]["depends_on_rounds"]).issubset(
                    selected_prefix
                ), view_name
                selected_prefix.add(round_number)
        fixture = rounds_by_number[9]["pre_run_fixtures"][0]
        assert fixture["kind"] == "incompatible_history_candidate"
        request_text = rounds_by_number[9]["request_text"].lower()
        assert "legacy" not in request_text
        assert "candidate" not in request_text
