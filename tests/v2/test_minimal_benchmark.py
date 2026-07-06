from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from runtime.llm import LLMResult, LLMUsage
from v2.benchmark import (
    MinimalBenchmarkSample,
    load_sample_family,
    run_minimal_benchmark,
    run_minimal_benchmark_family,
    run_minimal_benchmark_suite,
)


def test_minimal_benchmark_sample_loads_from_fixture() -> None:
    sample = MinimalBenchmarkSample.from_path(
        Path("v2/benchmark/samples/minimal_financial_report_sample.json")
    )
    assert sample.task_id == "benchmark-sample-1"
    assert "ACME revenue" in sample.request_text
    assert sample.canonical_task_spec is not None
    assert sample.canonical_task_spec.intent_op == "compare_metric"
    assert sample.canonical_task_spec.arguments["quarter"] == "2026Q1"
    assert sample.expected_facts == {
        "revenue_value": "120",
        "selected_doc_hashes": ["sha256:doc-acme-2026q1"],
    }


def test_minimal_benchmark_runs_formal_sample(tmp_path: Path) -> None:
    smoke, report = run_minimal_benchmark(
        sample=MinimalBenchmarkSample.from_path(
            Path("v2/benchmark/samples/minimal_financial_report_sample.json")
        ),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert smoke.compiler_status == "compiled"
    assert report.layer.value == "L3"
    assert report.quality_floor.quality_floor_pass is True
    assert report.eligible_for_headline is True
    assert report.metrics["workflow_step_count"] == 4.0
    assert report.metrics["attempt_count"] == 1.0
    assert smoke.replay_class == "disallowed"
    assert Path(smoke.replay_audit_path).exists()
    assert Path(smoke.hydration_audit_path).exists()
    assert Path(smoke.hydration_debug_audit_path).exists()
    assert Path(smoke.artifact_audit_path).exists()
    assert smoke.audit_summary["hydration"]["counting_scope"] == "hydrated_external_evidence_only"


def test_minimal_benchmark_sample_family_loads_multiple_samples() -> None:
    family = load_sample_family(Path("v2/benchmark/samples/minimal_family"))
    assert len(family) == 2
    assert family[0].task_id == "benchmark-sample-1"
    assert family[1].task_id == "benchmark-sample-2"


def test_formal_financial_family_loads_three_samples() -> None:
    family = load_sample_family(Path("v2/benchmark/samples/formal_financial_family"))
    assert len(family) == 8
    task_ids = {s.task_id for s in family}
    assert "benchmark-sample-1" in task_ids
    assert "benchmark-sample-3" in task_ids
    assert "benchmark-sample-5" in task_ids  # BETA 2026Q1
    assert "benchmark-sample-8" in task_ids  # BETA gross_margin
    assert family[0].canonical_task_spec is not None
    assert family[0].canonical_task_spec.required_tools == ("table_retriever", "semantic_retriever")


def test_minimal_benchmark_family_runs_and_persists_report(tmp_path: Path) -> None:
    family_samples = load_sample_family(Path("v2/benchmark/samples/minimal_family"))
    family_report = run_minimal_benchmark_family(
        samples=family_samples,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="family-suite-test",
    )
    assert len(family_report.cases) == 2
    assert family_report.eligible_for_headline is True
    assert family_report.aggregated_metrics["case_count"] == 2.0
    assert family_report.aggregated_metrics["quality_floor_pass_count"] == 2.0
    assert family_report.telemetry_summary["artifact_count"] == 2.0
    assert family_report.replay_class_distribution["disallowed"] == 2.0
    assert family_report.quality_floor_breakdown["fact_coverage_passed_count"] == 2.0
    assert family_report.cases[0].session_state == "GC_DONE"
    assert family_report.cases[0].output_artifact_hash != family_report.cases[1].output_artifact_hash
    assert family_report.cases[0].metrics["workflow_step_count"] == 4.0
    assert family_report.cases[0].metrics["attempt_count"] == 1.0
    assert family_report.cases[0].metrics["memory_candidate_count"] == 0.0
    assert family_report.cases[0].metrics["memory_rerank_selected_count"] == 0.0
    assert family_report.cases[0].metrics["codeact_plan_stage_count"] > 0.0
    assert family_report.metadata["benchmark_tier"] == "formal"
    assert set(family_report.cases[0].audit_paths) == {"replay", "hydration", "hydration_debug", "artifact"}
    assert family_report.cases[0].audit_summary["artifact"]["output_artifact_hash"] == family_report.cases[0].output_artifact_hash

    report_path = Path(family_report.report_path)
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["suite_id"] == "family-suite-test"
    assert payload["aggregated_metrics"]["case_count"] == 2.0
    assert payload["telemetry_summary"]["artifact_count"] == 2.0
    assert payload["replay_class_distribution"]["disallowed"] == 2.0
    assert len(payload["cases"]) == 2
    assert set(payload["cases"][0]["audit_paths"]) == {"replay", "hydration", "hydration_debug", "artifact"}


def test_minimal_benchmark_suite_writes_l0_l3_scaffold_reports(tmp_path: Path) -> None:
    suite_report = run_minimal_benchmark_suite(
        samples=load_sample_family(Path("v2/benchmark/samples/formal_financial_family")),
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="suite-sample-test",
    )
    assert len(suite_report.layer_reports) == 4
    assert suite_report.layer_reports[0].layer.value == "L0"
    assert suite_report.layer_reports[0].missing_reason == ""
    assert suite_report.layer_reports[0].eligible_for_headline is True
    assert suite_report.layer_reports[0].profile.structured_control_enabled is False
    assert suite_report.layer_reports[0].cases[0].metrics["handoff_mode_text_collaboration"] == 1.0
    assert suite_report.layer_reports[0].cases[0].metrics["handoff_mode_structured_collaboration"] == 0.0
    assert suite_report.family_case_count == 8
    assert suite_report.layer_reports[1].profile.structured_control_enabled is True
    assert suite_report.layer_reports[2].profile.semantic_pruning_enabled is True
    assert suite_report.layer_reports[3].eligible_for_headline is True
    assert suite_report.layer_reports[0].cases[0].replay_class == "disallowed"
    assert suite_report.layer_reports[3].cases[0].replay_class == "disallowed"
    assert suite_report.waterfall_metrics["L2_semantic_state_transfer_count"] == 8.0
    assert suite_report.waterfall_metrics["L3_artifact_reuse_count"] == 0.0
    assert suite_report.comparison_summary["reuse_gain_delta_l2_to_l3"] >= 0.0
    assert suite_report.comparison_summary["artifact_reuse_delta_l2_to_l3"] == 0.0
    assert suite_report.comparison_summary["codeact_action_delta_l0_to_l3"] == 0.0
    assert suite_report.layer_reports[3].cases[0].metrics["completed_workflow_step_count"] == 4.0
    assert suite_report.layer_reports[3].cases[0].metrics["attempt_count"] == 1.0
    assert suite_report.layer_reports[3].cases[0].metrics["memory_candidate_count"] == 0.0
    assert suite_report.layer_reports[3].cases[0].comparison_tags
    assert suite_report.metadata["benchmark_tier"] == "formal"
    assert suite_report.metadata["comparison_contract"] == "same_mainline_internal_attribution_ladder"
    assert suite_report.metadata["ladder_claim_scope"] == "internal_attribution_only_not_external_superiority"

    payload = json.loads(Path(suite_report.report_path).read_text(encoding="utf-8"))
    assert payload["suite_id"] == "suite-sample-test"
    assert "comparison_summary" in payload
    assert payload["family_case_count"] == 8
    assert len(payload["layers"]) == 4
    assert payload["metadata"]["comparison_contract"] == "same_mainline_internal_attribution_ladder"


def test_minimal_benchmark_suite_reports_actual_state_pool_backend_after_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("v2.state.store._memfd_create_safe", lambda _name: None)
    suite_report = run_minimal_benchmark_suite(
        samples=load_sample_family(Path("v2/benchmark/samples/formal_financial_family"))[:1],
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="suite-state-pool-fallback-test",
        state_pool_mode="memfd",
    )
    assert suite_report.metadata["state_pool_mode_requested"] == "memfd"
    assert suite_report.metadata["state_pool_mode_used"] == "shared_memory"
    assert suite_report.metadata["memfd_transfer_count"] == 0.0
    assert suite_report.layer_reports[3].telemetry_summary["state_pool_shared_memory_mode_count"] == 1.0

    payload = json.loads(Path(suite_report.report_path).read_text(encoding="utf-8"))
    assert payload["state_pool_mode_requested"] == "memfd"
    assert payload["state_pool_mode_used"] == "shared_memory"
    assert payload["memfd_transfer_count"] == 0.0


def test_minimal_benchmark_family_api_mode_accepts_compact_role_alias_responses(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "planner":
                return LLMResult(
                    text=json.dumps({"retrieval_objective": {"query_text": "ACME 2026Q1 revenue"}, "steps": []}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=5, total_tokens=17),
                )
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "r": "compare_metric",
                            "t": "table_retriever",
                            "d": ["sha256:doc-acme-2026q1"],
                            "selection_reason": "compact retriever alias response",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                )
            if purpose == "executor":
                return LLMResult(
                    text=json.dumps(
                        {
                            "selected_candidate": {
                                "candidate_key": "compare_metric::table_retriever",
                            },
                            "a": "execute_validated_tool",
                            "selection_reason": "compact executor alias response",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                )
            if purpose == "summarizer":
                return LLMResult(
                    text=json.dumps(
                        {
                            "summary": "ACME revenue for 2026Q1 is 120.",
                            "reusable_steps": ["retrieve", "execute"],
                            "confidence": 0.95,
                            "tags": ["revenue"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=11, completion_tokens=6, total_tokens=17),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    monkeypatch.setattr("v2.runtime.smoke.build_llm_client", lambda config=None: StubLLMClient())
    monkeypatch.setattr(
        "v2.runtime.smoke.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, missing_reasons=(), canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    family_report = run_minimal_benchmark_family(
        samples=load_sample_family(Path("v2/benchmark/samples/formal_financial_family"))[:1],
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="api-alias-family",
        role_path_mode="api",
        embedding_mode="deterministic",
    )

    assert len(family_report.cases) == 1
    assert family_report.aggregated_metrics["quality_floor_pass_count"] == 1.0
    assert family_report.cases[0].quality_floor.quality_floor_pass is True
    assert family_report.cases[0].metrics["llm_total_tokens"] > 0.0
    assert family_report.telemetry_summary["llm_total_tokens"] > 0.0


def test_minimal_benchmark_family_api_mode_accepts_string_candidate_alias(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "planner":
                return LLMResult(
                    text=json.dumps({"retrieval_objective": {"query_text": "ACME 2026Q1 revenue"}, "steps": []}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=5, total_tokens=17),
                )
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps({"candidate": "compare_metric::table_retriever"}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=9, completion_tokens=3, total_tokens=12),
                )
            if purpose == "executor":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "compare_metric",
                            "tool_name": "table_retriever",
                            "action_contract": "execute_validated_tool",
                            "reason": "validated",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                )
            if purpose == "summarizer":
                return LLMResult(
                    text=json.dumps(
                        {
                            "summary": "ACME revenue for 2026Q1 is 120.",
                            "reusable_steps": ["retrieve", "execute"],
                            "confidence": 0.95,
                            "tags": ["revenue"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=11, completion_tokens=6, total_tokens=17),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    monkeypatch.setattr("v2.runtime.smoke.build_llm_client", lambda config=None: StubLLMClient())
    monkeypatch.setattr(
        "v2.runtime.smoke.runtime_preflight",
        lambda **kwargs: SimpleNamespace(ok=True, missing_reasons=(), canonical_payload=lambda: {"ok": True, **kwargs}),
    )
    family_report = run_minimal_benchmark_family(
        samples=load_sample_family(Path("v2/benchmark/samples/formal_financial_family"))[:1],
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        suite_id="api-string-candidate-family",
        role_path_mode="api",
        embedding_mode="deterministic",
    )

    assert len(family_report.cases) == 1
    assert family_report.aggregated_metrics["quality_floor_pass_count"] == 1.0
    assert family_report.cases[0].quality_floor.quality_floor_pass is True
    assert family_report.cases[0].metrics["llm_total_tokens"] > 0.0
