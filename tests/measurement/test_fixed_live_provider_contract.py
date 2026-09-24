from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import statebus.benchmark.stage2_pilot as pilot
from statebus.integrations.llm import LLMConfig, LLMResult, LLMUsage, ProviderConfig
from statebus.integrations.llm import parse_tagged_json
from statebus.benchmark.minimal_runner import (
    _live_summarizer_claim_bound,
    _live_summarizer_config,
)
from statebus.runtime.fixed_mainline import _compact_live_summarizer_evidence, _live_call
from statebus.runtime.codeact_sandbox import (
    CodeActSandboxReadiness,
    CodeActSandboxResult,
    CodeActSandboxRunner,
)
from statebus.runtime.role_path import RolePathRunner


@pytest.fixture
def fake_codeact_bwrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the trusted fixture source without requiring host namespace privileges."""

    def readiness(self, *, policy_version: str, refresh: bool = False):
        del self, refresh
        return CodeActSandboxReadiness(
            ready=True,
            actual_backend="bwrap",
            sandbox_uid=65_534,
            sandbox_gid=65_534,
            policy_version=policy_version,
            bwrap_version="test-bwrap",
        )

    def run_llm_bwrap(
        self,
        *,
        source_path: Path,
        inputs_dir: Path,
        outputs_dir: Path,
        policy_version: str,
    ):
        del inputs_dir, outputs_dir, policy_version
        completed = subprocess.run(
            [sys.executable, str(source_path)],
            cwd=str(source_path.parent.parent),
            text=True,
            capture_output=True,
            check=False,
            timeout=self.config.timeout_seconds,
        )
        return CodeActSandboxResult(
            completed=completed,
            requested_backend="bwrap_required",
            actual_backend="bwrap",
            fallback_reason="" if completed.returncode == 0 else (completed.stderr or "test_codeact_failed"),
        )

    monkeypatch.setattr(CodeActSandboxRunner, "check_llm_bwrap_readiness", readiness)
    monkeypatch.setattr(CodeActSandboxRunner, "run_llm_bwrap", run_llm_bwrap)


class _FourRoleFakeClient:
    def __init__(
        self,
        *,
        failure_role: str | None = None,
        exception_role: str | None = None,
        invalid_executor_once: bool = False,
        invalid_executor_always: bool = False,
        failure_finish_reason: str | None = None,
    ) -> None:
        self.failure_role = failure_role
        self.exception_role = exception_role
        self.invalid_executor_once = invalid_executor_once
        self.invalid_executor_always = invalid_executor_always
        self.failure_finish_reason = failure_finish_reason
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

    @staticmethod
    def _codeact_source(*, invalid: bool) -> str:
        # Keep this fixture source-owned and independent of benchmark gold.
        # The production path audits and executes the same bounded-Python
        # contract; this fake only supplies a deterministic candidate.
        metric_value = "999.0" if invalid else "float(row['value'])"
        return (
            "import json\n"
            "from pathlib import Path\n"
            "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
            "selected = [row for row in rows if row.get('ticker') == 'ACME' "
            "and row.get('quarter') == '2026Q1' and row.get('metric') == 'revenue']\n"
            "if len(selected) != 1:\n"
            "    raise ValueError('fixture_metric_match_count')\n"
            "row = selected[0]\n"
            f"payload = {{'metric_name': str(row['metric']), 'metric_value': {metric_value}}}\n"
            "Path('outputs/result.json').write_text(json.dumps(payload), encoding='utf-8')\n"
        )

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
                finish_reason=self.failure_finish_reason,
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
            invalid_program = self.invalid_executor_always or (
                self.invalid_executor_once and self.executor_call_count == 1
            )
            if "sb-transform-program-v1" not in prompt:
                payload = {
                    "code": self._codeact_source(invalid=invalid_program),
                }
            else:
                request = parse_tagged_json(prompt, "sb-transform-program-v1")
                input_ref = request["authorized_input_refs"][0]
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


def _sample(case_id: str = "benchmark-sample-1"):
    return next(
        item[2]
        for item in pilot._select_samples()
        if item[2].task_id == case_id
    )


def test_live_summarizer_evidence_projection_is_bounded_and_locatable() -> None:
    payload = {
        "structured_evidence": [
            {
                "item_id": f"row-{index}",
                "locator": {"row": index},
                "rendered_text": "x" * 10_000,
            }
            for index in range(32)
        ]
    }

    projected = _compact_live_summarizer_evidence(payload)

    assert len(projected) == 8
    assert projected[0]["id"] == "row-0"
    assert all(item["locator"] for item in projected)
    assert all(len(item["text"]) <= 1_000 for item in projected)


def test_live_summarizer_evidence_projection_prioritizes_runtime_provenance() -> None:
    payload = {
        "structured_evidence": [
            {
                "item_id": f"row-{index}",
                "locator": {"row": index},
                "rendered_text": f"value-{index}",
            }
            for index in range(12)
        ]
    }

    projected = _compact_live_summarizer_evidence(
        payload,
        provenance_item_ids=("row-10", "row-11"),
    )

    ids = [item["id"] for item in projected]
    assert len(ids) == 8
    assert ids[:2] == ["row-10", "row-11"]
    assert {"row-0", "row-2", "row-4", "row-9"}.issubset(ids)


def test_live_summarizer_evidence_projection_renders_structured_row_without_text() -> None:
    projected = _compact_live_summarizer_evidence(
        {
            "structured_evidence": [
                {
                    "item_id": "row-1",
                    "locator": {"row": 1},
                    "rendered_text": "",
                    "metadata": {"structured_row": {"z": 2, "a": "source"}},
                }
            ]
        }
    )

    assert len(projected) == 1
    assert json.loads(projected[0]["text"]) == {"a": "source", "z": 2}


def test_live_provider_content_capture_is_opt_in() -> None:
    def run_once(*, capture_content: bool) -> dict[str, object]:
        client = _FourRoleFakeClient()
        runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
        sink: dict[str, object] = {}
        _live_call(
            runner,
            sink,
            "retriever",
            lambda: runner.build_evidence_request(
                task_id="task-1",
                step_id="retrieve",
                step_goal="find evidence",
                corpus_scope_ids=("formal-local",),
                evidence_types=("table",),
            ),
            capture_content=capture_content,
        )
        return sink

    compact = run_once(capture_content=False)
    compact_invocation = compact["role_invocations"][0]
    compact_audit = compact["rendered_request_audit"]["retriever"]
    assert "raw_response_text" not in compact_invocation
    assert compact_audit["content_persisted"] is False
    assert "messages" not in compact_audit["requests"][0]

    captured = run_once(capture_content=True)
    captured_invocation = captured["role_invocations"][0]
    captured_audit = captured["rendered_request_audit"]["retriever"]
    assert captured_invocation["raw_response_text"]
    assert captured_audit["content_persisted"] is True
    assert captured_audit["requests"][0]["messages"]


def test_live_claim_set_budget_and_finish_reason_remain_fail_closed(tmp_path: Path) -> None:
    config = LLMConfig(
        mode="local_vllm",
        providers={"default": ProviderConfig(timeout_s=12.5)},
    )
    budgeted = _live_summarizer_config(config, expected_claim_count=6)
    assert budgeted.role_config("summarizer").max_tokens == 3_072

    client = _FourRoleFakeClient(
        failure_role="summarizer",
        failure_finish_reason="length",
    )
    runner = RolePathRunner(llm_client=client, json_response_max_attempts=1)
    sink: dict[str, object] = {}
    with pytest.raises(ValueError, match="summarizer role returned invalid JSON"):
        _live_call(
            runner,
            sink,
            "summarizer",
            lambda: runner.build_claim_set(
                task_id="task-1",
                claim_set_id="claims-1",
                verified_artifact_refs=("artifact-1",),
                evidence_items=(
                    {"id": "evidence-1", "locator": "table:0", "text": "revenue 120"},
                ),
                artifact_summaries=(
                    {
                        "artifact_ref_id": "artifact-1",
                        "status": "verified",
                        "rows": [
                            {"quarter": f"202{index}Q1", "metric_value": float(index)}
                            for index in range(6)
                        ],
                    },
                ),
                expected_claim_count=6,
            ),
        )

    invocation = next(
        item
        for item in sink["role_invocations"]
        if item["role"] == "summarizer"
    )
    assert invocation["status"] == "error"
    assert invocation["finish_reason"] == "length"
    assert "invalid JSON" in invocation["error"]


@pytest.mark.parametrize(
    ("shape", "semantics", "expected"),
    [
        ("object", {"operation": "lookup_metric"}, 1),
        ("array", {"operation": "groupby_aggregate"}, 12),
        (
            "array",
            {"operation": "compute_trend", "tickers": ["ACME", "BETA"], "quarters": ["2026Q1", "2026Q2"]},
            4,
        ),
    ],
)
def test_live_summarizer_claim_bound_comes_from_operation_contract(
    shape: str,
    semantics: dict[str, object],
    expected: int,
) -> None:
    assert _live_summarizer_claim_bound(
        expected_output_shape=shape,
        operation_semantics=semantics,
    ) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"percentage_cases_min": 36.45}, [{"percentage_cases_min": 36.45}]),
        ([{"percentage_cases_min": 36.45}], [{"percentage_cases_min": 36.45}]),
        ([{"percentage_cases_min": 36.45}, {"percentage_deaths_max": 38.79}], [
            {"percentage_cases_min": 36.45},
            {"percentage_deaths_max": 38.79},
        ]),
    ],
)
def test_verified_executor_artifact_projection_accepts_object_or_rows(
    tmp_path: Path,
    payload: object,
    expected: list[dict[str, object]],
) -> None:
    artifact_path = tmp_path / "result.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    assert pilot._load_verified_executor_rows(artifact_path) == expected


def test_fixed_live_provider_records_all_role_telemetry_and_runtime_evidence(
    tmp_path: Path,
    fake_codeact_bwrap: None,
) -> None:
    del fake_codeact_bwrap
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
    assert "ACME" in executor_prompt
    assert "2026Q1" in executor_prompt
    assert "revenue" in executor_prompt
    for _role, prompt in client.calls:
        assert "expected_facts" not in prompt
        assert "gold" not in prompt.lower()
        assert "oracle" not in prompt.lower()
        assert "quality_checks" not in prompt

    assert trace["terminal_status"] == "success"
    assert len(trace["attempts"]) == 4
    assert len(trace["receipts"]) == 4
    assert {grant["max_runtime_ms"] for grant in trace["grants"]} == {17_500}
    executor_audit = sink["rendered_request_audit"]["executor"]
    assert executor_audit["request_count"] == 1
    assert executor_audit["content_persisted"] is False
    assert executor_audit["requests"][0]["prompt_bytes"] > 0
    assert "messages" not in executor_audit["requests"][0]
    assert any(
        item.get("produced_by") == "executor"
        and item.get("verification_state") == "verified"
        for item in trace["artifact_candidates"]
    )


def test_fixed_live_provider_repairs_invalid_transform_once(
    tmp_path: Path,
    fake_codeact_bwrap: None,
) -> None:
    del fake_codeact_bwrap
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
    executor_prompts = [
        prompt for role, prompt in client.calls if role == "executor"
    ]
    assert len(executor_prompts) == 2
    assert "Return only a Python file" in executor_prompts[0]
    assert "<sb-current-python-source>" not in executor_prompts[0]
    assert "<sb-current-python-source>" in executor_prompts[1]
    assert "quality_error:" in executor_prompts[1]
    invocations = sink["role_invocations"]
    assert isinstance(invocations, list)
    assert [item["role"] for item in invocations].count("executor") == 2
    assert all(item["status"] == "response_received" for item in invocations)


def test_fixed_live_provider_does_not_retry_invalid_repair(
    tmp_path: Path,
    fake_codeact_bwrap: None,
) -> None:
    del fake_codeact_bwrap
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
    assert summary["error_code"] == "capability_quality_rejected"
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
    assert set(Path(path).name for path in error.provider_evidence_paths) == {
        "provider_observation.json",
        "provider_request_events.json",
        "rendered_request_audit.json",
        "failure.json",
    }
    assert (tmp_path / "fixed" / "provider_observation.json").is_file()
    failure = json.loads((tmp_path / "fixed" / "failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "runtime_fail"
    assert failure["failure_stage"] == "plan"
    assert failure["provider_started"] is True
