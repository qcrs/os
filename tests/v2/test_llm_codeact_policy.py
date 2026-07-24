from __future__ import annotations

import time
from dataclasses import replace

import pytest

from v2.contracts import CapabilityGrant, CodeGenerationPolicy, CodeGenerationRequest
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.codeact_sandbox import CodeActSandboxReadiness
from v2.runtime.domain_packs import register_long_doc_analysis_capabilities
from v2.runtime.llm_codeact import (
    CodePolicyError,
    LlmCodeActRunner,
    audit_generated_source,
    build_code_repair_guidance,
    build_code_generation_prompt,
    extract_python_source,
)


def test_code_extraction_and_ast_policy_reject_network_and_parent_paths() -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    source = extract_python_source("```python\nimport socket\nPath('../bad')\n```")
    report = audit_generated_source(source, policy)
    assert not report.passed
    assert any("socket" in violation for violation in report.violations)
    assert "absolute_or_parent_path_literal" in report.violations


def test_code_extraction_accepts_a_json_code_object_inside_a_json_fence() -> None:
    raw = "```json\n{\"code\": \"import json\\nfrom pathlib import Path\\n\"}\n```"

    assert extract_python_source(raw) == "import json\nfrom pathlib import Path\n"


def test_generation_prompt_carries_controller_owned_analysis_semantics_without_input_values() -> None:
    policy = CodeGenerationPolicy(capability_id="compare_periods_python_v1", enabled=True)
    request = CodeGenerationRequest(
        task_id="task", step_id="compare", attempt_id="attempt", approved_plan_hash="plan",
        capability_grant_hash="grant-hash", capability_id="compare_periods_python_v1",
        input_ref_ids=("verified-input",), input_manifest_digest="input-hash",
        output_schema={"difference": "number"}, model_signature="model", prompt_signature="prompt",
        runtime_signature="runtime", policy=policy,
        task_goal="compare the earliest and latest authorized periods",
        operation_semantics={"operation": "compare_periods", "period_field": "quarter", "value_field": "revenue"},
        completion_criteria={"min_rows": 1}, output_contract_version="statebus.comparison.v1",
        validator_id="period_comparison", quality_constraints={"recompute_from_authorized_rows": True},
        authorized_input_schema={"quarter": "string", "revenue": "number"},
        expected_output_shape="object", provenance_item_ids=("evidence-row",),
    )
    prompt = build_code_generation_prompt(request)
    for text in ("Task goal:", "Operation semantics:", "Completion criteria:", "Validator ID: period_comparison", "Authorized input schema:"):
        assert text in prompt
    assert "Path.open" in prompt
    assert "Do not use open or Path.open" in prompt
    assert "exactly a top-level array of authorized row objects" in prompt
    assert "must never be opened" in prompt
    assert "String replacement is allowed only for in-memory text parsing" in prompt
    assert "Path.replace and every filesystem rename/replace operation remain forbidden" in prompt
    assert "Every referenced name must be a Python builtin, explicitly imported, or defined" in prompt
    assert "source profile reports missing_count greater than zero as nullable" in prompt
    assert "Preserving a row with None does not authorize passing None" in prompt
    assert "`metric_name` should use the task's canonical `metric` token" in prompt
    assert "120" not in prompt


def test_generation_prompt_requires_controller_owned_canonical_array_order() -> None:
    policy = CodeGenerationPolicy(capability_id="detect_anomaly_python_v1", enabled=True)
    request = CodeGenerationRequest(
        task_id="task", step_id="anomaly", attempt_id="attempt", approved_plan_hash="plan",
        capability_grant_hash="grant-hash", capability_id="detect_anomaly_python_v1",
        input_ref_ids=("verified-input",), input_manifest_digest="input-hash",
        output_schema={"quarter": "string", "is_anomaly": "boolean"}, model_signature="model",
        prompt_signature="prompt", runtime_signature="runtime", policy=policy,
        quality_constraints={"ordered_output_by": "quarter"}, expected_output_shape="array",
    )

    prompt = build_code_generation_prompt(request)

    assert "sort every output object in ascending lexical order by `quarter`" in prompt


def test_formal_llm_codeact_fails_closed_when_bwrap_not_ready(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1", enabled=True, allowed_input_relpaths=("inputs/task.json",),
        output_relpath="outputs/result.json", output_required_fields=("value",),
    )
    grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="bounded_metric_python_v1", capability_version="v1", input_ref_ids=("input",),
        output_contract_version="statebus.metric_series.v1", workspace_root_id="workspace", max_runtime_ms=1000,
        expires_at_ns=time.time_ns() + 1_000_000_000, approved_plan_hash="plan",
    )
    request = CodeGenerationRequest(
        task_id="task", step_id="step", attempt_id="attempt", approved_plan_hash="plan", capability_grant_hash=grant.grant_hash,
        capability_id="bounded_metric_python_v1", input_ref_ids=("input",), input_manifest_digest="inputs",
        output_schema={"value": "number"}, model_signature="model", prompt_signature="prompt", runtime_signature="runtime", policy=policy,
    )

    class FailingSandbox:
        def check_llm_bwrap_readiness(self, *, policy_version):
            return CodeActSandboxReadiness(False, "bwrap_failed", 65534, 65534, policy_version, reason="namespace_denied")

    outcome = LlmCodeActRunner(registry=registry, sandbox_runner=FailingSandbox()).execute(
        request=request, grant=grant,
        raw_response='import json\nfrom pathlib import Path\npayload=json.loads(Path("inputs/task.json").read_text())\nPath("outputs/result.json").write_text(json.dumps({"value":1}))\n',
        attempt_workspace=tmp_path, input_files={"inputs/task.json": b"{}"},
    )
    assert outcome.artifact is None
    assert outcome.record.sandbox_actual_backend == "bwrap_failed"
    assert outcome.record.fallback_reason.startswith("bwrap_not_ready")
    assert outcome.record.sandbox_actual_backend not in {"resource", "none"}
    repaired = LlmCodeActRunner(registry=registry, sandbox_runner=FailingSandbox()).execute(
        request=request, grant=grant, raw_response="result = {}\n", attempt_workspace=tmp_path / "repair",
        input_files={"inputs/task.json": b"{}"},
        repair_source=lambda previous_source, violations: (
            "import json\nfrom pathlib import Path\n"
            "payload=json.loads(Path(\"inputs/task.json\").read_text())\n"
            "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": 1}))\n"
        ),
    )
    assert len(repaired.repairs) == 1
    assert repaired.record.fallback_reason.startswith("bwrap_not_ready")

    policy_repair_calls = 0

    def still_invalid(previous_source: str, violations: tuple[str, ...]) -> str:
        nonlocal policy_repair_calls
        assert previous_source
        policy_repair_calls += 1
        return "import json\n"

    policy_rejected = LlmCodeActRunner(
        registry=registry, sandbox_runner=FailingSandbox()
    ).execute(
        request=request,
        grant=grant,
        raw_response="result = {}\n",
        attempt_workspace=tmp_path / "repair-budget",
        input_files={"inputs/task.json": b"{}"},
        repair_source=still_invalid,
    )
    assert policy_repair_calls == 1
    assert sum(not item.fallback_used for item in policy_rejected.repairs) == 1
    assert policy_rejected.record.fallback_reason == "code_policy_rejected"


def test_code_policy_accepts_repair_target_but_rejects_initial_source() -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    first = audit_generated_source("result = {}\n", policy)
    repaired = audit_generated_source(
        "import json\nfrom pathlib import Path\n"
        "payload=json.loads(Path(\"inputs/task.json\").read_text())\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({\"value\": 1}))\n",
        policy,
    )
    assert not first.passed
    assert repaired.passed


def test_code_policy_reports_undefined_names_before_sandbox_execution() -> None:
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1",
        enabled=True,
        allowed_module_roots=("json", "pathlib", "re"),
    )
    source = (
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "value=re.sub(',', '', rows[0]['value'])\n"
        "Path('outputs/result.json').write_text(json.dumps({'value': value}), encoding='utf-8')\n"
    )

    report = audit_generated_source(source, policy)

    assert not report.passed
    assert "undefined_name:re" in report.violations
    guidance = build_code_repair_guidance(report.violations, policy)
    assert "`import re`" in guidance


def test_runtime_name_error_guidance_does_not_expand_import_authority() -> None:
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1",
        enabled=True,
        allowed_module_roots=("json", "pathlib"),
    )

    guidance = build_code_repair_guidance(
        ("runtime_error:NameError: name 'helper' is not defined",),
        policy,
    )

    assert "Define `helper` before its first use" in guidance
    assert "do not assume hidden globals or add an unauthorized import" in guidance


def test_leading_numeric_text_policy_rejects_full_cell_digit_concatenation() -> None:
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1",
        enabled=True,
        numeric_text_mode="leading_token",
    )
    unsafe = audit_generated_source(
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "value=float(''.join(ch for ch in rows[0]['value'] if ch.isdigit()))\n"
        "Path('outputs/result.json').write_text(json.dumps({'value': value}), encoding='utf-8')\n",
        policy,
    )
    safe = audit_generated_source(
        "import json\nimport re\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "match=re.match(r'^[-+]?[0-9]+(?:[.][0-9]+)?', rows[0]['value'])\n"
        "value=float(match.group(0))\n"
        "Path('outputs/result.json').write_text(json.dumps({'value': value}), encoding='utf-8')\n",
        replace(policy, allowed_module_roots=("json", "pathlib", "re")),
    )

    assert "unsafe_full_string_digit_concatenation" in unsafe.violations
    assert safe.passed, safe.violations


def test_code_policy_allows_in_memory_string_replace() -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    report = audit_generated_source(
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "value=float(rows[0]['value'].replace(',', ''))\n"
        "Path('outputs/result.json').write_text(json.dumps({'value': value}), encoding='utf-8')\n",
        policy,
    )

    assert report.passed, report.violations


@pytest.mark.parametrize(
    "source",
    [
        (
            "import json\nfrom pathlib import Path\n"
            "Path('inputs/task.json').replace('outputs/result.json')\n"
            "Path('outputs/result.json').write_text(json.dumps({}), encoding='utf-8')\n"
        ),
        (
            "import json\nfrom pathlib import Path\n"
            "source_path=Path('inputs/task.json')\n"
            "source_path.replace('outputs/result.json')\n"
            "Path('outputs/result.json').write_text(json.dumps({}), encoding='utf-8')\n"
        ),
        (
            "import json\nfrom pathlib import Path as P\n"
            "P('inputs/task.json').replace('outputs/result.json')\n"
            "P('outputs/result.json').write_text(json.dumps({}), encoding='utf-8')\n"
        ),
        (
            "import json\nimport pathlib as pl\n"
            "source_path=pl.Path('inputs/task.json')\n"
            "nested_path=source_path.parent / 'renamed.json'\n"
            "nested_path.replace('outputs/result.json')\n"
            "pl.Path('outputs/result.json').write_text(json.dumps({}), encoding='utf-8')\n"
        ),
        (
            "import json\nfrom pathlib import Path as P\n"
            "(P('inputs/task.json').parent / 'renamed.json').replace('outputs/result.json')\n"
            "P('outputs/result.json').write_text(json.dumps({}), encoding='utf-8')\n"
        ),
    ],
)
def test_code_policy_rejects_filesystem_path_replace(source: str) -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    report = audit_generated_source(source, policy)

    assert not report.passed
    assert "forbidden_path_attribute:replace" in report.violations


def test_code_policy_repair_budgets_are_explicit_and_bounded() -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)

    assert policy.max_policy_repairs == 1
    assert policy.max_runtime_repairs == 1
    assert policy.max_quality_repairs == 1
    assert policy.canonical_payload()["max_policy_repairs"] == 1
    assert policy.canonical_payload()["max_runtime_repairs"] == 1
    assert policy.canonical_payload()["max_quality_repairs"] == 1
    with pytest.raises(CodePolicyError, match="invalid_policy_repair_budget"):
        LlmCodeActRunner._validate_policy_paths(replace(policy, max_policy_repairs=2))
    with pytest.raises(CodePolicyError, match="invalid_runtime_repair_budget"):
        LlmCodeActRunner._validate_policy_paths(replace(policy, max_runtime_repairs=2))
    with pytest.raises(CodePolicyError, match="invalid_quality_repair_budget"):
        LlmCodeActRunner._validate_policy_paths(replace(policy, max_quality_repairs=2))


def test_code_policy_rejects_input_mutation_and_reflection() -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    report = audit_generated_source(
        "import json\nfrom pathlib import Path\n"
        "Path(\"inputs/task.json\").unlink()\n"
        "Path(\"outputs/result.json\").write_text(json.dumps({}))\n",
        policy,
    )
    # unlink must be rejected before sandbox execution; it is added to the policy below.
    assert not report.passed


@pytest.mark.parametrize(
    "source, expected",
    [
        ("import json\nfrom pathlib import Path\nPath.cwd()\nPath(\"outputs/result.json\").write_text(json.dumps({}))\n", "forbidden_attribute:cwd"),
        ("import json\nfrom pathlib import Path\nprint(__file__)\nPath(\"outputs/result.json\").write_text(json.dumps({}))\n", "forbidden_name:__file__"),
        ("import json\nfrom pathlib import Path\nclass Escape: pass\nPath(\"outputs/result.json\").write_text(json.dumps({}))\n", "forbidden_ast_node:ClassDef"),
        ("import threading\nfrom pathlib import Path\nPath(\"outputs/result.json\").write_text(\"{}\")\n", "forbidden_import:threading"),
        ("import multiprocessing\nfrom pathlib import Path\nPath(\"outputs/result.json\").write_text(\"{}\")\n", "forbidden_import:multiprocessing"),
    ],
)
def test_code_policy_rejects_path_introspection_classes_and_concurrency(source: str, expected: str) -> None:
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    report = audit_generated_source(source, policy)
    assert not report.passed
    assert expected in report.violations


def test_code_request_rejects_cross_attempt_plan_and_unsafe_workspace_policy(tmp_path) -> None:
    registry = CapabilityRegistry()
    register_long_doc_analysis_capabilities(registry)
    policy = CodeGenerationPolicy(capability_id="bounded_metric_python_v1", enabled=True)
    grant = CapabilityGrant(
        grant_id="grant", task_id="task", session_id="session", step_id="step", attempt_id="attempt",
        capability_id="bounded_metric_python_v1", capability_version="v1", input_ref_ids=("input",),
        output_contract_version="statebus.metric_series.v1", workspace_root_id="workspace", max_runtime_ms=1_000,
        expires_at_ns=time.time_ns() + 1_000_000_000, approved_plan_hash="plan",
    )
    request = CodeGenerationRequest(
        task_id="task", step_id="step", attempt_id="attempt", approved_plan_hash="plan", capability_grant_hash=grant.grant_hash,
        capability_id="bounded_metric_python_v1", input_ref_ids=("input",), input_manifest_digest="inputs",
        output_schema={"value": "number"}, model_signature="model", prompt_signature="prompt", runtime_signature="runtime", policy=policy,
        session_id="session",
    )
    runner = LlmCodeActRunner(registry=registry)
    with pytest.raises(CodePolicyError, match="approved_plan_hash_mismatch"):
        runner.execute(
            request=replace(request, approved_plan_hash="other"), grant=grant, raw_response="", attempt_workspace=tmp_path,
            input_files={"inputs/task.json": b"{}"},
        )
    with pytest.raises(CodePolicyError, match="unsafe_output_path_policy"):
        LlmCodeActRunner(registry=registry).execute(
            request=replace(request, policy=replace(policy, output_relpath="../escape.json")), grant=grant, raw_response="",
            attempt_workspace=tmp_path / "unsafe", input_files={"inputs/task.json": b"{}"},
        )
    ordered_grant = replace(
        grant,
        grant_id="ordered-inputs",
        input_ref_ids=("first", "second"),
    )
    reordered_request = replace(
        request,
        capability_grant_hash=ordered_grant.grant_hash,
        input_ref_ids=("second", "first"),
    )
    with pytest.raises(CodePolicyError, match="grant_input_refs_mismatch"):
        LlmCodeActRunner(registry=registry).execute(
            request=reordered_request,
            grant=ordered_grant,
            raw_response="",
            attempt_workspace=tmp_path / "reordered",
            input_files={"inputs/task.json": b"{}"},
        )
