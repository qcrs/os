from __future__ import annotations

import asyncio
import json
from pathlib import Path
import time
from types import SimpleNamespace

import httpx
from openai import APIConnectionError
import pytest

from runtime.llm import (
    ChatMessage,
    LLMConfig,
    LLMResult,
    LLMUsage,
    OpenAICompatibleLLMClient,
    ProviderConfig,
    RoleLLMConfig,
    parse_tagged_json,
)
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
from v2.runtime.role_path import RolePathRunner, RoleSelectionError, RoleToolCandidate
from v2.runtime.driver import RuntimeDriverProfile


def _api_connection_error() -> APIConnectionError:
    return APIConnectionError(
        message="temporary dns failure",
        request=httpx.Request("POST", "https://example.test/v1/chat/completions"),
    )


def test_openai_compatible_client_retries_transient_transport_error() -> None:
    class FakeCompletions:
        def __init__(self, attempts: list[str]) -> None:
            self.attempts = attempts

        async def create(self, **request):
            self.attempts.append(str(request["model"]))
            if len(self.attempts) == 1:
                raise _api_connection_error()
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(message=SimpleNamespace(content='{"status":"ok"}')),
                ],
                model="retry-model",
                usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            )

    class FakeProviderClient:
        def __init__(self, attempts: list[str], close_count: list[int]) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions(attempts))
            self.close_count = close_count

        async def close(self) -> None:
            self.close_count[0] += 1

    class RetryClient(OpenAICompatibleLLMClient):
        def __init__(self, config: LLMConfig) -> None:
            super().__init__(config)
            self.attempts: list[str] = []
            self.close_count = [0]

        def _build_provider_client(self, provider_name: str):
            assert provider_name == "default"
            return FakeProviderClient(self.attempts, self.close_count)

    config = LLMConfig(
        mode="api",
        providers={
            "default": ProviderConfig(
                api_key="test-key",
                request_max_attempts=2,
                retry_initial_delay_s=0.0,
            )
        },
        roles={"planner": RoleLLMConfig(model="retry-model")},
    )
    client = RetryClient(config)

    result = asyncio.run(
        client.complete([ChatMessage(role="user", content="return json")], purpose="planner")
    )

    assert result.text == '{"status":"ok"}'
    assert result.usage.total_tokens == 5
    assert client.attempts == ["retry-model", "retry-model"]
    assert client.close_count[0] == 2


def test_openai_compatible_client_stops_after_transport_retry_budget() -> None:
    class AlwaysFailCompletions:
        def __init__(self, attempts: list[int]) -> None:
            self.attempts = attempts

        async def create(self, **request):
            del request
            self.attempts.append(1)
            raise _api_connection_error()

    class FakeProviderClient:
        def __init__(self, attempts: list[int], close_count: list[int]) -> None:
            self.chat = SimpleNamespace(completions=AlwaysFailCompletions(attempts))
            self.close_count = close_count

        async def close(self) -> None:
            self.close_count[0] += 1

    class RetryClient(OpenAICompatibleLLMClient):
        def __init__(self, config: LLMConfig) -> None:
            super().__init__(config)
            self.attempts: list[int] = []
            self.close_count = [0]

        def _build_provider_client(self, provider_name: str):
            assert provider_name == "default"
            return FakeProviderClient(self.attempts, self.close_count)

    config = LLMConfig(
        mode="api",
        providers={
            "default": ProviderConfig(
                api_key="test-key",
                request_max_attempts=2,
                retry_initial_delay_s=0.0,
            )
        },
        roles={"planner": RoleLLMConfig(model="retry-model")},
    )
    client = RetryClient(config)

    with pytest.raises(APIConnectionError):
        asyncio.run(
            client.complete([ChatMessage(role="user", content="return json")], purpose="planner")
        )

    assert len(client.attempts) == 2
    assert client.close_count[0] == 2


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


def test_external_fairness_gate_rejects_raw_invisible_choice_after_normalization() -> None:
    from v2.benchmark.external_text_baseline import PublicRouteCandidate, _fairness_gate

    candidate = PublicRouteCandidate(
        route="visible_route",
        tool_name="semantic_retriever",
        support_terms=(),
        source_doc_hashes=(),
        support_doc_count=0,
    )
    gate = _fairness_gate(
        route_candidates=(candidate,),
        planner_payload={"route": "visible_route", "tool_name": "semantic_retriever"},
        planner_payload_raw={
            "route": "invisible_route",
            "tool_name": "unknown_tool",
            "note": "visible_route::semantic_retriever",
        },
        retriever_payload_raw={"route": "visible_route", "tool_name": "semantic_retriever"},
        executor_payload_raw={"route": "visible_route", "tool_name": "semantic_retriever"},
        summarizer_payload={"summary": "ok"},
        combined_surface="",
    )

    assert gate["pass_hard_gate"] is False
    assert gate["checks"]["planner_visible_choice_only"] is False
    assert "planner_visible_choice_only" in gate["failed_checks"]


def test_external_fairness_gate_accepts_visible_candidate_key_echoed_in_route_slot() -> None:
    from v2.benchmark.external_text_baseline import PublicRouteCandidate, _fairness_gate

    candidate = PublicRouteCandidate(
        route="compare_metric",
        tool_name="table_retriever",
        support_terms=(),
        source_doc_hashes=(),
        support_doc_count=0,
    )
    gate = _fairness_gate(
        route_candidates=(candidate,),
        planner_payload_raw={
            "route": "compare_metric::table_retriever",
            "tool_name": "table_retriever",
        },
        retriever_payload_raw={"route": "compare_metric", "tool_name": "table_retriever"},
        executor_payload_raw={"route": "compare_metric", "tool_name": "table_retriever"},
        summarizer_payload={"summary": "ok"},
        combined_surface="",
    )

    assert gate["checks"]["planner_visible_choice_only"] is True
    assert gate["pass_hard_gate"] is True


def test_external_fairness_gate_rejects_candidate_key_route_slot_with_conflicting_tool() -> None:
    from v2.benchmark.external_text_baseline import PublicRouteCandidate, _fairness_gate

    candidate = PublicRouteCandidate(
        route="compare_metric",
        tool_name="table_retriever",
        support_terms=(),
        source_doc_hashes=(),
        support_doc_count=0,
    )
    gate = _fairness_gate(
        route_candidates=(candidate,),
        planner_payload_raw={
            "route": "compare_metric::table_retriever",
            "tool_name": "semantic_retriever",
        },
        retriever_payload_raw={"route": "compare_metric", "tool_name": "table_retriever"},
        executor_payload_raw={"route": "compare_metric", "tool_name": "table_retriever"},
        summarizer_payload={"summary": "ok"},
        combined_surface="",
    )

    assert gate["checks"]["planner_visible_choice_only"] is False
    assert "planner_visible_choice_only" in gate["failed_checks"]


def test_external_fairness_gate_scans_raw_role_json_for_leakage_and_typed_state() -> None:
    from v2.benchmark.external_text_baseline import PublicRouteCandidate, _fairness_gate

    candidate = PublicRouteCandidate(
        route="visible_route",
        tool_name="semantic_retriever",
        support_terms=(),
        source_doc_hashes=(),
        support_doc_count=0,
    )
    gate = _fairness_gate(
        route_candidates=(candidate,),
        planner_payload_raw={
            "route": "visible_route",
            "tool_name": "semantic_retriever",
            "oracle_answer": "hidden truth",
        },
        retriever_payload_raw={"route": "visible_route", "tool_name": "semantic_retriever"},
        executor_payload_raw={
            "route": "visible_route",
            "tool_name": "semantic_retriever",
            "debug": "StateRef should not appear in external raw role JSON",
        },
        summarizer_payload={"summary": "ok"},
        combined_surface="",
    )

    assert gate["pass_hard_gate"] is False
    assert gate["checks"]["no_metadata_leakage"] is False
    assert gate["checks"]["no_typed_state_used"] is False
    assert "no_metadata_leakage" in gate["failed_checks"]
    assert "no_typed_state_used" in gate["failed_checks"]


def test_fixed_answer_family_loads_samples() -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    assert len(family) == 3
    assert family[0].task_family == "fixed_answer_route_tool"
    assert family[0].canonical_task_spec.intent_op == "triage_route_tool"
    assert family[0].request_text == "sso callback issuer mismatch stale jwks session cookies"


def test_fixed_answer_retrieval_scope_prefers_request_text_for_triage_query() -> None:
    from v2.retrieval import RetrieverFanoutPipeline

    sample = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))[0]
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=sample.canonical_task_spec)

    assert retrieval.query_text == sample.request_text


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
    assert result.correctness_label == "mismatch"
    assert result.revenue_value == ""
    assert result.revenue_fallback_used is True
    assert result.quality_floor.revenue_exact is False
    assert result.quality_floor.quality_floor.quality_floor_pass is False
    assert result.planner_usage.prompt_bytes > 0
    assert result.retriever_usage.prompt_bytes > 0
    assert result.executor_usage.prompt_bytes > 0
    assert result.summarizer_usage.prompt_bytes > 0
    assert result.fairness_gate["pass_hard_gate"] is True
    payload = json.loads(Path(result.report_path).read_text(encoding="utf-8"))
    assert payload["revenue_fallback_used"] == 1.0
    assert payload["fairness_gate"]["pass_hard_gate"] is True
    output_payload = json.loads(Path(result.output_path).read_text(encoding="utf-8"))
    assert output_payload["revenue_value"] == ""


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
    assert report.aggregated_metrics["external_fairness_gate_pass_count"] == 3.0
    assert report.aggregated_metrics["external_fairness_gate_failed_case_count"] == 0.0
    assert report.metadata["external_fairness_gate_pass"] is True
    assert report.metadata["baseline_kind"] == "external_pure_text_four_role"
    assert report.metadata["formal_comparator_eligible"] is True
    assert report.metadata["external_comparator_claim_scope"] == "dev_fixed_answer_only"
    assert (
        report.metadata["claim_restriction"]
        == "dev_fixed_answer_external_fairness_only_not_formal_financial_superiority"
    )


def _fake_external_result_for_fairness_gate(sample, runtime_root: Path, *, fairness_gate: dict[str, object]):
    from v2.benchmark.external_text_baseline import ExternalTextCaseResult, ExternalTextRoleUsage
    from v2.benchmark.models import QualityFloorResult
    from v2.benchmark.scoring import FixedAnswerScore

    case_root = runtime_root / sample.task_id
    case_root.mkdir(parents=True, exist_ok=True)
    output_path = case_root / "external_text_output.json"
    report_path = case_root / "external_text_report.json"
    output_path.write_text("{}\n", encoding="utf-8")
    report_path.write_text("{}\n", encoding="utf-8")
    quality_floor = QualityFloorResult(
        quality_floor_pass=True,
        deterministic_checks_passed=True,
        fact_coverage_passed=True,
        llm_judge_passed=None,
    )
    score = FixedAnswerScore(
        route_exact=True,
        tool_exact=True,
        revenue_exact=True,
        selected_doc_hashes_exact=True,
        summary_present=True,
        exact_match=True,
        admissible_match=True,
        correctness_label="exact_match",
        quality_floor=quality_floor,
    )
    usage = ExternalTextRoleUsage(prompt_bytes=10, prompt_tokens=1, completion_tokens=1, total_tokens=2)
    selected_doc_hashes = tuple(
        str(item)
        for item in sample.expected_facts.get("selected_doc_hashes", ["doc"])
    )
    return ExternalTextCaseResult(
        task_id=sample.task_id,
        route=sample.expected_route,
        tool_name=sample.expected_tool_name,
        summary_text="summary",
        revenue_value=str(sample.expected_facts.get("revenue_value", "1")),
        metric_name=str(sample.expected_facts.get("metric_name", "")),
        metric_value=str(sample.expected_facts.get("metric_value", sample.expected_facts.get("revenue_value", "1"))),
        output_path=str(output_path),
        report_path=str(report_path),
        message_count=4,
        text_bytes=40,
        prompt_bytes=40,
        prompt_tokens=4,
        completion_tokens=4,
        total_tokens=8,
        llm_ms=1.0,
        end_to_end_ms=2.0,
        llm_call_count=4,
        route_exact=True,
        tool_exact=True,
        metric_name_exact=True,
        metric_value_exact=True,
        revenue_fallback_used=False,
        exact_match=True,
        admissible_match=True,
        correctness_label="exact_match",
        contamination_detected=False,
        fairness_gate=fairness_gate,
        selected_doc_hashes=selected_doc_hashes,
        supporting_doc_ids=selected_doc_hashes,
        quality_floor=score,
        planner_usage=usage,
        retriever_usage=usage,
        executor_usage=usage,
        summarizer_usage=usage,
    )


def test_external_text_family_aggregates_per_case_fairness_gate_failures(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.benchmark import external_text_baseline as baseline

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    failed_task_id = family[0].task_id
    passing_gate = {
        "checks": {"planner_visible_choice_only": True},
        "failed_checks": [],
        "pass_hard_gate": True,
        "visible_candidate_keys": ["route::tool"],
    }
    failing_gate = {
        "checks": {"planner_visible_choice_only": False},
        "failed_checks": ["planner_visible_choice_only"],
        "pass_hard_gate": False,
        "visible_candidate_keys": ["route::tool"],
    }

    def fake_run_external_text_case(*, sample, runtime_root, role_path_mode, embedding_mode):
        del role_path_mode, embedding_mode
        return _fake_external_result_for_fairness_gate(
            sample,
            runtime_root,
            fairness_gate=failing_gate if sample.task_id == failed_task_id else passing_gate,
        )

    monkeypatch.setattr(baseline, "run_external_text_case", fake_run_external_text_case)
    report = baseline.run_external_text_family(samples=family, runtime_root=tmp_path / "external")

    assert report.aggregated_metrics["external_fairness_gate_pass_count"] == 2.0
    assert report.aggregated_metrics["external_fairness_gate_failed_case_count"] == 1.0
    assert report.aggregated_metrics["external_fairness_gate_failed_check_count"] == 1.0
    assert report.aggregated_metrics["external_fairness_gate_reported_case_count"] == 3.0
    assert report.metadata["external_fairness_gate_pass"] is False
    assert report.metadata["external_fairness_gate_failed_checks"] == ["planner_visible_choice_only"]
    assert report.cases[0].metrics["external_fairness_gate_failed"] == 1.0
    assert report.cases[0].audit_summary["external_fairness_gate"]["pass_hard_gate"] is False
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["aggregated_metrics"]["external_fairness_gate_failed_case_count"] == 1.0
    assert payload["cases"][0]["audit_summary"]["external_fairness_gate"]["failed_checks"] == [
        "planner_visible_choice_only"
    ]


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
    assert mode_report.comparison_valid is False
    assert mode_report.invalid_reason == "quality_floor_gate_failed"
    assert mode_report.headline_metrics == {}
    assert "exact_match_delta" in mode_report.debug_metrics
    assert "end_to_end_ms_delta" in mode_report.debug_metrics
    assert "llm_ms_delta" in mode_report.debug_metrics
    assert "prompt_bytes_delta" in mode_report.debug_metrics
    assert "statebus_prompt_tokens" in mode_report.debug_metrics
    assert "external_prompt_tokens" in mode_report.debug_metrics
    assert "prompt_tokens_delta" in mode_report.debug_metrics
    assert "statebus_completion_tokens" in mode_report.debug_metrics
    assert "external_completion_tokens" in mode_report.debug_metrics
    assert "completion_tokens_delta" in mode_report.debug_metrics
    assert "llm_call_count_delta" in mode_report.debug_metrics
    assert mode_report.debug_metrics["external_quality_floor_pass_count"] == 0.0
    assert mode_report.fairness_manifest["external_formal_eligible"] is True
    assert mode_report.fairness_manifest["pass_hard_gate"] is True
    assert Path(mode_report.report_path).exists()
    assert Path(mode_report.markdown_report_path).exists()
    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    assert payload["metadata"]["formal_headline_eligible"] is False
    assert payload["metadata"]["formal_efficiency_claim_allowed"] is False
    assert payload["metadata"]["formal_efficiency_superiority_claim_allowed"] is False
    assert payload["metadata"]["comparator_token_split_schema"] == "statebus.comparator.token_split.v1"
    assert payload["metadata"]["timing_execution_contract"] == "serialized_statebus_then_external_within_each_mode_v1"
    assert payload["metadata"]["serialized_latency_superiority_claim_allowed"] is False
    assert payload["metadata"]["formal_quality_superiority_claim_allowed"] is False
    assert payload["metadata"]["formal_superiority_claim_allowed"] is False
    assert payload["metadata"]["strict_equal_quality_comparison_valid"] is False
    assert payload["metadata"]["quality_superiority_comparison_valid"] is True
    assert payload["metadata"]["formal_external_claim_kind"] == "none"
    assert payload["metadata"]["fixed_answer_external_comparison_valid"] is False
    assert (
        payload["metadata"]["claim_restriction"]
        == "external_compare_debug_only_until_strict_or_quality_gate_passes"
    )
    assert payload["mode_reports"][0]["role_path_mode"] == "deterministic"
    assert payload["mode_reports"][0]["comparison_valid"] is False
    assert payload["mode_reports"][0]["comparison_summary"]["strict_equal_quality_comparison_valid"] == 0.0
    assert payload["mode_reports"][0]["comparison_summary"]["quality_superiority_comparison_valid"] == 1.0
    assert payload["mode_reports"][0]["comparison_summary"]["formal_efficiency_claim_allowed"] == 0.0
    assert "prompt_tokens_delta" in payload["mode_reports"][0]["comparison_summary"]
    assert "completion_tokens_delta" in payload["mode_reports"][0]["comparison_summary"]
    assert payload["comparison_summary"]["formal_efficiency_claim_allowed"] == 0.0
    assert "deterministic_prompt_tokens_delta" in payload["comparison_summary"]
    assert "deterministic_completion_tokens_delta" in payload["comparison_summary"]
    assert "deterministic_debug_exact_match_delta" in payload["comparison_summary"]


def test_formal_external_comparator_splits_strict_and_quality_superiority(tmp_path: Path) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        benchmark_tier="formal",
    )

    payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
    metadata = payload["metadata"]
    assert metadata["strict_equal_quality_comparison_valid"] is False
    assert metadata["quality_superiority_comparison_valid"] is True
    assert metadata["formal_quality_superiority_claim_allowed"] is True
    assert metadata["formal_efficiency_superiority_claim_allowed"] is False
    assert metadata["formal_efficiency_claim_allowed"] is False
    assert metadata["formal_superiority_claim_allowed"] is True
    assert metadata["formal_external_claim_kind"] == "quality_superiority"
    assert metadata["fixed_answer_external_comparison_valid"] is False
    assert metadata["legacy_comparison_valid_semantics"] == "strict_equal_quality_comparison_valid"
    assert metadata["formal_compare_scope_label"] == "formal_partial_1family_3case_compare"
    assert metadata["formal_compare_case_count"] == 3
    assert metadata["formal_compare_family_count"] == 1
    assert metadata["formal_registry_case_count"] == 25
    assert metadata["formal_compare_full_registry_coverage"] is False
    assert payload["comparison_summary"]["strict_equal_quality_comparison_valid"] == 0.0
    assert payload["comparison_summary"]["quality_superiority_comparison_valid"] == 1.0
    assert payload["comparison_summary"]["formal_quality_superiority_claim_allowed"] == 1.0
    assert payload["comparison_summary"]["formal_efficiency_superiority_claim_allowed"] == 0.0


def test_formal_financial_compare_scope_metadata_is_not_full_registry() -> None:
    from v2.benchmark.comparator_runner import _formal_compare_scope_metadata

    samples = load_fixed_answer_family(Path("v2/benchmark/samples/formal_financial_family"))
    metadata = _formal_compare_scope_metadata(samples=samples, benchmark_tier="formal")

    assert metadata["formal_compare_scope_label"] == "formal_financial_family_8case_compare"
    assert metadata["formal_compare_case_count"] == 8
    assert metadata["formal_compare_family_count"] == 1
    assert metadata["formal_registry_case_count"] == 25
    assert metadata["formal_compare_full_registry_coverage"] is False


def test_registered_formal_fixed_answer_adapter_covers_full_registry() -> None:
    from v2.benchmark.comparator_runner import _formal_compare_scope_metadata
    from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples

    samples = load_registered_formal_fixed_answer_samples()
    metadata = _formal_compare_scope_metadata(samples=samples, benchmark_tier="formal")
    families = {sample.task_family for sample in samples}
    projection_by_task = {sample.task_id: sample.metric_projection_key for sample in samples}
    route_by_task = {sample.task_id: sample.expected_route for sample in samples}

    assert len(samples) == 25
    assert len(families) == 5
    assert metadata["formal_compare_case_count"] == 25
    assert metadata["formal_compare_family_count"] == 5
    assert metadata["formal_compare_full_registry_coverage"] is True
    assert projection_by_task["formal-trend-001"] == "trend_direction"
    assert projection_by_task["formal-agg-004"] == "monthly_avg_windspeed.month_1"
    assert projection_by_task["formal-anomaly-002"] == "baro_outlier_count"
    assert route_by_task["formal-join-004"] == "compare_metric"


def test_external_context_uses_registry_route_catalog_for_adapted_formal_samples() -> None:
    from v2.benchmark.external_text_baseline import _load_execution_context
    from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples

    samples = load_registered_formal_fixed_answer_samples()
    sample = next(item for item in samples if item.task_id == "formal-anomaly-002")
    context = _load_execution_context(sample)
    visible_keys = {candidate.candidate_key() for candidate in context.route_candidates}

    assert "detect_outliers::table_retriever" in visible_keys
    assert "compare_metric::table_retriever" not in visible_keys
    assert context.metric_name == "baro_outlier_count"


def test_metric_projection_fills_partial_statebus_metric_output() -> None:
    from v2.benchmark.fixed_answer_runner import _project_metric_for_scoring
    from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples

    sample = next(
        item
        for item in load_registered_formal_fixed_answer_samples()
        if item.task_id == "formal-agg-004"
    )
    metric_name, metric_value = _project_metric_for_scoring(
        sample=sample,
        output_payload={
            "metric_name": "monthly_avg_windspeed.month_1",
            "monthly_avg_windspeed": {"month_1": "7.17"},
        },
    )

    assert metric_name == "monthly_avg_windspeed.month_1"
    assert metric_value == "7.17"


def test_fixed_answer_external_comparator_fails_closed_on_external_fairness_gate_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from v2.benchmark import comparator_runner
    from v2.benchmark import external_text_baseline as baseline

    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    failed_task_id = family[0].task_id
    passing_gate = {
        "checks": {"planner_visible_choice_only": True},
        "failed_checks": [],
        "pass_hard_gate": True,
        "visible_candidate_keys": ["route::tool"],
    }
    failing_gate = {
        "checks": {"planner_visible_choice_only": False},
        "failed_checks": ["planner_visible_choice_only"],
        "pass_hard_gate": False,
        "visible_candidate_keys": ["route::tool"],
    }

    def fake_run_external_text_case(*, sample, runtime_root, role_path_mode, embedding_mode):
        del role_path_mode, embedding_mode
        return _fake_external_result_for_fairness_gate(
            sample,
            runtime_root,
            fairness_gate=failing_gate if sample.task_id == failed_task_id else passing_gate,
        )

    monkeypatch.setattr(baseline, "run_external_text_case", fake_run_external_text_case)
    external_report = baseline.run_external_text_family(
        samples=family,
        runtime_root=tmp_path / "external-report-source",
    )
    monkeypatch.setattr(comparator_runner, "run_external_text_family", lambda **kwargs: external_report)

    report = comparator_runner.compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
    )

    mode_report = report.mode_reports[0]
    assert mode_report.comparison_valid is False
    assert mode_report.invalid_reason == "fairness_gate_failed"
    assert mode_report.headline_metrics == {}
    assert mode_report.fairness_manifest["external_fairness_gate_coverage"] is True
    assert mode_report.fairness_manifest["no_external_fairness_gate_failures"] is False
    assert mode_report.fairness_manifest["external_fairness_gate_failed_case_count"] == 1.0
    assert mode_report.fairness_manifest["external_fairness_gate_failed_checks"] == [
        "planner_visible_choice_only"
    ]
    assert mode_report.fairness_manifest["pass_hard_gate"] is False
    payload = json.loads(Path(mode_report.report_path).read_text(encoding="utf-8"))
    assert payload["fairness_manifest"]["external_fairness_gate_failed_case_count"] == 1.0
    assert payload["invalid_reason"] == "fairness_gate_failed"


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
    assert mode_report.comparison_valid is False
    assert mode_report.invalid_reason == "quality_floor_gate_failed"
    assert mode_report.debug_metrics["statebus_exact_match_count"] == 3.0
    assert mode_report.debug_metrics["external_quality_floor_pass_count"] == 0.0
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


def test_fixed_answer_external_comparator_records_serialized_repeat_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    family = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))
    monkeypatch.setenv("STATEBUS_COMPARATOR_SERIALIZED_REPEAT_COUNT", "3")
    monkeypatch.setenv("STATEBUS_COMPARATOR_SERIALIZED_REPEAT_INDEX", "2")
    monkeypatch.setenv("STATEBUS_COMPARATOR_TIMING_CONTRACT", "serialized_formal_compare_latency_rerun_v1")
    report = compare_fixed_answer_with_external(
        samples=family,
        workspace_root=tmp_path / "workspaces",
        runtime_root=tmp_path / "runtime",
        socket_path=tmp_path / "control.sock",
        role_path_modes=("deterministic",),
        statebus_mode="cold-start",
    )

    assert report.metadata["serialized_repeat_count"] == 3
    assert report.metadata["serialized_repeat_index"] == 2
    assert report.metadata["timing_execution_contract"] == "serialized_formal_compare_latency_rerun_v1"
    assert report.comparison_summary["serialized_repeat_count"] == 3.0
    assert report.comparison_summary["serialized_repeat_index"] == 2.0


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


def test_role_path_strict_selection_uses_visible_candidate_surface_for_fixed_answer_triage() -> None:
    from runtime.llm import DeterministicLLMClient
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    sample = load_fixed_answer_family(Path("v2/benchmark/samples/fixed_answer_family"))[0]
    spec = sample.canonical_task_spec
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=spec)
    candidates = financial_tool_candidates(spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=DeterministicLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
    )

    assert decision.route == sample.expected_route
    assert decision.tool_name == sample.expected_tool_name
    assert decision.candidate_rank == 3


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


def test_role_path_accepts_tool_only_selection_when_route_hint_is_unambiguous() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "table_retriever",
                            "tool_name": "table_retriever",
                            "supporting_doc_ids": ["sha256:doc-acme-2026q1"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="summarize_risk", tool_name="semantic_retriever", helper_rank=2),
        RoleToolCandidate(route="generate_chart", tool_name="table_retriever", helper_rank=3),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text="ACME 2026Q1 revenue compare_metric",
        retrieved_doc_ids=("sha256:doc-acme-2026q1",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
        route_hints=("compare_metric",),
    )

    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 1


def test_role_path_rejects_ambiguous_tool_only_selection_without_route_hint() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps({"route": "table_retriever", "tool_name": "table_retriever"}),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="generate_chart", tool_name="table_retriever", helper_rank=2),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    with pytest.raises(RoleSelectionError):
        runner.choose_retrieval_candidate(
            query_text="ACME 2026Q1 revenue",
            retrieved_doc_ids=("sha256:doc-acme-2026q1",),
            visible_candidates=candidates,
            allow_assisted_correction=False,
        )


def test_role_path_accepts_swapped_route_tool_selection_when_pair_is_visible() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "table_retriever",
                            "tool_name": "compare_metric",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="summarize_risk", tool_name="semantic_retriever", helper_rank=2),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text="ACME 2026Q1 revenue compare_metric",
        retrieved_doc_ids=("sha256:doc-acme-2026q1",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )

    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 1


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


def test_role_path_accepts_candidate_key_echoed_in_route_slot_with_matching_tool() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "compare_metric::table_retriever",
                            "tool_name": "table_retriever",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="generate_chart", tool_name="table_retriever", helper_rank=2),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.choose_retrieval_candidate(
        query_text="ACME 2026Q1 revenue compare_metric",
        retrieved_doc_ids=("sha256:doc-acme-2026q1",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )

    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 1


def test_role_path_rejects_candidate_key_route_slot_with_conflicting_tool() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "retriever":
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "compare_metric::table_retriever",
                            "tool_name": "semantic_retriever",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    candidates = (
        RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        RoleToolCandidate(route="summarize_risk", tool_name="semantic_retriever", helper_rank=2),
    )
    runner = RolePathRunner(llm_client=StubLLMClient())
    with pytest.raises(RoleSelectionError):
        runner.choose_retrieval_candidate(
            query_text="ACME 2026Q1 revenue compare_metric",
            retrieved_doc_ids=("sha256:doc-acme-2026q1",),
            visible_candidates=candidates,
            allow_assisted_correction=False,
        )


def test_role_path_retries_strict_retriever_visible_candidate_mismatch() -> None:
    class StubLLMClient:
        def __init__(self) -> None:
            self.calls = 0
            self.prompts: list[str] = []

        async def complete(self, messages, *, purpose, temperature=None):
            del temperature
            assert purpose == "retriever"
            self.calls += 1
            self.prompts.append(messages[0].content)
            if self.calls == 1:
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "csv_profiler",
                            "tool_name": "csv_profiler",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10),
                )
            return LLMResult(
                text=json.dumps(
                    {
                        "candidate_key": "aggregate_and_extreme::table_retriever",
                        "route": "aggregate_and_extreme",
                        "tool_name": "table_retriever",
                    }
                ),
                model="stub-model",
                usage=LLMUsage(prompt_tokens=9, completion_tokens=4, total_tokens=13),
            )

        def describe(self):
            return {"backend": "stub"}

    llm = StubLLMClient()
    candidates = (
        RoleToolCandidate(route="profile_table", tool_name="csv_profiler", helper_rank=1),
        RoleToolCandidate(route="aggregate_and_extreme", tool_name="table_retriever", helper_rank=2),
        RoleToolCandidate(route="profile_and_mean", tool_name="csv_profiler", helper_rank=3),
    )
    runner = RolePathRunner(llm_client=llm, json_response_max_attempts=2)
    decision = runner.choose_retrieval_candidate(
        query_text="disease_estimates aggregate_and_extreme task/csv/estimated_numbers.csv",
        retrieved_doc_ids=("sha256:csv-disease_estimates",),
        visible_candidates=candidates,
        allow_assisted_correction=False,
    )

    assert llm.calls == 2
    assert "Selection retry instruction" in llm.prompts[1]
    assert decision.route == "aggregate_and_extreme"
    assert decision.tool_name == "table_retriever"
    assert decision.prompt_tokens == 16
    assert decision.total_tokens == 23


def test_role_path_retries_strict_executor_visible_candidate_mismatch() -> None:
    class StubLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            assert purpose == "executor"
            self.calls += 1
            if self.calls == 1:
                return LLMResult(
                    text=json.dumps(
                        {
                            "route": "csv_profiler",
                            "tool_name": "csv_profiler",
                            "action_contract": "materialize_validated_artifact",
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
                )
            return LLMResult(
                text=json.dumps(
                    {
                        "candidate_key": "aggregate_and_extreme::table_retriever",
                        "route": "aggregate_and_extreme",
                        "tool_name": "table_retriever",
                        "action_contract": "materialize_validated_artifact",
                    }
                ),
                model="stub-model",
                usage=LLMUsage(prompt_tokens=6, completion_tokens=4, total_tokens=10),
            )

        def describe(self):
            return {"backend": "stub"}

    llm = StubLLMClient()
    candidates = (
        RoleToolCandidate(route="profile_table", tool_name="csv_profiler", helper_rank=1),
        RoleToolCandidate(route="aggregate_and_extreme", tool_name="table_retriever", helper_rank=2),
    )
    runner = RolePathRunner(llm_client=llm, json_response_max_attempts=2)
    decision = runner.validate_execution_choice(
        route="aggregate_and_extreme",
        tool_name="table_retriever",
        visible_candidates=candidates,
        action_contract="materialize_validated_artifact",
        allow_assisted_correction=False,
    )

    assert llm.calls == 2
    assert decision.route == "aggregate_and_extreme"
    assert decision.tool_name == "table_retriever"
    assert decision.total_tokens == 18


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


def test_role_path_retries_empty_executor_json_response() -> None:
    class StubLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            assert purpose == "executor"
            self.calls += 1
            if self.calls == 1:
                return LLMResult(
                    text="",
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=3, completion_tokens=0, total_tokens=3),
                )
            return LLMResult(
                text=json.dumps(
                    {
                        "candidate_key": "compare_metric::table_retriever",
                        "route": "compare_metric",
                        "tool_name": "table_retriever",
                        "action_contract": "materialize_validated_artifact",
                        "reason": "valid retry",
                    }
                ),
                model="stub-model",
                usage=LLMUsage(prompt_tokens=5, completion_tokens=4, total_tokens=9),
            )

        def describe(self):
            return {"backend": "stub"}

    llm = StubLLMClient()
    runner = RolePathRunner(llm_client=llm)
    decision = runner.validate_execution_choice(
        route="compare_metric",
        tool_name="table_retriever",
        visible_candidates=(
            RoleToolCandidate(route="compare_metric", tool_name="table_retriever", helper_rank=1),
        ),
        action_contract="materialize_validated_artifact",
        allow_assisted_correction=False,
    )

    assert llm.calls == 2
    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.reason == "valid retry"
    assert decision.prompt_tokens == 8
    assert decision.total_tokens == 12


def test_role_path_retries_malformed_summarizer_json_response() -> None:
    class StubLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            assert purpose == "summarizer"
            self.calls += 1
            if self.calls == 1:
                return LLMResult(
                    text='{"summary": "ok"; "reusable_steps": ["retrieve"], "confidence": 0.9, "tags": []}',
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=7, completion_tokens=3, total_tokens=10),
                )
            return LLMResult(
                text=json.dumps(
                    {
                        "summary": "retry summary",
                        "reusable_steps": ["retrieve", "execute"],
                        "confidence": "high",
                        "tags": ["finance"],
                    }
                ),
                model="stub-model",
                usage=LLMUsage(prompt_tokens=8, completion_tokens=5, total_tokens=13),
            )

        def describe(self):
            return {"backend": "stub"}

    llm = StubLLMClient()
    runner = RolePathRunner(llm_client=llm)
    decision = runner.summarize(
        task_id="task-1",
        task_theme="financial_report_analysis",
        summary_hint="hint",
        actions_text="route=compare_metric",
        tags=("finance",),
    )

    assert llm.calls == 2
    assert decision.summary_text == "retry summary"
    assert decision.confidence == 0.9
    assert decision.prompt_tokens == 15
    assert decision.total_tokens == 23


def test_role_path_summarizer_accepts_textual_confidence_label() -> None:
    class StubLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del messages, temperature
            if purpose == "summarizer":
                return LLMResult(
                    text=json.dumps(
                        {
                            "summary": "ok",
                            "reusable_steps": ["retrieve", "execute"],
                            "confidence": "high",
                            "tags": ["finance"],
                        }
                    ),
                    model="stub-model",
                    usage=LLMUsage(prompt_tokens=12, completion_tokens=6, total_tokens=18),
                )
            raise AssertionError(f"unexpected purpose {purpose}")

        def describe(self):
            return {"backend": "stub"}

    runner = RolePathRunner(llm_client=StubLLMClient())
    decision = runner.summarize(
        task_id="task-1",
        task_theme="financial_report_analysis",
        summary_hint="hint",
        actions_text="route=compare_metric",
        tags=("table_retriever",),
    )

    assert decision.confidence == 0.9
    assert decision.summary_text == "ok"


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
    assert retriever_payload["pc"]["k"] == f"{sample.expected_route}::{sample.expected_tool_name}"
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
    assert executor_payload["pc"]["k"] == f"{sample.expected_route}::{sample.expected_tool_name}"
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


def test_formal_trend_002_structured_prompt_exposes_preferred_candidate_tiebreak() -> None:
    class PreferenceAwareLLMClient:
        async def complete(self, messages, *, purpose, temperature=None):
            del temperature
            assert purpose == "retriever"
            prompt = messages[-1].content
            payload = parse_tagged_json(prompt, "sb-retriever-v1")
            preferred = payload.get("pc")
            selected = preferred if isinstance(preferred, dict) else payload["tc"][-1]
            return LLMResult(
                text=json.dumps(
                    {
                        "candidate_key": selected["k"],
                        "route": selected["r"],
                        "tool_name": selected["t"],
                        "reason": "follow preferred candidate tie-break",
                    }
                ),
                model="stub-model",
                usage=LLMUsage(prompt_tokens=12, completion_tokens=8, total_tokens=20),
            )

        def describe(self):
            return {"backend": "preference-aware"}

    from v2.benchmark.formal_registry_adapter import load_registered_formal_fixed_answer_samples
    from v2.retrieval import RetrieverFanoutPipeline
    from v2.runtime.role_path import financial_tool_candidates

    sample = next(
        item for item in load_registered_formal_fixed_answer_samples() if item.task_id == "formal-trend-002"
    )
    retrieval = RetrieverFanoutPipeline().run(task_id=sample.task_id, spec=sample.canonical_task_spec)
    candidates = financial_tool_candidates(sample.canonical_task_spec, retrieval.candidate_pool)
    runner = RolePathRunner(llm_client=PreferenceAwareLLMClient())

    decision = runner.choose_retrieval_candidate(
        query_text=retrieval.query_text,
        retrieved_doc_ids=retrieval.selected_doc_hashes,
        visible_candidates=candidates,
        allow_assisted_correction=False,
        route_hints=(sample.canonical_task_spec.intent_op, sample.expected_route),
    )

    assert decision.route == "compare_metric"
    assert decision.tool_name == "table_retriever"
    assert decision.candidate_rank == 1


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
