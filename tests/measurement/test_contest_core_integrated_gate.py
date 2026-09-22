import json
from pathlib import Path

from statebus.benchmark.contest_core_integrated_gate import evaluate_integrated_gate


def _write(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_integrated_gate_requires_live_stage_artifact_closure(tmp_path: Path) -> None:
    _write(
        tmp_path / "campaign_manifest.json",
        {
            "p1_selection": {
                "scope": "full_registry",
                "max_cases_per_family": 0,
                "family_ids": [
                    "financial_report_analysis_v1",
                    "multi_period_trend_analysis_v1",
                    "cross_table_join_analysis_v1",
                    "conditional_aggregation_v1",
                    "anomaly_detection_v1",
                ],
                "independent_case_count": 48,
                "lane_count": 4,
                "planned_rows": 192,
            }
        },
    )
    _write(
        tmp_path / "p1" / "acceptance.json",
        {
            "status": "pilot_ready",
            "run_mode": "live_measurement",
            "planned_slots": 192,
            "observed_rows": 192,
            "denominator": {
                "planned_count": 192,
                "started_count": 192,
                "provider_started_count": 192,
                "settled_count": 192,
                "observed_row_count": 192,
                "observed_slot_id_count": 192,
                "arithmetic_closed": True,
                "not_started_count": 0,
                "unknown_count": 0,
                "unsupported_count": 0,
                "missing": [],
                "extra": [],
                "duplicate": [],
            },
        },
    )
    _write(tmp_path / "p2" / "acceptance.json", {"status": "passed"})
    _write(
        tmp_path / "p3" / "run" / "summary.json",
        {
            "schema_version": "statebus.semantic_state_ablation_summary.v1",
            "ok": True,
            "denominator": {"closed_pairs": 1, "inactive_negative_control_pairs": 1},
        },
    )
    _write(
        tmp_path / "p4" / "acceptance.json",
        {
            "status": "passed",
            "metrics": {"verified_recipe_work_avoided": {"status": "observed"}},
        },
    )
    _write(
        tmp_path / "p4-live" / "run" / "final_gate_status.json",
        {
            "schema_version": "statebus.g6b2.final_gate_status.v1",
            "status": "MINIMAL_PAIR_VERIFIED_FOR_USER_CAMPAIGN",
            "service_stop_called": False,
        },
    )
    _write(
        tmp_path / "p5-live" / "run" / "summary.json",
        {
            "schema_version": "statebus.adaptive_live_task.v1",
            "ok": True,
            "telemetry": {
                "llm_codeact_verified_count": 1.0,
                "llm_codeact_sandbox_fallback_count": 0.0,
            },
            "execution_identity": {
                "container": {"uid": 0, "gid": 0, "is_root": True},
                "sandbox_children": [
                    {
                        "backend": "bwrap",
                        "uid": 65534,
                        "gid": 65534,
                        "fallback_reason": "",
                    }
                ],
            },
        },
    )

    result = evaluate_integrated_gate(campaign_root=tmp_path)

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert all(result["checks"].values())


def test_integrated_gate_rejects_bounded_p1_as_full_campaign(tmp_path: Path) -> None:
    _write(
        tmp_path / "campaign_manifest.json",
        {
            "p1_selection": {
                "scope": "bounded_pilot",
                "max_cases_per_family": 1,
                "family_ids": ["financial_report_analysis_v1"],
                "independent_case_count": 1,
                "lane_count": 4,
                "planned_rows": 4,
            }
        },
    )
    _write(
        tmp_path / "p1" / "acceptance.json",
        {
            "status": "pilot_ready",
            "run_mode": "live_measurement",
            "planned_slots": 4,
            "observed_rows": 4,
            "denominator": {
                "planned_count": 4,
                "started_count": 4,
                "provider_started_count": 4,
                "settled_count": 4,
                "observed_row_count": 4,
                "observed_slot_id_count": 4,
                "arithmetic_closed": True,
                "not_started_count": 0,
                "unknown_count": 0,
                "unsupported_count": 0,
                "missing": [],
                "extra": [],
                "duplicate": [],
            },
        },
    )

    result = evaluate_integrated_gate(campaign_root=tmp_path)

    assert result["status"] == "failed"
    assert result["checks"]["p1_full_registry_manifest"] is False
    assert result["checks"]["p1_full_denominator_closed"] is False


def test_integrated_gate_does_not_claim_unimplemented_p11_variants(tmp_path: Path) -> None:
    result = evaluate_integrated_gate(
        campaign_root=tmp_path,
        feature_variant="without_memory",
    )

    assert result["status"] == "unsupported"
    assert result["exit_code"] == 3
    assert result["reason"] == "p11_variant_execution_runner_not_implemented"
