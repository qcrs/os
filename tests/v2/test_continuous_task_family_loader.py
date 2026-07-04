from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.benchmark import load_continuous_task_family
from v2.benchmark.continuous_task_family import ContinuousTaskFamilyValidationError


def test_load_continuous_task_family_csv_profile_manifest() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_table_profile")
    )
    assert family.family_id == "csv_table_profile_v1"
    assert family.claim_tier == "formal_primary"
    assert family.round_count == 10
    assert family.datasets[0].dataset_id == "disease_estimates"
    assert family.rounds[0].canonical_task_spec.intent_op == "profile_table"
    assert family.rounds[-1].reuse_contract.minimum_reuse_class == "assist"
    assert family.design_audit_payload()["reuse_edge_count"] > 0


def test_load_continuous_task_family_long_doc_manifest() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_table")
    )
    assert family.family_id == "long_doc_table_v1"
    assert family.claim_tier == "formal_secondary"
    assert family.round_count == 10
    assert family.datasets[0].dataset_id == "acme_ops_2026"
    assert family.rounds[0].canonical_task_spec.intent_op == "build_semantic_index"
    assert family.rounds[-1].reuse_contract.minimum_reuse_class == "assist"


def test_load_continuous_task_family_long_doc_replay_manifest() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_metric_replay")
    )
    assert family.family_id == "long_doc_metric_replay_v1"
    assert family.claim_tier == "formal_secondary"
    assert family.round_count == 10
    assert family.datasets[0].dataset_id == "acme_ops_2026"
    assert family.rounds[1].canonical_task_spec.intent_op == "extract_metric_series_generic"
    assert family.rounds[2].reuse_contract.minimum_reuse_class == "validated_replay"
    assert family.rounds[-1].reuse_contract.minimum_reuse_class == "exact_replay"
    assert family.design_audit_payload()["exact_replay_target_rounds"] == [5, 7, 10]
    assert family.design_audit_payload()["validated_replay_target_rounds"] == [3, 4, 6, 8, 9]


def test_load_continuous_task_family_incident_manifest() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/incident_diagnosis")
    )
    assert family.family_id == "incident_diagnosis_v2"
    assert family.claim_tier == "formal_secondary"
    assert family.round_count == 10
    assert family.datasets[0].dataset_id == "inference_gateway_boot"
    assert family.rounds[0].canonical_task_spec.intent_op == "diagnose_startup_latency"
    assert family.rounds[1].reuse_contract.minimum_reuse_class == "validated_replay"
    assert family.rounds[2].reuse_contract.minimum_reuse_class == "exact_replay"
    assert family.design_audit_payload()["exact_replay_target_rounds"] == [3, 4, 6, 7, 8, 9, 10]
    assert family.design_audit_payload()["validated_replay_target_rounds"] == [2, 5]


def test_load_continuous_task_family_csv_replay_manifest() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_correlation_replay")
    )
    assert family.family_id == "csv_correlation_replay_v1"
    assert family.claim_tier == "formal_primary"
    assert family.round_count == 10
    assert family.datasets[0].dataset_id == "disease_estimates"
    assert family.rounds[1].canonical_task_spec.intent_op == "correlate_columns"
    assert family.rounds[2].reuse_contract.minimum_reuse_class == "validated_replay"
    assert family.rounds[-1].reuse_contract.minimum_reuse_class == "validated_replay"
    assert family.design_audit_payload()["exact_replay_target_rounds"] == []
    assert family.design_audit_payload()["validated_replay_target_rounds"] == [3, 4, 5, 6, 7, 8, 9, 10]
    assert family.l3_target_nonzero_rounds() == (3, 4, 5, 6, 7, 8, 9, 10)
    assert family.replay_target_rounds_by_class() == {
        "validated_replay": (3, 4, 5, 6, 7, 8, 9, 10),
        "exact_replay": (),
    }


def test_load_continuous_task_family_grid_world_fixture_is_verified() -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/gridops_world")
    )
    assert family.family_id == "gridops_world_v1"
    assert family.claim_tier == "demo_secondary"
    assert family.datasets[0].kind == "grid_world"
    assert family.rounds[2].canonical_task_spec.intent_op == "deliver_crate"


def test_load_continuous_task_family_fails_closed_for_forward_dependency(tmp_path: Path) -> None:
    source_dir = Path("v2/benchmark/samples/continuous_task_families/csv_table_profile")
    family_dir = tmp_path / "family"
    family_dir.mkdir()
    payload = json.loads((source_dir / "manifest.json").read_text(encoding="utf-8"))
    payload["rounds"][0]["depends_on_rounds"] = [2]
    (family_dir / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ContinuousTaskFamilyValidationError):
        load_continuous_task_family(family_dir)
