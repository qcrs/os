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


def test_csv_profile_outlier_contract_uses_iqr_for_gold_values() -> None:
    manifest_path = Path("v2/benchmark/samples/continuous_task_families/csv_table_profile/manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rounds_by_number = {round_payload["round"]: round_payload for round_payload in manifest["rounds"]}

    assert rounds_by_number[4]["canonical_task_spec"]["arguments"]["method"] == "iqr"
    assert "IQR" in rounds_by_number[4]["request_text"]
    assert "strategy:iqr_outlier" in rounds_by_number[4]["reuse_contract"]["produces"]
    assert rounds_by_number[8]["canonical_task_spec"]["arguments"]["method"] == "iqr"
    assert "strategy:iqr_outlier" in rounds_by_number[8]["reuse_contract"]["consumes"]


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
        assert "long_doc_metric_replay_v1" in str(exc)
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
    assert l3_report.quality_floor_breakdown["quality_floor_pass_count"] == 10.0
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
    )

    assert report.family_case_count == 10
    assert report.metadata["continuous_execution"] is True
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
    assert l3_report.telemetry_summary["answer_restoration_replay_count"] == 0.0
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
    assert exact_case.metrics["answer_restoration_replay_count"] == 0.0
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
    csv_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/csv_table_profile")
    )
    long_doc_family = load_continuous_task_family(
        Path("v2/benchmark/samples/continuous_task_families/long_doc_table")
    )
    report = run_continuous_benchmark_collection(
        families=(csv_family, long_doc_family),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="continuous-collection",
        role_path_mode="deterministic",
        embedding_mode="deterministic",
    )

    assert report.metadata["continuous_execution"] is True
    assert report.metadata["collection_scope"] == "formal_continuous_task_families"
    assert report.collection_summary["family_count"] == 2.0
    assert report.collection_summary["continuous_round_count"] == 20.0
    assert report.collection_summary["L2_semantic_state_transfer_count"] > 0.0
    assert report.collection_summary["L3_artifact_reuse_count"] >= 14.0
    assert report.collection_summary["L3_reuse_gain"] == 0.0
    assert report.collection_summary["L3_history_reuse_gain"] > 0.0
    assert report.collection_summary["L3_history_step_reduction_count"] > 0.0
    assert report.collection_summary["history_backed_reuse_count"] >= 14.0
    assert report.collection_summary["quality_headline_eligible_family_count"] == 2.0
    assert report.collection_summary["replay_headline_eligible_family_count"] == 0.0
    assert report.collection_summary["history_backed_only_family_count"] == 2.0
    assert report.collection_summary["history_target_round_count"] == 10.0
    assert report.collection_summary["history_observed_reuse_round_count"] == 18.0
    assert report.collection_summary["history_missing_target_round_count"] == 0.0
    assert report.collection_summary["history_additional_reuse_round_count"] == 8.0
    assert report.collection_summary["validated_replay_count"] == 0.0
    assert report.collection_summary["exact_replay_count"] == 0.0
    assert report.collection_summary["replay_target_round_count"] == 0.0
    assert report.collection_summary["replay_observed_round_count"] == 0.0
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
    assert report.evidence_pack["runtime_overhead_summary"]["write_count_totals"]["role_prompt_slice_artifact_count"] >= 80.0
    assert Path(report.markdown_report_path).exists()
    assert report.eligible_for_quality_headline is True
    assert report.eligible_for_replay_headline is False
    assert report.eligible_for_headline is False
    assert report.admissibility_summary["csv_table_profile_v1"]["L3_history_artifact_reuse_count"] >= 7.0
    assert report.admissibility_summary["csv_table_profile_v1"]["L3_history_step_reduction_count"] > 0.0
    assert report.admissibility_summary["csv_table_profile_v1"]["history_target_round_count"] == 6.0
    assert report.admissibility_summary["csv_table_profile_v1"]["history_observed_reuse_round_count"] == 9.0
    assert report.admissibility_summary["csv_table_profile_v1"]["history_additional_reuse_round_count"] == 3.0
    assert report.admissibility_summary["csv_table_profile_v1"]["replay_target_round_count"] == 0.0
    assert report.admissibility_summary["csv_table_profile_v1"]["eligible_for_replay_headline"] is False
    assert report.admissibility_summary["csv_table_profile_v1"]["replay_gate_reason"] == ""
    assert report.admissibility_summary["csv_table_profile_v1"]["replay_admissibility_audit"]["audit_mode"] == "history_backed"
    assert report.admissibility_summary["csv_table_profile_v1"]["replay_admissibility_audit"]["unexpected_history_target_rounds"] == [2, 3, 6]
    assert report.admissibility_summary["long_doc_table_v1"]["L3_history_artifact_reuse_count"] >= 7.0
    assert report.admissibility_summary["long_doc_table_v1"]["L3_history_step_reduction_count"] > 0.0
    assert report.admissibility_summary["long_doc_table_v1"]["history_target_round_count"] == 4.0
    assert report.admissibility_summary["long_doc_table_v1"]["history_observed_reuse_round_count"] == 9.0
    assert report.admissibility_summary["long_doc_table_v1"]["history_additional_reuse_round_count"] == 5.0
    assert report.admissibility_summary["long_doc_table_v1"]["replay_target_round_count"] == 0.0
    assert report.admissibility_summary["long_doc_table_v1"]["eligible_for_replay_headline"] is False
    assert report.admissibility_summary["long_doc_table_v1"]["replay_gate_reason"] == ""
    assert report.admissibility_summary["long_doc_table_v1"]["replay_admissibility_audit"]["audit_mode"] == "history_backed"
    assert report.admissibility_summary["long_doc_table_v1"]["replay_admissibility_audit"]["unexpected_history_target_rounds"] == [2, 3, 4, 6, 7]
    assert {family_report.task_family for family_report in report.family_reports} == {
        "csv_table_profile_v1",
        "long_doc_table_v1",
    }


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
    assert report.collection_summary["answer_restoration_replay_count"] == 0.0
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
