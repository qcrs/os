from __future__ import annotations

import json

import pytest

import statebus.benchmark.codeact_dsl_showcase as showcase
from statebus.benchmark.codeact_dsl_showcase import (
    CASE_IDS,
    SHOWCASE_CODE_MAX_TOKENS,
    _dsl_program,
    _provider_code,
    _provider_config,
    _program_from_payload,
    _python_source,
    _run_case,
    build_parser,
    load_showcase_cases,
    run_showcase,
)


def test_fixed_manifest_has_three_dsl_and_two_python_cases() -> None:
    cases = load_showcase_cases()
    assert tuple(item.case.task_id for item in cases) == CASE_IDS
    assert CASE_IDS == (
        "formal-trend-001",
        "formal-trend-005",
        "formal-join-001",
        "formal-agg-004",
        "formal-anomaly-001",
    )
    assert [item.expected_backend for item in cases] == ["dsl", "dsl", "dsl", "python", "python"]
    assert build_parser().parse_args(["--output", "runs/test"]).codeact_fallback == "off"


def test_offline_fallback_is_closed_by_default(tmp_path) -> None:
    result_dir = tmp_path / "off"
    assert run_showcase(mode="offline", fallback_enabled=False, case_id="all", output=result_dir) == 1
    rows = [json.loads(line) for line in (result_dir / "task_results.jsonl").read_text().splitlines()]
    assert [row["status"] for row in rows[:3]] == ["passed"] * 3
    assert [row["python_attempts"] for row in rows[3:]] == [0, 0]
    assert all(row["fallback_attempted"] is False for row in rows)


def test_offline_fallback_runs_one_python_attempt_after_one_dsl_repair(tmp_path) -> None:
    result_dir = tmp_path / "on"
    assert run_showcase(mode="offline", fallback_enabled=True, case_id="all", output=result_dir) == 0
    rows = [json.loads(line) for line in (result_dir / "task_results.jsonl").read_text().splitlines()]
    assert [row["final_backend"] for row in rows] == ["dsl", "dsl", "dsl", "python", "python"]
    for row in rows[:3]:
        assert row["fallback_attempted"] is False
        assert row["dsl_repair_count"] == 0
        assert row["python_attempts"] == 0
    for row in rows[3:]:
        assert row["dsl_attempts"] == 2
        assert row["dsl_repair_count"] == 1
        assert row["python_attempts"] == 1
        assert row["python_internal_repair_count"] == 0
    summary = json.loads((result_dir / "summary.json").read_text())
    assert summary["dsl_passed"] == sum(row["status"] == "passed" and row["final_backend"] == "dsl" for row in rows)
    assert summary["codeact_passed"] == sum(row["status"] == "passed" and row["final_backend"] == "python" for row in rows)
    assert summary["passed"] == sum(row["status"] == "passed" for row in rows)


def test_showcase_refuses_nonempty_output(tmp_path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(SystemExit, match="refusing_nonempty_output"):
        run_showcase(mode="dry-run", fallback_enabled=False, case_id="all", output=output)


def test_provider_uses_controller_owned_logical_input_binding() -> None:
    payload = {
        "program_id": "provider-program",
        "input_artifact_refs": ["source"],
        "output_contract_version": "statebus.analysis_result.v2",
        "operations": [
            {"op": "select", "arguments": {"columns": ["value"]}},
        ],
    }
    program = _program_from_payload(payload, "formal-source:formal-anomaly-001", "statebus.analysis_result.v2")
    assert program.input_artifact_refs == ("formal-source:formal-anomaly-001",)

    with pytest.raises(ValueError, match="showcase_provider_input_ref_mismatch"):
        _program_from_payload(
            {**payload, "input_artifact_refs": ["formal-source:formal-anomaly-001"]},
            "formal-source:formal-anomaly-001",
            "statebus.analysis_result.v2",
        )
    with pytest.raises(ValueError, match="showcase_provider_output_contract_mismatch"):
        _program_from_payload(
            {**payload, "output_contract_version": "invented-version"},
            "formal-source:formal-anomaly-001",
            "statebus.analysis_result.v2",
        )
    with pytest.raises(ValueError, match="showcase_provider_operation_format_invalid"):
        _program_from_payload(
            {**payload, "operations": [{"name": "select", "arguments": {"columns": ["value"]}}]},
            "formal-source:formal-anomaly-001",
            "statebus.analysis_result.v2",
        )


def test_showcase_raw_code_provider_matches_adaptive_codeact_contract() -> None:
    from statebus.integrations.llm import LLMConfig

    active = LLMConfig.from_runtime().with_mode("local_vllm")
    config = _provider_config()
    raw_code = _provider_config(raw_code=True)
    provider_name = config.role_config("executor").provider
    assert config.provider_config(provider_name) == active.provider_config(provider_name)
    assert raw_code.provider_config(provider_name) == active.provider_config(provider_name)
    assert config.role_config("executor").json_output is True
    assert raw_code.role_config("executor").json_output is False
    assert raw_code.role_config("executor").max_tokens == SHOWCASE_CODE_MAX_TOKENS


def test_provider_timeout_is_recorded_without_replanning_again(tmp_path, monkeypatch) -> None:
    case = load_showcase_cases()[-1]

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        return {
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": [{"op": "unsupported_operation", "arguments": {}}],
        }, 0

    class TimeoutClient:
        async def complete(self, *args, **kwargs):
            raise TimeoutError("provider timed out")

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    monkeypatch.setattr(showcase, "_provider_client", lambda *, raw_code=False: TimeoutClient())
    row = _run_case(case, mode="live", fallback_enabled=True, case_root=tmp_path / "timeout")
    assert row["status"] == "failed"
    assert row["fallback_attempted"] is True
    assert row["dsl_attempts"] == 2
    assert row["python_attempts"] == 1
    assert row["reason"] == "showcase_provider_timeout"


def test_stubbed_live_prompt_supplies_authorized_output_contract(tmp_path, monkeypatch) -> None:
    case = load_showcase_cases()[1]
    prompts = []

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        prompts.append(request)
        assert set(response_schema["properties"]["operations"]["items"]["required"]) == {"op", "arguments"}
        program = _dsl_program(case, "source")
        return {
            "program_id": "stub-program",
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": [dict(op=step.op, arguments=step.arguments) for step in program.operations],
        }, 0

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    root = tmp_path / "trend"
    row = _run_case(case, mode="live", fallback_enabled=False, case_root=root)
    assert row["status"] == "passed"
    assert len(prompts) == 1
    assert prompts[0]["output_contract_version"] == "statebus.analysis_result.v2"
    assert (root / "provider_initial_contract.json").exists()


def test_join_prompt_reuses_controller_owned_dsl_operation(tmp_path, monkeypatch) -> None:
    case = load_showcase_cases()[2]

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        assert request["operation_semantics"]["dsl_operation"] == "compare_metric"
        assert "return exactly that one operation" in request["instruction"]
        program = _dsl_program(case, "source")
        return {
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": [
                {"op": step.op, "arguments": step.arguments}
                for step in program.operations
            ],
        }, 0

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    row = _run_case(case, mode="live", fallback_enabled=True, case_root=tmp_path / "join")

    assert row["status"] == "passed"
    assert row["final_backend"] == "dsl"
    assert row["dsl_attempts"] == 1
    assert row["python_attempts"] == 0


def test_adapted_dsl_candidate_reaches_runtime_repair(tmp_path, monkeypatch) -> None:
    case = load_showcase_cases()[0]
    phases = []

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        repair = "validation_errors" in request
        phases.append("repair" if repair else "initial")
        assert request["operation_semantics"]["dsl_operation"] == "trend_series"
        assert "return exactly that one operation" in request["instruction"]
        program = _dsl_program(case, "source") if repair else None
        return {
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": (
                [dict(op=step.op, arguments=step.arguments) for step in program.operations]
                if program is not None
                else [{"op": "select", "arguments": {"columns": ["missing_column"]}}]
            ),
        }, 0

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    row = _run_case(case, mode="live", fallback_enabled=True, case_root=tmp_path / "trend-repair")

    assert phases == ["initial", "repair"]
    assert row["status"] == "passed"
    assert row["final_backend"] == "dsl"
    assert row["dsl_attempts"] == 2
    assert row["python_attempts"] == 0
    assert row["fallback_attempted"] is False


def test_stubbed_live_invalid_dsl_repairs_then_uses_python(tmp_path, monkeypatch) -> None:
    case = load_showcase_cases()[-1]
    calls = []

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        calls.append("dsl")
        return {
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": [{"op": "unsupported_operation", "arguments": {}}],
        }, 0

    def stub_code(prompt):
        calls.append("python")
        assert "Task goal:" in prompt
        assert "Operation semantics:" in prompt
        assert "inclusive_quantile_definition" in prompt
        assert "mean_no_of_deaths_without_outliers" in prompt
        assert "unknown_operation" not in prompt
        assert "unsupported_operation" not in prompt
        assert "previous_program" not in prompt
        return _python_source(case), 0

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    monkeypatch.setattr(showcase, "_provider_code", stub_code)
    row = _run_case(case, mode="live", fallback_enabled=True, case_root=tmp_path / "anomaly")
    assert calls == ["dsl", "dsl", "python"]
    assert row["status"] == "passed"
    assert row["last_dsl_failure"] == "unknown_operation:0"
    assert row["final_backend"] == "python"
    assert row["python_attempts"] == 1


@pytest.mark.parametrize(
    ("failure", "operations"),
    [
        (
            "unknown_column:0",
            [{"op": "select", "arguments": {"columns": ["missing_column"]}}],
        ),
        (
            "operation_budget_exceeded:-1",
            [
                {"op": "select", "arguments": {"columns": ["WINDSPEED"]}}
                for _ in range(13)
            ],
        ),
    ],
)
def test_exhausted_invalid_dsl_replans_to_one_python_attempt(
    tmp_path,
    monkeypatch,
    failure,
    operations,
) -> None:
    case = load_showcase_cases()[3]
    calls = []

    def stub_provider(prompt, *, response_schema):
        request = json.loads(prompt)
        calls.append("dsl")
        return {
            "input_artifact_refs": request["authorized_input_refs"],
            "output_contract_version": request["output_contract_version"],
            "operations": operations,
        }, 0

    def stub_code(prompt):
        calls.append("python")
        return _python_source(case), 0

    monkeypatch.setattr(showcase, "_provider_json", stub_provider)
    monkeypatch.setattr(showcase, "_provider_code", stub_code)
    row = _run_case(
        case,
        mode="live",
        fallback_enabled=True,
        case_root=tmp_path / failure.split(":", 1)[0],
    )

    assert calls == ["dsl", "dsl", "python"]
    assert row["status"] == "passed"
    assert row["last_dsl_failure"] == failure
    assert row["final_backend"] == "python"
    assert row["python_attempts"] == 1
