from __future__ import annotations

import json

from v2.contracts import AdaptiveTaskEnvelope, PlanProposal, PlanStepProposal, RiskClass, StepLifecycleState, WorkflowMode
from v2.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.domain_packs import register_long_doc_analysis_capabilities
from v2.runtime.driver import RuntimeDriver
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.runtime.state_consumption import build_state_consumption_record
from v2.utils import sha256_digest


def _setup(mode: WorkflowMode = WorkflowMode.ADAPTIVE_BOUNDED):
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="task", canonical_task_spec_hash="spec", workflow_mode=mode, domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(sorted({registry.get(cap).output_contract_version for cap in pack.capability_ids})),
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    proposal = PlanProposal(
        proposal_id="proposal", task_id="task", final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal("retrieve", "retriever", "retrieve_semantic_evidence_v1", "retrieve", output_contract_version="statebus.evidence_pack.v2"),
            PlanStepProposal("extract", "executor", "extract_metric_series_v1", "extract", depends_on=("retrieve",), output_contract_version="statebus.metric_series.v1", on_failure="request_replan"),
            PlanStepProposal("report", "summarizer", "compose_cited_report_v1", "report", depends_on=("retrieve", "extract"), output_contract_version="statebus.cited_report.v1"),
        ),
    )
    approved = PlanPolicyValidator(registry).validate(proposal, envelope).approved_plan
    assert approved is not None
    return registry, envelope, approved


def test_driver_executes_approved_nonfixed_dag_with_one_grant_per_step(tmp_path) -> None:
    registry, envelope, approved = _setup()
    called: list[str] = []

    def execute(step, grant):
        called.append(step.step_id)
        kinds = {
            "retrieve": "canonical_evidence_pack", "extract": "execution_artifact", "report": "execution_artifact",
        }
        return AdaptiveStepResult(grant_hash=grant.grant_hash, success=True, output_refs=(f"ref-{step.step_id}",), output_ref_kinds=(kinds[step.step_id],))

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="trace", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path), workspace_root_id="workspace", execute_step=execute,
    ))
    assert called == ["retrieve", "extract", "report"]
    assert result.completed
    assert len({dispatch.grant_hash for dispatch in result.dispatches}) == 3


def test_driver_rejects_missing_actual_required_input_kind_before_dispatch(tmp_path) -> None:
    registry, envelope, approved = _setup()
    called: list[str] = []

    def execute(step, grant):
        called.append(step.step_id)
        if step.step_id == "retrieve":
            return AdaptiveStepResult(
                grant_hash=grant.grant_hash,
                success=True,
                output_refs=("evidence-ref",),
                output_ref_kinds=("canonical_evidence_pack",),
            )
        if step.step_id == "extract":
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=True)
        raise AssertionError("summarizer must not be dispatched without an analysis artifact")

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="missing-required-kind",
        task_id="task",
        canonical_task_spec_hash="spec",
        envelope=envelope,
        approved_plan=approved,
        registry=registry,
        runtime_root=str(tmp_path),
        workspace_root_id="workspace",
        execute_step=execute,
    ))

    assert called == ["retrieve", "extract"]
    assert not result.completed
    report_step = next(step for step in result.session.workflow_steps if step.step_id == "report")
    assert report_step.state == StepLifecycleState.FAILED.value
    assert report_step.last_error == "grant_required_input_kind_missing"
    events = [
        json.loads(line)
        for line in (tmp_path / "telemetry" / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "STEP_REJECTED_PRE_DISPATCH"
        and event["payload"]["error_code"] == "grant_required_input_kind_missing"
        and event["payload"]["missing_input_kinds"] == ["execution_artifact"]
        for event in events
    )


def test_shadow_plan_never_dispatches_role_work(tmp_path) -> None:
    registry, envelope, approved = _setup(WorkflowMode.ADAPTIVE_SHADOW)
    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="trace", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path), workspace_root_id="workspace",
        execute_step=lambda step, grant: (_ for _ in ()).throw(AssertionError("shadow dispatched")),
    ))
    assert result.shadow_only
    assert result.dispatches == ()


def test_driver_suppresses_dependents_after_failure_and_rejects_expired_grant_pre_dispatch(tmp_path) -> None:
    registry, envelope, approved = _setup()
    called: list[str] = []

    def failing(step, grant):
        called.append(step.step_id)
        return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, error_code="retrieval_failed")

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="trace", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path / "failed"), workspace_root_id="workspace", execute_step=failing,
    ))
    assert called == ["retrieve"]
    assert not result.completed
    assert {step.state for step in result.session.workflow_steps if step.step_id != "retrieve"} == {StepLifecycleState.CANCELLED.value}

    never_called: list[str] = []
    expired = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="expired", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path / "expired"), workspace_root_id="workspace",
        grant_ttl_ms=-1, execute_step=lambda step, grant: never_called.append(step.step_id) or AdaptiveStepResult(grant.grant_hash, True),
    ))
    assert never_called == []
    assert not expired.dispatches


def test_driver_replan_changes_only_unexecuted_subgraph(tmp_path) -> None:
    registry, envelope, approved = _setup()
    replacement_proposal = PlanProposal(
        proposal_id="replacement", task_id="task", final_output_contract_version="statebus.cited_report.v1",
        steps=(
            approved.steps[0],
            PlanStepProposal("fallback-extract", "executor", "extract_metric_series_v1", "fallback", depends_on=("retrieve",), output_contract_version="statebus.metric_series.v1"),
            PlanStepProposal("report", "summarizer", "compose_cited_report_v1", "report", depends_on=("retrieve", "fallback-extract"), output_contract_version="statebus.cited_report.v1"),
        ),
    )
    replacement = PlanPolicyValidator(registry).validate(replacement_proposal, envelope).approved_plan
    assert replacement is not None
    calls: list[str] = []

    def execute(step, grant):
        calls.append(step.step_id)
        if step.step_id == "extract":
            return AdaptiveStepResult(grant_hash=grant.grant_hash, success=False, error_code="bad_extract")
        kind = "canonical_evidence_pack" if step.role == "retriever" else "execution_artifact"
        return AdaptiveStepResult(grant_hash=grant.grant_hash, success=True, output_refs=(step.step_id + "-ref",), output_ref_kinds=(kind,))

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="replan", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path), workspace_root_id="workspace", execute_step=execute,
        replan=lambda previous, completed, reason: replacement,
    ))
    assert result.completed and result.plan_replaced
    assert calls == ["retrieve", "extract", "fallback-extract", "report"]
    assert result.session.replan_count == 1
    assert result.runtime_signature is not None
    assert result.runtime_signature.approved_plan_hash == replacement.approved_plan_hash


def test_driver_attaches_verified_coverage_and_state_consumption_audit_hashes(tmp_path) -> None:
    registry, envelope, approved = _setup()
    consumption = build_state_consumption_record(
        state_ref_id="state", consumer_role="retriever", consumer_step_id="retrieve", operation="rerank",
        read_field_ids=("embedding",), input_decision_surface_hash="before", output_decision_surface_hash="after", selected_ids=("e1",),
        consumed_at_ns=1,
    )
    decision = {
        "decision": "coverage_complete_no_expansion",
        "before_candidate_count": 3,
        "after_candidate_count": 3,
        "missing_evidence_types": [],
    }

    def execute(step, grant):
        kind = "canonical_evidence_pack" if step.role == "retriever" else "execution_artifact"
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash, success=True, output_refs=(step.step_id + "-ref",), output_ref_kinds=(kind,),
            evidence_coverage_report_hashes=("coverage-hash",) if step.step_id == "retrieve" else (),
            evidence_coverage_decision_records=(decision,) if step.step_id == "retrieve" else (),
            state_consumption_records=(consumption,) if step.step_id == "retrieve" else (),
        )

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="audit", task_id="task", canonical_task_spec_hash="spec", envelope=envelope, approved_plan=approved,
        registry=registry, runtime_root=str(tmp_path), workspace_root_id="workspace", execute_step=execute,
    ))
    assert result.completed
    assert result.session.evidence_coverage_report_hashes == ("coverage-hash",)
    assert result.session.adaptive_decision_record_hashes == (sha256_digest(decision),)
    assert result.session.state_consumption_record_hashes
    events = [
        json.loads(line)
        for line in (tmp_path / "telemetry" / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert any(
        event["event_type"] == "EVIDENCE_COVERAGE_DECIDED"
        and event["payload"]["decision_hash"] == sha256_digest(decision)
        for event in events
    )


def test_driver_records_raw_proposal_policy_separately_from_approved_plan(tmp_path) -> None:
    registry, envelope, approved = _setup()

    def execute(step, grant):
        kind = "canonical_evidence_pack" if step.role == "retriever" else "execution_artifact"
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            output_refs=(step.step_id + "-ref",),
            output_ref_kinds=(kind,),
        )

    result = RuntimeDriver().run_adaptive(AdaptiveRuntimeRequest(
        trace_id="policy-audit", task_id="task", canonical_task_spec_hash="spec", envelope=envelope,
        approved_plan=approved, registry=registry, runtime_root=str(tmp_path), workspace_root_id="workspace",
        execute_step=execute, proposal_valid=False, policy_rejected=True, fallback_used=True,
    ))
    metrics = result.telemetry.summarize_task("task")
    assert metrics["proposal_valid"] == 0.0
    assert metrics["policy_rejected"] == 1.0
    assert metrics["fallback_used"] == 1.0
    assert metrics["approved_plan_valid"] == 1.0
