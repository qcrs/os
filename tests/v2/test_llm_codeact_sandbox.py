from __future__ import annotations

import time
from dataclasses import replace

import pytest

from v2.contracts import CapabilityGrant, CodeGenerationPolicy, CodeGenerationRequest, GeneratedCodeCandidate, RefStatus
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.domain_packs import register_long_doc_analysis_capabilities
from v2.runtime.llm_codeact import CodePolicyError, LlmCodeActRunner
from v2.utils import sha256_digest


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


def test_llm_codeact_runs_only_in_nonroot_bwrap_and_signs_verified_artifact(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    request, grant = _request_and_grant()
    source = (
        "import json\n"
        "from pathlib import Path\n"
        "payload = json.loads(Path(\"inputs/task.json\").read_text(encoding=\"utf-8\"))\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": float(payload[\"value\"])}), encoding=\"utf-8\")\n"
    )
    outcome = LlmCodeActRunner(registry=registry).execute(
        request=request, grant=grant, raw_response=source, attempt_workspace=tmp_path,
        input_files={"inputs/task.json": b'{"value": 12}'},
    )
    assert outcome.record.sandbox_actual_backend == "bwrap"
    assert outcome.record.sandbox_uid != 0 and outcome.record.sandbox_gid != 0
    assert outcome.record.output_schema_valid
    assert outcome.artifact is not None
    assert outcome.artifact.verification_state == RefStatus.VERIFIED
    assert outcome.artifact.metadata["attempt_id"] == "attempt"
    assert outcome.output_payload == {"value": 12.0}


@pytest.mark.parametrize(
    "payload_expression, expected_error",
    [
        ("{}", "output_schema_fields_mismatch"),
        ('{"value": float("nan")}', "output_type:value"),
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


def test_llm_codeact_cache_requires_new_authorized_grant_and_compatible_signature(tmp_path) -> None:
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
    second_grant = replace(grant, grant_id="grant-2", attempt_id="attempt-2", expires_at_ns=time.time_ns() + 5_000_000_000)
    second_request = replace(request, attempt_id="attempt-2", capability_grant_hash=second_grant.grant_hash)
    cached = runner.execute(
        request=second_request, grant=second_grant, raw_response=source, attempt_workspace=tmp_path / "second",
        input_files={"inputs/task.json": b'{"value": 12}'},
    )
    assert cached.artifact is not None
    assert cached.record.fallback_reason == "verified_cache_hit"
    candidate = GeneratedCodeCandidate(
        request_hash="request", source=source, source_hash=sha256_digest(source.encode("utf-8")), raw_response_hash="raw",
    )
    assert runner.cache.key(request, candidate) != runner.cache.key(
        replace(request, policy=replace(request.policy, policy_version="changed")), candidate,
    )
    with pytest.raises(CodePolicyError, match="already_consumed"):
        runner.execute(
            request=second_request, grant=second_grant, raw_response=source, attempt_workspace=tmp_path / "third",
            input_files={"inputs/task.json": b'{"value": 12}'},
        )


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
