from __future__ import annotations

from pathlib import Path

import json

from v2.benchmark import BenchmarkLayer
from v2.benchmark.continuous_runner import (
    run_continuous_benchmark_collection,
    run_continuous_benchmark_suite,
    run_continuous_text_semantic_selection_family,
)
from v2.benchmark.continuous_task_family import load_continuous_task_family
from v2.runtime.codeact_data_tasks import build_candidate_output_payload


def _codeact_data_request(
    *,
    task_id: str,
    task_family: str,
    intent_op: str,
    required_outputs: list[str],
    spec_arguments: dict[str, object],
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "task_family": task_family,
        "intent_op": intent_op,
        "query_text": "schema drift adapter test",
        "summary_suffix": "verified",
        "selected_doc_hashes": [],
        "supporting_doc_ids": [],
        "evidence_pack_hash": "sha256:test-pack",
        "retrieval_log_hash": "sha256:test-log",
        "downgraded_execution_goal": False,
        "execution_goal": "full_execution_goal",
        "required_outputs": required_outputs,
        "spec_arguments": spec_arguments,
        "execution_context": {
            "reuse_contract": {
                "produces": [],
                "consumes": [],
                "minimum_reuse_class": "assist",
            }
        },
        "history_runtime_roots": [],
    }


def test_schema_drift_markdown_aliases_are_resolved_generically(tmp_path: Path) -> None:
    payload = build_candidate_output_payload(
        _codeact_data_request(
            task_id="schema-drift-financial",
            task_family="cross_period_financial_analysis",
            intent_op="compare_metric",
            required_outputs=["revenue_value", "summary_text"],
            spec_arguments={
                "ticker": "BETA",
                "quarter": "2025Q3",
                "metric": "revenue",
                "document_path": (
                    "v2/benchmark/samples/continuous_task_families/cross_period_financial/"
                    "cross_period_financial_report_schema_drift.md"
                ),
                "schema_aliases": {
                    "period": "quarter",
                    "revenue_usd_millions": "revenue_musd",
                },
            },
        ),
        tmp_path,
    )

    assert payload["revenue_value"] == "72"
    assert payload["document_source_path"].endswith(
        "cross_period_financial_report_schema_drift.md"
    )


def test_schema_drift_csv_aliases_are_resolved_with_lineage(tmp_path: Path) -> None:
    payload = build_candidate_output_payload(
        _codeact_data_request(
            task_id="schema-drift-weather",
            task_family="continuous_csv_table_analysis",
            intent_op="profile_and_mean",
            required_outputs=["schema_profile_ref", "mean_windspeed"],
            spec_arguments={
                "dataset_id": "weather_baro_2015_schema_drift",
                "csv_path": (
                    "v2/benchmark/samples/continuous_task_families/formal_operating_metrics/"
                    "baro_2015_schema_drift.csv"
                ),
                "column": "WINDSPEED",
                "schema_aliases": {
                    "DATE_TIME": "DATE TIME",
                    "WIND_SPEED_MPS": "WINDSPEED",
                },
            },
        ),
        tmp_path,
    )

    assert payload["mean_windspeed"] == "7.500"
    assert payload["resolved_schema_aliases"] == {
        "DATE_TIME": "DATE TIME",
        "WIND_SPEED_MPS": "WINDSPEED",
    }
    profile = json.loads((tmp_path / str(payload["schema_profile_ref"])).read_text(encoding="utf-8"))
    assert profile["resolved_schema_aliases"] == payload["resolved_schema_aliases"]
from v2.runtime.codeact_data_tasks import (
    _parse_cross_period_revenue_tables,
    _read_csv_rows,
    _resolve_csv_schema_aliases,
    _numeric_series,
)


def test_csv_profile_outlier_contract_uses_iqr_for_gold_values() -> None:
    manifest_path = Path("v2/benchmark/samples/continuous_task_families/csv_table_profile/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rounds_by_number = {round_payload["round"]: round_payload for round_payload in manifest["rounds"]}

    assert rounds_by_number[4]["canonical_task_spec"]["arguments"]["method"] == "iqr"
    assert "IQR" in rounds_by_number[4]["request_text"]
    assert "strategy:iqr_outlier" in rounds_by_number[4]["reuse_contract"]["produces"]
    assert rounds_by_number[8]["canonical_task_spec"]["arguments"]["method"] == "iqr"
    assert "strategy:iqr_outlier" in rounds_by_number[8]["reuse_contract"]["consumes"]


def test_schema_drift_fixtures_resolve_public_aliases_without_task_id_branches() -> None:
    document_path = Path(
        "v2/benchmark/samples/continuous_task_families/"
        "cross_period_financial/cross_period_financial_report_schema_drift.md"
    )
    revenue = _parse_cross_period_revenue_tables(
        document_path.read_text(encoding="utf-8"),
        {
            "period": "quarter",
            "revenue_usd_millions": "revenue_musd",
        },
    )
    assert revenue["BETA"]["2025Q3"] == 72.0

    rows, fieldnames, _ = _read_csv_rows(
        "v2/benchmark/samples/continuous_task_families/"
        "formal_operating_metrics/baro_2015_schema_drift.csv"
    )
    normalized_rows, normalized_fields, aliases = _resolve_csv_schema_aliases(
        rows,
        fieldnames,
        {"DATE_TIME": "DATE TIME", "WIND_SPEED_MPS": "WINDSPEED"},
    )
    assert aliases == {
        "DATE_TIME": "DATE TIME",
        "WIND_SPEED_MPS": "WINDSPEED",
    }
    assert "WINDSPEED" in normalized_fields
    assert sum(_numeric_series(normalized_rows, "WINDSPEED")) / len(normalized_rows) == 7.5


def test_continuous_runner_rejects_unsupported_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/gridops_world")
    )
    try:
        run_continuous_benchmark_suite(
            family=family,
            workspace_root=tmp_path / "workspaces",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "control.sock",
            suite_id="continuous-gridops",
            role_path_mode="deterministic",
            embedding_mode="deterministic",
        )
    except ValueError as exc:
        assert "no registered dataset capability" in str(exc)
        assert "kind=grid_world" in str(exc)
    else:
        raise AssertionError("expected continuous runner to reject unsupported family")


def test_continuous_runner_executes_csv_profile_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_table_profile")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-csv-profile",
        role_path_mode="deterministic",
        planner_mode="deterministic",
        retriever_mode="deterministic",
        executor_mode="deterministic_codeact",
        summarizer_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.waterfall_metrics["L0_case_count"] == 10.0
    assert report.waterfall_metrics["L3_history_runtime_root_count"] > 0.0
    assert report.waterfall_metrics["L3_artifact_reuse_count"] >= 7.0
    assert report.waterfall_metrics["L3_reuse_gain"] == 0.0
    assert report.waterfall_metrics["L3_history_reuse_gain"] > 0.0
    assert report.waterfall_metrics["L3_history_step_reduction_count"] > 0.0
    assert report.metadata["eligible_for_quality_headline"] is True
    assert report.metadata["fairness_comparison_valid"] is True
    assert report.metadata["role_execution_profile"] == {
        "planner": "deterministic",
        "retriever": "deterministic",
        "executor": "deterministic_codeact",
        "summarizer": "deterministic",
        "embedding": "deterministic",
    }
    assert report.metadata["eligible_for_replay_headline"] is False
    assert report.metadata["headline_scope"] == "history_backed_only"
    assert report.evidence_pack["schema_version"] == "statebus.continuous_evidence_pack.v1"
    assert report.evidence_pack["family_id"] == "csv_table_profile_v1"
    assert report.evidence_pack["headline_scope"] == "history_backed_only"
    assert report.evidence_pack["l1_l2_non_text_delta"]["semantic_state_transfer_count"] > 0.0
    assert report.evidence_pack["l1_l2_non_text_delta"]["raw_evidence_bytes_seen_by_llm"] < 0.0
    assert report.evidence_pack["runtime_overhead_summary"]["schema_version"] == "statebus.runtime_overhead_collection_summary.v1"
    assert report.evidence_pack["runtime_overhead_summary"]["top_driver_stage_buckets"]
    assert report.evidence_pack["runtime_overhead_summary"]["top_persist_and_reload_buckets"]
    assert (
        report.evidence_pack["runtime_overhead_summary"]["persist_and_reload_breakdown_totals_ms"][
            "persist_bundle_write_stage_ms"
        ]
        >= 0.0
    )
    assert report.evidence_pack["runtime_overhead_summary"]["write_count_totals"]["role_prompt_slice_artifact_count"] >= 40.0
    assert report.evidence_pack["round_evidence"][-1]["audit_paths"]["replay"].endswith("replay_audit.json")
    assert report.evidence_pack["round_evidence"][-1]["role_prompt_slice_ref_ids"]
    assert Path(report.markdown_report_path).exists()
    assert report.metadata["replay_admissibility_audit"]["audit_mode"] == "history_backed"
    assert report.metadata["replay_admissibility_audit"]["observed_history_reuse_rounds"] == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert report.metadata["replay_admissibility_audit"]["missing_history_target_rounds"] == []
    assert report.metadata["replay_admissibility_audit"]["unexpected_history_target_rounds"] == [2, 3, 6]
    assert report.metadata["replay_gate_reason"] == ""
    assert report.comparison_summary["history_target_round_count"] == 6.0
    assert report.comparison_summary["history_observed_reuse_round_count"] == 9.0
    assert report.comparison_summary["history_missing_target_round_count"] == 0.0
    assert report.comparison_summary["history_additional_reuse_round_count"] == 3.0
    assert report.comparison_summary["replay_target_round_count"] == 0.0
    assert report.comparison_summary["replay_missing_target_round_count"] == 0.0
    assert report.comparison_summary["replay_unexpected_round_count"] == 0.0
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert {
        layer_report.metadata["role_execution_profile"]["executor"]
        for layer_report in report.layer_reports
    } == {"deterministic_codeact"}
    for layer_report in report.layer_reports:
        for case in layer_report.cases:
            assert case.audit_summary["role_execution_profile"]["executor"] == "deterministic_codeact"
            gold_audit = case.audit_summary["fairness_contract"]["gold_visibility_audit"]
            assert gold_audit["ok"] is True
            assert all(role_audit["ok"] for role_audit in gold_audit["roles"].values())
            for relpath in case.audit_summary["rendered_llm_requests"]["role_relpaths"].values():
                request_text = (Path(case.workspace_root) / relpath).read_text(encoding="utf-8")
                assert '"expected_facts"' not in request_text
                assert '"quality_checks"' not in request_text
                assert '"expected_metric_effects"' not in request_text
    fairness_cases = report.metadata["fairness_manifest"]["cases"]
    for lanes in fairness_cases.values():
        assert len({lane["task_contract_digest"] for lane in lanes.values()}) == 1
        assert len({lane["source_content_digest"] for lane in lanes.values()}) == 1
        assert len({lane["prior_fact_digest"] for lane in lanes.values()}) == 1
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert l3_report.telemetry_summary["task_ms"] > 0.0
    assert all(case.metrics["task_ms"] > 0.0 for case in l3_report.cases)
    prefix_queries = l3_report.telemetry_summary["neural_prefix_cache_query_count_estimate"]
    prefix_hits = l3_report.telemetry_summary["neural_prefix_cache_hit_count_estimate"]
    assert l3_report.telemetry_summary["neural_prefix_cache_hit_rate_estimate"] == (
        prefix_hits / prefix_queries
    )
    assert 0.0 <= l3_report.telemetry_summary["neural_prefix_prefill_savings_ratio_estimate"] <= 1.0
    assert l3_report.telemetry_summary["skipped_step_count"] == 0.0
    assert l3_report.telemetry_summary["history_step_reduction_count"] > 0.0
    assert l3_report.telemetry_summary["history_artifact_reuse_count"] >= 7.0
    assert l3_report.telemetry_summary["history_strategy_reuse_count"] >= 3.0
    l2_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L2)
    assert l2_report.telemetry_summary.get("history_artifact_reuse_count", 0.0) == 0.0
    assert l2_report.telemetry_summary.get("reuse_gain", 0.0) == 0.0
    final_case = l3_report.cases[-1]
    assert final_case.task_id == "csv-profile-010"
    assert final_case.metrics["history_dependency_count"] == 9.0
    assert final_case.metrics["artifact_reuse_count"] >= 7.0
    assert final_case.metrics["skipped_step_count"] == 0.0
    assert final_case.metrics["reuse_gain"] == 0.0
    assert final_case.metrics["history_step_reduction_count"] >= 2.0
    assert final_case.metrics["history_reuse_gain"] >= 1.0
    assert final_case.audit_summary["replay"]["history_artifact_reuse_count"] >= 7
    assert final_case.audit_summary["replay"]["history_strategy_reuse_count"] >= 3
    assert final_case.audit_summary["replay"]["history_step_reduction_count"] >= 2
    output_payload = json.loads(Path(final_case.output_artifact_path).read_text(encoding="utf-8"))
    assert int(output_payload["reused_artifact_count"]) >= 7
    assert int(output_payload["reused_strategy_count"]) >= 3
    assert len(output_payload["reused_artifact_refs"]) >= 7
    assert len(output_payload["reused_strategy_refs"]) >= 3


def test_continuous_text_semantic_selection_diagnostic_does_not_transfer_state_ref(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_table_profile")
    )
    report = run_continuous_text_semantic_selection_family(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-text-semantic-selection",
    )
    assert len(report.cases) == 10
    assert report.profile.structured_control_enabled is False
    assert report.profile.semantic_pruning_enabled is True
    assert report.metadata["baseline_kind"] == "internal_text_same_semantic_selection"
    assert report.metadata["layer_contract_gate_enabled"] is False
    assert report.telemetry_summary["semantic_state_transfer_count"] == 0.0
    assert report.telemetry_summary["raw_evidence_bytes_seen_by_llm"] > 0.0
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["semantic_state_transfer_enabled"] is False


def test_continuous_runner_executes_long_doc_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_table")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-long-doc",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert "long_doc_table_v1" in report.metadata["supported_continuous_execution_families"]
    assert report.waterfall_metrics["L2_semantic_state_transfer_count"] > 0.0
    assert report.waterfall_metrics["L3_artifact_reuse_count"] >= 7.0
    assert report.waterfall_metrics["L3_reuse_gain"] == 0.0
    assert report.waterfall_metrics["L3_history_reuse_gain"] > 0.0
    assert report.waterfall_metrics["L3_history_step_reduction_count"] > 0.0
    assert report.metadata["eligible_for_quality_headline"] is True
    assert report.metadata["eligible_for_replay_headline"] is False
    assert report.metadata["headline_scope"] == "history_backed_only"
    assert report.metadata["replay_admissibility_audit"]["audit_mode"] == "history_backed"
    assert report.metadata["replay_admissibility_audit"]["observed_history_reuse_rounds"] == [2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert report.metadata["replay_admissibility_audit"]["missing_history_target_rounds"] == []
    assert report.metadata["replay_admissibility_audit"]["unexpected_history_target_rounds"] == [2, 3, 4, 6, 7]
    assert report.metadata["replay_gate_reason"] == ""
    assert report.comparison_summary["history_target_round_count"] == 4.0
    assert report.comparison_summary["history_observed_reuse_round_count"] == 9.0
    assert report.comparison_summary["history_missing_target_round_count"] == 0.0
    assert report.comparison_summary["history_additional_reuse_round_count"] == 5.0
    assert report.comparison_summary["replay_target_round_count"] == 0.0
    assert report.comparison_summary["replay_missing_target_round_count"] == 0.0
    assert report.comparison_summary["replay_unexpected_round_count"] == 0.0
    l2_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L2)
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert l2_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    final_case = l3_report.cases[-1]
    assert final_case.task_id == "longdoc-010"
    assert final_case.metrics["artifact_reuse_count"] >= 7.0
    assert final_case.metrics["skipped_step_count"] == 0.0
    assert final_case.metrics["reuse_gain"] == 0.0
    assert final_case.metrics["history_step_reduction_count"] >= 2.0
    assert final_case.metrics["history_reuse_gain"] >= 1.0
    output_payload = json.loads(Path(final_case.output_artifact_path).read_text(encoding="utf-8"))
    assert int(output_payload["citation_count"]) >= 5
    assert int(output_payload["reused_artifact_count"]) >= 7


def test_continuous_runner_executes_kv_prefix_reuse_family_as_explicit_probe(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/kv_prefix_reuse")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-kv-prefix-reuse",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
        task_schedule_plan="cache_friendly",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert report.metadata["task_schedule_plan"] == "cache_friendly"
    assert report.metadata["task_schedule_task_ids"] == list(family.kv_prefix_probe["cache_friendly_order"])
    assert report.metadata["task_schedule_adjacent_reuse_opportunity_count"] == 8
    assert report.metadata["claim_tier"] == "demo_secondary"
    assert report.metadata["source_basis"]["not_default_formal_chain"] is True
    assert "kv_prefix_reuse_v1" in report.metadata["supported_continuous_execution_families"]
    assert report.waterfall_metrics["L2_semantic_state_transfer_count"] > 0.0
    assert report.waterfall_metrics["L3_kv_corpus_prefix_hash_reuse_count"] > 0.0
    assert report.waterfall_metrics["L3_kv_corpus_level_prefill_saved_tokens_estimate"] > 0.0
    assert report.evidence_pack["kv_reuse_analysis_by_layer"]["L3"]["corpus_prefix_hash_reuse_count"] > 0
    assert report.evidence_pack["headline_scope"] in {"history_backed_only", "replay_admissible"}
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert [case.task_id for case in l3_report.cases] == list(family.kv_prefix_probe["cache_friendly_order"])
    assert l3_report.metadata["task_schedule_max_contiguous_same_affinity_run"] == 5
    assert l3_report.metadata["kv_reuse_analysis"]["claim_boundary"].endswith(
        "actual_vllm_metrics_required_for_mechanism_claim"
    )


def test_continuous_runner_executes_replay_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_metric_replay")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-long-doc-replay",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert report.metadata["eligible_for_quality_headline"] is True
    assert report.metadata["eligible_for_replay_headline"] is True
    assert report.metadata["replay_gate_reason"] == ""
    assert report.metadata["headline_scope"] == "replay_admissible"
    assert report.metadata["replay_admissibility_audit"]["audit_mode"] == "replay_admissible"
    assert report.metadata["replay_admissibility_audit"]["expected_target_rounds"] == [3, 4, 5, 6, 7, 8, 9, 10]
    assert report.metadata["replay_admissibility_audit"]["missing_target_rounds"] == []
    assert report.metadata["replay_admissibility_audit"]["unexpected_target_rounds"] == []
    assert report.metadata["replay_admissibility_audit"]["validated_target_rounds"] == [3, 4, 6, 8, 9]
    assert report.metadata["replay_admissibility_audit"]["exact_target_rounds"] == [5, 7, 10]
    assert report.comparison_summary["replay_target_round_count"] == 8.0
    assert report.comparison_summary["replay_missing_target_round_count"] == 0.0
    assert report.comparison_summary["replay_unexpected_round_count"] == 0.0
    assert report.waterfall_metrics["L2_semantic_state_transfer_count"] > 0.0
    assert report.waterfall_metrics["L3_artifact_reuse_count"] >= 8.0
    assert report.waterfall_metrics["L3_reuse_gain"] > 0.0
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert l3_report.telemetry_summary["validated_replay_count"] >= 5.0
    assert (
        l3_report.telemetry_summary["validated_downgraded_reuse_count"]
        == l3_report.telemetry_summary["validated_replay_count"]
    )
    assert l3_report.telemetry_summary["exact_replay_count"] >= 3.0
    assert (
        l3_report.telemetry_summary["answer_restoration_replay_count"]
        == l3_report.telemetry_summary["exact_replay_count"]
    )
    assert l3_report.telemetry_summary["skipped_step_count"] >= 11.0
    assert l3_report.telemetry_summary["downgrade_execution_goal_count"] >= 4.0
    validated_case = next(case for case in l3_report.cases if case.task_id == "replay-longdoc-003")
    exact_case = next(case for case in l3_report.cases if case.task_id == "replay-longdoc-005")
    validated_from_api_exact_mismatch_case = next(case for case in l3_report.cases if case.task_id == "replay-longdoc-008")
    assert validated_case.replay_class == "validated_replay"
    assert validated_case.metrics["validated_replay_count"] == 1.0
    assert validated_case.metrics["validated_downgraded_reuse_count"] == 1.0
    assert validated_case.metrics["answer_restoration_replay_count"] == 0.0
    assert validated_case.metrics["skipped_step_count"] == 1.0
    assert validated_case.metrics["downgrade_execution_goal_count"] == 1.0
    assert validated_from_api_exact_mismatch_case.replay_class == "validated_replay"
    assert validated_from_api_exact_mismatch_case.metrics["validated_replay_count"] == 1.0
    assert validated_from_api_exact_mismatch_case.metrics["skipped_step_count"] == 1.0
    validated_output = json.loads(Path(validated_case.output_artifact_path).read_text(encoding="utf-8"))
    assert validated_output["downgraded_execution_goal"] is True
    exact_output = json.loads(Path(exact_case.output_artifact_path).read_text(encoding="utf-8"))
    assert exact_case.replay_class == "exact_replay"
    assert exact_case.metrics["exact_replay_count"] == 1.0
    assert exact_case.metrics["answer_restoration_replay_count"] == 1.0
    assert exact_case.metrics["validated_downgraded_reuse_count"] == 0.0
    assert exact_case.metrics["skipped_step_count"] == 2.0
    assert exact_output["restored_replay_class"] == "exact_replay"
    assert exact_output["task_id"] == "replay-longdoc-005"
    assert Path(exact_case.workspace_root, exact_output["metric_series_ref"]).exists()


def test_continuous_runner_executes_cross_period_family_with_replay_safety(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/cross_period_financial")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-cross-period",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert report.metadata["eligible_for_quality_headline"] is True
    assert report.metadata["eligible_for_replay_headline"] is True
    assert report.metadata["replay_gate_reason"] == ""
    assert report.metadata["headline_scope"] == "replay_admissible"
    assert report.metadata["replay_admissibility_audit"]["expected_target_rounds"] == [2, 4, 6, 8]
    assert report.metadata["replay_admissibility_audit"]["validated_target_rounds"] == [2, 4, 6, 8]
    assert report.metadata["replay_admissibility_audit"]["exact_target_rounds"] == []
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert l3_report.telemetry_summary["validated_replay_count"] == 4.0
    assert l3_report.telemetry_summary["validated_downgraded_reuse_count"] == 4.0
    assert l3_report.telemetry_summary["exact_replay_count"] == 0.0
    assert l3_report.telemetry_summary["answer_restoration_replay_count"] == 0.0
    assert report.comparison_summary["validated_downgraded_reuse_count"] == 4.0
    assert report.comparison_summary["answer_restoration_replay_count"] == 0.0
    assert report.comparison_summary["replay_target_round_count"] == 4.0
    assert report.comparison_summary["replay_observed_round_count"] == 4.0
    assert report.comparison_summary["replay_missing_target_round_count"] == 0.0
    assert report.comparison_summary["replay_unexpected_round_count"] == 0.0
    beta_case = next(case for case in l3_report.cases if case.task_id == "cross-period-006")
    assert beta_case.replay_class == "validated_replay"
    assert beta_case.metrics["validated_replay_count"] == 1.0
    assert beta_case.metrics["validated_downgraded_reuse_count"] == 1.0
    assert beta_case.metrics["skipped_step_count"] == 1.0
    output_payload = json.loads(Path(beta_case.output_artifact_path).read_text(encoding="utf-8"))
    assert output_payload["revenue_value"] == "87"


def test_continuous_runner_executes_incident_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/incident_diagnosis")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-incident",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert report.metadata["eligible_for_replay_headline"] is True
    assert report.metadata["headline_scope"] == "replay_admissible"
    assert report.metadata["replay_gate_reason"] == ""
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    validated_case = next(case for case in l3_report.cases if case.task_id == "incident-002")
    exact_case = next(case for case in l3_report.cases if case.task_id == "incident-003")
    assert validated_case.replay_class == "validated_replay"
    assert validated_case.metrics["validated_replay_count"] == 1.0
    assert exact_case.replay_class == "exact_replay"
    assert exact_case.metrics["exact_replay_count"] == 1.0
    assert exact_case.metrics["skipped_step_count"] == 2.0
    output_payload = json.loads(Path(validated_case.output_artifact_path).read_text(encoding="utf-8"))
    assert output_payload["service_name"] == "service-b.service"
    assert output_payload["root_cause"] == "high_io_wait"


def test_continuous_runner_executes_csv_replay_family(tmp_path: Path) -> None:
    family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_correlation_replay")
    )
    report = run_continuous_benchmark_suite(
        family=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-csv-replay",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
    assert report.metadata["eligible_for_quality_headline"] is True
    assert report.metadata["eligible_for_replay_headline"] is True
    assert report.metadata["replay_gate_reason"] == ""
    assert report.metadata["headline_scope"] == "replay_admissible"
    assert report.metadata["replay_admissibility_audit"]["audit_mode"] == "replay_admissible"
    assert report.metadata["replay_admissibility_audit"]["expected_target_rounds"] == [3, 4, 5, 6, 7, 8, 9, 10]
    assert report.metadata["replay_admissibility_audit"]["missing_target_rounds"] == []
    assert report.metadata["replay_admissibility_audit"]["unexpected_target_rounds"] == []
    assert report.comparison_summary["replay_target_round_count"] == 8.0
    assert report.comparison_summary["replay_missing_target_round_count"] == 0.0
    assert report.comparison_summary["replay_unexpected_round_count"] == 0.0
    assert "csv_correlation_replay_v1" in report.metadata["supported_continuous_execution_families"]
    assert report.waterfall_metrics["L2_semantic_state_transfer_count"] > 0.0
    assert report.waterfall_metrics["L3_artifact_reuse_count"] >= 9.0
    assert report.waterfall_metrics["L3_reuse_gain"] > 0.0
    l3_report = next(layer_report for layer_report in report.layer_reports if layer_report.layer == BenchmarkLayer.L3)
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
    assert l3_report.telemetry_summary["validated_replay_count"] >= 8.0
    assert l3_report.telemetry_summary["exact_replay_count"] == 0.0
    assert l3_report.telemetry_summary["skipped_step_count"] >= 8.0
    assert l3_report.telemetry_summary["downgrade_execution_goal_count"] >= 8.0
    validated_case = next(case for case in l3_report.cases if case.task_id == "replay-csv-005")
    validated_repeat_case = next(case for case in l3_report.cases if case.task_id == "replay-csv-008")
    assert validated_case.replay_class == "validated_replay"
    assert validated_case.metrics["validated_replay_count"] == 1.0
    assert validated_case.metrics["skipped_step_count"] == 1.0
    assert validated_repeat_case.replay_class == "validated_replay"
    assert validated_repeat_case.metrics["validated_replay_count"] == 1.0
    assert validated_repeat_case.metrics["skipped_step_count"] == 1.0
    validated_output = json.loads(Path(validated_repeat_case.output_artifact_path).read_text(encoding="utf-8"))
    assert validated_output["downgraded_execution_goal"] is True
    assert validated_output["task_id"] == "replay-csv-008"
    assert Path(validated_repeat_case.workspace_root, validated_output["correlation_artifact_ref"]).exists()


def test_continuous_runner_executes_formal_collection(tmp_path: Path) -> None:
    operating_metrics_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/formal_operating_metrics")
    ).select_view("causal_core")
    financial_reports_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/formal_financial_reports")
    ).select_view("causal_core")
    report = run_continuous_benchmark_collection(
        families=(operating_metrics_family, financial_reports_family),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-collection",
        role_path_mode="deterministic",
        planner_mode="deterministic",
        retriever_mode="deterministic",
        executor_mode="deterministic_codeact",
        summarizer_mode="deterministic",
        embedding_mode="deterministic",
        state_pool_mode="shared_memory",
        execution_scope="formal_causal_view",
        experiment_view="causal_core",
        executor_transport="subprocess",
    )

    assert report.metadata["continuous_execution"] is True
    assert report.metadata["formal_headline_eligible"] is True
    assert report.metadata["round_view"] == "causal_core"
    assert report.metadata["collection_scope"] == "formal_continuous_task_families"
    assert report.metadata["state_pool_mode_requested"] == "shared_memory"
    assert report.metadata["observed_semantic_state_storage_kinds"] == ["shared_memory"]
    assert report.collection_summary["family_count"] == 2.0
    assert report.collection_summary["continuous_round_count"] == 10.0
    assert report.collection_summary["L2_semantic_state_transfer_count"] > 0.0
    assert report.collection_summary["L3_artifact_reuse_count"] > 0.0
    assert report.collection_summary["L3_reuse_gain"] == 2.0
    assert report.collection_summary["L3_history_reuse_gain"] > 0.0
    assert report.collection_summary["L3_history_step_reduction_count"] > 0.0
    assert report.collection_summary["history_backed_reuse_count"] > 0.0
    assert report.collection_summary["quality_headline_eligible_family_count"] == 2.0
    assert report.collection_summary["replay_headline_eligible_family_count"] == 1.0
    assert report.collection_summary["history_backed_only_family_count"] == 1.0
    assert report.collection_summary["history_target_round_count"] == 4.0
    assert report.collection_summary["history_observed_reuse_round_count"] == 4.0
    assert report.collection_summary["history_missing_target_round_count"] == 0.0
    assert report.collection_summary["history_additional_reuse_round_count"] == 0.0
    assert report.collection_summary["validated_replay_count"] >= 2.0
    assert report.collection_summary["exact_replay_count"] == 0.0
    assert report.collection_summary["replay_target_round_count"] == 2.0
    assert report.collection_summary["replay_observed_round_count"] == 2.0
    assert report.collection_summary["replay_missing_target_round_count"] == 0.0
    assert report.collection_summary["replay_unexpected_round_count"] == 0.0
    assert report.evidence_pack["schema_version"] == "statebus.continuous_collection_evidence_pack.v1"
    assert report.evidence_pack["headline_scope"] == "history_backed_only"
    assert len(report.evidence_pack["family_evidence"]) == 2
    assert all(family["l1_l2_non_text_delta"]["raw_evidence_bytes_seen_by_llm"] < 0.0 for family in report.evidence_pack["family_evidence"])
    assert report.evidence_pack["runtime_overhead_summary"]["top_outer_stage_buckets"]
    assert report.evidence_pack["runtime_overhead_summary"]["top_persist_and_reload_buckets"]
    assert (
        report.evidence_pack["runtime_overhead_summary"]["persist_and_reload_breakdown_totals_ms"][
            "persist_integrity_check_stage_ms"
        ]
        >= 0.0
    )
    assert report.evidence_pack["runtime_overhead_summary"]["write_count_totals"]["role_prompt_slice_artifact_count"] >= 40.0
    assert Path(report.markdown_report_path).exists()
    assert report.eligible_for_quality_headline is True
    assert report.eligible_for_replay_headline is False
    assert report.eligible_for_headline is False
    operating_audit = report.admissibility_summary["formal_operating_metrics_v1"]
    assert operating_audit["history_target_round_count"] == 4.0
    assert operating_audit["history_observed_reuse_round_count"] == 4.0
    assert operating_audit["history_missing_target_round_count"] == 0.0
    assert operating_audit["replay_admissibility_audit"]["audit_mode"] == "history_backed"
    financial_audit = report.admissibility_summary["formal_financial_reports_v1"]
    assert financial_audit["replay_target_round_count"] == 2.0
    assert financial_audit["replay_observed_round_count"] == 2.0
    assert financial_audit["replay_missing_target_round_count"] == 0.0
    assert financial_audit["eligible_for_replay_headline"] is True
    assert {family_report.task_family for family_report in report.family_reports} == {
        "formal_operating_metrics_v1",
        "formal_financial_reports_v1",
    }
    assert all(
        family_report.metadata["observed_semantic_state_storage_kinds"] == ["shared_memory"]
        for family_report in report.family_reports
    )
    for family_report in report.family_reports:
        reports_by_layer = {
            layer_report.layer: layer_report
            for layer_report in family_report.layer_reports
        }
        assert all(
            case.audit_summary["fairness_runtime_contract"]["control_carrier"]
            == "utf8_text"
            for case in reports_by_layer[BenchmarkLayer.L0].cases
        )
        assert all(
            case.audit_summary["fairness_runtime_contract"]["control_carrier"]
            == "protobuf"
            for layer in (BenchmarkLayer.L1, BenchmarkLayer.L2, BenchmarkLayer.L3)
            for case in reports_by_layer[layer].cases
        )
        assert reports_by_layer[BenchmarkLayer.L0].telemetry_summary[
            "utf8_text_frame_count"
        ] > 0.0
        assert reports_by_layer[BenchmarkLayer.L1].telemetry_summary[
            "protobuf_frame_count"
        ] > 0.0
        for layer in (BenchmarkLayer.L0, BenchmarkLayer.L1, BenchmarkLayer.L2):
            assert reports_by_layer[layer].telemetry_summary.get(
                "hybrid_memory_query_count", 0.0
            ) == 0.0
            assert reports_by_layer[layer].telemetry_summary.get(
                "memory_consumed_count", 0.0
            ) == 0.0
        for layer_report in reports_by_layer.values():
            for case in layer_report.cases:
                transport_audit = case.audit_summary["control_transport"]
                assert transport_audit["backend"] == "subprocess"
                assert transport_audit["worker_pids"]
                assert transport_audit["driver_pid"] not in transport_audit["worker_pids"]
                assert transport_audit["total_wire_bytes"] > 0


def test_continuous_runner_executes_formal_long_horizon_l3_with_negative_fixture(
    tmp_path: Path,
) -> None:
    families = tuple(
        load_continuous_task_family(
            Path("v2/benchmark/samples/continuous_task_families") / name
        ).select_view("long_horizon")
        for name in ("formal_operating_metrics", "formal_financial_reports")
    )
    report = run_continuous_benchmark_collection(
        families=families,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-long-horizon",
        role_path_mode="deterministic",
        planner_mode="deterministic",
        retriever_mode="deterministic",
        executor_mode="deterministic_codeact",
        summarizer_mode="deterministic",
        embedding_mode="deterministic",
        state_pool_mode="shared_memory",
        execution_scope="formal_stability_view",
        executor_transport="subprocess",
        layers=(BenchmarkLayer.L3,),
        experiment_view="long_horizon",
    )

    assert report.collection_summary["continuous_round_count"] == 20.0
    assert report.metadata["formal_headline_eligible"] is False
    assert report.metadata["stability_evidence_eligible"] is True
    assert report.metadata["selected_layers"] == ["L3"]
    assert report.collection_summary["L3_memory_candidate_count"] > 0.0
    assert report.collection_summary["L3_memory_consumed_count"] > 0.0
    assert report.collection_summary["L3_memory_behavioral_effect_count"] > 0.0
    assert report.collection_summary["L3_memory_rejected_incompatible_count"] >= 2.0
    assert all(family.evidence_pack["l0_l3_delta"] == {} for family in report.family_reports)

    reports_by_family = {family.task_family: family for family in report.family_reports}
    for family_report in reports_by_family.values():
        assert len(family_report.layer_reports) == 1
        assert family_report.layer_reports[0].layer == BenchmarkLayer.L3
        assert family_report.layer_reports[0].quality_floor_breakdown[
            "quality_floor_pass_count"
        ] == 10.0
        round9 = family_report.layer_reports[0].cases[8]
        assert round9.metrics["memory_candidate_count"] >= 1.0
        assert round9.metrics["memory_rejected_incompatible_count"] >= 1.0
        assert round9.metrics["memory_consumed_count"] >= 0.0
        fixture_audit = round9.audit_summary["fairness_contract"][
            "pre_run_fixture_audits"
        ][0]
        assert fixture_audit["source_replay_ready"] is True
        assert fixture_audit["unexpected_changes"] == []
        assert fixture_audit["eligible_for_role_input"] is False
        assert Path(fixture_audit["audit_path"]).is_file()
        fixture_memory_id = fixture_audit["source_memory_id"]
        memory_audit = round9.audit_summary["memory_consumption"]
        assert fixture_memory_id in memory_audit["candidate_memory_ids"]
        fixture_decision = next(
            decision
            for decision in memory_audit["compatibility_decisions"]
            if decision["memory_id"] == fixture_memory_id
        )
        assert fixture_decision["verdict"] == "incompatible"
        assert fixture_decision["policy_approved"] is False
        assert fixture_memory_id not in {
            record["memory_id"]
            for record in memory_audit["records"]
        }
        for relpath in round9.audit_summary["rendered_llm_requests"][
            "role_relpaths"
        ].values():
            rendered_request = (Path(round9.workspace_root) / relpath).read_text(
                encoding="utf-8"
            )
            assert fixture_memory_id not in rendered_request

    financial = reports_by_family["formal_financial_reports_v1"].layer_reports[0]
    operating = reports_by_family["formal_operating_metrics_v1"].layer_reports[0]
    financial_r8 = json.loads(Path(financial.cases[7].output_artifact_path).read_text(encoding="utf-8"))
    operating_r8 = json.loads(Path(operating.cases[7].output_artifact_path).read_text(encoding="utf-8"))
    financial_r10 = json.loads(Path(financial.cases[9].output_artifact_path).read_text(encoding="utf-8"))
    assert financial_r8["revenue_value"] == "72"
    assert operating_r8["mean_windspeed"] == "7.500"
    assert financial_r10["consumed_artifact_refs"]


def test_continuous_runner_executes_replay_collection(tmp_path: Path) -> None:
    csv_replay_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_correlation_replay")
    )
    long_doc_replay_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_metric_replay")
    )
    report = run_continuous_benchmark_collection(
        families=(csv_replay_family, long_doc_replay_family),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-replay-collection",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
        collection_scope="formal_replay_task_families",
    )

    assert report.metadata["continuous_execution"] is True
    assert report.metadata["collection_scope"] == "formal_replay_task_families"
    assert report.collection_summary["family_count"] == 2.0
    assert report.collection_summary["continuous_round_count"] == 20.0
    assert report.collection_summary["replay_headline_eligible_family_count"] == 2.0
    assert report.collection_summary["history_target_round_count"] == 0.0
    assert report.collection_summary["history_observed_reuse_round_count"] == 0.0
    assert report.collection_summary["history_missing_target_round_count"] == 0.0
    assert report.collection_summary["history_additional_reuse_round_count"] == 0.0
    assert report.collection_summary["validated_replay_count"] >= 13.0
    assert (
        report.collection_summary["validated_downgraded_reuse_count"]
        == report.collection_summary["validated_replay_count"]
    )
    assert report.collection_summary["exact_replay_count"] >= 3.0
    assert (
        report.collection_summary["answer_restoration_replay_count"]
        == report.collection_summary["exact_replay_count"]
    )
    assert report.collection_summary["replay_target_round_count"] == 16.0
    assert report.collection_summary["replay_observed_round_count"] == 16.0
    assert report.collection_summary["replay_missing_target_round_count"] == 0.0
    assert report.collection_summary["replay_unexpected_round_count"] == 0.0
    assert report.evidence_pack["schema_version"] == "statebus.continuous_collection_evidence_pack.v1"
    assert report.evidence_pack["headline_scope"] == "replay_admissible"
    assert len(report.evidence_pack["family_evidence"]) == 2
    assert all(family["replay_headline_eligible"] is True for family in report.evidence_pack["family_evidence"])
    assert report.evidence_pack["runtime_overhead_summary"]["top_driver_stage_buckets"]
    assert report.evidence_pack["runtime_overhead_summary"]["top_persist_and_reload_buckets"]
    assert (
        report.evidence_pack["runtime_overhead_summary"]["persist_and_reload_breakdown_totals_ms"][
            "persist_session_ledger_reload_stage_ms"
        ]
        >= 0.0
    )
    assert report.evidence_pack["runtime_overhead_summary"]["write_count_totals"]["role_prompt_slice_artifact_count"] >= 80.0
    assert Path(report.markdown_report_path).exists()
    assert report.eligible_for_quality_headline is True
    assert report.eligible_for_replay_headline is True
    assert report.eligible_for_headline is True
    assert report.admissibility_summary["csv_correlation_replay_v1"]["eligible_for_replay_headline"] is True
    assert report.admissibility_summary["csv_correlation_replay_v1"]["replay_gate_reason"] == ""
    assert report.admissibility_summary["csv_correlation_replay_v1"]["L3_validated_replay_count"] >= 8.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["L3_validated_downgraded_reuse_count"] >= 8.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["L3_exact_replay_count"] == 0.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["L3_answer_restoration_replay_count"] == 0.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["history_target_round_count"] == 0.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["replay_target_round_count"] == 8.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["replay_observed_round_count"] == 8.0
    assert report.admissibility_summary["csv_correlation_replay_v1"]["replay_admissibility_audit"]["missing_target_rounds"] == []
    assert report.admissibility_summary["long_doc_metric_replay_v1"]["eligible_for_replay_headline"] is True
    assert report.admissibility_summary["long_doc_metric_replay_v1"]["history_target_round_count"] == 0.0
    assert report.admissibility_summary["long_doc_metric_replay_v1"]["replay_target_round_count"] == 8.0
    assert report.admissibility_summary["long_doc_metric_replay_v1"]["replay_observed_round_count"] == 8.0
    assert report.admissibility_summary["long_doc_metric_replay_v1"]["replay_admissibility_audit"]["unexpected_target_rounds"] == []
    assert {family_report.task_family for family_report in report.family_reports} == {
        "csv_correlation_replay_v1",
        "long_doc_metric_replay_v1",
    }
