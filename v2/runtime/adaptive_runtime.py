from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
import time
from typing import Callable, TYPE_CHECKING

from v2.contracts import (
    AdaptiveTaskEnvelope,
    ApprovedPlan,
    CapabilityGrant,
    PlanPolicyReport,
    PlanStepProposal,
    PlanProposal,
    StateConsumptionRecord,
    StepLifecycleState,
    WorkflowMode,
)
from v2.runtime.capability_registry import CapabilityRegistry
from v2.runtime.plan_policy import PlanPolicyValidator
from v2.runtime.session import (
    RuntimeLeaseConfig,
    RuntimeReplanRecord,
    RuntimeSessionManager,
    RuntimeTaskSession,
    RuntimeWorkflowStep,
    StepAttemptRecord,
)
from v2.runtime.supervisor import RuntimeSupervisor
from v2.runtime.telemetry import TelemetryEmitter, TelemetryEvent
from v2.utils import sha256_digest

if TYPE_CHECKING:
    from v2.runtime.adaptive_dispatcher import AdaptiveCapabilityDispatcher


@dataclass(frozen=True)
class AdaptiveStepResult:
    grant_hash: str
    success: bool
    output_refs: tuple[str, ...] = ()
    output_ref_kinds: tuple[str, ...] = ()
    validator_report_hashes: tuple[str, ...] = ()
    error_code: str = ""
    retryable: bool = False
    attempt_id: str = ""
    timed_out: bool = False
    evidence_coverage_report_hashes: tuple[str, ...] = ()
    evidence_coverage_decision_records: tuple[dict[str, object], ...] = ()
    state_consumption_records: tuple[StateConsumptionRecord, ...] = ()
    projection_report_hashes: tuple[str, ...] = ()
    quality_report_hashes: tuple[str, ...] = ()
    program_hashes: tuple[str, ...] = ()
    source_hashes: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AdaptiveRuntimeRequest:
    trace_id: str
    task_id: str
    canonical_task_spec_hash: str
    envelope: AdaptiveTaskEnvelope
    approved_plan: ApprovedPlan
    registry: CapabilityRegistry
    runtime_root: str
    workspace_root_id: str
    state_root: str = ""
    available_input_refs: dict[str, str] = field(default_factory=dict)
    proposal_hash: str = ""
    planner_model_id: str = ""
    planner_raw_output_hash: str = ""
    proposal_valid: bool = True
    policy_rejected: bool = False
    repair_used: bool = False
    fallback_used: bool = False
    evidence_coverage_report_hashes: tuple[str, ...] = ()
    state_consumption_records: tuple[StateConsumptionRecord, ...] = ()
    grant_ttl_ms: int | None = None
    execute_step: Callable[[PlanStepProposal, CapabilityGrant], AdaptiveStepResult] | None = None
    dispatcher: "AdaptiveCapabilityDispatcher | None" = None
    replan: Callable[[ApprovedPlan, tuple[str, ...], str], ApprovedPlan | None] | None = None
    layer_name: str = "L3"


@dataclass(frozen=True)
class AdaptiveShadowRequest:
    """Audit an untrusted planner proposal while retaining the strict runtime path."""

    trace_id: str
    task_id: str
    envelope: AdaptiveTaskEnvelope
    registry: CapabilityRegistry
    runtime_root: str
    propose_plan: Callable[[], PlanProposal]
    repair_plan: Callable[[PlanPolicyReport], PlanProposal | None] | None = None
    fallback_proposal: PlanProposal | None = None
    available_input_refs: dict[str, str] = field(default_factory=dict)
    fixed_workflow_hash: str = ""


@dataclass(frozen=True)
class AdaptiveShadowAudit:
    proposal: PlanProposal
    initial_policy_report: PlanPolicyReport
    plan_policy_report: PlanPolicyReport
    approved_plan: ApprovedPlan
    fixed_workflow_hash: str
    proposal_valid: bool
    policy_rejected: bool
    repair_used: bool
    fallback_used: bool
    runtime_signature: "AdaptiveRuntimeSignature"
    schema_version: str = "statebus.adaptive_shadow_audit.v1"

    def canonical_payload(self) -> dict[str, object]:
        return {
            "proposal_hash": self.proposal.proposal_hash,
            "initial_policy_report_hash": self.initial_policy_report.report_hash,
            "plan_policy_report_hash": self.plan_policy_report.report_hash,
            "approved_plan_hash": self.approved_plan.approved_plan_hash,
            "fixed_workflow_hash": self.fixed_workflow_hash,
            "proposal_valid": self.proposal_valid,
            "policy_rejected": self.policy_rejected,
            "repair_used": self.repair_used,
            "fallback_used": self.fallback_used,
            "adaptive_runtime_signature": self.runtime_signature.canonical_payload(),
            "adaptive_runtime_signature_hash": self.runtime_signature.digest,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True)
class AdaptiveShadowResult:
    """The strict result is returned by identity and is never adapted or rewritten."""

    strict_result: object
    audit: AdaptiveShadowAudit
    telemetry: TelemetryEmitter


@dataclass(frozen=True)
class AdaptiveDispatchRecord:
    step_id: str
    attempt_id: str
    grant_hash: str
    state: str
    output_refs: tuple[str, ...] = ()
    error_code: str = ""


@dataclass(frozen=True)
class AdaptiveRuntimeResult:
    session: RuntimeTaskSession
    dispatches: tuple[AdaptiveDispatchRecord, ...]
    telemetry: TelemetryEmitter
    approved_plan_hash: str
    completed: bool
    plan_replaced: bool = False
    shadow_only: bool = False
    runtime_signature: "AdaptiveRuntimeSignature | None" = None


@dataclass(frozen=True)
class AdaptiveRuntimeSignature:
    workflow_mode: WorkflowMode
    envelope_hash: str
    approved_plan_hash: str
    capability_registry_digest: str
    policy_version: str
    schema_version: str = "statebus.adaptive_runtime_signature.v1"

    def canonical_payload(self) -> dict[str, str]:
        return {
            "workflow_mode": self.workflow_mode.value,
            "envelope_hash": self.envelope_hash,
            "approved_plan_hash": self.approved_plan_hash,
            "capability_registry_digest": self.capability_registry_digest,
            "policy_version": self.policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def digest(self) -> str:
        return sha256_digest(self.canonical_payload())


class AdaptiveRuntimeError(RuntimeError):
    pass


class AdaptiveShadowController:
    """Run planner policy audit first, then invoke the existing strict runtime once."""

    def run(
        self,
        request: AdaptiveShadowRequest,
        *,
        strict_runner: Callable[[], object],
    ) -> AdaptiveShadowResult:
        if request.envelope.workflow_mode != WorkflowMode.ADAPTIVE_SHADOW:
            raise AdaptiveRuntimeError("adaptive_shadow_workflow_mode_required")
        if request.envelope.task_id != request.task_id:
            raise AdaptiveRuntimeError("adaptive_shadow_task_id_mismatch")

        proposal = request.propose_plan()
        validator = PlanPolicyValidator(request.registry)
        initial = validator.validate(
            proposal,
            request.envelope,
            available_input_refs=request.available_input_refs,
        )
        outcome = validator.validate_with_single_repair(
            proposal,
            request.envelope,
            repair=request.repair_plan,
            fallback_proposal=request.fallback_proposal,
            available_input_refs=request.available_input_refs,
        )
        if outcome.approved_plan is None:
            raise AdaptiveRuntimeError("adaptive_shadow_no_approved_or_fallback_plan")

        runtime_signature = AdaptiveRuntimeSignature(
            workflow_mode=request.envelope.workflow_mode,
            envelope_hash=request.envelope.envelope_hash,
            approved_plan_hash=outcome.approved_plan.approved_plan_hash,
            capability_registry_digest=request.registry.digest,
            policy_version=request.envelope.policy_version,
        )
        audit = AdaptiveShadowAudit(
            proposal=proposal,
            initial_policy_report=initial.report,
            plan_policy_report=outcome.report,
            approved_plan=outcome.approved_plan,
            fixed_workflow_hash=request.fixed_workflow_hash,
            proposal_valid=initial.approved_plan is not None,
            policy_rejected=initial.approved_plan is None,
            repair_used=outcome.repair_used,
            fallback_used=outcome.fallback_used,
            runtime_signature=runtime_signature,
        )
        telemetry = TelemetryEmitter(
            runtime_event_log_path=Path(request.runtime_root) / "telemetry" / "runtime_events.jsonl",
            runtime_fact_log_path=Path(request.runtime_root) / "telemetry" / "runtime_facts.jsonl",
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=request.trace_id,
                task_id=request.task_id,
                event_type="ADAPTIVE_SHADOW_AUDITED",
                role="runtime_driver",
                payload=audit.canonical_payload(),
                metrics={
                    "proposal_valid": float(audit.proposal_valid),
                    "policy_rejected": float(audit.policy_rejected),
                    "repair_used": float(audit.repair_used),
                    "fallback_used": float(audit.fallback_used),
                },
            )
        )
        try:
            strict_result = strict_runner()
        finally:
            telemetry.close()
        return AdaptiveShadowResult(
            strict_result=strict_result,
            audit=audit,
            telemetry=telemetry,
        )


class AdaptiveRuntimeEngine:
    """Controller-owned bounded dispatcher. Role code only receives a one-attempt grant."""

    def run(self, request: AdaptiveRuntimeRequest) -> AdaptiveRuntimeResult:
        if request.envelope.workflow_mode == WorkflowMode.STRICT_FIXED:
            raise AdaptiveRuntimeError("strict_fixed_must_use_RuntimeDriver_run")
        if request.approved_plan.task_id != request.task_id:
            raise AdaptiveRuntimeError("approved_plan_task_id_mismatch")
        if request.approved_plan.capability_registry_digest != request.registry.digest:
            raise AdaptiveRuntimeError("capability_registry_digest_mismatch")
        if request.execute_step is None and request.dispatcher is None:
            raise AdaptiveRuntimeError("dispatcher_or_execute_step_required")
        self._validate_approved_plan(request)

        session_manager = RuntimeSessionManager()
        session_id = f"adaptive-session-{request.task_id}"
        session = session_manager.start(
            session_id=session_id,
            trace_id=request.trace_id,
            task_id=request.task_id,
            layer_name=request.layer_name,
            canonical_task_spec_hash=request.canonical_task_spec_hash,
            workspace_root=request.runtime_root,
            state_root=request.state_root,
            lease_config=RuntimeLeaseConfig(max_attempts_per_step=1),
        )
        current_plan = request.approved_plan
        runtime_signature = AdaptiveRuntimeSignature(
            workflow_mode=request.envelope.workflow_mode,
            envelope_hash=request.envelope.envelope_hash,
            approved_plan_hash=current_plan.approved_plan_hash,
            capability_registry_digest=request.registry.digest,
            policy_version=request.envelope.policy_version,
        )
        session = session_manager.attach_workflow(session_id, workflow_steps=self._workflow(current_plan))
        session = session_manager.attach_adaptive_audit(
            session_id,
            workflow_mode=request.envelope.workflow_mode.value,
            proposal_hash=request.proposal_hash,
            approved_plan_hash=current_plan.approved_plan_hash,
            plan_policy_report_hash=current_plan.plan_policy_report_hash,
        )
        for report_hash in request.evidence_coverage_report_hashes:
            session = session_manager.attach_adaptive_audit(
                session_id,
                workflow_mode=request.envelope.workflow_mode.value,
                evidence_coverage_report_hash=report_hash,
            )
        for record in request.state_consumption_records:
            session = session_manager.attach_adaptive_audit(
                session_id,
                workflow_mode=request.envelope.workflow_mode.value,
                state_consumption_record_hash=sha256_digest(record.canonical_payload()),
            )
        telemetry = TelemetryEmitter(
            runtime_event_log_path=Path(request.runtime_root) / "telemetry" / "runtime_events.jsonl",
            runtime_fact_log_path=Path(request.runtime_root) / "telemetry" / "runtime_facts.jsonl",
        )
        supervisor = RuntimeSupervisor()
        dispatches: list[AdaptiveDispatchRecord] = []
        produced_refs = dict(request.available_input_refs)
        produced_refs_by_step: dict[str, tuple[str, ...]] = {}
        completed: set[str] = set()
        terminal_failed: set[str] = set()
        replan_count = 0
        plan_replaced = False
        attempt_count = 0

        telemetry.emit(
            TelemetryEvent.create(
                trace_id=request.trace_id,
                task_id=request.task_id,
                event_type="ADAPTIVE_PLAN_APPROVED",
                role="runtime_driver",
                payload={
                    "workflow_mode": request.envelope.workflow_mode.value,
                    "approved_plan_hash": current_plan.approved_plan_hash,
                    "policy_report_hash": current_plan.plan_policy_report_hash,
                    "registry_digest": request.registry.digest,
                    "requested_memory_policy": current_plan.requested_memory_policy,
                    "adaptive_runtime_signature": runtime_signature.digest,
                    "proposal_valid": request.proposal_valid,
                    "policy_rejected": request.policy_rejected,
                    "repair_used": request.repair_used,
                    "fallback_used": request.fallback_used,
                },
                metrics={
                    "proposal_valid": float(request.proposal_valid),
                    "policy_rejected": float(request.policy_rejected),
                    "repair_used": float(request.repair_used),
                    "fallback_used": float(request.fallback_used),
                    "approved_plan_valid": 1.0,
                    "adaptive_plan_model_used": float(bool(request.planner_model_id and request.planner_raw_output_hash)),
                    "adaptive_plan_changed_execution": float(
                        request.envelope.workflow_mode == WorkflowMode.ADAPTIVE_BOUNDED
                        and bool(request.planner_model_id and request.planner_raw_output_hash)
                    ),
                    "adaptive_selected_capability_count": float(len(current_plan.steps)),
                },
            )
        )
        if request.envelope.workflow_mode == WorkflowMode.ADAPTIVE_SHADOW:
            telemetry.close()
            return AdaptiveRuntimeResult(
                session=session_manager.sessions[session_id], dispatches=(), telemetry=telemetry,
                approved_plan_hash=current_plan.approved_plan_hash, completed=True, shadow_only=True,
                runtime_signature=runtime_signature,
            )
        while True:
            remaining = [step for step in current_plan.steps if step.step_id not in completed and step.step_id not in terminal_failed]
            if not remaining:
                break
            ready = [step for step in remaining if set(step.depends_on) <= completed]
            if not ready:
                for step in remaining:
                    terminal_failed.add(step.step_id)
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.CANCELLED.value,
                        last_error="dependency_not_completed",
                    )
                break
            for step in sorted(ready, key=lambda item: item.step_id):
                telemetry.emit(TelemetryEvent.create(
                    trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                    event_type="STEP_READY", role="runtime_driver",
                    payload={"depends_on": list(step.depends_on), "approved_plan_hash": current_plan.approved_plan_hash},
                    metrics={"ready_queue_depth": float(len(ready))},
                ))
                if attempt_count >= current_plan.total_attempt_budget:
                    terminal_failed.add(step.step_id)
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                        last_error="total_attempt_budget_exhausted",
                    )
                    continue
                attempt_count += 1
                attempt_id = f"adaptive-attempt-{attempt_count}"
                descriptor = request.registry.get(step.capability_id)
                input_refs = self._input_refs(step, produced_refs_by_step, produced_refs)
                if any(produced_refs[ref_id] not in descriptor.input_ref_kinds for ref_id in input_refs if descriptor.input_ref_kinds):
                    terminal_failed.add(step.step_id)
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                        last_error="grant_input_ref_kind_mismatch",
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        event_type="STEP_REJECTED_PRE_DISPATCH", role="runtime_driver", severity="error",
                        payload={"error_code": "grant_input_ref_kind_mismatch"},
                    ))
                    continue
                actual_input_kinds = {produced_refs[ref_id] for ref_id in input_refs}
                missing_required_kinds = tuple(
                    kind
                    for kind in descriptor.required_input_ref_kinds
                    if kind not in actual_input_kinds
                )
                if missing_required_kinds:
                    terminal_failed.add(step.step_id)
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                        last_error="grant_required_input_kind_missing",
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        event_type="STEP_REJECTED_PRE_DISPATCH", role="runtime_driver", severity="error",
                        payload={
                            "error_code": "grant_required_input_kind_missing",
                            "missing_input_kinds": list(missing_required_kinds),
                        },
                    ))
                    continue
                grant = self._issue_grant(
                    request=request,
                    plan=current_plan,
                    step=step,
                    attempt_id=attempt_id,
                    input_refs=input_refs,
                )
                if grant.expires_at_ns <= time.time_ns():
                    terminal_failed.add(step.step_id)
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                        last_error="capability_grant_expired_pre_dispatch",
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        event_type="STEP_REJECTED_PRE_DISPATCH", role="runtime_driver", severity="error",
                        payload={"error_code": "capability_grant_expired_pre_dispatch"},
                    ))
                    continue
                self._dispatch_lifecycle(
                    request=request,
                    session_manager=session_manager,
                    session_id=session_id,
                    supervisor=supervisor,
                    telemetry=telemetry,
                    step=step,
                    attempt_id=attempt_id,
                    grant=grant,
                )
                session = session_manager.attach_adaptive_audit(
                    session_id, workflow_mode=request.envelope.workflow_mode.value,
                    capability_grant_hash=grant.grant_hash,
                )
                if request.dispatcher is not None:
                    result = request.dispatcher.dispatch(
                        envelope=request.envelope,
                        approved_plan=current_plan,
                        step=step,
                        grant=grant,
                        attempt_workspace=Path(request.runtime_root) / "adaptive_attempts" / attempt_id,
                    )
                else:
                    assert request.execute_step is not None
                    result = request.execute_step(step, grant)
                # A bounded-Python failure may only downgrade through the
                # descriptor's registered fallback capability. The Controller
                # issues a fresh Grant; the Python Grant is never reused.
                if (
                    not result.success
                    and descriptor.execution_kind.value == "llm_bounded_python"
                    and step.on_failure == "fallback_deterministic"
                    and descriptor.fallback_capability_id
                    and attempt_count < current_plan.total_attempt_budget
                ):
                    fallback_descriptor = request.registry.get(descriptor.fallback_capability_id)
                    fallback_step = replace(
                        step,
                        capability_id=fallback_descriptor.capability_id,
                        output_contract_version=fallback_descriptor.output_contract_version,
                        on_failure="fail",
                    )
                    attempt_count += 1
                    fallback_attempt_id = f"adaptive-attempt-{attempt_count}"
                    fallback_grant = self._issue_grant(
                        request=request,
                        plan=current_plan,
                        step=fallback_step,
                        attempt_id=fallback_attempt_id,
                        input_refs=input_refs,
                    )
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        capability_grant_hash=fallback_grant.grant_hash,
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id,
                        task_id=request.task_id,
                        step_id=step.step_id,
                        attempt_id=fallback_attempt_id,
                        event_type="STEP_FALLBACK_REGRANTED",
                        role="runtime_driver",
                        payload={
                            "failed_capability_id": descriptor.capability_id,
                            "fallback_capability_id": fallback_descriptor.capability_id,
                            "failed_grant_hash": grant.grant_hash,
                            "fallback_grant_hash": fallback_grant.grant_hash,
                        },
                        metrics={"model_fallback_count": 1.0, "adaptive_capability_grant_count": 1.0},
                    ))
                    self._dispatch_lifecycle(
                        request=request,
                        session_manager=session_manager,
                        session_id=session_id,
                        supervisor=supervisor,
                        telemetry=telemetry,
                        step=fallback_step,
                        attempt_id=fallback_attempt_id,
                        grant=fallback_grant,
                    )
                    if request.dispatcher is not None:
                        fallback_result = request.dispatcher.dispatch(
                            envelope=request.envelope,
                            approved_plan=current_plan,
                            step=fallback_step,
                            grant=fallback_grant,
                            attempt_workspace=Path(request.runtime_root) / "adaptive_attempts" / fallback_attempt_id,
                        )
                    else:
                        assert request.execute_step is not None
                        fallback_result = request.execute_step(fallback_step, fallback_grant)
                    prior_metrics = dict(result.metrics)
                    for key, value in fallback_result.metrics.items():
                        prior_metrics[key] = prior_metrics.get(key, 0.0) + value
                    result = replace(
                        fallback_result,
                        projection_report_hashes=(
                            result.projection_report_hashes + fallback_result.projection_report_hashes
                        ),
                        quality_report_hashes=(result.quality_report_hashes + fallback_result.quality_report_hashes),
                        program_hashes=result.program_hashes + fallback_result.program_hashes,
                        source_hashes=result.source_hashes + fallback_result.source_hashes,
                        validator_report_hashes=(
                            result.validator_report_hashes + fallback_result.validator_report_hashes
                        ),
                        metrics=prior_metrics,
                    )
                    step = fallback_step
                    descriptor = fallback_descriptor
                    grant = fallback_grant
                    attempt_id = fallback_attempt_id
                for report_hash in result.evidence_coverage_report_hashes:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        evidence_coverage_report_hash=report_hash,
                    )
                for report_hash in result.projection_report_hashes:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        projection_report_hash=report_hash,
                    )
                for report_hash in result.quality_report_hashes:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        capability_quality_report_hash=report_hash,
                    )
                for program_hash in result.program_hashes:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        transform_program_hash=program_hash,
                    )
                for source_hash in result.source_hashes:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        code_source_hash=source_hash,
                    )
                for decision_record in result.evidence_coverage_decision_records:
                    decision_hash = sha256_digest(decision_record)
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        adaptive_decision_record_hash=decision_hash,
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id,
                        task_id=request.task_id,
                        step_id=step.step_id,
                        attempt_id=attempt_id,
                        event_type="EVIDENCE_COVERAGE_DECIDED",
                        role="runtime_driver",
                        payload={
                            "decision_hash": decision_hash,
                            "decision_record": decision_record,
                        },
                        metrics={"evidence_coverage_decision_count": 1.0},
                    ))
                for record in result.state_consumption_records:
                    session = session_manager.attach_adaptive_audit(
                        session_id,
                        workflow_mode=request.envelope.workflow_mode.value,
                        state_consumption_record_hash=sha256_digest(record.canonical_payload()),
                    )
                if result.grant_hash != grant.grant_hash or (result.attempt_id and result.attempt_id != attempt_id):
                    terminal_failed.add(step.step_id)
                    supervisor.fail(step.step_id, "grant_binding_mismatch")
                    session = session_manager.update_attempt_record(
                        session_id, attempt_id=attempt_id, state=StepLifecycleState.FAILED.value,
                        validator_report_hashes=result.validator_report_hashes,
                    )
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                        last_error="grant_binding_mismatch",
                    )
                    dispatches.append(AdaptiveDispatchRecord(step.step_id, attempt_id, grant.grant_hash, StepLifecycleState.FAILED.value, error_code="grant_binding_mismatch"))
                    continue
                if result.timed_out:
                    terminal_failed.add(step.step_id)
                    supervisor.trap(step.step_id, "step_timeout")
                    session = session_manager.update_attempt_record(
                        session_id, attempt_id=attempt_id, state=StepLifecycleState.TRAPPED.value,
                        trap_reason="step_timeout", validator_report_hashes=result.validator_report_hashes,
                    )
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.TRAPPED.value,
                        attempt_id=attempt_id, last_error="step_timeout", metrics=result.metrics,
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        attempt_id=attempt_id, event_type="STEP_TRAPPED", role=step.role, severity="error",
                        payload={"grant_hash": grant.grant_hash, "reason": "step_timeout"},
                        metrics={"adaptive_step_timeout": 1.0},
                    ))
                    dispatches.append(AdaptiveDispatchRecord(step.step_id, attempt_id, grant.grant_hash, StepLifecycleState.TRAPPED.value, error_code="step_timeout"))
                    continue
                if (
                    result.success
                    and len(result.output_refs) == len(result.output_ref_kinds)
                    and all(kind in descriptor.output_ref_kinds for kind in result.output_ref_kinds)
                ):
                    supervisor.complete(step.step_id)
                    completed.add(step.step_id)
                    produced_refs.update(dict(zip(result.output_refs, result.output_ref_kinds, strict=True)))
                    produced_refs_by_step[step.step_id] = result.output_refs
                    session = session_manager.update_attempt_record(
                        session_id, attempt_id=attempt_id, state=StepLifecycleState.COMPLETED.value,
                        validator_report_hashes=result.validator_report_hashes,
                    )
                    session = session_manager.update_workflow_step(
                        session_id, step_id=step.step_id, state=StepLifecycleState.COMPLETED.value,
                        attempt_id=attempt_id, output_refs=result.output_refs, metrics=result.metrics,
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        attempt_id=attempt_id, event_type="STEP_COMPLETED", role=step.role,
                        payload={"grant_hash": grant.grant_hash, "approved_plan_hash": current_plan.approved_plan_hash},
                        metrics={"adaptive_step_completed": 1.0, **result.metrics},
                    ))
                    dispatches.append(AdaptiveDispatchRecord(step.step_id, attempt_id, grant.grant_hash, StepLifecycleState.COMPLETED.value, result.output_refs))
                    continue
                error_code = result.error_code or "step_validator_failed"
                supervisor.fail(step.step_id, error_code)
                session = session_manager.update_attempt_record(
                    session_id, attempt_id=attempt_id, state=StepLifecycleState.FAILED.value,
                    validator_report_hashes=result.validator_report_hashes,
                )
                session = session_manager.update_workflow_step(
                    session_id, step_id=step.step_id, state=StepLifecycleState.FAILED.value,
                    attempt_id=attempt_id, last_error=error_code, metrics=result.metrics,
                )
                telemetry.emit(TelemetryEvent.create(
                    trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                    attempt_id=attempt_id, event_type="STEP_FAILED", role=step.role, severity="error",
                    payload={"grant_hash": grant.grant_hash, "error_code": error_code},
                    metrics={"adaptive_step_failed": 1.0},
                ))
                dispatches.append(AdaptiveDispatchRecord(step.step_id, attempt_id, grant.grant_hash, StepLifecycleState.FAILED.value, error_code=error_code))
                replacement = None
                if (
                    step.on_failure == "request_replan"
                    and replan_count < request.envelope.max_replans
                    and request.replan is not None
                ):
                    replacement = request.replan(current_plan, tuple(sorted(completed)), error_code)
                if replacement is not None and self._valid_replan(request, current_plan, replacement, completed):
                    replan_count += 1
                    plan_replaced = True
                    current_plan = replacement
                    runtime_signature = replace(
                        runtime_signature,
                        approved_plan_hash=current_plan.approved_plan_hash,
                    )
                    # The failed source step may be replaced by the approved
                    # unexecuted subgraph; retain failures only for steps that
                    # still exist in the replacement plan.
                    terminal_failed = {
                        step_id for step_id in terminal_failed
                        if step_id in {candidate.step_id for candidate in current_plan.steps}
                    }
                    session = session_manager.append_replan_record(
                        session_id,
                        record=RuntimeReplanRecord(
                            replan_id=f"replan-{request.task_id}-{replan_count}", task_id=request.task_id,
                            source_step_id=step.step_id, attempt_id=attempt_id,
                            trigger_state=StepLifecycleState.FAILED.value, trigger_reason=error_code,
                            fallback_action="replace_unexecuted_subgraph", selected_capability=step.capability_id,
                            fallback_dag_hash=sha256_digest(replacement.canonical_payload()),
                        ),
                    )
                    telemetry.emit(TelemetryEvent.create(
                        trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id,
                        attempt_id=attempt_id, event_type="STEP_REPLAN_REQUESTED", role="runtime_driver",
                        payload={"old_plan_hash": grant.approved_plan_hash, "new_plan_hash": replacement.approved_plan_hash, "error_code": error_code},
                        metrics={"adaptive_replan_count": 1.0},
                    ))
                    session = session_manager.attach_workflow(session_id, workflow_steps=self._workflow(current_plan, completed=completed, failed=terminal_failed))
                    break
                terminal_failed.add(step.step_id)
            # A replacement plan restarts ready-step calculation; otherwise loop finds any successors blocked.
        session = session_manager.sessions[session_id]
        telemetry.close()
        return AdaptiveRuntimeResult(
            session=session,
            dispatches=tuple(dispatches),
            telemetry=telemetry,
            approved_plan_hash=current_plan.approved_plan_hash,
            completed=not terminal_failed and len(completed) == len(current_plan.steps),
            plan_replaced=plan_replaced,
            runtime_signature=runtime_signature,
        )

    @staticmethod
    def _workflow(plan: ApprovedPlan, *, completed: set[str] | None = None, failed: set[str] | None = None) -> tuple[RuntimeWorkflowStep, ...]:
        completed = completed or set()
        failed = failed or set()
        return tuple(
            RuntimeWorkflowStep(
                step_id=step.step_id, role=step.role, capability=step.capability_id,
                depends_on=step.depends_on, input_refs=step.input_ref_ids,
                state=(StepLifecycleState.COMPLETED.value if step.step_id in completed else StepLifecycleState.FAILED.value if step.step_id in failed else StepLifecycleState.PENDING.value),
            )
            for step in plan.steps
        )

    @staticmethod
    def _input_refs(
        step: PlanStepProposal,
        produced_refs_by_step: dict[str, tuple[str, ...]],
        refs: dict[str, str],
    ) -> tuple[str, ...]:
        ordered: list[str] = []
        for ref_id in step.input_ref_ids:
            if ref_id in refs and ref_id not in ordered:
                ordered.append(ref_id)
        for dependency in step.depends_on:
            for ref_id in produced_refs_by_step.get(dependency, ()):
                if ref_id in refs and ref_id not in ordered:
                    ordered.append(ref_id)
        return tuple(ordered)

    @staticmethod
    def _issue_grant(
        *, request: AdaptiveRuntimeRequest, plan: ApprovedPlan, step: PlanStepProposal,
        attempt_id: str, input_refs: tuple[str, ...],
    ) -> CapabilityGrant:
        descriptor = request.registry.get(step.capability_id)
        return CapabilityGrant(
            grant_id=f"grant-{request.task_id}-{step.step_id}-{attempt_id}", task_id=request.task_id,
            session_id=f"adaptive-session-{request.task_id}", step_id=step.step_id, attempt_id=attempt_id,
            capability_id=descriptor.capability_id, capability_version=descriptor.version,
            input_ref_ids=input_refs, output_contract_version=step.output_contract_version,
            workspace_root_id=request.workspace_root_id, max_runtime_ms=descriptor.max_runtime_ms,
            expires_at_ns=time.time_ns() + (descriptor.max_runtime_ms if request.grant_ttl_ms is None else request.grant_ttl_ms) * 1_000_000,
            approved_plan_hash=plan.approved_plan_hash,
        )

    @staticmethod
    def _dispatch_lifecycle(
        *, request: AdaptiveRuntimeRequest, session_manager: RuntimeSessionManager, session_id: str,
        supervisor: RuntimeSupervisor, telemetry: TelemetryEmitter, step: PlanStepProposal,
        attempt_id: str, grant: CapabilityGrant,
    ) -> None:
        supervisor.register(task_id=request.task_id, step_id=step.step_id, attempt_id=attempt_id, role=step.role)
        dispatched = supervisor.dispatch(step.step_id)
        session_manager.append_attempt_record(session_id, record=StepAttemptRecord(
            task_id=request.task_id, step_id=step.step_id, attempt_id=attempt_id, owner_role=step.role,
            state=StepLifecycleState.DISPATCHED.value, dispatched_at_ns=dispatched.dispatched_at_ns,
            resource_handles=(grant.grant_hash,), workspace_dirs=(request.workspace_root_id,),
        ))
        session_manager.update_workflow_step(session_id, step_id=step.step_id, state=StepLifecycleState.DISPATCHED.value, attempt_id=attempt_id)
        telemetry.emit(TelemetryEvent.create(
            trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id, attempt_id=attempt_id,
            event_type="STEP_DISPATCHED", role="runtime_driver",
            payload={"workflow_mode": request.envelope.workflow_mode.value, "grant_hash": grant.grant_hash, "capability_id": grant.capability_id},
            metrics={"capability_grant_issued": 1.0, "adaptive_capability_grant_count": 1.0},
        ))
        acked = supervisor.ack(step.step_id)
        session_manager.update_attempt_record(session_id, attempt_id=attempt_id, state=StepLifecycleState.ACKED.value, acked_at_ns=acked.acked_at_ns)
        telemetry.emit(TelemetryEvent.create(trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id, attempt_id=attempt_id, event_type="STEP_ACKED", role=step.role, metrics={"ack_count": 1.0}))
        running = supervisor.run_start(step.step_id)
        session_manager.update_attempt_record(session_id, attempt_id=attempt_id, state=StepLifecycleState.RUNNING.value, running_at_ns=running.started_at_ns, heartbeat_at_ns=running.last_heartbeat_ns)
        session_manager.update_workflow_step(session_id, step_id=step.step_id, state=StepLifecycleState.RUNNING.value, attempt_id=attempt_id)
        telemetry.emit(TelemetryEvent.create(trace_id=request.trace_id, task_id=request.task_id, step_id=step.step_id, attempt_id=attempt_id, event_type="STEP_RUNNING", role=step.role, metrics={"run_start_count": 1.0}))

    def _validate_approved_plan(self, request: AdaptiveRuntimeRequest) -> None:
        proposal = PlanProposal(
            proposal_id=request.approved_plan.source_proposal_id,
            task_id=request.approved_plan.task_id,
            steps=request.approved_plan.steps,
            final_output_contract_version=request.approved_plan.final_output_contract_version,
            requested_memory_policy=request.approved_plan.requested_memory_policy,
        )
        outcome = PlanPolicyValidator(
            request.registry,
            allow_llm_python=request.envelope.allow_llm_python,
        ).validate(
            proposal,
            request.envelope,
            available_input_refs=request.available_input_refs,
        )
        if outcome.approved_plan is None or outcome.approved_plan.steps != request.approved_plan.steps:
            raise AdaptiveRuntimeError("approved_plan_policy_validation_failed")
        if request.approved_plan.total_attempt_budget > request.envelope.max_total_attempts:
            raise AdaptiveRuntimeError("approved_plan_attempt_budget_exceeded")

    def _valid_replan(
        self,
        request: AdaptiveRuntimeRequest,
        previous: ApprovedPlan,
        replacement: ApprovedPlan,
        completed: set[str],
    ) -> bool:
        if replacement.task_id != previous.task_id:
            return False
        if replacement.capability_registry_digest != request.registry.digest:
            return False
        if not replacement.plan_policy_report_hash or replacement.total_attempt_budget > request.envelope.max_total_attempts:
            return False
        try:
            self._validate_approved_plan(replace(request, approved_plan=replacement))
        except AdaptiveRuntimeError:
            return False
        previous_steps = {step.step_id: step for step in previous.steps}
        replacement_steps = {step.step_id: step for step in replacement.steps}
        return all(
            step_id in replacement_steps and replacement_steps[step_id].canonical_payload() == previous_steps[step_id].canonical_payload()
            for step_id in completed
        )
