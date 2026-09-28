from __future__ import annotations

import time
from dataclasses import replace

import pytest

from statebus.contracts import CapabilityGrant, CodeGenerationPolicy, CodeGenerationRequest, RefStatus
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.llm_codeact import CodePolicyError, LlmCodeActRunner, audit_generated_source


def _request_and_grant() -> tuple[CodeGenerationRequest, CapabilityGrant]:
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1", enabled=True, require_bwrap=True,
        allowed_input_relpaths=("inputs/task.json",), output_relpath="outputs/result.json",
        output_required_fields=("value",),
    )
    grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="bounded_metric_python_v1", capability_version="v1", input_ref_ids=("input",),
        output_contract_version="statebus.metric_series.v1", workspace_root_id="workspace", max_runtime_ms=5_000,
        expires_at_ns=time.time_ns() + 5_000_000_000, approved_plan_hash="plan",
    )
    request = CodeGenerationRequest(
        task_id="task", step_id="step", attempt_id="attempt", approved_plan_hash="plan", capability_grant_hash=grant.grant_hash,
        capability_id="bounded_metric_python_v1", input_ref_ids=("input",), input_manifest_digest="input-manifest",
        output_schema={"value": "number"}, model_signature="deterministic", prompt_signature="prompt", runtime_signature="runtime", policy=policy,
    )
    return request, grant


@pytest.mark.parametrize(
    "payload_expression, expected_error",
    [
        ("{}", "output_schema_fields_mismatch"),
        ('{"value": float("nan")}', "output_type:value"),
        ('{"value": float("inf")}', "output_type:value"),
        ('{"value": float("-inf")}', "output_type:value"),
        ('{"value": True}', "output_type:value"),
    ],
)
def test_llm_codeact_rejects_invalid_or_nonfinite_output_after_bwrap(tmp_path, payload_expression: str, expected_error: str) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    source = (
        "import json\nfrom pathlib import Path\n"
        "marker = Path(\"inputs/task.json\").read_text()\n"
        f"Path(\"outputs/result.json\").write_text(json.dumps({payload_expression}))\n"
    )
    outcome = LlmCodeActRunner(registry=registry).execute(
        request=request, grant=grant, raw_response=source, attempt_workspace=tmp_path,
        input_files={"inputs/task.json": b"{}"},
    )
    assert outcome.artifact is None
    assert expected_error in outcome.record.validator_errors
    assert outcome.record.sandbox_actual_backend == "bwrap"


def test_llm_codeact_repairs_output_type_failure_once_with_exact_fields(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    request = replace(
        request,
        output_schema={"value": "string", "locator": "string"},
        policy=replace(
            request.policy,
            output_required_fields=("value", "locator"),
            allowed_module_roots=("json", "pathlib"),
        ),
    )
    failing_source = (
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "Path('outputs/result.json').write_text(json.dumps({'value':None,'locator':None}), encoding='utf-8')\n"
    )
    repaired_source = (
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "Path('outputs/result.json').write_text(json.dumps({'value':rows[0]['value'],'locator':rows[0]['locator']}), encoding='utf-8')\n"
    )
    calls: list[tuple[str, tuple[str, ...]]] = []

    def repair(previous: str, diagnostics: tuple[str, ...]) -> str:
        calls.append((previous, diagnostics))
        return repaired_source

    outcome = LlmCodeActRunner(registry=registry).execute(
        request=request,
        grant=grant,
        raw_response=failing_source,
        attempt_workspace=tmp_path,
        input_files={"inputs/task.json": b'[{"value":"North Coast corridor","locator":"Market signal"}]'},
        repair_source=repair,
    )

    assert calls == [(failing_source, (
        "quality_error:output_type:locator",
        "quality_error:output_type:value",
    ))]
    assert outcome.artifact is not None
    assert outcome.output_payload == {"value": "North Coast corridor", "locator": "Market signal"}
    assert len(outcome.repairs) == 1
    assert outcome.repairs[0].repair_kind == "quality"
    assert outcome.repairs[0].diagnostic == "output_type:locator,output_type:value"
    assert outcome.artifact.root_id.endswith("-quality-repair-1")


def test_llm_codeact_keeps_output_validation_failure_after_bounded_repair(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    failing_source = (
        "import json\nfrom pathlib import Path\n"
        "marker=Path('inputs/task.json').read_text(encoding='utf-8')\n"
        "Path('outputs/result.json').write_text(json.dumps({'value':None}), encoding='utf-8')\n"
    )
    calls = 0

    def repair(_previous: str, diagnostics: tuple[str, ...]) -> str:
        nonlocal calls
        calls += 1
        assert diagnostics == ("quality_error:output_type:value",)
        return failing_source

    outcome = LlmCodeActRunner(registry=registry).execute(
        request=request,
        grant=grant,
        raw_response=failing_source,
        attempt_workspace=tmp_path,
        input_files={"inputs/task.json": b"{}"},
        repair_source=repair,
    )

    assert calls == 1
    assert outcome.artifact is None
    assert outcome.record.fallback_reason == "output_validation_failed"
    assert outcome.record.validator_errors == ("output_type:value",)
    assert len(outcome.repairs) == 1
    assert outcome.repairs[0].repair_kind == "quality"


def test_no_import_finite_normalization_preserves_nullable_cells_in_bwrap(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    request = replace(
        request, output_schema={"value": "number", "missing_count": "integer"},
        policy=replace(request.policy, allowed_module_roots=("json", "pathlib")),
    )
    source = (
        "import json\nfrom pathlib import Path\n"
        "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "output = []\n"
        "for row in rows:\n"
        "    raw = row['value']\n"
        "    value = None\n"
        "    if raw is not None and not isinstance(raw, bool):\n"
        "        try:\n"
        "            value = float(raw)\n"
        "        except (ValueError, TypeError):\n"
        "            value = None\n"
        "    if value is not None and not (-float('inf') < value < float('inf')):\n"
        "        value = None\n"
        "    output.append(value)\n"
        "result = {'value': sum(value for value in output if value is not None), "
        "'missing_count': sum(value is None for value in output)}\n"
        "Path('outputs/result.json').write_text(json.dumps(result), encoding='utf-8')\n"
    )
    assert audit_generated_source(source, request.policy).passed
    runner = LlmCodeActRunner(registry=registry)
    source_path, inputs_dir, outputs_dir = runner._materialize_attempt(
        attempt_workspace=tmp_path, policy=request.policy, source=source,
        input_files={"inputs/task.json": (
            b'[{"value":0},{"value":-3},{"value":"1.25e2"},{"value":null},'
            b'{"value":"bad"},{"value":"NaN"},{"value":"inf"},{"value":"-inf"},{"value":true}]'
        )},
    )
    # Exercise parsing and schema validation, not metric-series row selection.
    outcome = runner._sandbox_for_policy(request.policy).run_llm_bwrap(
        source_path=source_path, inputs_dir=inputs_dir, outputs_dir=outputs_dir,
        policy_version=request.policy.sandbox_policy_version,
    )
    assert outcome.actual_backend == "bwrap"
    assert outcome.completed.returncode == 0, outcome.completed.stderr
    payload, errors, _ = runner._validate_output(outputs_dir, request)
    assert not errors
    assert payload == {"value": 122.0, "missing_count": 6}


def test_llm_codeact_producer_returns_candidate_and_does_not_reuse_legacy_verified_cache(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    source = (
        "import json\nfrom pathlib import Path\n"
        "payload=json.loads(Path(\"inputs/task.json\").read_text())\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": float(payload[\"value\"])}))\n"
    )
    runner = LlmCodeActRunner(registry=registry)
    first = runner.execute(
        request=request, grant=grant, raw_response=source, attempt_workspace=tmp_path / "first",
        input_files={"inputs/task.json": b'{"value": 12}'},
    )
    assert first.artifact is not None
    assert first.record.sandbox_actual_backend == "bwrap"
    assert first.record.sandbox_uid != 0 and first.record.sandbox_gid != 0
    assert first.record.output_schema_valid
    assert first.artifact.verification_state == RefStatus.CANDIDATE
    assert first.record.verified_artifact_id == ""
    assert first.artifact.metadata["attempt_id"] == "attempt"
    assert first.output_payload == {"value": 12.0}
    second_grant = replace(grant, grant_id="grant-2", attempt_id="attempt-2", expires_at_ns=time.time_ns() + 5_000_000_000)
    second_request = replace(request, attempt_id="attempt-2", capability_grant_hash=second_grant.grant_hash)
    cached = runner.execute(
        request=second_request, grant=second_grant, raw_response=source, attempt_workspace=tmp_path / "second",
        input_files={"inputs/task.json": b'{"value": 12}'},
    )
    assert cached.artifact is not None
    assert cached.artifact.verification_state == RefStatus.CANDIDATE
    assert cached.record.fallback_reason == ""
    assert cached.record.verified_artifact_id == ""
    assert cached.output_payload == {"value": 12.0}
    with pytest.raises(CodePolicyError, match="already_consumed"):
        runner.execute(
            request=second_request, grant=second_grant, raw_response=source, attempt_workspace=tmp_path / "third",
            input_files={"inputs/task.json": b'{"value": 12}'},
        )


def test_accepted_repaired_source_reexecutes_new_input_without_generation(tmp_path) -> None:
    from statebus.utils import sha256_digest
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    source = (
        "import json\nfrom pathlib import Path\n"
        "row=json.loads(Path('inputs/task.json').read_text())\n"
        "Path('outputs/result.json').write_text(json.dumps({'value':row['value']}))\n"
    )
    runner = LlmCodeActRunner(registry=registry)
    first = runner.execute(
        request=request, grant=grant, raw_response="result = {}\n", attempt_workspace=tmp_path / "producer",
        input_files={"inputs/task.json": b'{"value":12}'}, repair_source=lambda *_: source,
    )
    assert first.artifact is not None and len(first.repairs) == 1
    assert first.accepted_source == source
    assert sha256_digest(first.accepted_source.encode()) == first.record.source_hash
    second_grant = replace(grant, grant_id="new-grant", attempt_id="new-input", expires_at_ns=time.time_ns() + 5_000_000_000)
    second_request = replace(request, attempt_id="new-input", capability_grant_hash=second_grant.grant_hash)
    second = runner.execute(
        request=second_request, grant=second_grant, raw_response=first.accepted_source,
        attempt_workspace=tmp_path / "consumer", input_files={"inputs/task.json": b'{"value":37}'},
        repair_source=lambda *_: pytest.fail("validated source unexpectedly required generation"),
    )
    assert second.artifact is not None and not second.repairs
    assert first.output_payload == {"value": 12} and second.output_payload == {"value": 37}


def test_llm_codeact_bwrap_keeps_inputs_read_only_and_enforces_timeout(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    mutation_source = (
        "import json\nfrom pathlib import Path\n"
        "Path(\"inputs/task.json\").write_text(\"mutated\")\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": 1}))\n"
    )
    mutation = LlmCodeActRunner(registry=registry).execute(
        request=request, grant=grant, raw_response=mutation_source, attempt_workspace=tmp_path / "readonly",
        input_files={"inputs/task.json": b'{"value": 12}'},
    )
    assert mutation.artifact is None
    assert mutation.record.sandbox_actual_backend == "bwrap"
    assert (tmp_path / "readonly" / "inputs" / "task.json").read_bytes() == b'{"value": 12}'

    timeout_grant = replace(grant, grant_id="timeout", attempt_id="timeout", expires_at_ns=time.time_ns() + 5_000_000_000)
    timeout_policy = replace(request.policy, timeout_seconds=1.0, cpu_seconds=5)
    timeout_request = replace(request, attempt_id="timeout", capability_grant_hash=timeout_grant.grant_hash, policy=timeout_policy)
    timeout_source = (
        "import json\nfrom pathlib import Path\n"
        "marker = Path(\"inputs/task.json\").read_text()\n"
        "while True:\n    pass\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": 1}))\n"
    )
    timed_out = LlmCodeActRunner(registry=registry).execute(
        request=timeout_request, grant=timeout_grant, raw_response=timeout_source, attempt_workspace=tmp_path / "timeout",
        input_files={"inputs/task.json": b"{}"},
    )
    assert timed_out.artifact is None
    assert timed_out.record.timeout
    assert timed_out.record.sandbox_actual_backend == "bwrap"


def test_llm_output_validator_rejects_extra_symlink_and_non_json_outputs(tmp_path) -> None:
    request, _ = _request_and_grant()
    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "result.json").write_text('{"value": 1}', encoding="utf-8")
    (outputs / "extra.json").write_text("{}", encoding="utf-8")
    _, errors, _ = LlmCodeActRunner._validate_output(outputs, request)
    assert "unauthorized_extra_output" in errors
    (outputs / "extra.json").unlink()
    (outputs / "result.json").unlink()
    (outputs / "result.json").symlink_to("/etc/passwd")
    _, errors, _ = LlmCodeActRunner._validate_output(outputs, request)
    assert errors == ("missing_or_symlink_output",)


def test_codeact_policy_transfers_cpu_memory_file_and_nproc_limits() -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1", enabled=True, timeout_seconds=3.0, cpu_seconds=2,
        address_space_bytes=64 * 1024 * 1024, file_size_bytes=4_096, nofile_limit=17, nproc_limit=23,
        max_output_bytes=1_024,
    )
    sandbox = LlmCodeActRunner(registry=registry)._sandbox_for_policy(policy)
    assert sandbox.config.timeout_seconds == 3.0
    assert sandbox.config.cpu_seconds == 2
    assert sandbox.config.address_space_bytes == 64 * 1024 * 1024
    assert sandbox.config.file_size_bytes == 4_096
    assert sandbox.config.nofile_limit == 17
    assert sandbox.config.llm_nproc_limit == 23


@pytest.mark.parametrize('fixed', [True, False])
def test_malformed_wrapper_uses_existing_policy_repair_before_any_execution(tmp_path, fixed):
    from pathlib import Path
    fixtures = Path(__file__).parent / 'fixtures/contest_stage1_failures'
    raw = (fixtures / 'executor_initial_raw.txt').read_text()
    bad_repair = (fixtures / 'executor_repair_1_raw.txt').read_text()
    request, grant = _request_and_grant()
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    source = ("import json\nfrom pathlib import Path\n"
              "row=json.loads(Path('inputs/task.json').read_text())\n"
              "Path('outputs/result.json').write_text(json.dumps({'value':row['value']}))\n")
    calls = []
    def repair(previous, violations):
        calls.append(violations)
        assert previous.strip() == raw.strip()
        assert violations[0].startswith('code_response_format:json_decode:')
        return source if fixed else bad_repair
    outcome = LlmCodeActRunner(registry=registry).execute(
        request=request, grant=grant, raw_response=raw, attempt_workspace=tmp_path,
        input_files={'inputs/task.json': b'{"value": 73}'}, repair_source=repair)
    assert len(calls) == 1
    assert sum(not r.fallback_used for r in outcome.repairs) == 1
    assert all(r.repair_kind == 'policy' for r in outcome.repairs)
    if fixed:
        assert outcome.artifact is not None and outcome.output_payload == {'value': 73}
        assert outcome.accepted_source == source and outcome.record.sandbox_actual_backend == 'bwrap'
    else:
        assert outcome.artifact is None and outcome.accepted_source == ''
        assert outcome.record.fallback_reason == 'code_policy_rejected'
        assert outcome.policy_report.violations[0].startswith('code_response_format:json_decode:')
        assert not (tmp_path / 'outputs').exists()
