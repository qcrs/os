from __future__ import annotations

import json
from pathlib import Path
import time

import pytest

from runtime.llm import LLMResult, LLMUsage, parse_tagged_json
from v2.benchmark import (
    compare_fixed_answer_with_external,
    load_fixed_answer_family,
    run_external_text_case,
    run_external_text_family,
    run_external_text_suite,
    run_fixed_answer_benchmark_family,
    run_fixed_answer_internal_carrier_compare_suite,
    run_fixed_answer_text_semantic_selection_family,
    run_fixed_answer_suite,
)
from v2.benchmark.models import BenchmarkLayer
from v2.runtime.role_path import RolePathRunner, RoleToolCandidate
from v2.runtime.driver import RuntimeDriverProfile


def test_external_text_normalizes_candidate_key_route_payload() -> None:
    from v2.benchmark.external_text_baseline import (
        _load_execution_context,
        _normalize_visible_candidate_payload,
    )

    sample = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))[2]
    context = _load_execution_context(sample)
    normalized = _normalize_visible_candidate_payload(
        {
            "route": "worker_queue_starvation::semantic_retriever",
            "tool_name": "semantic_retriever",
        },
        context.route_candidates,
    )

    assert normalized["route"] == "worker_queue_starvation"
    assert normalized["tool_name"] == "semantic_retriever"
    assert normalized["candidate_key"] == "worker_queue_starvation::semantic_retriever"


def test_fixed_answer_family_loads_samples() -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    assert len(family) == 3
    assert family[0].task_family == "fixed_answer_route_tool"
    assert family[0].canonical_task_spec.intent_op == "triage_route_tool"
    assert family[0].request_text == "sso callback issuer mismatch stale jwks session cookies"


def test_fixed_answer_family_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_benchmark_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer=BenchmarkLayer.L3,
    )
    assert len(report.cases) == 3
    assert report.aggregated_metrics["case_count"] == 3.0
    assert report.aggregated_metrics["quality_floor_pass_count"] == 3.0
    assert report.telemetry_summary["route_exact"] == 3.0
    assert report.telemetry_summary["tool_exact"] == 3.0
    assert report.telemetry_summary["exact_match"] == 3.0
    assert report.telemetry_summary["llm_total_tokens"] == 0.0
    assert report.metadata["benchmark_tier"] == "dev"
    assert report.metadata["synthetic_replay_seed_enabled"] is False
    assert Path(report.report_path).exists()
    first_case = report.cases[0]
    assert set(first_case.audit_paths) == {"replay", "hydration", "hydration_debug", "artifact"}
    assert first_case.audit_summary["replay"]["replay_class"] == first_case.replay_class
    assert first_case.audit_summary["hydration"]["counting_scope"] == "hydrated_external_evidence_only"
    assert first_case.audit_summary["artifact"]["output_artifact_hash"] == first_case.output_artifact_hash
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    case_payload = payload["cases"][0]
    assert set(case_payload["audit_paths"]) == {"replay", "hydration", "hydration_debug", "artifact"}
    assert case_payload["audit_summary"]["replay"]["replay_class"] == first_case.replay_class


def test_fixed_answer_family_uses_core_roundtrip_persistence_verification(tmp_path: Path, monkeypatch) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    captured_levels: list[str] = []

    from v2.benchmark import fixed_answer_runner as runner

    original_run_smoke = runner.run_smoke

    def recording_run_smoke(*args, **kwargs):
        override = kwargs.get("driver_profile_override")
        assert isinstance(override, RuntimeDriverProfile)
        captured_levels.append(override.persistence_verification_level)
        return original_run_smoke(*args, **kwargs)

    monkeypatch.setattr(runner, "run_smoke", recording_run_smoke)
    run_fixed_answer_benchmark_family(
        samples=family[:1],
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer=BenchmarkLayer.L3,
        statebus_mode="cold-start",
    )

    assert captured_levels == ["core_roundtrip"]


def test_fixed_answer_family_runs_in_cold_start_mode(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_benchmark_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer=BenchmarkLayer.L3,
        statebus_mode="cold-start",
    )

    assert len(report.cases) == 3
    assert report.aggregated_metrics["quality_floor_pass_count"] == 3.0
    assert report.replay_class_distribution["disallowed"] == 3.0
    assert report.telemetry_summary["artifact_reuse_count"] == 0.0
    assert report.telemetry_summary["reuse_gain"] == 0.0
    assert report.telemetry_summary["skipped_step_count"] == 0.0
    assert report.telemetry_summary["codeact_plan_stage_count"] > 0.0
    assert report.telemetry_summary["codeact_plan_action_count"] > 0.0
    assert all(case.replay_class == "disallowed" for case in report.cases)
    assert report.profile.description.endswith("(cold-start)")
    assert report.metadata["synthetic_replay_seed_enabled"] is False
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["profile"]["description"].endswith("(cold-start)")


def test_fixed_answer_suite_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_suite(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert report.family_case_count == 3
    assert report.metadata["statebus_mode"] == "cold_start"
    assert len(report.layer_reports) == 4
    assert [layer.layer.value for layer in report.layer_reports] == ["L0", "L1", "L2", "L3"]
    assert report.layer_reports[0].metadata["handoff_mode"] == "text_collaboration"
    assert report.layer_reports[1].metadata["handoff_mode"] == "structured_collaboration"
    assert report.layer_reports[0].metadata["comparison_contract"] == "same_mainline_internal_attribution_ladder"
    assert report.layer_reports[0].metadata["ladder_claim_scope"] == "internal_attribution_only_not_external_superiority"
    assert report.layer_reports[2].profile.semantic_pruning_enabled is True
    assert report.layer_reports[3].profile.replay_enabled is True
    assert report.comparison_summary["handoff_bytes_delta_l0_to_l1"] >= 0.0
    assert report.comparison_summary["prompt_visible_bytes_delta_l0_to_l1"] >= 0.0
    assert report.comparison_summary["prompt_scaffolding_bytes_delta_l0_to_l1"] >= 0.0
    assert report.comparison_summary["raw_evidence_bytes_delta_l1_to_l2"] >= 0.0
    assert report.metadata["comparison_contract"] == "same_mainline_internal_attribution_ladder"
    assert report.metadata["ladder_claim_scope"] == "internal_attribution_only_not_external_superiority"
    assert Path(report.report_path).exists()
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["family_case_count"] == 3


def test_fixed_answer_text_semantic_selection_lane_does_not_transfer_state_ref(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_text_semantic_selection_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert len(report.cases) == 3
    assert report.profile.structured_control_enabled is False
    assert report.profile.semantic_pruning_enabled is True
    assert report.metadata["handoff_mode"] == "text_collaboration"
    assert report.metadata["baseline_kind"] == "internal_text_same_semantic_selection"
    assert report.metadata["uses_semantic_state_ref"] is False
    assert report.telemetry_summary["raw_evidence_bytes_seen_by_llm"] > 0.0
    assert report.telemetry_summary["semantic_state_transfer_count"] == 0.0
    assert report.telemetry_summary["handoff_mode_text_collaboration"] == 3.0
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["semantic_state_transfer_enabled"] is False


def test_fixed_answer_internal_carrier_compare_suite_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_internal_carrier_compare_suite(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
    )
    assert report.benchmark_tier == "dev"
    assert len(report.mode_reports) == 1
    mode = report.mode_reports[0]
    assert mode.comparison_valid is True
    assert mode.invalid_reason == ""
    assert mode.fairness_manifest["comparison_contract"] == "same_mainline_internal_text_vs_structured_carrier"
    assert mode.fairness_manifest["text_handoff_mode"] == "text_collaboration"
    assert mode.fairness_manifest["structured_handoff_mode"] == "structured_collaboration"
    assert mode.debug_metrics["case_count"] == 3.0
    assert "prompt_scaffolding_bytes_total_delta" in mode.debug_metrics
    assert "prompt_visible_total_bytes_delta" in mode.debug_metrics
    assert Path(report.report_path).exists()
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["mode_reports"][0]["comparison_valid"] is True


def test_fixed_answer_replay_ready_defaults_to_history_backed_replay(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_benchmark_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer=BenchmarkLayer.L3,
        statebus_mode="replay-ready",
    )

    assert report.metadata["statebus_mode"] == "replay_ready"
    assert report.metadata["synthetic_replay_seed_enabled"] is False
    assert report.metadata["history_backed_replay_enabled"] is True
    assert report.metadata["replay_history_source"] == "history_bootstrap"
    assert report.replay_class_distribution["exact_replay"] == 3.0
    assert report.telemetry_summary["artifact_reuse_count"] == 3.0
    assert report.telemetry_summary["retriever_call_count"] == 0.0
    assert report.telemetry_summary["executor_call_count"] == 0.0
    assert report.telemetry_summary["summarizer_call_count"] == 0.0


def test_fixed_answer_cold_start_rejects_synthetic_seed(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    with pytest.raises(ValueError, match="synthetic replay seed is dev-only and requires replay_ready statebus_mode"):
        run_fixed_answer_benchmark_family(
            samples=family,
            workspace_root=tmp_path / "workspaces",
            runtime_root=tmp_path / "runtime",
            socket_path=tmp_path / "control.sock",
            layer=BenchmarkLayer.L3,
            statebus_mode="cold-start",
            seed_replay_memory=True,
        )


def test_fixed_answer_replay_ready_dev_probe_requires_explicit_opt_in_and_still_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_benchmark_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        layer=BenchmarkLayer.L3,
        statebus_mode="replay-ready",
        seed_replay_memory=True,
    )

    assert report.metadata["statebus_mode"] == "replay_ready"
    assert report.metadata["synthetic_replay_seed_enabled"] is True
    assert report.metadata["history_backed_replay_enabled"] is False
    assert report.metadata["replay_history_source"] == "synthetic_seed"
    assert report.replay_class_distribution["exact_replay"] == 3.0
    assert report.telemetry_summary["artifact_reuse_count"] == 3.0


def test_fixed_answer_suite_keeps_history_backed_and_synthetic_reports_separate(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    history_report = run_fixed_answer_suite(
        samples=family,
        workspace_root=tmp_path / "workspaces-history",
        runtime_root=tmp_path / "runtime-history",
        socket_path=tmp_path / "history.sock",
        suite_id="statebus-v2-benchmark-statebus",
        statebus_mode="replay-ready",
        seed_replay_memory=False,
    )
    synthetic_report = run_fixed_answer_suite(
        samples=family,
        workspace_root=tmp_path / "workspaces-synthetic",
        runtime_root=tmp_path / "runtime-synthetic",
        socket_path=tmp_path / "synthetic.sock",
        suite_id="statebus-v2-benchmark-synthetic-seed-statebus",
        statebus_mode="replay-ready",
        seed_replay_memory=True,
    )

    assert history_report.suite_id == "statebus-v2-benchmark-statebus"
    assert synthetic_report.suite_id == "statebus-v2-benchmark-synthetic-seed-statebus"
    assert Path(history_report.report_path).name == "statebus-v2-benchmark-statebus.json"
    assert Path(synthetic_report.report_path).name == "statebus-v2-benchmark-synthetic-seed-statebus.json"
    assert Path(history_report.report_path).exists()
    assert Path(synthetic_report.report_path).exists()


def test_fixed_answer_family_api_mode_skips_when_api_not_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "llm-api-missing.yaml"
    config_path.write_text(
        """
mode: api
providers:
  default:
    kind: openai_compatible
    base_url: https://api.deepseek.com
    api_key_env: STATEBUS_TEST_MISSING_KEY
    timeout_s: 60
roles:
  planner:
    provider: default
    model: deepseek-v4-flash
  retriever:
    provider: default
    model: deepseek-v4-flash
  executor:
    provider: default
    model: deepseek-v4-flash
  summarizer:
    provider: default
    model: deepseek-v4-flash
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STATEBUS_LLM_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("STATEBUS_TEST_MISSING_KEY", raising=False)

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_fixed_answer_benchmark_family(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_mode="api",
    )

    assert report.missing_reason
    assert "STATEBUS_TEST_MISSING_KEY" in report.missing_reason
    assert len(report.cases) == 0
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["missing_reason"] == report.missing_reason


def test_external_text_case_runs(tmp_path: Path) -> None:
    sample = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))[0]
    result = run_external_text_case(sample=sample, runtime_root=tmp_path / "external")
    assert result.message_count == 4
    assert result.text_bytes > 0
    assert result.prompt_bytes > 0
    assert result.llm_call_count == 4
    assert result.end_to_end_ms >= result.llm_ms >= 0.0
    assert Path(result.output_path).exists()
    assert Path(result.report_path).exists()
    assert result.correctness_label == "exact_match"
    assert result.quality_floor.quality_floor.quality_floor_pass is True
    assert result.planner_usage.prompt_bytes > 0
    assert result.retriever_usage.prompt_bytes > 0
    assert result.executor_usage.prompt_bytes > 0
    assert result.summarizer_usage.prompt_bytes > 0


def test_external_text_family_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_external_text_family(samples=family, runtime_root=tmp_path / "external")
    assert len(report.cases) == 3
    assert Path(report.report_path).exists()
    assert report.telemetry_summary["message_count"] == 12.0
    assert report.telemetry_summary["llm_call_count"] == 12.0
    assert report.telemetry_summary["planner_call_count"] == 3.0
    assert report.telemetry_summary["retriever_call_count"] == 3.0
    assert report.telemetry_summary["executor_call_count"] == 3.0
    assert report.telemetry_summary["summarizer_call_count"] == 3.0
    assert report.telemetry_summary["prompt_bytes"] > 0.0
    assert report.telemetry_summary["end_to_end_ms"] >= report.telemetry_summary["llm_ms"] >= 0.0
    assert report.metadata["baseline_kind"] == "external_pure_text_four_role"
    assert report.metadata["formal_comparator_eligible"] is True
    assert report.metadata["external_comparator_claim_scope"] == "dev_fixed_answer_only"
    assert (
        report.metadata["claim_restriction"]
        == "dev_fixed_answer_external_fairness_only_not_formal_financial_superiority"
    )


def test_external_text_case_end_to_end_ms_includes_prep_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sample = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))[0]
    from v2.benchmark import external_text_baseline as baseline

    original_loader = baseline._load_execution_context

    def delayed_loader(sample_arg):
        time.sleep(0.01)
        return original_loader(sample_arg)

    monkeypatch.setattr(baseline, "_load_execution_context", delayed_loader)
    result = run_external_text_case(sample=sample, runtime_root=tmp_path / "external")
    assert result.end_to_end_ms > result.llm_ms


def test_external_text_suite_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = run_external_text_suite(samples=family, runtime_root=tmp_path / "external-suite")
    assert report.family_case_count == 3
    assert Path(report.report_path).exists()


def test_fixed_answer_external_comparator_suite_runs(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
    )

    assert len(report.mode_reports) == 1
    mode_report = report.mode_reports[0]
    assert mode_report.role_path_mode == "deterministic"
    assert mode_report.missing_reason == ""
    assert mode_report.comparison_valid is True
    assert mode_report.invalid_reason == ""
    assert "llm_total_tokens_delta" in mode_report.headline_metrics
    assert "prompt_bytes_delta" in mode_report.headline_metrics
    assert "exact_match_delta" in mode_report.debug_metrics
    assert "end_to_end_ms_delta" in mode_report.debug_metrics
    assert "llm_ms_delta" in mode_report.debug_metrics
    assert "prompt_bytes_delta" in mode_report.debug_metrics
    assert "llm_call_count_delta" in mode_report.debug_metrics
    assert mode_report.fairness_manifest["external_formal_eligible"] is True
    assert mode_report.fairness_manifest["pass_hard_gate"] is True
    assert Path(mode_report.report_path).exists()
    assert Path(mode_report.markdown_report_path).exists()
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["formal_headline_eligible"] is False
    assert payload["metadata"]["formal_superiority_claim_allowed"] is False
    assert payload["metadata"]["fixed_answer_external_comparison_valid"] is True
    assert (
        payload["metadata"]["claim_restriction"]
        == "dev_fixed_answer_external_fairness_gate_passed_not_formal_superiority"
    )
    assert payload["mode_reports"][0]["role_path_mode"] == "deterministic"
    assert payload["mode_reports"][0]["comparison_valid"] is True
    assert "deterministic_debug_exact_match_delta" in payload["comparison_summary"]


def test_fixed_answer_external_comparator_suite_runs_in_cold_start_mode(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        statebus_mode="cold-start",
    )

    assert len(report.mode_reports) == 1
    mode_report = report.mode_reports[0]
    assert mode_report.missing_reason == ""
    assert mode_report.statebus_report.replay_class_distribution["disallowed"] == 3.0
    assert mode_report.statebus_report.telemetry_summary["artifact_reuse_count"] == 0.0
    assert mode_report.statebus_report.telemetry_summary["codeact_plan_stage_count"] > 0.0
    assert mode_report.comparison_valid is True
    assert mode_report.invalid_reason == ""
    assert mode_report.debug_metrics["statebus_exact_match_count"] == 3.0
    assert mode_report.debug_metrics["exact_match_delta"] >= 0.0
    assert mode_report.debug_metrics["llm_call_count_delta"] == 0.0
    payload = json.loads(Path(mode_report.report_path).read_text(encoding="utf-8"))
    assert payload["statebus_report"]["profile"]["description"].endswith("(cold-start)")


def test_fixed_answer_external_comparator_replay_ready_is_invalid_due_to_history_policy(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        statebus_mode="replay-ready",
    )

    mode_report = report.mode_reports[0]
    assert mode_report.comparison_valid is False
    assert mode_report.invalid_reason == "fairness_gate_failed"
    assert mode_report.fairness_manifest["same_history_policy"] is False
    assert mode_report.headline_metrics == {}


def test_role_path_normalizes_invalid_api_route_to_best_visible_candidate() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "wrong_freeform_label",
                            "tool_name": "semantic_retriever",
                            "supporting_doc_ids": ["doc-x"],
                            "reason": "freeform guess",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
    )
    assert decision.route == sample.expected_route
    assert decision.tool_name == sample.expected_tool_name
    assert decision.candidate_rank == 3
    assert decision.total_tokens == 18


def test_role_path_strict_selection_fails_closed_for_invalid_route_choice() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "wrong_freeform_label",
                            "tool_name": "semantic_retriever",
                            "supporting_doc_ids": ["doc-x"],
                            "reason": "freeform guess",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import RoleSelectionError, financial_tool_candidates

    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=StubLLMClient())
    with pytest.raises(RoleSelectionError):
        runner.choose_retrieval_candidate(
            query_text=retrieval.query_text,
            retrieved_doc_ids=retrieval.selected_doc_hashes,
            visible_candidates=candidates,
            allow_assisted_correction=False,
        )


def test_role_path_accepts_compact_api_retriever_alias_keys() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "r": "auth_session_drift",
                            "t": "semantic_retriever",
                            "d": ["doc-x"],
                            "selection_reason": "compact alias response",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )
    assert decision.route == sample.expected_route
    assert decision.tool_name == sample.expected_tool_name
    assert decision.supporting_doc_ids == ("doc-x",)
    assert decision.reason == "compact alias response"


def test_role_path_accepts_string_candidate_key_alias() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "candidate": "auth_session_drift::semantic_retriever",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=10, completion_tokens=4, total_tokens=14),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )
    assert decision.route == sample.expected_route
    assert decision.tool_name == sample.expected_tool_name
    assert decision.candidate_rank > 0


def test_role_path_accepts_unique_route_when_tool_name_echoes_route() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "detect_outliers",
                            "tool_name": "detect_outliers",
                            "supporting_doc_ids": ["sha256:csv-disease_estimates"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="aggregate_and_extreme", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="correlate_columns", tool_name="table_retriever", helper_rank=2),
        RoleToolCandidate(
            route="detect_outliers",
            tool_name="table_retriever",
            helper_rank=3,
            supporting_doc_ids=("sha256:csv-disease_estimates",),
        ),
        RoleToolCandidate(route="groupby_aggregate", tool_name="table_retriever", helper_rank=4),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text="disease_estimates detect_outliers",
        retrieved_doc_ids=("sha256:csv-disease_estimates",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )

    assert decision.route == "detect_outliers"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 3


def test_role_path_accepts_candidate_key_echoed_in_tool_name_slot() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "aggregate_and_extreme",
                            "tool_name": "aggregate_and_extreme::table_retriever",
                            "supporting_doc_ids": ["sha256:csv-disease_estimates"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="aggregate_and_extreme", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="correlate_columns", tool_name="table_retriever", helper_rank=2),
        RoleToolCandidate(route="detect_outliers", tool_name="table_retriever", helper_rank=3),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text="disease_estimates aggregate_and_extreme",
        retrieved_doc_ids=("sha256:csv-disease_estimates",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )

    assert decision.route == "aggregate_and_extreme"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 1


def test_role_path_accepts_executor_candidate_key_and_compact_action_alias() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "executor":
                return LLMResult(
                    text=json.dumps(
                        {
                            "selected_candidate": {
                                "candidate_key": "auth_session_drift::semantic_retriever",
                            },
                            "a": "execute_validated_tool",
                            "selection_reason": "candidate-key response",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=13, completion_tokens=5, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.validate_execution_choice(
        route=sample.expected_route,
        tool_name=sample.expected_tool_name,
        visible_candidates=candidates,
        action_contract="execute_validated_tool",
        allow_assisted_correction=False,
    )
    assert decision.route == sample.expected_route
    assert decision.tool_name == sample.expected_tool_name
    assert decision.action_contract == "execute_validated_tool"
    assert decision.reason == "candidate-key response"


def test_role_path_structured_prompts_use_compact_payloads() -> None:
    captured_messages: list[tuple[str, str]] = []

    class RecordingLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del temperature
            captured_messages.append((purpose, messages[-1].content))
            if purpose == "planner":
                return LLMResult(
                    text=json.dumps({"retrieval_objective": {"query_text": "q"}, "steps": []}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps({"route": "compare_metric", "tool_name": "table_retriever"}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
            if purpose == "executor":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "compare_metric",
                            "tool_name": "table_retriever",
                            "action_contract": "execute_validated_tool",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
            if purpose == "summarizer":
                return LLMResult(
                    text=json.dumps(
                        {
                            "summary": "ok",
                            "reusable_steps": ["retrieve", "execute"],
                            "confidence": 0.9,
                            "tags": ["finance"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "recording"}

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    sample = family[0]
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import RolePromptSlice, financial_tool_candidates

    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=sample.canonical_task_spec)
    candidates = financial_tool_candidates(sample.canonical_task_spec, retrieval.candidate_pool)
    prompt_slice = RolePromptSlice(
        role="retriever",
        hydrated_text="evidence text",
        hydrated_bytes=len("evidence text".encode("utf-8")),
        item_count=1,
        table_text="table fact",
        table_bytes=len("table fact".encode("utf-8")),
        table_item_count=1,
    )
    runner = RolePathRunner(llm_client=RecordingLLMClient())
    runner.plan_workflow(
        task_id=sample.task_id,
        task_group=sample.task_family,
        task_theme=sample.task_family,
        goal="compare ACME revenue",
        query_text=retrieval.query_text,
        summary_hint=sample.summary_hint,
        visible_candidates=candidates,
        prompt_slice=prompt_slice,
        tags=sample.scenario_tags,
    )
    runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
        prompt_slice=prompt_slice,
    )
    runner.validate_execution_choice(
        route=sample.expected_route,
        tool_name=sample.expected_tool_name,
        visible_candidates=candidates,
        action_contract="execute_validated_tool",
        prompt_slice=prompt_slice,
    )
    runner.summarize(
        task_id=sample.task_id,
        task_theme=sample.task_family,
        summary_hint=sample.summary_hint,
        prompt_slice=prompt_slice,
        actions_text="did the thing",
        tags=sample.scenario_tags,
    )

    prompt_by_purpose = {purpose: content for purpose, content in captured_messages}
    planner_prompt = prompt_by_purpose["planner"]
    retriever_prompt = prompt_by_purpose["retriever"]
    executor_prompt = prompt_by_purpose["executor"]
    summarizer_prompt = prompt_by_purpose["summarizer"]

    assert "<sb-plan-v1>" in planner_prompt
    assert "<statebus-planner-input>" not in planner_prompt
    assert '"hydrated_slice"' not in planner_prompt
    assert "Visible route/tool candidates" not in planner_prompt
    assert "<statebus-planner-evidence>" not in planner_prompt
    planner_payload = parse_tagged_json(planner_prompt, "sb-plan-v1")
    assert planner_payload["e"] == "evidence text\ntable fact"

    assert '"tc"' in retriever_prompt
    assert '"q"' in retriever_prompt
    assert '"rd"' in retriever_prompt
    retriever_payload = parse_tagged_json(retriever_prompt, "sb-retriever-v1")
    assert retriever_payload["e"] == "evidence text\ntable fact"
    assert f"{sample.expected_route}::{sample.expected_tool_name}" in {
        item["k"] for item in retriever_payload["tc"]
    }
    assert "candidate_key" in retriever_prompt
    assert "Do not invent labels" in retriever_prompt
    assert '"hydrated_slice"' not in retriever_prompt
    assert "Hydrated Slice Summary" not in retriever_prompt
    assert '"s"' not in retriever_prompt
    assert "<sb-retriever-evidence>" not in retriever_prompt

    assert '"tc"' in executor_prompt
    assert '"r"' in executor_prompt
    assert '"t"' in executor_prompt
    assert '"a"' in executor_prompt
    executor_payload = parse_tagged_json(executor_prompt, "sb-executor-v1")
    assert executor_payload["e"] == "evidence text\ntable fact"
    assert f"{sample.expected_route}::{sample.expected_tool_name}" in {
        item["k"] for item in executor_payload["tc"]
    }
    assert "candidate_key" in executor_prompt
    assert "Do not invent labels" in executor_prompt
    assert '"hydrated_slice"' not in executor_prompt
    assert "Hydrated Slice Summary" not in executor_prompt
    assert '"s"' not in executor_prompt
    assert "<sb-executor-evidence>" not in executor_prompt

    assert "<sb-summary-v1>" in summarizer_prompt
    assert "<statebus-summary-input>" not in summarizer_prompt
    assert '"tf"' in summarizer_prompt
    assert '"h"' in summarizer_prompt
    assert '"r"' in summarizer_prompt
    summarizer_payload = parse_tagged_json(summarizer_prompt, "sb-summary-v1")
    assert summarizer_payload["e"] == "evidence text\ntable fact"
    assert summarizer_payload["a"] == "did the thing"
    assert '"hydrated_slice"' not in summarizer_prompt
    assert "Hydrated Slice Summary" not in summarizer_prompt
    assert "<statebus-summary-evidence>" not in summarizer_prompt
    assert "<statebus-summary-actions>" not in summarizer_prompt


def test_fixed_answer_external_comparator_suite_skips_api_when_not_configured(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "llm-api-missing.yaml"
    config_path.write_text(
        """
mode: api
providers:
  default:
    kind: openai_compatible
    base_url: https://api.deepseek.com
    api_key_env: STATEBUS_TEST_MISSING_KEY
    timeout_s: 60
roles:
  planner:
    provider: default
    model: deepseek-v4-flash
  retriever:
    provider: default
    model: deepseek-v4-flash
  executor:
    provider: default
    model: deepseek-v4-flash
  summarizer:
    provider: default
    model: deepseek-v4-flash
""".strip()
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STATEBUS_LLM_CONFIG_FILE", str(config_path))
    monkeypatch.delenv("STATEBUS_TEST_MISSING_KEY", raising=False)

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("api",),
    )

    assert len(report.mode_reports) == 1
    mode_report = report.mode_reports[0]
    assert "STATEBUS_TEST_MISSING_KEY" in mode_report.missing_reason
    assert Path(mode_report.report_path).exists()
    assert Path(mode_report.markdown_report_path).exists()
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["mode_reports"][0]["missing_reason"] == mode_report.missing_reason
