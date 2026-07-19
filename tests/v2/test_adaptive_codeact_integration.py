from __future__ import annotations

from dataclasses import replace
import time

from v2.contracts import (
    AdaptiveTaskEnvelope,
    CapabilityGrant,
    CodeExecutionRecord,
    CodeGenerationPolicy,
    CodePolicyReport,
    EvidenceCoverageStatus,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    RiskClass,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from v2.refs import CanonicalEvidencePack, EvidenceItem, ExecutionArtifactRef, TableCellLocator
from v2.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    StoredAdaptiveArtifact,
)
from v2.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.domain_packs import (
    register_generic_adaptive_analysis_capabilities,
    register_long_doc_analysis_capabilities,
)
from v2.runtime.driver import RuntimeDriver
from v2.runtime.llm_codeact import LlmCodeActOutcome
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.utils import sha256_digest, stable_json_dumps


def _approved_codeact_plan(*, fallback: bool = False):
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="code-task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(sorted({registry.get(item).output_contract_version for item in pack.capability_ids})),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
    )
    proposal = PlanProposal(
        proposal_id="code-proposal",
        task_id="code-task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="code",
                role="executor",
                capability_id="bounded_metric_python_v1",
                goal="copy the verified metric row through the registered bounded Python capability",
                input_ref_ids=("input",),
                input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.metric_series.v1",
                on_failure="fallback_deterministic" if fallback else "fail",
            ),
            PlanStepProposal(
                step_id="report",
                role="summarizer",
                capability_id="compose_cited_report_v1",
                goal="publish a cited report from the verified metric artifact",
                depends_on=("code",),
                input_ref_ids=("evidence",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        proposal,
        envelope,
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
    )
    approved = outcome.approved_plan
    assert approved is not None, outcome.report.canonical_payload()
    return registry, envelope, approved


def _input_artifact(tmp_path) -> StoredAdaptiveArtifact:
    rows = ({"quarter": "2026Q1", "revenue_musd": 120.0},)
    payload = stable_json_dumps(list(rows)).encode("utf-8")
    path = tmp_path / "input.json"
    path.write_bytes(payload)
    artifact = ExecutionArtifactRef(
        artifact_id="input",
        task_id="code-task",
        step_id="upstream",
        artifact_type="json",
        root_id=str(tmp_path),
        relpath="input.json",
        blob_hash=sha256_digest(payload),
        size_bytes=len(payload),
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
        metadata={
            "session_id": "adaptive-session-code-task",
            "attempt_id": "controller-bound-source",
        },
    )
    return StoredAdaptiveArtifact(artifact=artifact, rows=rows, provenance_item_ids=("evidence-row",))


def _report_handler(envelope, plan, step, grant, workspace) -> AdaptiveStepResult:
    del envelope, plan, step, workspace
    return AdaptiveStepResult(
        grant_hash=grant.grant_hash,
        attempt_id=grant.attempt_id,
        success=True,
        output_refs=("cited-report",),
        output_ref_kinds=("execution_artifact",),
    )


def test_python_executor_consumes_verified_retrieval_context_without_mounting_it_as_data(tmp_path) -> None:
    registry = CapabilityRegistry()
    pack = register_generic_adaptive_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="context-task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=("statebus.analysis_result.v2", "statebus.cited_report.v1"),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_execution_runtime_ms=200_000,
    )
    proposal = PlanProposal(
        proposal_id="context-plan",
        task_id="context-task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "analyze", "executor", "execute_bounded_python_v2", "compute the requested result",
                input_ref_ids=("source", "evidence"),
                input_ref_kinds=("execution_artifact", "canonical_evidence_pack"),
                output_contract_version="statebus.analysis_result.v2",
                completion_criteria={"min_rows": 1, "required_fields": ["value"]},
            ),
            PlanStepProposal(
                "report", "summarizer", "compose_claim_set_v2", "report the verified result",
                depends_on=("analyze",),
                input_ref_ids=("evidence",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version="statebus.cited_report.v1",
                completion_criteria={"min_locator_count": 1},
            ),
        ),
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        proposal,
        envelope,
        available_input_refs={"source": "execution_artifact", "evidence": "canonical_evidence_pack"},
    )
    approved = outcome.approved_plan
    assert approved is not None, outcome.report.canonical_payload()

    rows = ({"value": 2.0},)
    payload = stable_json_dumps(list(rows)).encode("utf-8")
    source_path = tmp_path / "source.json"
    source_path.write_bytes(payload)
    source = StoredAdaptiveArtifact(
        artifact=ExecutionArtifactRef(
            artifact_id="source", task_id="context-task", step_id="source", artifact_type="json",
            root_id=str(tmp_path), relpath=source_path.name, blob_hash=sha256_digest(payload),
            size_bytes=len(payload), produced_by="controller", verification_state=RefStatus.VERIFIED,
            metadata={"session_id": "session", "attempt_id": "source-attempt"},
        ),
        rows=rows,
        provenance_item_ids=("source-row",),
    )
    locator = TableCellLocator(source_doc_hash="doc", table_id="metrics", row_idx=0, col_idx=0)
    evidence = CanonicalEvidencePack(
        pack_id="pack",
        task_id="context-task",
        source_doc_hashes=("doc",),
        semantic_contexts=(EvidenceItem(
            item_id="metric-definition", bucket="semantic_context", locator=locator,
            rendered_text="value is the requested operating metric",
        ),),
    )
    captured: dict[str, object] = {}

    class CapturingRunner:
        def execute(self, **kwargs):
            request = kwargs["request"]
            captured["request"] = request
            captured["input_files"] = kwargs["input_files"]
            return LlmCodeActOutcome(
                record=CodeExecutionRecord(
                    request_hash="request", source_hash="source", raw_response_hash="raw",
                    policy_report_hash="policy", sandbox_requested_backend="bwrap_required",
                    sandbox_actual_backend="not_executed", sandbox_readiness_digest="",
                    sandbox_policy_digest="policy", sandbox_uid=-1, sandbox_gid=-1,
                    mount_policy_digest="mount", input_ref_ids=request.input_ref_ids,
                    fallback_reason="test_stop_after_request_capture",
                ),
                policy_report=CodePolicyReport(source_hash="source", passed=True),
                repairs=(),
            )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"source": source},
        evidence_packs={"evidence": evidence},
        evidence_statuses={"evidence": EvidenceCoverageStatus.COMPLETE},
        evidence_ref_scopes={"evidence": ("session", "retrieve-attempt")},
        code_policy_factory=lambda step: CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_input_relpaths=("inputs/task.json",),
            output_required_fields=("value",),
        ),
        code_source_factory=lambda request, prompt: (
            captured.update(prompt=prompt) or "pass"
        ),
        codeact_contracts={
            "execute_bounded_python_v2": {
                "operation_semantics": {"analysis_context": "follow the task goal"},
                "quality_constraints": {"finite_numbers_only": True},
                "expected_output_shape": "object",
            }
        },
        output_schema_by_capability={"execute_bounded_python_v2": {"value": "number"}},
    )
    step = approved.steps[0]
    grant = CapabilityGrant(
        grant_id="grant", task_id="context-task", session_id="session", step_id=step.step_id,
        attempt_id="attempt", capability_id=step.capability_id, capability_version="v2",
        input_ref_ids=("source", "evidence"), output_contract_version=step.output_contract_version,
        workspace_root_id="workspace", max_runtime_ms=120_000,
        expires_at_ns=time.time_ns() + 1_000_000_000,
        approved_plan_hash=approved.approved_plan_hash,
    )
    result = AdaptiveCapabilityDispatcher(
        context=context,
        codeact_runner=CapturingRunner(),
    ).dispatch(
        envelope=envelope,
        approved_plan=approved,
        step=step,
        grant=grant,
        attempt_workspace=tmp_path / "attempt",
    )

    assert not result.success
    assert "request" in captured, result.error_code
    request = captured["request"]
    assert request.input_ref_ids == ("source", "evidence")
    assert request.retrieval_context[0]["item_id"] == "metric-definition"
    assert set(captured["input_files"]) == {"inputs/task.json"}
    assert "value is the requested operating metric" in captured["prompt"]


def test_run_adaptive_dispatches_approved_python_through_bwrap_and_quality_gate(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()

    def policy_factory(step) -> CodeGenerationPolicy:
        assert step.capability_id == "bounded_metric_python_v1"
        return CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=("quarter", "revenue_musd"),
        )

    def source_factory(request, prompt: str) -> str:
        assert "120" not in prompt
        assert "inputs/task.json" in prompt
        return (
            "import json\n"
            "from pathlib import Path\n"
            "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
            "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=policy_factory,
        code_source_factory=source_factory,
        output_schema_by_capability={"bounded_metric_python_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    dispatcher = AdaptiveCapabilityDispatcher(context=context)
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="trace",
            task_id="code-task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "input": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=dispatcher,
            proposal_hash="model-proposal",
        )
    )
    assert result.completed
    assert result.session.code_source_hashes
    assert result.session.capability_quality_report_hashes
    codeact_artifact = next(
        stored.artifact
        for artifact_id, stored in context.artifacts.items()
        if artifact_id != "input"
    )
    assert codeact_artifact.metadata["session_id"] == "adaptive-session-code-task"
    assert codeact_artifact.metadata["attempt_id"] == "adaptive-attempt-1"
    metrics = result.telemetry.summarize_task("code-task")
    assert metrics["llm_codeact_generation_count"] == 1.0
    assert metrics["llm_codeact_execution_count"] == 1.0
    assert metrics["llm_codeact_verified_count"] == 1.0
    assert metrics["llm_codeact_sandbox_fallback_count"] == 0.0


def test_run_adaptive_rejects_cross_session_artifact_before_model_generation(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()
    stored = _input_artifact(tmp_path)
    foreign_session = StoredAdaptiveArtifact(
        artifact=replace(
            stored.artifact,
            metadata={**stored.artifact.metadata, "session_id": "other-session"},
        ),
        rows=stored.rows,
        provenance_item_ids=stored.provenance_item_ids,
    )
    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": foreign_session},
        code_policy_factory=lambda step: CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
        ),
        code_source_factory=lambda request, prompt: (_ for _ in ()).throw(
            AssertionError("model must not run for a cross-session artifact")
        ),
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="cross-session-trace",
        task_id="code-task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path / "cross-session-runtime"),
        workspace_root_id="workspace",
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
    ))

    assert not result.completed
    assert result.dispatches[0].error_code == "llm_python_input_artifact_not_verified"


def test_python_failure_falls_back_only_with_a_fresh_dsl_grant(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan(fallback=True)
    seen_grants: list[tuple[str, str]] = []

    def program_factory(step, grant, input_ref_id, rows) -> TransformProgram:
        seen_grants.append((step.capability_id, grant.grant_hash))
        return TransformProgram(
            program_id="fallback-program",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=(TransformStep("select", {"columns": ["quarter", "revenue_musd"]}),),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=lambda step: CodeGenerationPolicy(capability_id=step.capability_id, enabled=False),
        code_source_factory=lambda request, prompt: "",
        transform_program_factory=program_factory,
        output_schema_by_capability={"extract_metric_series_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="fallback-trace",
            task_id="code-task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "fallback-runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "input": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
        )
    )
    assert result.completed
    assert seen_grants and seen_grants[0][0] == "extract_metric_series_v1"
    assert len(result.session.capability_grant_hashes) == 3
    assert len(set(result.session.capability_grant_hashes)) == 3
    assert result.telemetry.summarize_task("code-task")["model_fallback_count"] == 1.0


def test_runtime_dispatcher_allows_one_ast_repair_without_expanding_authority(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()
    repair_calls: list[tuple[str, ...]] = []

    def policy_factory(step) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=("quarter", "revenue_musd"),
        )

    def repair_factory(request, prompt: str, previous_source: str, violations: tuple[str, ...]) -> str:
        assert request.capability_id == "bounded_metric_python_v1"
        assert "inputs/task.json" in prompt
        assert "import os" in previous_source
        repair_calls.append(violations)
        return (
            "import json\n"
            "from pathlib import Path\n"
            "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
            "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=policy_factory,
        code_source_factory=lambda request, prompt: "import os\n",
        code_repair_factory=repair_factory,
        output_schema_by_capability={"bounded_metric_python_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="repair-trace",
            task_id="code-task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "repair-runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "input": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
        )
    )

    assert result.completed
    assert repair_calls and any("forbidden_import:os" in item for item in repair_calls[0])
    assert result.telemetry.summarize_task("code-task")["llm_codeact_repair_count"] == 1.0


def test_runtime_dispatcher_repairs_python_runtime_error_in_fresh_bwrap_workspace(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()
    repair_calls: list[tuple[str, ...]] = []

    def policy_factory(step) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_module_roots=("json", "pathlib", "statistics"),
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=("quarter", "revenue_musd"),
        )

    def repair_factory(request, prompt: str, previous_source: str, diagnostics: tuple[str, ...]) -> str:
        assert request.capability_id == "bounded_metric_python_v1"
        assert any(item.startswith("runtime_error:") and "TypeError" in item for item in diagnostics)
        assert "statistics.mean([None])" in previous_source
        repair_calls.append(diagnostics)
        return (
            "import json\n"
            "from pathlib import Path\n"
            "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
            "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
        )

    initial_source = (
        "import json\n"
        "import statistics\n"
        "from pathlib import Path\n"
        "rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "statistics.mean([None])\n"
        "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
    )
    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=policy_factory,
        code_source_factory=lambda request, prompt: initial_source,
        code_repair_factory=repair_factory,
        output_schema_by_capability={"bounded_metric_python_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="runtime-repair-trace",
        task_id="code-task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path / "runtime-repair-runtime"),
        workspace_root_id="workspace",
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
    ))

    assert result.completed
    assert len(repair_calls) == 1
    metrics = result.telemetry.summarize_task("code-task")
    assert metrics["llm_codeact_repair_count"] == 1.0
    assert metrics["llm_codeact_runtime_repair_count"] == 1.0
    repaired_artifact = next(
        stored.artifact for artifact_id, stored in context.artifacts.items() if artifact_id != "input"
    )
    assert "codeact-runtime-repair-1" in repaired_artifact.root_id


def test_policy_repair_does_not_consume_the_independent_runtime_repair_budget(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()
    repair_calls: list[tuple[str, ...]] = []

    def policy_factory(step) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_module_roots=("json", "pathlib", "statistics"),
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=("quarter", "revenue_musd"),
        )

    runtime_defect = (
        "import json\nimport statistics\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "statistics.mean([None])\n"
        "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
    )
    corrected = (
        "import json\nfrom pathlib import Path\n"
        "rows=json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        "Path('outputs/result.json').write_text(json.dumps(rows[0]), encoding='utf-8')\n"
    )

    def repair_factory(request, prompt: str, previous_source: str, diagnostics: tuple[str, ...]) -> str:
        repair_calls.append(diagnostics)
        if any(item.startswith("runtime_error:") for item in diagnostics):
            assert "statistics.mean([None])" in previous_source
            return corrected
        assert "import os" in previous_source
        return runtime_defect

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=policy_factory,
        code_source_factory=lambda request, prompt: "import os\n",
        code_repair_factory=repair_factory,
        output_schema_by_capability={
            "bounded_metric_python_v1": {"quarter": "string", "revenue_musd": "number"}
        },
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="policy-and-runtime-repair-trace",
        task_id="code-task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path / "policy-and-runtime-repair-runtime"),
        workspace_root_id="workspace",
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
    ))

    assert result.completed
    assert len(repair_calls) == 2
    record = next(iter(context.code_execution_records.values()))
    assert record.verified_artifact_id
    metrics = result.telemetry.summarize_task("code-task")
    assert metrics["llm_codeact_repair_count"] == 2.0
    assert metrics["llm_codeact_runtime_repair_count"] == 1.0


def test_runtime_dispatcher_exposes_source_and_upstream_artifact_as_distinct_inputs(tmp_path) -> None:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="code-task",
        canonical_task_spec_hash="spec",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(sorted({
            registry.get(item).output_contract_version for item in pack.capability_ids
        })),
        risk_class=RiskClass.BOUNDED_CODE,
        allow_llm_python=True,
        max_execution_runtime_ms=120_000,
    )
    proposal = PlanProposal(
        proposal_id="multi-code-proposal",
        task_id="code-task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "code-1", "executor", "bounded_metric_python_v1", "select the verified metric",
                input_ref_ids=("input",), input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.metric_series.v1",
            ),
            PlanStepProposal(
                "code-2", "executor", "bounded_metric_python_v1", "verify the selected metric against source",
                depends_on=("code-1",), input_ref_ids=("input",), input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.metric_series.v1",
            ),
            PlanStepProposal(
                "report", "summarizer", "compose_cited_report_v1", "publish the verified result",
                depends_on=("code-2",), input_ref_ids=("evidence",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    outcome = PlanPolicyValidator(registry, allow_llm_python=True).validate(
        proposal,
        envelope,
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
    )
    assert outcome.approved_plan is not None, outcome.report.canonical_payload()
    seen_inputs: list[tuple[str, ...]] = []

    def source_factory(request, prompt: str) -> str:
        seen_inputs.append(request.input_ref_ids)
        if len(request.input_ref_ids) == 1:
            assert "inputs/upstream-1.json" not in prompt
            result_expression = "source_rows[0]"
            reads = "source_rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
        else:
            assert "inputs/upstream-1.json" in prompt
            assert set(request.authorized_input_schemas) == {"inputs/task.json", "inputs/upstream-1.json"}
            result_expression = "upstream_rows[0]"
            reads = (
                "source_rows = json.loads(Path('inputs/task.json').read_text(encoding='utf-8'))\n"
                "upstream_rows = json.loads(Path('inputs/upstream-1.json').read_text(encoding='utf-8'))\n"
            )
        return (
            "import json\nfrom pathlib import Path\n"
            f"{reads}"
            f"Path('outputs/result.json').write_text(json.dumps({result_expression}), encoding='utf-8')\n"
        )

    def policy_factory(step) -> CodeGenerationPolicy:
        return CodeGenerationPolicy(
            capability_id=step.capability_id,
            enabled=True,
            require_bwrap=True,
            allowed_input_relpaths=("inputs/task.json",),
            output_relpath="outputs/result.json",
            output_required_fields=("quarter", "revenue_musd"),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": _input_artifact(tmp_path)},
        code_policy_factory=policy_factory,
        code_source_factory=source_factory,
        output_schema_by_capability={"bounded_metric_python_v1": {"quarter": "string", "revenue_musd": "number"}},
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    runtime = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="multi-input-trace",
        task_id="code-task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=outcome.approved_plan,
        registry=registry,
        runtime_root=str(tmp_path / "multi-input-runtime"),
        workspace_root_id="workspace",
        available_input_refs={
            "input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
        dispatcher=AdaptiveCapabilityDispatcher(context=context),
    ))

    assert runtime.completed
    assert [len(item) for item in seen_inputs] == [1, 2]
    assert runtime.telemetry.summarize_task("code-task")["llm_codeact_verified_count"] == 2.0


def test_runtime_rejects_cached_rows_that_do_not_match_the_verified_artifact(tmp_path) -> None:
    registry, envelope, approved = _approved_codeact_plan()
    stored = _input_artifact(tmp_path)
    tampered = StoredAdaptiveArtifact(
        artifact=stored.artifact,
        rows=({"quarter": "2026Q1", "revenue_musd": 999.0},),
        provenance_item_ids=stored.provenance_item_ids,
    )
    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={"input": tampered},
        code_policy_factory=lambda step: CodeGenerationPolicy(capability_id=step.capability_id, enabled=True, require_bwrap=True),
        code_source_factory=lambda request, prompt: (_ for _ in ()).throw(AssertionError("must not call model")),
        builtin_handlers={"compose_cited_report_v1": _report_handler},
    )
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="tampered-trace",
            task_id="code-task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "tampered-runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "input": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
        )
    )

    assert not result.completed
    assert result.dispatches[0].error_code == "artifact_cached_rows_mismatch"
