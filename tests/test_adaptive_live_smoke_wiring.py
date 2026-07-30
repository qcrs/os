from __future__ import annotations

import inspect

from scripts.diagnostics import run_adaptive_agent_smoke, run_adaptive_mode_matrix, run_llm_codeact_smoke


def _model_attempt() -> dict[str, object]:
    return {"model": "qwen3-32b", "raw_response_hash": "model-output-hash"}


def _live_summary(
    task_name: str,
    *,
    plan_hash: str,
    capabilities: list[str],
    program_hash: str,
    codeact: bool,
) -> dict[str, object]:
    telemetry: dict[str, float] = {
        "fallback_used": 0.0,
        "model_fallback_count": 0.0,
        "llm_codeact_sandbox_fallback_count": 0.0,
        "llm_codeact_verified_count": 1.0 if codeact else 0.0,
        "llm_codeact_generation_count": 1.0 if codeact else 0.0,
    }
    return {
        "task_name": task_name,
        "ok": True,
        "runtime_completed": True,
        "approved_plan_hash": plan_hash,
        "approved_capability_ids": capabilities,
        "telemetry": telemetry,
        "role_invocations": [
            {"role": "planner", "attempts": [_model_attempt()]},
            {"role": "retriever", "attempts": [_model_attempt()]},
            {"role": "summarizer", "attempts": [_model_attempt()]},
        ],
        "generation_attempts": (
            [{"model_id": "qwen3-32b", "raw_response_hash": "code-output-hash"}]
            if codeact else []
        ),
        "execution_records": (
            [{
                "sandbox_actual_backend": "bwrap",
                "sandbox_uid": 65534,
                "sandbox_gid": 65534,
                "exit_code": 0,
                "output_schema_valid": True,
                "output_quality_valid": True,
                "verified_artifact_id": f"artifact-{task_name}",
            }]
            if codeact else []
        ),
        "quality_reports": [{"verified": True}],
        "claim_sets": [{"claim_set_id": f"claims-{task_name}"}],
        "claim_validation_reports": {"claims": {"claim_validation": {"ok": True}}},
        "state_consumption_records": [{"behavioral_effect": "changed"}],
        "codeact_source_hashes": [program_hash] if codeact else [],
        "session": {"transform_program_hashes": [] if codeact else [program_hash]},
    }
def test_adaptive_live_smoke_enters_runtime_through_dispatcher() -> None:
    source = inspect.getsource(run_adaptive_agent_smoke.main)

    assert "dispatcher=AdaptiveCapabilityDispatcher(context=dispatch_context)" in source
    assert "execute_step=" not in source


def test_codeact_live_smoke_uses_runtime_projection_upstream_artifact() -> None:
    planner_source = inspect.getsource(run_llm_codeact_smoke._planner_runtime_plan)
    main_source = inspect.getsource(run_llm_codeact_smoke.main)

    assert '_isolated_role_completion("planner"' in planner_source
    assert "PlanProposal(" not in planner_source
    assert "task.analysis_python_capability" in planner_source
    assert "planner_did_not_select_authorized_codeact_capability" in planner_source
    assert "_metric_input_artifact" not in main_source
    assert "code_source_factory=code_source_factory" in main_source
    assert "claim_set_factory=claim_set_factory" in main_source
    assert "compose_report_handler" not in main_source


def test_live_matrix_runs_five_real_task_cases_and_aggregates_runtime_summaries() -> None:
    source = inspect.getsource(run_adaptive_mode_matrix)

    assert '"aggregation_by_quarter"' in source
    assert '"anomaly_acme_delivery"' in source
    assert "run_llm_codeact_smoke.py" in source
    assert "approved_plan_hashes" in source
    assert "program_or_source_hashes" in source
    assert "state_consumption_not_changed" in source
    assert "model_fallback_used" in source
    assert "codeact_sandbox_identity_invalid" in source
    assert "STATEBUS_ADAPTIVE_ROLE_WORKER_TIMEOUT_S" in source
    assert "test_python_failure_falls_back_only_with_a_fresh_dsl_grant" in source


def test_five_case_pre_run_adds_distinct_quarter_aggregation_and_acme_anomaly_tasks() -> None:
    quarter_aggregation = run_llm_codeact_smoke._task_definition("aggregation_by_quarter")
    acme_anomaly = run_llm_codeact_smoke._task_definition("anomaly_acme_delivery")

    assert quarter_aggregation.task_id == "adaptive-aggregation-quarter-live-001"
    assert quarter_aggregation.analysis_semantics["group_field"] == "quarter"
    assert quarter_aggregation.analysis_semantics["value_field"] == "revenue_musd"
    assert acme_anomaly.task_id == "adaptive-acme-delivery-anomaly-live-001"
    assert acme_anomaly.source_schema == {"quarter": "string", "on_time_delivery_pct": "number"}
    assert acme_anomaly.require_codeact


def test_claim_row_batches_are_controller_bounded_and_lossless() -> None:
    rows = (
        {"quarter": "2026Q1", "sum": 125.0},
        {"quarter": "2026Q2", "sum": 134.0},
        {"quarter": "2026Q3", "sum": 140.0},
    )

    assert run_llm_codeact_smoke._bounded_claim_row_batches(rows) == (
        rows[:2],
        rows[2:],
    )


def test_live_matrix_rejects_model_fallback_and_non_bwrap_codeact_identity() -> None:
    summaries = [
        _live_summary(
            "comparison",
            plan_hash="plan-comparison",
            capabilities=["retrieve_table_evidence_v1", "compare_periods_python_v1", "compose_comparison_report_v1"],
            program_hash="source-comparison",
            codeact=True,
        ),
        _live_summary(
            "aggregation",
            plan_hash="plan-aggregation",
            capabilities=["retrieve_table_evidence_v1", "aggregate_metrics_v1", "compose_cited_report_v1"],
            program_hash="program-aggregation",
            codeact=False,
        ),
        _live_summary(
            "aggregation_by_quarter",
            plan_hash="plan-aggregation-quarter",
            capabilities=["retrieve_table_evidence_v1", "aggregate_metrics_v1", "compose_cited_report_v1"],
            program_hash="program-aggregation-quarter",
            codeact=False,
        ),
        _live_summary(
            "anomaly",
            plan_hash="plan-anomaly",
            capabilities=["retrieve_semantic_evidence_v1", "detect_anomaly_python_v1", "compose_risk_memo_v1"],
            program_hash="source-anomaly",
            codeact=True,
        ),
        _live_summary(
            "anomaly_acme_delivery",
            plan_hash="plan-acme-delivery-anomaly",
            capabilities=["retrieve_table_evidence_v1", "detect_anomaly_python_v1", "compose_risk_memo_v1"],
            program_hash="source-acme-delivery-anomaly",
            codeact=True,
        ),
    ]
    assertions = run_adaptive_mode_matrix._assert_live_matrix(summaries)
    assert assertions["ok"]
    assert assertions["model_fallback_counts"] == {
        "aggregation": 0.0,
        "aggregation_by_quarter": 0.0,
        "anomaly": 0.0,
        "anomaly_acme_delivery": 0.0,
        "comparison": 0.0,
    }
    assert assertions["codeact_sandbox_required_uid_gid"] == [65534, 65534]

    summaries[0]["telemetry"]["model_fallback_count"] = 1.0  # type: ignore[index]
    summaries[3]["execution_records"][0]["sandbox_uid"] = 0  # type: ignore[index]
    rejected = run_adaptive_mode_matrix._assert_live_matrix(summaries)
    assert not rejected["ok"]
    assert "model_fallback_used:comparison" in rejected["failures"]
    assert "codeact_sandbox_identity_invalid:anomaly" in rejected["failures"]
