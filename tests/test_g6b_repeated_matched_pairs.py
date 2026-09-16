from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from statebus.benchmark.continuous_runner import (
    _c2c_pair_key,
    _g6b_campaign_manifest,
    _g6b_pair_slot_manifest,
    _g6b_repeated_pair_projection,
    _g6b_write_artifacts,
    run_g6b_repeated_matched_pair_validation,
)
from statebus.benchmark.metric_aggregation import _g6b_metric_availability
from statebus.benchmark.scoring import (
    _g6b_validate_campaign_claim,
    _g6b_validate_pair_equivalence,
)
from statebus.utils import sha256_digest


def _pair_rows(*, suffix: str = "one") -> tuple[dict[str, object], dict[str, object]]:
    grant = {"grant_id": f"grant:{suffix}", "attempt_id": f"c1-attempt:{suffix}"}
    binding = {"binding_id": f"binding:{suffix}", "attempt_id": f"c1-attempt:{suffix}"}
    eligibility = {"receipt_id": f"eligibility:{suffix}", "decision": "ELIGIBLE"}
    grant_hash = sha256_digest(grant)
    binding_hash = sha256_digest(binding)
    eligibility_hash = sha256_digest(eligibility)
    baseline = {
        "row_id": f"baseline:{suffix}",
        "lane": "memory-off",
        "provenance_scope": "baseline_runtime",
        "family_id": "cross_period_financial",
        "round_number": 1,
        "repeat_id": 1,
        "cache_epoch": f"baseline-epoch:{suffix}",
        "task_contract_hash": "task-contract",
        "input_lineage_hashes": ["input-lineage"],
        "quality_contract_hash": "quality-contract",
        "deterministic_seed": 610111,
        "runtime_root": f"/runtime/baseline/{suffix}",
        "workspace_root": f"/workspace/baseline/{suffix}",
        "memory_root": f"/memory/baseline/{suffix}",
        "session_id": f"baseline-session:{suffix}",
        "attempt_id": f"baseline-attempt:{suffix}",
        "memory_policy": "off",
        "runtime_memory_policy": "none",
        "terminal_status": "success",
        "failure_stage": "",
        "reason": "",
        "provider_invocation_evidence": {
            "status": "observed",
            "invocation_status": "completed",
            "provider_id": "provider-execute-memory-recipe",
            "invocation_id": f"provider-invocation:{suffix}",
            "evidence_hash": f"provider-evidence:{suffix}",
            "request_hash": f"provider-request:{suffix}",
            "candidate_hash": f"provider-candidate:{suffix}",
            "source": "Runtime provider call boundary",
        },
        "quality_evidence": {
            "status": "observed",
            "passed": True,
            "report_hash": f"quality:{suffix}",
        },
        "result_admission": {
            "status": "observed",
            "receipt_hash": f"baseline-admission:{suffix}",
        },
    }
    c1 = {
        **baseline,
        "row_id": f"c1:{suffix}",
        "lane": "validated-replay",
        "provenance_scope": "c1_runtime",
        "cache_epoch": f"c1-epoch:{suffix}",
        "runtime_root": f"/runtime/c1/{suffix}",
        "workspace_root": f"/workspace/c1/{suffix}",
        "memory_root": f"/memory/c1/{suffix}",
        "session_id": f"c1-session:{suffix}",
        "attempt_id": f"c1-attempt:{suffix}",
        "memory_policy": "validated_replay",
        "runtime_memory_policy": "validated_replay",
        "runtime_authority": "AdaptiveRuntimeEngine",
        "provider_not_started_observation": {
            "status": "observed",
            "provider_invocation_status": "not_started",
            "observation_id": f"provider-not-started:{suffix}",
            "created_at_ns": 1,
            "execution_binding_hash": binding_hash,
            "capability_grant_hash": grant_hash,
            "memory_admission_receipt_hash": f"memory-admission:{suffix}",
            "replay_eligibility_receipt_hash": eligibility_hash,
            "quality_report_hash": f"quality:{suffix}",
            "attempt_result_admission_receipt_hash": f"c1-admission:{suffix}",
            "recipe_step_status": "unknown",
            "artifact_restore_status": "not_applicable",
        },
        "result_admission": {
            "status": "observed",
            "receipt_hash": f"c1-admission:{suffix}",
        },
        "recipe_recomputed": True,
        "capability_grant": grant,
        "execution_binding": binding,
        "replay_eligibility_receipt": eligibility,
        "memory_consumption_receipt": {
            "memory_admission_receipt_hash": f"memory-admission:{suffix}",
            "replay_eligibility_receipt_hash": eligibility_hash,
            "attempt_result_admission_receipt_hash": f"c1-admission:{suffix}",
        },
    }
    c1.pop("provider_invocation_evidence")
    return baseline, c1


def _b0_acceptance_projection() -> dict[str, object]:
    projection = _g6b_repeated_pair_projection([], [], stage="G6-B0")
    manifest = projection["campaign_manifest"]
    projection["pair_equivalence_rules"] = {
        "status": "frozen",
        "pair_key_fields": manifest["pair_key_fields"],
        "pair_key_excluded_fields": manifest["pair_key_excluded_fields"],
        "required_fields": manifest["pair_equivalence_required_fields"],
        "rejection_conditions": manifest["pair_rejection_conditions"],
    }
    projection["protected_diff_status"] = {
        area: "UNCHANGED_BY_G6B0"
        for area in (
            "runtime",
            "memory",
            "control",
            "state",
            "refs",
            "contracts",
            "protocol",
            "authority",
            "terminal_semantics",
        )
    }
    projection["focused_test_status"] = {"status": "passed"}
    projection["artifact_references"] = {
        "pair_identity": "manifest.json",
        "pair_equivalence": "pair_equivalence_rules.json",
        "denominator": "failure_denominator.json",
        "metrics": "metric_availability.json",
        "protected_sources": "runtime_memory_contract_protocol_diff_status.json",
        "focused_tests": "focused_test_status.json",
    }
    return projection


def test_g6b0_campaign_identity_and_pair_key_are_frozen() -> None:
    slot_manifest = _g6b_pair_slot_manifest()
    manifest = _g6b_campaign_manifest()

    assert slot_manifest["slot_count"] == 12
    assert len({slot["pair_slot_id"] for slot in slot_manifest["slots"]}) == 12
    assert len({slot["deterministic_seed"] for slot in slot_manifest["slots"]}) == 12
    assert all(slot["execution_status"] == "NOT_RUN" for slot in slot_manifest["slots"])
    assert manifest["pair_key_fields"] == [
        "task_contract_hash",
        "input_lineage_hashes",
        "quality_contract_hash",
        "deterministic_seed",
    ]
    assert manifest["pair_key_excluded_fields"] == [
        "lane",
        "family_id",
        "round_number",
        "repeat_id",
        "cache_epoch",
    ]

    baseline, c1 = _pair_rows()
    assert _c2c_pair_key(baseline) == _c2c_pair_key(c1)
    for field, value in (
        ("lane", "negative"),
        ("family_id", "another-family"),
        ("round_number", 99),
        ("repeat_id", 99),
        ("cache_epoch", "another-epoch"),
    ):
        changed = dict(baseline)
        changed[field] = value
        assert _c2c_pair_key(changed) == _c2c_pair_key(baseline)


def test_g6b_pair_equivalence_requires_lane_separation_and_runtime_evidence() -> None:
    baseline, c1 = _pair_rows()
    validation = _g6b_validate_pair_equivalence(baseline=baseline, c1=c1)
    assert validation["status"] == "eligible"
    assert all(validation["equivalence_checks"].values())

    same_session = dict(c1)
    same_session["session_id"] = baseline["session_id"]
    rejected = _g6b_validate_pair_equivalence(baseline=baseline, c1=same_session)
    assert rejected["status"] == "rejected"
    assert "pair_equivalence_failed:root_session_attempt_cache_separation" in rejected["failures"]


@pytest.mark.parametrize(
    "side,terminal_status",
    [
        ("baseline", "unsupported"),
        ("c1", "runtime_fail"),
        ("baseline", "quality_fail"),
        ("c1", "policy_reject"),
        ("baseline", "timeout"),
        ("c1", "environment_fail"),
    ],
)
def test_g6b_pair_equivalence_rejects_non_success_terminal_status(
    side: str,
    terminal_status: str,
) -> None:
    baseline, c1 = _pair_rows()
    row = baseline if side == "baseline" else c1
    row["terminal_status"] = terminal_status

    validation = _g6b_validate_pair_equivalence(baseline=baseline, c1=c1)

    assert validation["status"] == "rejected"
    assert "pair_equivalence_failed:terminal_status_gate" in validation["failures"]
    assert validation[f"{side if side == 'baseline' else 'replay'}_terminal_status"] == terminal_status


@pytest.mark.parametrize("missing_value", [None, ""])
def test_g6b_pair_equivalence_rejects_missing_null_or_empty_identity(missing_value: object) -> None:
    baseline, c1 = _pair_rows()
    baseline["family_id"] = missing_value
    c1["family_id"] = missing_value

    validation = _g6b_validate_pair_equivalence(baseline=baseline, c1=c1)

    assert validation["status"] == "rejected"
    assert "pair_equivalence_failed:baseline_required_family_id" in validation["failures"]
    assert "None" not in validation["source_receipt_hashes"]

    baseline, c1 = _pair_rows()
    baseline.pop("family_id")
    validation = _g6b_validate_pair_equivalence(baseline=baseline, c1=c1)
    assert validation["status"] == "rejected"
    assert "pair_equivalence_failed:baseline_required_family_id" in validation["failures"]


def test_g6b_pair_equivalence_rejects_missing_provider_and_c1_receipts() -> None:
    baseline, c1 = _pair_rows()
    baseline["provider_invocation_evidence"] = None
    observation = dict(c1["provider_not_started_observation"])
    observation["replay_eligibility_receipt_hash"] = None
    observation["attempt_result_admission_receipt_hash"] = ""
    c1["provider_not_started_observation"] = observation
    c1["result_admission"] = None

    validation = _g6b_validate_pair_equivalence(baseline=baseline, c1=c1)

    assert validation["status"] == "rejected"
    assert "pair_equivalence_failed:baseline_provider_invocation" in validation["failures"]
    assert "pair_equivalence_failed:c1_provider_not_started" in validation["failures"]
    assert "pair_equivalence_failed:result_admission" in validation["failures"]
    assert "None" not in validation["source_receipt_hashes"]


def test_g6b_projection_retains_duplicate_unmatched_and_quality_failure_rows() -> None:
    baseline, c1 = _pair_rows()
    duplicate = {**baseline, "row_id": "baseline:duplicate", "cache_epoch": "duplicate-epoch"}
    projection = _g6b_repeated_pair_projection([baseline, duplicate], [c1], stage="G6-B1")

    assert projection["pairings"] == []
    assert {row["row_id"] for row in projection["failure_rows"]} == {
        "baseline:one",
        "baseline:duplicate",
        "c1:one",
    }
    assert all(row["status"] == "unmatched" for row in projection["failure_rows"])
    assert projection["denominator"]["attempted"] == 3
    assert projection["denominator"]["unmatched_row_count"] == 3
    assert projection["denominator"]["matched_pair_count"] == 0
    assert projection["denominator"]["arithmetic_closed"] is True

    baseline, c1 = _pair_rows(suffix="quality-fail")
    c1["quality_evidence"] = {
        "status": "observed",
        "passed": False,
        "report_hash": "quality:quality-fail",
    }
    projection = _g6b_repeated_pair_projection([baseline], [c1], stage="G6-B1")
    assert projection["pairings"][0]["status"] == "rejected"
    assert projection["denominator"]["eligible_matched_pair_count"] == 0
    assert projection["metrics"]["provider_work_avoided"]["value"] is None


def test_g6b_denominator_and_metric_boundaries_do_not_fill_unsupported_with_zero() -> None:
    baseline, c1 = _pair_rows()
    projection = _g6b_repeated_pair_projection([baseline], [c1], stage="G6-B1")
    denominator = projection["denominator"]
    assert denominator["baseline_row_count"] == 1
    assert denominator["c1_row_count"] == 1
    assert denominator["attempted"] == 2
    assert denominator["matched_pair_count"] == 1
    assert denominator["eligible_matched_pair_count"] == 1
    assert denominator["unmatched_row_count"] == 0
    assert denominator["success"] == 2
    assert denominator["unsupported"] == 0
    assert denominator["arithmetic_closed"] is True
    assert denominator["row_ids"] == ["baseline:one", "c1:one"]

    metrics = _g6b_metric_availability([], {
        "arithmetic_closed": True,
    }, stage="G6-B0")
    assert metrics["exact_replay"] == {
        "status": "unsupported",
        "value": None,
        "reason": "c2_exact_restore_not_implemented",
        "source_receipt_hashes": [],
    }
    assert metrics["recipe_step_skip"]["status"] == "deferred"
    assert metrics["verified_recipe_work_avoided"]["reason"] == "recipe_step_skip_deferred_to_c2"
    assert metrics["provider_work_avoided"] == {
        "status": "unsupported",
        "value": None,
        "reason": "no_matched_baseline_or_runtime_skip_receipt",
        "source_receipt_hashes": [],
    }


def test_g6b0_writer_freezes_contract_and_refuses_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "g6b-repeated-matched-pairs-20260915-v1"
    diff_status = {
        "runtime": "UNCHANGED_BY_G6B0",
        "memory": "UNCHANGED_BY_G6B0",
        "contracts": "UNCHANGED_BY_G6B0",
        "control": "UNCHANGED_BY_G6B0",
        "state": "UNCHANGED_BY_G6B0",
        "refs": "UNCHANGED_BY_G6B0",
        "protocol": "UNCHANGED_BY_G6B0",
        "authority": "UNCHANGED_BY_G6B0",
        "terminal_semantics": "UNCHANGED_BY_G6B0",
    }
    _g6b_write_artifacts(
        root,
        focused_test_status={"status": "passed", "command": "focused synthetic contract test"},
        diff_status=diff_status,
    )

    acceptance = json.loads((root / "g6b_acceptance.json").read_text(encoding="utf-8"))
    metrics = json.loads((root / "metric_availability.json").read_text(encoding="utf-8"))["metrics"]
    assert acceptance["stage_status"] == "B0_ACCEPTED"
    assert acceptance["campaign_execution_status"] == "NOT_RUN"
    assert acceptance["live_vllm_gpu_validation"] == "NOT_RUN"
    assert acceptance["benchmark_superiority"] == "NOT_ESTABLISHED"
    assert acceptance["memfd_limitation"] == "skipped: memfd unavailable; SHM actual-read retained"
    assert metrics["provider_work_avoided"]["value"] is None
    contract = json.loads((root / "measurement_contract.json").read_text(encoding="utf-8"))
    assert contract["denominator_dimensions"] == [
        "lane",
        "family_id",
        "round_number",
        "repeat_id",
        "cache_epoch",
    ]
    assert contract["denominator_count_fields"] == [
        "baseline_row_count",
        "c1_row_count",
        "matched_pair_count",
        "eligible_matched_pair_count",
        "unmatched_row_count",
        "attempted",
        "success",
        "unsupported",
        "policy_reject",
        "runtime_fail",
        "timeout",
        "quality_fail",
        "environment_fail",
    ]
    assert all(check["passed"] for check in acceptance["acceptance_checks"].values())
    assert (root / "final_gate_status.json").is_file()
    assert not (root / "final_verification.json").exists()
    assert json.loads((root / "b1_readiness.json").read_text(encoding="utf-8"))["status"] == "PENDING_ASTRA_REAUDIT"
    assert json.loads((root / "b2_live_validation_status.json").read_text(encoding="utf-8"))["status"] == "DEFERRED"

    with pytest.raises(FileExistsError):
        _g6b_write_artifacts(
            root,
            focused_test_status={"status": "passed"},
            diff_status=diff_status,
        )


def test_g6b_acceptance_rejects_missing_contract_and_unbacked_observed_metric() -> None:
    projection = _b0_acceptance_projection()
    del projection["campaign_manifest"]["denominator_dimensions"]
    validation = _g6b_validate_campaign_claim(projection, stage="G6-B0")
    assert validation["status"] == "rejected"
    assert "denominator_dimensions_or_counts_incomplete" in validation["failures"]

    projection = _b0_acceptance_projection()
    del projection["pair_equivalence_rules"]["required_fields"]
    validation = _g6b_validate_campaign_claim(projection, stage="G6-B0")
    assert validation["status"] == "rejected"
    assert "pair_equivalence_rules_incomplete" in validation["failures"]

    projection = _b0_acceptance_projection()
    projection["metrics"]["provider_latency"] = {
        "status": "observed",
        "value": 1.0,
        "reason": "",
        "source_receipt_hashes": ["invented-source"],
    }
    validation = _g6b_validate_campaign_claim(projection, stage="G6-B0")
    assert validation["status"] == "rejected"
    assert "metric_status_not_supported_by_raw_evidence" in validation["failures"]


def test_g6b_projection_reuses_c2c_pairing_helper() -> None:
    baseline, c1 = _pair_rows()
    with patch(
        "statebus.benchmark.continuous_runner._c2c_baseline_pairing",
        wraps=__import__(
            "statebus.benchmark.continuous_runner",
            fromlist=["_c2c_baseline_pairing"],
        )._c2c_baseline_pairing,
    ) as pairing:
        projection = _g6b_repeated_pair_projection([baseline], [c1], stage="G6-B1")

    pairing.assert_called_once()
    assert projection["c2c_pairing_helper_reused"] is True
    assert projection["pairings"][0]["status"] == "eligible"


def test_g6b1_runner_executes_twelve_pairs_and_retains_negative_denominator(
    tmp_path: Path,
) -> None:
    root = tmp_path / "g6b-repeated-matched-pairs-20260915-b1-v1"
    run_g6b_repeated_matched_pair_validation(root=root)

    baseline = json.loads((root / "baseline_rows.json").read_text(encoding="utf-8"))["rows"]
    c1 = json.loads((root / "c1_rows.json").read_text(encoding="utf-8"))["rows"]
    pairs = json.loads((root / "pair_projection.json").read_text(encoding="utf-8"))["rows"]
    negative = json.loads((root / "negative_row_index.json").read_text(encoding="utf-8"))["rows"]
    denominator = json.loads((root / "failure_denominator.json").read_text(encoding="utf-8"))
    acceptance = json.loads((root / "g6b_acceptance.json").read_text(encoding="utf-8"))

    eligible = [row for row in pairs if row["status"] == "eligible"]
    assert len(eligible) == 12
    assert denominator["eligible_matched_pair_count"] == 12
    assert denominator["arithmetic_closed"] is True
    assert acceptance["stage_status"] == "B1_ACCEPTED"
    assert acceptance["campaign_execution_status"] == "COMPLETED_FROM_RAW_ROWS"
    assert acceptance["benchmark_superiority"] == "NOT_ESTABLISHED"
    assert acceptance["live_vllm_gpu_validation"] == "NOT_RUN"
    assert len({row["row_id"] for row in [*baseline, *c1]}) == len([*baseline, *c1])
    assert len({row["cache_epoch"] for row in [*baseline, *c1]}) == len([*baseline, *c1])
    assert all(row["baseline_provider_invocation_status"] == "completed" for row in eligible)
    assert all(row["replay_provider_invocation_status"] == "not_started" for row in eligible)
    reasons = {row["reason"] for row in negative}
    assert {
        "required_unmatched_baseline",
        "missing_pair_identity",
        "duplicate_pair_key",
        "quality_failure",
        "result_admission_failure",
        "runtime_failure",
        "runtime_policy_failure",
        "rejected_pair",
    } <= reasons
    assert all(row.get("denominator_linkage") for row in negative)
    for name in (
        "manifest.json",
        "measurement_contract.json",
        "pair_slots.json",
        "baseline_rows.json",
        "c1_rows.json",
        "pair_projection.json",
        "negative_row_index.json",
        "failure_denominator.json",
        "metric_availability.json",
        "quality_evidence.json",
        "result_admission_projection.json",
        "g6b_acceptance.json",
        "final_gate_status.json",
    ):
        assert (root / name).is_file()

    with pytest.raises(FileExistsError):
        run_g6b_repeated_matched_pair_validation(root=root)
