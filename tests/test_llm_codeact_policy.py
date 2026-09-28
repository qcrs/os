from __future__ import annotations

import time
from dataclasses import replace

import pytest

from statebus.contracts import CapabilityGrant, CodeGenerationPolicy, CodeGenerationRequest
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.codeact_sandbox import CodeActSandboxReadiness
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.llm_codeact import (
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
    assert "store only a finite int/float or None" in prompt
    assert "have no .isfinite() method" in prompt
    assert '`-float("inf") < value < float("inf")`' in prompt
    assert "Never preserve or reinsert the original string" in prompt
    assert "`metric_name` should use the task's canonical `metric` token" in prompt
    assert "omit comments, docstrings, unused imports, main wrappers, and one-use helpers" in prompt
    assert "Keep every required parsing, missing-value, calculation, and output-validation step" in prompt
    assert "120" not in prompt


def test_generation_and_repair_guidance_explain_regex_transport_and_forbidden_compile() -> None:
    policy = CodeGenerationPolicy(
        capability_id="extract_narrative_facts_python_v1",
        enabled=True,
        allowed_module_roots=("json", "pathlib", "re"),
    )
    request = CodeGenerationRequest(
        task_id="semantic-holdout-s1", step_id="execute", attempt_id="attempt",
        approved_plan_hash="plan", capability_grant_hash="grant",
        capability_id=policy.capability_id, input_ref_ids=("input",),
        input_manifest_digest="inputs", output_schema={"value": "string"},
        model_signature="model", prompt_signature="prompt", runtime_signature="runtime",
        policy=policy, operation_semantics={
            "operation": "extract_narrative_facts",
            "labeled_fact_algorithm": {"python_regex_template": "r'\\s+'"},
        },
    )

    prompt = build_code_generation_prompt(request)
    guidance = build_code_repair_guidance(
        ("forbidden_call:re.compile", "quality_error:output_type:value"),
        policy, operation_semantics=request.operation_semantics,
    )

    assert "Output JSON type validation is strict for these fields" in guidance
    assert '"value":"declared schema type"' in guidance
    assert "Do not leave a declared field null" in guidance
    assert "Apply each public fact selector independently" in guidance
    assert "(?:was|is)" in guidance
    for text in (prompt, guidance):
        assert "re.compile" in text
        assert "re.search or re.match" in text
        assert "one backslash" in text
        assert 'r"\\s+"' in text
        assert 'r"\\\\s+"' in text


def test_repair_guidance_replaces_path_open_with_literal_read_write_calls() -> None:
    policy = CodeGenerationPolicy(
        capability_id="extract_narrative_facts_python_v1",
        enabled=True,
        allowed_module_roots=("json", "pathlib", "re"),
        allowed_input_relpaths=("inputs/task.json",),
        output_relpath="outputs/result.json",
    )
    guidance = build_code_repair_guidance(
        (
            "forbidden_call:input_path.open",
            "forbidden_call:output_path.open",
            "missing_output_write",
        ),
        policy,
    )

    assert "Do not use open, Path.open" in guidance
    assert "Path('literal').read_text" in guidance
    assert "Path('literal').write_text" in guidance
    assert "literal write_text call" in guidance


def test_finite_number_guidance_works_without_an_allowed_math_import() -> None:
    policy = CodeGenerationPolicy(
        capability_id="bounded_metric_python_v1", enabled=True,
        allowed_module_roots=("json", "pathlib", "re", "statistics", "collections"),
    )
    request = CodeGenerationRequest(
        task_id="task", step_id="execute", attempt_id="attempt", approved_plan_hash="plan",
        capability_grant_hash="grant", capability_id=policy.capability_id,
        input_ref_ids=("input",), input_manifest_digest="inputs", output_schema={"value": "number"},
        model_signature="model", prompt_signature="prompt", runtime_signature="runtime", policy=policy,
    )
    prompt = build_code_generation_prompt(request)
    guidance = build_code_repair_guidance(
        ("runtime_error:AttributeError: 'float' object has no attribute 'isfinite'",), policy,
    )
    for text in (prompt, guidance):
        assert '`-float("inf") < value < float("inf")`' in text
        assert "Checking only inequality with infinities does not reject NaN" in text
        assert "import math" not in text


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


def test_generation_prompt_omits_empty_locator_only_retrieval_context() -> None:
    request = CodeGenerationRequest(
        task_id="task", step_id="execute", attempt_id="attempt", approved_plan_hash="plan",
        capability_grant_hash="grant-hash", capability_id="bounded_metric_python_v1",
        input_ref_ids=("verified-input",), input_manifest_digest="input-hash",
        output_schema={"value": "number"}, model_signature="model", prompt_signature="prompt",
        runtime_signature="runtime", policy=CodeGenerationPolicy(capability_id="bounded_metric_python_v1"),
        retrieval_context=(
            {
                "item_id": "locator-only",
                "bucket": "structured_evidence",
                "locator": "TableCellLocator(source_doc_hash='doc', row_idx=1, col_idx=2)",
                "text": "",
            },
            {
                "item_id": "semantic-text",
                "bucket": "semantic_context",
                "locator": "TableCellLocator(source_doc_hash='doc', row_idx=3, col_idx=4)",
                "text": "WINDSPEED is the requested metric.",
            },
        ),
    )

    prompt = build_code_generation_prompt(request)

    assert "locator-only" not in prompt
    assert "semantic-text" in prompt
    assert "WINDSPEED is the requested metric." in prompt
    assert request.retrieval_context[0]["item_id"] == "locator-only"


def test_generation_prompt_preserves_nonstandard_semantic_retrieval_fields() -> None:
    request = CodeGenerationRequest(
        task_id="task", step_id="execute", attempt_id="attempt", approved_plan_hash="plan",
        capability_grant_hash="grant-hash", capability_id="bounded_metric_python_v1",
        input_ref_ids=("verified-input",), input_manifest_digest="input-hash",
        output_schema={"value": "number"}, model_signature="model", prompt_signature="prompt",
        runtime_signature="runtime", policy=CodeGenerationPolicy(capability_id="bounded_metric_python_v1"),
        retrieval_context=({
            "item_id": "future-semantic-field",
            "bucket": "semantic_context",
            "locator": "",
            "text": "",
            "method_hint": "Use a monthly arithmetic mean.",
        },),
    )

    prompt = build_code_generation_prompt(request)

    assert "future-semantic-field" in prompt
    assert "Use a monthly arithmetic mean." in prompt


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


@pytest.mark.parametrize('name', ['executor_initial_raw.txt', 'executor_repair_1_raw.txt'])
def test_real_invalid_json_code_wrappers_are_not_python_syntax_errors(name):
    from pathlib import Path
    raw = (Path(__file__).parent / 'fixtures/contest_stage1_failures' / name).read_text()
    source = extract_python_source(raw)
    assert source.strip() == raw.strip()  # No quote guessing or executable patching.
    policy = CodeGenerationPolicy(capability_id='bounded_metric_python_v1', enabled=True)
    report = audit_generated_source(source, policy)
    assert not report.passed and len(report.violations) == 1
    assert report.violations[0].startswith('code_response_format:json_decode:line=2:column=')
    assert len(report.violations[0]) < 240
    assert 'complete raw Python file, NOT JSON' in build_code_repair_guidance(report.violations, policy)


@pytest.mark.parametrize('wrapper', ['raw', 'python', 'py', 'fence', 'json', 'json_fence'])
def test_all_valid_code_response_formats_preserve_source(wrapper):
    import json
    source = ('import json\nfrom pathlib import Path\n'
              'row=json.loads(Path("inputs/task.json").read_text())\n'
              'Path("outputs/result.json").write_text(json.dumps(row))\n')
    raw = {'raw': source, 'python': f'```python\n{source}```', 'py': f'```py\n{source}```',
           'fence': f'```\n{source}```', 'json': json.dumps({'code': source}),
           'json_fence': '```json\n' + json.dumps({'code': source}) + '\n```'}[wrapper]
    extracted = extract_python_source(raw)
    assert extracted == source
    assert audit_generated_source(extracted, CodeGenerationPolicy(capability_id='bounded_metric_python_v1')).passed


def test_python_syntax_diagnostic_is_bounded_and_does_not_include_source():
    policy = CodeGenerationPolicy(capability_id='bounded_metric_python_v1')
    report = audit_generated_source('for item in [1, 2]\n    pass\n', policy)
    assert not report.passed and report.violations[0].startswith('syntax_error:1:column=')
    assert 'expected' in report.violations[0] and 'for item' not in report.violations[0]
    assert 'complete raw Python file' in build_code_repair_guidance(report.violations, policy)


@pytest.mark.parametrize('raw', ['```json\n{"code": "pass"}', '{"code": 17}', '{"code":"pass","other":1}'])
def test_invalid_code_wrapper_structure_fails_closed(raw):
    report = audit_generated_source(extract_python_source(raw), CodeGenerationPolicy(capability_id='bounded_metric_python_v1'))
    assert not report.passed and report.violations[0].startswith('code_response_format:')


def _request_with_memory(memory_inputs):
    return CodeGenerationRequest(
        task_id="schema-transition", step_id="execute", attempt_id="attempt",
        approved_plan_hash="plan", capability_grant_hash="grant",
        capability_id="bounded_metric_python_v1", input_ref_ids=("current-input",),
        input_manifest_digest="inputs", output_schema={"net": "number"},
        model_signature="model", prompt_signature="prompt", runtime_signature="runtime",
        policy=CodeGenerationPolicy(capability_id="bounded_metric_python_v1"),
        task_goal="Compute net from booked minus refunds using current rows.",
        authorized_input_schema={"booked": "number", "refunds": "number"},
        memory_inputs=memory_inputs,
    )


def test_memory_prompt_retains_methods_and_drift_without_duplicate_code_or_authority_payload():
    import copy
    source = "old_net = sum(row['net_revenue'] for row in rows)\n"
    recipe = {
        "execution_kind": "llm_bounded_python", "source": source,
        "source_hash": "runtime-only-source-hash", "validator_digest": "runtime-only-validator",
    }
    memory = tuple({
        "ref_id": f"memory:round-{index}", "source_task_id": f"round-{index}",
        "summary": "Group current rows by unit before calculating the ratio.",
        "replay_class": "assist", "compatibility_verdict": "degraded",
        "compatibility_reasons": ["input_schema_drift"],
        "artifact_lineage": {"artifact_root_id": "/private/old-run", "old_result": 999999},
        "memory_admission_receipt_hash": "runtime-only-receipt",
        "input_payload_hash": f"runtime-only-payload-{index}",
        "execution_recipe": recipe,
    } for index in range(2))
    before = copy.deepcopy(memory)
    request = _request_with_memory(memory)
    prompt = build_code_generation_prompt(request)

    assert prompt.count("old_net =") == 1
    assert "execution_recipe_ref" in prompt
    for item in memory:
        assert item["ref_id"] in prompt
    assert "input_schema_drift" in prompt and '"replay_class":"assist"' in prompt
    assert "old field names or formulas never override the current contract" in prompt
    assert "booked minus refunds" in prompt
    for excluded in ("/private/old-run", "999999", "runtime-only"):
        assert excluded not in prompt
    assert request.memory_inputs == before  # Runtime still receives the full inputs.


def test_memory_prompt_dedup_uses_content_not_claimed_hash():
    from statebus.runtime.memory_projection import provider_visible_memory_inputs
    memory = tuple({
        "ref_id": f"memory:{index}", "execution_recipe_hash": "same-claimed-hash",
        "execution_recipe": {"source": source, "source_hash": "same-claimed-source-hash"},
    } for index, source in enumerate(("total = sum(rows)", "total = max(rows)")))
    projected = provider_visible_memory_inputs(memory)
    assert [item["execution_recipe"]["source"] for item in projected] == [
        "total = sum(rows)", "total = max(rows)",
    ]


def test_memory_repair_prompt_keeps_decisions_and_current_contract_without_old_source():
    request = _request_with_memory(({
        "ref_id": "memory:previous", "summary": "Aggregate by unit.",
        "replay_class": "assist", "compatibility_reasons": ["input_schema_drift"],
        "execution_recipe": {"source": "obsolete_field = row['old_name']\n"},
    },))
    prompt = build_code_generation_prompt(request, include_memory_recipes=False)
    for required in ("memory:previous", "Aggregate by unit.", "input_schema_drift", "booked minus refunds"):
        assert required in prompt
    assert "obsolete_field" not in prompt
    assert "obsolete_field" in build_code_generation_prompt(request)
    empty = replace(request, memory_inputs=())
    assert build_code_generation_prompt(empty) == build_code_generation_prompt(empty, include_memory_recipes=False)
