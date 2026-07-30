from __future__ import annotations

import time

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    PlanProposal,
    PlanStepProposal,
    RefStatus,
    RiskClass,
    TransformProgram,
    TransformStep,
    WorkflowMode,
)
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.adaptive_dispatcher import (
    AdaptiveCapabilityDispatcher,
    AdaptiveDispatchContext,
    StoredAdaptiveArtifact,
)
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.utils import sha256_digest, stable_json_dumps


@pytest.mark.parametrize(
    ("case_id", "capability_id", "input_rows", "operations", "output_schema", "output_contract"),
    (
        (
            "period-comparison",
            "compare_periods_v1",
            (
                {"quarter": "2026Q1", "current_musd": 120.0, "previous_musd": 100.0},
            ),
            (
                TransformStep("derive_safe", {"numerator": "current_musd", "denominator": "previous_musd", "output": "delta_musd", "kind": "difference"}),
                TransformStep("derive_safe", {"numerator": "current_musd", "denominator": "previous_musd", "output": "growth_pct", "kind": "pct_change"}),
            ),
            {"quarter": "string", "current_musd": "number", "previous_musd": "number", "delta_musd": "number", "growth_pct": "number"},
            "statebus.comparison.v1",
        ),
        (
            "grouped-aggregation",
            "aggregate_metrics_v1",
            (
                {"segment": "enterprise", "revenue_musd": 80.0},
                {"segment": "consumer", "revenue_musd": 40.0},
            ),
            (TransformStep("aggregate", {"column": "revenue_musd", "function": "sum", "output": "total_revenue_musd"}),),
            {"total_revenue_musd": "number"},
            "statebus.aggregation.v1",
        ),
        (
            "anomaly-detection",
            "detect_anomaly_v1",
            (
                {"quarter": "2025Q3", "revenue_musd": 10.0},
                {"quarter": "2025Q4", "revenue_musd": 11.0},
                {"quarter": "2026Q1", "revenue_musd": 100.0},
            ),
            (TransformStep("anomaly_check", {"column": "revenue_musd", "output": "is_anomaly"}),),
            {"quarter": "string", "revenue_musd": "number", "is_anomaly": "boolean"},
            "statebus.anomaly_report.v1",
        ),
    ),
)
def test_lightweight_financial_capability_gates_are_verified_and_attributable(
    tmp_path,
    case_id: str,
    capability_id: str,
    input_rows: tuple[dict[str, object], ...],
    operations: tuple[TransformStep, ...],
    output_schema: dict[str, str],
    output_contract: str,
) -> None:
    task_id = f"lightweight-{case_id}"
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id=task_id,
        canonical_task_spec_hash=f"spec-{case_id}",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=(capability_id, "compose_cited_report_v1"),
        allowed_output_contracts=(output_contract, "statebus.cited_report.v1"),
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    proposal = PlanProposal(
        proposal_id=f"proposal-{case_id}",
        task_id=task_id,
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="analyze",
                role="executor",
                capability_id=capability_id,
                goal=f"run the registered {case_id} capability on the verified artifact",
                input_ref_ids=("verified-input",),
                input_ref_kinds=("execution_artifact",),
                output_contract_version=output_contract,
                completion_criteria={"min_rows": 1},
            ),
            PlanStepProposal(
                step_id="report",
                role="summarizer",
                capability_id="compose_cited_report_v1",
                goal="make the verified result available for cited reporting",
                depends_on=("analyze",),
                input_ref_ids=("evidence",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    approved = PlanPolicyValidator(registry).validate(
        proposal,
        envelope,
        available_input_refs={
            "verified-input": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
    ).approved_plan
    assert approved is not None
    payload = stable_json_dumps(list(input_rows)).encode("utf-8")
    source_path = tmp_path / f"{case_id}-input.json"
    source_path.write_bytes(payload)
    input_artifact = ExecutionArtifactRef(
        artifact_id="verified-input",
        task_id=task_id,
        step_id="verified-upstream",
        artifact_type="json",
        root_id=str(tmp_path),
        relpath=source_path.name,
        blob_hash=sha256_digest(payload),
        size_bytes=len(payload),
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
        metadata={
            "session_id": f"adaptive-session-{task_id}",
            "attempt_id": "controller-bound-source",
        },
    )

    def program_factory(step, grant, input_ref_id, rows) -> TransformProgram:
        assert step.capability_id == capability_id
        assert input_ref_id == "verified-input"
        assert rows == input_rows
        return TransformProgram(
            program_id=f"{case_id}-program",
            input_artifact_refs=(input_ref_id,),
            output_contract_version=grant.output_contract_version,
            operations=operations,
        )

    def report_handler(envelope, plan, step, grant, workspace) -> AdaptiveStepResult:
        del envelope, plan, step, workspace
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            attempt_id=grant.attempt_id,
            output_refs=(f"{case_id}-report",),
            output_ref_kinds=("execution_artifact",),
        )

    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={
            "verified-input": StoredAdaptiveArtifact(
                artifact=input_artifact,
                rows=input_rows,
                provenance_item_ids=(f"{case_id}-source-row",),
            )
        },
        transform_program_factory=program_factory,
        output_schema_by_capability={capability_id: output_schema},
        builtin_handlers={"compose_cited_report_v1": report_handler},
    )
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id=f"trace-{case_id}",
            task_id=task_id,
            canonical_task_spec_hash=envelope.canonical_task_spec_hash,
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "verified-input": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
        )
    )

    assert result.completed
    assert len(result.session.transform_program_hashes) == 1
    assert len(result.session.capability_quality_report_hashes) == 1
    assert context.quality_reports
    assert all(report.verified for report in context.quality_reports.values())
    artifact = next(
        stored.artifact for artifact_id, stored in context.artifacts.items() if artifact_id != "verified-input"
    )
    assert artifact.verification_state == RefStatus.VERIFIED


def test_dispatcher_rejects_cross_task_artifact_before_transform_execution(tmp_path) -> None:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="task-a",
        canonical_task_spec_hash="spec-a",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=("extract_metric_series_v1", "compose_cited_report_v1"),
        allowed_output_contracts=("statebus.metric_series.v1", "statebus.cited_report.v1"),
    )
    proposal = PlanProposal(
        proposal_id="cross-task",
        task_id="task-a",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                step_id="extract", role="executor", capability_id="extract_metric_series_v1",
                goal="extract", input_ref_ids=("foreign",), input_ref_kinds=("execution_artifact",),
                output_contract_version="statebus.metric_series.v1",
            ),
            PlanStepProposal(
                step_id="report", role="summarizer", capability_id="compose_cited_report_v1",
                goal="report", depends_on=("extract",), input_ref_ids=("evidence",),
                input_ref_kinds=("canonical_evidence_pack",),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    approved = PlanPolicyValidator(registry).validate(
        proposal,
        envelope,
        available_input_refs={
            "foreign": "execution_artifact",
            "evidence": "canonical_evidence_pack",
        },
    ).approved_plan
    assert approved is not None
    context = AdaptiveDispatchContext(
        registry=registry,
        artifacts={
            "foreign": StoredAdaptiveArtifact(
                artifact=ExecutionArtifactRef(
                    artifact_id="foreign", task_id="task-b", step_id="upstream", artifact_type="json",
                    root_id=str(tmp_path), relpath="missing.json", blob_hash="hash", size_bytes=0,
                    produced_by="executor", verification_state=RefStatus.VERIFIED,
                    metadata={
                        "session_id": "adaptive-session-task-b",
                        "attempt_id": "foreign-attempt",
                    },
                ),
                rows=({"quarter": "2026Q1", "revenue_musd": 1.0},),
                provenance_item_ids=("foreign-row",),
            )
        },
        transform_program_factory=lambda *args: (_ for _ in ()).throw(AssertionError("must not execute")),
    )
    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="cross-task", task_id="task-a", canonical_task_spec_hash="spec-a", envelope=envelope,
            approved_plan=approved, registry=registry, runtime_root=str(tmp_path / "runtime"),
            workspace_root_id="workspace",
            available_input_refs={
                "foreign": "execution_artifact",
                "evidence": "canonical_evidence_pack",
            },
            dispatcher=AdaptiveCapabilityDispatcher(context=context),
        )
    )
    assert not result.completed
    assert result.dispatches[0].error_code == "transform_input_not_verified"
