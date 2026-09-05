from __future__ import annotations

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    StepLifecycleState,
    WorkflowMode,
)
from statebus.runtime import LifecycleOrigin, RuntimeSessionManager, RuntimeSupervisor
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest, AdaptiveStepResult
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.session import RuntimeWorkflowStep, StepAttemptRecord


def _adaptive_setup(
    mode: WorkflowMode = WorkflowMode.ADAPTIVE_BOUNDED,
) -> tuple[CapabilityRegistry, AdaptiveTaskEnvelope, object]:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="task",
        canonical_task_spec_hash="spec",
        workflow_mode=mode,
        domain_pack_id=pack.pack_id,
        allowed_capability_ids=pack.capability_ids,
        allowed_output_contracts=tuple(
            sorted(
                {
                    registry.get(capability_id).output_contract_version
                    for capability_id in pack.capability_ids
                }
            )
        ),
        risk_class=RiskClass.WORKSPACE_WRITE,
    )
    proposal = PlanProposal(
        proposal_id="proposal",
        task_id="task",
        final_output_contract_version="statebus.cited_report.v1",
        steps=(
            PlanStepProposal(
                "retrieve",
                "retriever",
                "retrieve_semantic_evidence_v1",
                "retrieve",
                output_contract_version="statebus.evidence_pack.v2",
            ),
            PlanStepProposal(
                "extract",
                "executor",
                "extract_metric_series_v1",
                "extract",
                depends_on=("retrieve",),
                output_contract_version="statebus.metric_series.v1",
                on_failure="request_replan",
            ),
            PlanStepProposal(
                "report",
                "summarizer",
                "compose_cited_report_v1",
                "report",
                depends_on=("retrieve", "extract"),
                output_contract_version="statebus.cited_report.v1",
            ),
        ),
    )
    approved = PlanPolicyValidator(registry).validate(proposal, envelope).approved_plan
    assert approved is not None
    return registry, envelope, approved


def test_session_active_attempt_settlement_preserves_attempt_history() -> None:
    manager = RuntimeSessionManager()
    manager.start(
        session_id="session-06a",
        trace_id="trace-06a",
        task_id="task-06a",
        layer_name="L3",
        canonical_task_spec_hash="sha256:spec-06a",
        workspace_root="/tmp/workspace-06a",
        state_root="/tmp/state-06a",
    )
    manager.attach_workflow(
        "session-06a",
        workflow_steps=(
            RuntimeWorkflowStep(
                step_id="step-06a",
                role="executor",
                capability="execute",
            ),
        ),
    )
    manager.append_attempt_record(
        "session-06a",
        record=StepAttemptRecord(
            task_id="task-06a",
            step_id="step-06a",
            attempt_id="attempt-a",
            owner_role="executor",
            state=StepLifecycleState.PENDING.value,
        ),
    )
    manager.append_attempt_record(
        "session-06a",
        record=StepAttemptRecord(
            task_id="task-06a",
            step_id="step-06a",
            attempt_id="attempt-b",
            owner_role="executor",
            state=StepLifecycleState.PENDING.value,
        ),
    )

    manager.activate_attempt("session-06a", step_id="step-06a", attempt_id="attempt-a")
    assert manager.active_attempt_id("session-06a", "step-06a") == "attempt-a"
    manager.activate_attempt("session-06a", step_id="step-06a", attempt_id="attempt-b")
    assert manager.active_attempt_id("session-06a", "step-06a") == "attempt-b"

    manager.settle_attempt(
        "session-06a",
        step_id="step-06a",
        attempt_id="attempt-a",
        terminal_state=StepLifecycleState.FAILED.value,
        trap_reason="superseded",
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    session = manager.sessions["session-06a"]
    assert manager.active_attempt_id("session-06a", "step-06a") == "attempt-b"
    assert {record.attempt_id for record in session.attempt_records} == {
        "attempt-a",
        "attempt-b",
    }
    assert next(
        record for record in session.attempt_records if record.attempt_id == "attempt-a"
    ).state == StepLifecycleState.FAILED.value

    with pytest.raises(ValueError, match="non_active_attempt_workflow_mutation"):
        manager.update_workflow_step(
            "session-06a",
            step_id="step-06a",
            attempt_id="attempt-a",
            state=StepLifecycleState.COMPLETED.value,
        )

    manager.settle_attempt(
        "session-06a",
        step_id="step-06a",
        attempt_id="attempt-b",
        terminal_state=StepLifecycleState.COMPLETED.value,
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    assert manager.active_attempt_id("session-06a", "step-06a") is None


def test_supervisor_keeps_attempts_independent_and_rejects_local_ack() -> None:
    supervisor = RuntimeSupervisor()
    supervisor.register(
        task_id="task-06a",
        step_id="step-06a",
        attempt_id="attempt-a",
        role="executor",
        session_id="session-06a",
    )
    supervisor.register(
        task_id="task-06a",
        step_id="step-06a",
        attempt_id="attempt-b",
        role="executor",
        session_id="session-06a",
    )
    supervisor.dispatch(
        "step-06a",
        session_id="session-06a",
        attempt_id="attempt-a",
        origin=LifecycleOrigin.LOCAL_RUNTIME,
    )
    with pytest.raises(ValueError, match="local_runtime_cannot_ack"):
        supervisor.ack(
            "step-06a",
            session_id="session-06a",
            attempt_id="attempt-a",
            origin=LifecycleOrigin.LOCAL_RUNTIME,
        )
    with pytest.raises(ValueError, match="invalid transition"):
        supervisor.complete(
            "step-06a",
            session_id="session-06a",
            attempt_id="attempt-b",
            origin=LifecycleOrigin.LOCAL_RUNTIME,
        )

    supervisor.run_start(
        "step-06a",
        session_id="session-06a",
        attempt_id="attempt-a",
        origin=LifecycleOrigin.LOCAL_RUNTIME,
    )
    supervisor.complete(
        "step-06a",
        session_id="session-06a",
        attempt_id="attempt-a",
        origin=LifecycleOrigin.LOCAL_RUNTIME,
    )
    supervisor.dispatch(
        "step-06a",
        session_id="session-06a",
        attempt_id="attempt-b",
        origin=LifecycleOrigin.LOCAL_RUNTIME,
    )
    supervisor.run_start(
        "step-06a",
        session_id="session-06a",
        attempt_id="attempt-b",
        origin=LifecycleOrigin.LOCAL_RUNTIME,
    )

    assert supervisor.attempts[("session-06a", "step-06a", "attempt-a")].state == (
        StepLifecycleState.COMPLETED
    )
    assert supervisor.attempts[("session-06a", "step-06a", "attempt-b")].state == (
        StepLifecycleState.RUNNING
    )
    assert supervisor.attempts[("session-06a", "step-06a", "attempt-a")].lifecycle_origin == (
        LifecycleOrigin.LOCAL_RUNTIME
    )
    assert supervisor.steps["step-06a"].attempt_id == "attempt-b"
    assert {trace["attempt_id"] for trace in supervisor.transition_trace} == {
        "attempt-a",
        "attempt-b",
    }


def test_adaptive_local_provider_has_no_worker_ack_and_expired_attempt_is_settled(
    tmp_path,
) -> None:
    registry, envelope, approved = _adaptive_setup()
    calls: list[str] = []

    def execute(step, grant):
        calls.append(step.step_id)
        kind = "canonical_evidence_pack" if step.role == "retriever" else "execution_artifact"
        return AdaptiveStepResult(
            grant_hash=grant.grant_hash,
            success=True,
            output_refs=(f"ref-{step.step_id}",),
            output_ref_kinds=(kind,),
            attempt_id=grant.attempt_id,
        )

    result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="trace-local-06a",
            task_id="task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "local"),
            workspace_root_id="workspace",
            execute_step=execute,
        )
    )
    assert result.completed
    assert calls == ["retrieve", "extract", "report"]
    assert result.session.active_attempt_by_step == ()
    assert all(
        record.state == StepLifecycleState.COMPLETED.value
        and record.lifecycle_origin == LifecycleOrigin.LOCAL_RUNTIME.value
        for record in result.session.attempt_records
    )
    assert not any(event.event_type == "STEP_ACKED" for event in result.telemetry.events)
    assert all(
        event.payload.get("origin") != LifecycleOrigin.WORKER_OBSERVED.value
        for event in result.telemetry.events
    )

    expired = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="trace-expired-06a",
            task_id="task",
            canonical_task_spec_hash="spec",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "expired"),
            workspace_root_id="workspace",
            grant_ttl_ms=-1,
            execute_step=lambda *_args: pytest.fail("expired grant was dispatched"),
        )
    )
    expired_attempt = next(
        record for record in expired.session.attempt_records if record.step_id == "retrieve"
    )
    assert expired_attempt.state == StepLifecycleState.FAILED.value
    assert expired_attempt.lifecycle_origin == LifecycleOrigin.LOCAL_RUNTIME.value
    assert expired.session.active_attempt_id("retrieve") is None
    assert not expired.dispatches

