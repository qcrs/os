from __future__ import annotations

import json
from pathlib import Path

import pytest

import statebus.benchmark.stage2_pilot as pilot
from statebus.integrations.llm import LLMConfig, LLMResult, LLMUsage, ProviderConfig
from statebus.integrations.llm import parse_tagged_json
from statebus.runtime.fixed_mainline import _live_call
from statebus.runtime.role_path import RolePathRunner


class _FourRoleFakeClient:
    def __init__(
        self,
        *,
        failure_role: str | None = None,
        exception_role: str | None = None,
        invalid_executor_once: bool = False,
        invalid_executor_always: bool = False,
    ) -> None:
        self.failure_role = failure_role
        self.exception_role = exception_role
        self.invalid_executor_once = invalid_executor_once
        self.invalid_executor_always = invalid_executor_always
        self.executor_call_count = 0
        self.calls: list[tuple[str, str]] = []
        self.request_events: list[dict[str, object]] = []

    def describe(self) -> dict[str, object]:
        return {"backend": "measurement-fake", "mode": "local_vllm", "roles": {}}

    def describe_role(self, role: str) -> dict[str, object]:
        return {
            "backend": "measurement-fake",
            "mode": "local_vllm",
            "role": role,
            "model": "fake-qwen3-32b",
        }

    async def complete(self, messages, *, purpose: str, response_schema=None, **kwargs) -> LLMResult:
        del response_schema, kwargs
        prompt = messages[0].content
        self.calls.append((purpose, prompt))
        if purpose == self.exception_role:
            raise RuntimeError(f"fake provider failure: {purpose}")
        if purpose == self.failure_role:
            return LLMResult(
                text="not-json",
                model="fake-qwen3-32b",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
            )

        if purpose == "planner":
            request = parse_tagged_json(prompt, "sb-plan-v1")
            payload = {
                "semantic_task_plan": {
                    "goal": "find requested metric",
                    "entities": ["ACME", "revenue"],
                    "time_scope": "2026Q1",
                    "lexical_query": "ACME quarterly report 2026Q1",
                    "lexical_objective": "locate the relevant report scope",
                    "semantic_query": "ACME revenue context for 2026Q1",
                    "semantic_objective": "find cited explanatory context",
                    "table_query": "ACME revenue value 2026Q1",
                    "table_objective": "find the requested metric cells",
                    "memory_query": "compatible prior ACME revenue analysis",
                    "memory_objective": "find compatible prior context",
                    "memory_reuse_intent": "assist",
                    "required_evidence": ["table_cell", "table_schema", "citation"],
                    "required_outputs": request["ao"],
                },
            }
        elif purpose == "retriever":
            payload = {
                "queries": ["ACME revenue 2026Q1"],
                "evidence_types": ["table"],
                "corpus_scope_ids": ["formal-local"],
                "max_candidates": 3,
            }
        elif purpose == "executor":
            self.executor_call_count += 1
            request = parse_tagged_json(prompt, "sb-transform-program-v1")
            input_ref = request["authorized_input_refs"][0]
            invalid_program = self.invalid_executor_always or (
                self.invalid_executor_once and self.executor_call_count == 1
            )
            payload = {
                "input_artifact_refs": [input_ref],
                "operations": (
                    [{"op": "select", "arguments": {"columns": ["invented_value"]}}]
                    if invalid_program
                    else [
                        {"op": "filter_eq", "arguments": {"column": "ticker", "value": "ACME"}},
                        {"op": "filter_eq", "arguments": {"column": "quarter", "value": "2026Q1"}},
                        {"op": "filter_eq", "arguments": {"column": "metric", "value": "revenue"}},
                        {"op": "select", "arguments": {"columns": ["metric", "value"]}},
                        {"op": "rename", "arguments": {"source": "metric", "target": "metric_name"}},
                        {"op": "rename", "arguments": {"source": "value", "target": "metric_value"}},
                    ]
                ),
                "output_contract_version": request["output_contract_version"],
            }
        elif purpose == "summarizer":
            request = parse_tagged_json(prompt, "sb-claim-set-v1")
            artifact = request["reference_catalog"]["artifacts"][0]
            evidence = request["reference_catalog"]["evidence"][0]
            rows = artifact["verified_rows"]
            payload = {
                "status": "ready",
                "claims": [
                    {
                        "claim_id": f"claim-{index}",
                        "claim_text": "Revenue was 120 million USD in 2026Q1.",
                        "claim_type": "fact",
                        "supporting_evidence_item_ids": [evidence["evidence_id"]],
                        "supporting_artifact_ref_ids": [artifact["artifact_ref_id"]],
                        "citation_locators": [evidence["citation_locator"]],
                        "numeric_fields": {"metric_value": 120.0},
                        "uncertainty_note": "",
                        "status": "ready",
                    }
                    for index, _row in enumerate(rows)
                ],
            }
        else:  # pragma: no cover - the runner should only issue the four roles.
            raise AssertionError(f"unexpected role: {purpose}")

        self.request_events.append(
            {
                "event": "provider_request",
                "request_id": f"{purpose}-{len(self.request_events) + 1}",
                "role": purpose,
                "model": "fake-qwen3-32b",
                "attempt": 1,
                "retry_kind": "none",
                "status": "response_received",
            }
        )
        return LLMResult(
            text=json.dumps(payload),
            model="fake-qwen3-32b",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def _sample():
    return next(
        item[2]
        for item in pilot._select_samples()
        if item[2].task_id == "benchmark-sample-1"
    )


def test_fixed_live_provider_records_all_role_telemetry_and_runtime_evidence(tmp_path: Path) -> None:
    client = _FourRoleFakeClient()
    runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
    sink: dict[str, object] = {}

    summary, trace = pilot._c2b_structured_runtime(
        _sample(),
        lane="fixed_structured",
        root=tmp_path / "case",
        provider_mode="live",
        llm_config=LLMConfig(
            mode="local_vllm",
            providers={"default": ProviderConfig(timeout_s=12.5)},
        ),
        role_path_runner=runner,
        provider_observation_sink=sink,
    )

    assert summary["terminal_status"] == "success"
    assert summary["provider_observation_gate"]["passed"] is True
    assert {role for role, _prompt in client.calls} == {
        "planner",
        "retriever",
        "executor",
        "summarizer",
    }
    invocations = sink["role_invocations"]
    assert isinstance(invocations, list)
    assert len(invocations) == 4
    for invocation in invocations:
        assert invocation["status"] == "response_received"
        assert invocation["model"] == "fake-qwen3-32b"
        assert invocation["prompt_tokens"] == 10
        assert invocation["completion_tokens"] == 5
        assert invocation["total_tokens"] == 15
        assert invocation["latency_ms"] >= 0
        assert len(invocation["raw_response_hash"]) == 64

    executor_prompt = next(prompt for role, prompt in client.calls if role == "executor")
    assert '"ticker": "ACME"' in executor_prompt
    assert '"value": 120.0' in executor_prompt
    for _role, prompt in client.calls:
        assert "expected_facts" not in prompt
        assert "gold" not in prompt.lower()
        assert "oracle" not in prompt.lower()
        assert "quality_checks" not in prompt

    assert trace["terminal_status"] == "success"
    assert len(trace["attempts"]) == 4
    assert len(trace["receipts"]) == 4
    assert {grant["max_runtime_ms"] for grant in trace["grants"]} == {17_500}
    assert any(
        item.get("produced_by") == "executor"
        and item.get("verification_state") == "verified"
        for item in trace["artifact_candidates"]
    )


def test_fixed_live_provider_repairs_invalid_transform_once(tmp_path: Path) -> None:
    client = _FourRoleFakeClient(invalid_executor_once=True)
    runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
    sink: dict[str, object] = {}

    summary, trace = pilot._c2b_structured_runtime(
        _sample(),
        lane="fixed_structured",
        root=tmp_path / "case",
        provider_mode="live",
        llm_config=LLMConfig(
            mode="local_vllm",
            providers={"default": ProviderConfig(timeout_s=12.5)},
        ),
        role_path_runner=runner,
        provider_observation_sink=sink,
    )

    assert summary["terminal_status"] == "success"
    assert trace["terminal_status"] == "success"
    assert client.executor_call_count == 2
    executor_requests = [
        parse_tagged_json(prompt, "sb-transform-program-v1")
        for role, prompt in client.calls
        if role == "executor"
    ]
    assert executor_requests[0]["repair_context"] == {}
    assert executor_requests[1]["repair_context"]["reason"] == "single_structured_dsl_repair"
    assert executor_requests[1]["repair_context"]["validation_errors"] == ["unknown_column:0"]
    assert executor_requests[1]["input_schema"] == executor_requests[0]["input_schema"]
    invocations = sink["role_invocations"]
    assert isinstance(invocations, list)
    assert [item["role"] for item in invocations].count("executor") == 2
    assert all(item["status"] == "response_received" for item in invocations)


def test_fixed_live_provider_does_not_retry_invalid_repair(tmp_path: Path) -> None:
    client = _FourRoleFakeClient(invalid_executor_always=True)
    runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
    sink: dict[str, object] = {}

    summary, trace = pilot._c2b_structured_runtime(
        _sample(),
        lane="fixed_structured",
        root=tmp_path / "case",
        provider_mode="live",
        llm_config=LLMConfig(
            mode="local_vllm",
            providers={"default": ProviderConfig(timeout_s=12.5)},
        ),
        role_path_runner=runner,
        provider_observation_sink=sink,
    )

    assert summary["terminal_status"] == "runtime_fail"
    assert trace["terminal_status"] == "runtime_fail"
    assert summary["error_code"] == "unknown_column:0"
    assert client.executor_call_count == 2
    assert not any(role == "summarizer" for role, _prompt in client.calls)


@pytest.mark.parametrize("failure_kind", ["malformed", "exception"])
def test_fixed_live_provider_failure_cannot_be_recorded_as_success(failure_kind: str) -> None:
    role = "retriever"
    client = _FourRoleFakeClient(
        failure_role=role if failure_kind == "malformed" else None,
        exception_role=role if failure_kind == "exception" else None,
    )
    runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
    sink: dict[str, object] = {}

    with pytest.raises((RuntimeError, ValueError)):
        _live_call(
            runner,
            sink,
            role,
            lambda: runner.build_evidence_request(
                task_id="task-1",
                step_id="retrieve",
                step_goal="find evidence",
                corpus_scope_ids=("formal-local",),
                evidence_types=("table",),
            ),
        )

    invocations = sink["role_invocations"]
    assert isinstance(invocations, list) and len(invocations) == 1
    assert invocations[0]["status"] == "error"
    assert invocations[0]["role"] == role
    assert not any(item.get("status") == "response_received" for item in invocations)


def test_fixed_case_preserves_runtime_terminal_failure(monkeypatch, tmp_path: Path) -> None:
    observation = {
        "role_invocations": [{"role": "planner", "status": "error"}],
        "provider_request_events": [
            {
                "event": "provider_request",
                "request_id": "planner-1",
                "retry_kind": "none",
                "status": "response_received",
            }
        ],
    }

    def failed_runtime(*args, **kwargs):
        del args, kwargs
        return (
            {
                "terminal_status": "runtime_fail",
                "failure_stage": "plan",
                "error_code": "fixed_live_planner_semantic_plan_invalid",
                "provider_observation": observation,
            },
            {
                "terminal_status": "runtime_fail",
                "failure_stage": "plan",
                "error_code": "fixed_live_planner_semantic_plan_invalid",
                "artifact_candidates": [],
            },
        )

    monkeypatch.setattr(pilot, "_c2b_structured_runtime", failed_runtime)
    with pytest.raises(
        RuntimeError,
        match="fixed_runtime_failed:plan:fixed_live_planner_semantic_plan_invalid",
    ) as captured:
        pilot._fixed_case(
            _sample(),
            tmp_path / "fixed",
            public_case={"public_sources": ["doc-1"]},
        )

    error = captured.value
    assert error.failure_stage == "plan"
    assert error.error_code == "fixed_live_planner_semantic_plan_invalid"
    assert error.provider_request_events == observation["provider_request_events"]
