from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from statebus.contracts import (
    AdaptiveTaskEnvelope,
    CONTROL_PLANE_SCHEMA_VERSION,
    PlanProposal,
    PlanStepProposal,
    RiskClass,
    StepLifecycleState,
    WorkflowMode,
)
from statebus.control import (
    ControlHeader,
    ControlResponseOrigin,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SuccessResult,
)
import statebus.control.transport as transport_module
from statebus.control.transport import (
    SubprocessExecutorTransport,
    SubprocessTransportTimeout,
)
from statebus.runtime import LifecycleOrigin, RuntimeSessionManager
from statebus.runtime.adaptive_runtime import AdaptiveRuntimeRequest
from statebus.runtime.capability_registry import CapabilityRegistry
from statebus.runtime.domain_packs import register_long_doc_analysis_capabilities
from statebus.runtime.driver import RuntimeDriver
from statebus.runtime.plan_policy import PlanPolicyValidator
from statebus.runtime.session import RuntimeWorkflowStep, StepAttemptRecord


def _adaptive_setup() -> tuple[CapabilityRegistry, AdaptiveTaskEnvelope, object]:
    registry = CapabilityRegistry()
    pack = register_long_doc_analysis_capabilities(registry)
    envelope = AdaptiveTaskEnvelope(
        task_id="task-06b",
        canonical_task_spec_hash="spec-06b",
        workflow_mode=WorkflowMode.ADAPTIVE_BOUNDED,
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
        proposal_id="proposal-06b",
        task_id="task-06b",
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


class _DelayedPhysicalDispatcher:
    def __init__(self, *, socket_path: Path, trace: list[str]) -> None:
        self.socket_path = socket_path
        self.trace = trace
        self.timeout: SubprocessTransportTimeout | None = None
        self.transport: SubprocessExecutorTransport | None = None

    def dispatch(
        self,
        *,
        step: PlanStepProposal,
        grant: Any,
        attempt_workspace: Path,
        runtime_identity: Any,
        **_kwargs: object,
    ) -> object:
        plain_grant = grant.grant
        self.trace.append("T1 A dispatched")
        request = ExecRequest(
            header=ControlHeader(
                trace_id=runtime_identity.trace_id,
                task_id=runtime_identity.runtime_task_id,
                run_id=runtime_identity.run_id,
                session_id=runtime_identity.session_id,
                step_id=step.step_id,
                attempt_id=plain_grant.attempt_id,
                invocation_id="invocation-attempt-a-06b",
                target_role=step.role,
                timeout_ms=50,
                execution_binding_hash=grant.execution_binding_hash,
                capability_grant_hash=plain_grant.grant_hash,
                event_type=EventType.REQ_EXEC,
                schema_version=CONTROL_PLANE_SCHEMA_VERSION,
            ),
            artifact_refs=(RefHandle("artifact-input-a", "artifact"),),
            runtime_reuse_contract="no_semantic_state",
            output_contract_version=plain_grant.output_contract_version,
            workspace_root=str(attempt_workspace),
            input_manifest_hash="sha256:input-manifest-06b",
            capability_grant_hash=plain_grant.grant_hash,
        )
        self.transport = SubprocessExecutorTransport(
            socket_path=self.socket_path,
            timeout_s=0.05,
        )
        try:
            return self.transport.execute(request)
        except SubprocessTransportTimeout as exc:
            self.timeout = exc
            raise


def _append_attempt(
    manager: RuntimeSessionManager,
    *,
    session_id: str,
    step_id: str,
    attempt_id: str,
) -> None:
    manager.append_attempt_record(
        session_id,
        record=StepAttemptRecord(
            task_id=manager.sessions[session_id].task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            owner_role="retriever",
            state=StepLifecycleState.PENDING.value,
        ),
    )


def test_late_attempt_a_result_is_fenced_after_attempt_b_activation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trace: list[str] = []
    worker_script = Path(__file__).parent / "fixtures" / "mrr_06b_delayed_worker.py"
    real_popen = transport_module.subprocess.Popen

    def delayed_worker_popen(command: list[str], **kwargs: object) -> Any:
        replacement = [command[0], str(worker_script), *command[3:]]
        return real_popen(replacement, **kwargs)

    monkeypatch.setattr(transport_module.subprocess, "Popen", delayed_worker_popen)

    original_activate = RuntimeSessionManager.activate_attempt
    activation_count = 0

    def observed_activate(
        manager: RuntimeSessionManager,
        session_id: str,
        *,
        step_id: str,
        attempt_id: str,
    ) -> object:
        nonlocal activation_count
        session = original_activate(
            manager,
            session_id,
            step_id=step_id,
            attempt_id=attempt_id,
        )
        activation_count += 1
        trace.append("T0 A activated" if activation_count == 1 else "T4 B activated")
        return session

    monkeypatch.setattr(RuntimeSessionManager, "activate_attempt", observed_activate)
    original_settle = RuntimeSessionManager.settle_attempt

    def observed_settle(manager: RuntimeSessionManager, *args: object, **kwargs: object) -> object:
        if kwargs.get("terminal_state") == StepLifecycleState.TRAPPED.value:
            trace.append("T2 A timeout decision")
        session = original_settle(manager, *args, **kwargs)
        if kwargs.get("terminal_state") == StepLifecycleState.TRAPPED.value:
            trace.append("T3 A terminal settlement")
        return session

    monkeypatch.setattr(RuntimeSessionManager, "settle_attempt", observed_settle)

    def preserve_late_worker(
        timeout: SubprocessTransportTimeout,
        *,
        grace_s: float = 1.0,
    ) -> bool:
        del grace_s
        trace.append("physical terminate attempted after T3")
        timeout.termination_attempted = True
        timeout.termination_succeeded = False
        timeout.termination_outcome = "worker_outlived_best_effort_cancel"
        return False

    monkeypatch.setattr(SubprocessTransportTimeout, "terminate", preserve_late_worker)

    registry, envelope, approved = _adaptive_setup()
    dispatcher = _DelayedPhysicalDispatcher(
        socket_path=tmp_path / "late-attempt-a.sock",
        trace=trace,
    )
    runtime_result = RuntimeDriver().run_adaptive(
        AdaptiveRuntimeRequest(
            trace_id="trace-06b",
            task_id="task-06b",
            canonical_task_spec_hash="spec-06b",
            envelope=envelope,
            approved_plan=approved,
            registry=registry,
            runtime_root=str(tmp_path / "runtime"),
            workspace_root_id="workspace-06b",
            dispatcher=dispatcher,
        )
    )

    assert dispatcher.timeout is not None
    assert dispatcher.transport is not None
    timeout = dispatcher.timeout
    attempt_a = timeout.request.header.attempt_id
    session_id = runtime_result.session.session_id
    attempt_a_record = next(
        record
        for record in runtime_result.session.attempt_records
        if record.attempt_id == attempt_a
    )
    assert attempt_a_record.state == StepLifecycleState.TRAPPED.value
    assert runtime_result.session.active_attempt_id("retrieve") is None
    assert trace[:5] == [
        "T0 A activated",
        "T1 A dispatched",
        "T2 A timeout decision",
        "T3 A terminal settlement",
        "physical terminate attempted after T3",
    ]
    assert timeout.origin == "LOCAL_TRANSPORT"
    assert timeout.termination_outcome == "worker_outlived_best_effort_cancel"
    assert not any(
        isinstance(response, ErrorResult) for response in timeout._responses
    )

    manager = RuntimeSessionManager(sessions={session_id: runtime_result.session})
    attempt_b = "attempt-b-06b"
    _append_attempt(
        manager,
        session_id=session_id,
        step_id="retrieve",
        attempt_id=attempt_b,
    )
    manager.activate_attempt(
        session_id,
        step_id="retrieve",
        attempt_id=attempt_b,
    )
    manager.update_workflow_step(
        session_id,
        step_id="retrieve",
        state=StepLifecycleState.RUNNING.value,
        attempt_id=attempt_b,
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    assert timeout.thread.is_alive()
    assert not any(
        isinstance(response, SuccessResult) for response in timeout._responses
    )

    admitted = timeout.wait_for_admitted_sequence(timeout_s=5.0)
    trace.append("T5 late A terminal observed")
    assert isinstance(admitted[-1], SuccessResult)
    assert admitted[-1].header.attempt_id == attempt_a
    assert admitted[-1].header.invocation_id == "invocation-attempt-a-06b"
    assert not any(isinstance(response, ErrorResult) for response in admitted)
    assert all(
        receipt.origin == ControlResponseOrigin.NATIVE_TYPED_WORKER
        and receipt.admitted
        for receipt in dispatcher.transport.last_admission_receipts
    )

    before_fence = manager.sessions[session_id].workflow_steps[0]
    fence = manager.admit_attempt_result(
        session_id,
        step_id="retrieve",
        observed_attempt_id=attempt_a,
        invocation_id=admitted[-1].header.invocation_id,
    )
    trace.append("T6 FENCED_STALE_ATTEMPT")
    assert fence.decision == "FENCED_STALE_ATTEMPT"
    assert fence.active_attempt_id == attempt_b
    assert not fence.commit_authorized
    assert manager.sessions[session_id].workflow_steps[0] == before_fence
    assert manager.active_attempt_id(session_id, "retrieve") == attempt_b
    trace.append("T7 B still active")

    duplicate_fence = manager.admit_attempt_result(
        session_id,
        step_id="retrieve",
        observed_attempt_id=attempt_a,
        invocation_id=admitted[-1].header.invocation_id,
    )
    assert duplicate_fence.decision == "FENCED_STALE_ATTEMPT"
    assert manager.sessions[session_id].workflow_steps[0] == before_fence

    commit_b = manager.admit_attempt_result(
        session_id,
        step_id="retrieve",
        observed_attempt_id=attempt_b,
        invocation_id="invocation-attempt-b-06b",
    )
    assert commit_b.commit_authorized
    manager.update_attempt_record(
        session_id,
        step_id="retrieve",
        attempt_id=attempt_b,
        state=StepLifecycleState.COMPLETED.value,
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    manager.update_workflow_step(
        session_id,
        step_id="retrieve",
        state=StepLifecycleState.COMPLETED.value,
        attempt_id=attempt_b,
        output_refs=("output-b",),
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    manager.settle_attempt(
        session_id,
        step_id="retrieve",
        attempt_id=attempt_b,
        terminal_state=StepLifecycleState.COMPLETED.value,
        lifecycle_origin=LifecycleOrigin.LOCAL_RUNTIME.value,
    )
    trace.append("T8 B commits")
    final_step = manager.sessions[session_id].workflow_steps[0]
    assert final_step.attempt_id == attempt_b
    assert final_step.output_refs == ("output-b",)
    assert manager.active_attempt_id(session_id, "retrieve") is None

    (tmp_path / "late_result_fencing_trace.json").write_text(
        json.dumps(
            {
                "trace": trace,
                "transport_timeout": timeout.canonical_payload(),
                "physical_admission_receipts": [
                    receipt.canonical_payload()
                    for receipt in dispatcher.transport.last_admission_receipts
                ],
                "runtime_fence_receipts": [
                    receipt.canonical_payload()
                    for receipt in manager.attempt_result_admissions[session_id]
                ],
                "committed_output_refs": list(final_step.output_refs),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_cancelled_attempt_late_result_and_repeat_settlement_cannot_mutate_b() -> None:
    manager = RuntimeSessionManager()
    session_id = "session-cancel-06b"
    manager.start(
        session_id=session_id,
        trace_id="trace-cancel-06b",
        task_id="task-cancel-06b",
        layer_name="L3",
        canonical_task_spec_hash="sha256:spec-cancel-06b",
        workspace_root="/tmp/workspace-cancel-06b",
        state_root="/tmp/state-cancel-06b",
    )
    manager.attach_workflow(
        session_id,
        workflow_steps=(
            RuntimeWorkflowStep("step-06b", "executor", "execute"),
        ),
    )
    _append_attempt(
        manager,
        session_id=session_id,
        step_id="step-06b",
        attempt_id="attempt-a",
    )
    manager.activate_attempt(
        session_id,
        step_id="step-06b",
        attempt_id="attempt-a",
    )
    manager.update_workflow_step(
        session_id,
        step_id="step-06b",
        state=StepLifecycleState.CANCELLED.value,
        attempt_id="attempt-a",
    )
    manager.settle_attempt(
        session_id,
        step_id="step-06b",
        attempt_id="attempt-a",
        terminal_state=StepLifecycleState.CANCELLED.value,
        cancel_reason="runtime_cancelled",
    )

    _append_attempt(
        manager,
        session_id=session_id,
        step_id="step-06b",
        attempt_id="attempt-b",
    )
    manager.activate_attempt(
        session_id,
        step_id="step-06b",
        attempt_id="attempt-b",
    )
    manager.update_workflow_step(
        session_id,
        step_id="step-06b",
        state=StepLifecycleState.RUNNING.value,
        attempt_id="attempt-b",
    )
    before_late_result = manager.sessions[session_id].workflow_steps[0]

    for _ in range(2):
        receipt = manager.admit_attempt_result(
            session_id,
            step_id="step-06b",
            observed_attempt_id="attempt-a",
            invocation_id="invocation-a",
        )
        assert receipt.decision == "FENCED_STALE_ATTEMPT"
        assert manager.sessions[session_id].workflow_steps[0] == before_late_result

    manager.settle_attempt(
        session_id,
        step_id="step-06b",
        attempt_id="attempt-a",
        terminal_state=StepLifecycleState.CANCELLED.value,
        cancel_reason="repeat_late_terminal",
    )
    assert manager.active_attempt_id(session_id, "step-06b") == "attempt-b"
    assert manager.sessions[session_id].workflow_steps[0] == before_late_result
    with pytest.raises(ValueError, match="non_active_attempt_workflow_mutation"):
        manager.update_workflow_step(
            session_id,
            step_id="step-06b",
            state=StepLifecycleState.COMPLETED.value,
            attempt_id="attempt-a",
            output_refs=("late-a",),
        )
