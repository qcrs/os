from __future__ import annotations

import time
from dataclasses import dataclass, field, replace

from v2.contracts import StepLifecycleState
from v2.contracts import RUNTIME_REPLAN_RECORD_SCHEMA_VERSION
from v2.contracts import RUNTIME_TASK_SESSION_SCHEMA_VERSION
from v2.runtime.supervisor import WorkerSessionSnapshot
from v2.utils import compact_json_payload, sha256_digest


def _audit_list_payload(*, prefix: str, items: tuple[str, ...]) -> dict[str, object]:
    normalized = tuple(str(item) for item in items if str(item))
    if not normalized:
        return {}
    return {
        f"{prefix}_count": len(normalized),
        f"{prefix}_hash": sha256_digest(normalized),
    }


@dataclass(frozen=True)
class RuntimeWorkflowStep:
    step_id: str
    role: str
    capability: str
    depends_on: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    can_skip_if: str = ""
    max_retries: int = 0
    state: str = StepLifecycleState.PENDING.value
    attempt_id: str = ""
    last_error: str = ""
    started_at_ns: int = 0
    completed_at_ns: int = 0
    updated_at_ns: int = 0
    metrics: dict[str, float] = field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "step_id": self.step_id,
            "role": self.role,
            "capability": self.capability,
            "depends_on": list(self.depends_on),
            **_audit_list_payload(prefix="input_ref", items=self.input_refs),
            **_audit_list_payload(prefix="output_ref", items=self.output_refs),
            "can_skip_if": self.can_skip_if,
            "max_retries": self.max_retries,
            "state": self.state,
            "attempt_id": self.attempt_id,
            "metrics": dict(sorted(self.metrics.items())),
            }
        )


@dataclass(frozen=True)
class StepAttemptRecord:
    task_id: str
    step_id: str
    attempt_id: str
    owner_role: str
    state: str
    attempt_index: int = 0
    worker_id: str = ""
    dispatched_at_ns: int = 0
    acked_at_ns: int = 0
    running_at_ns: int = 0
    heartbeat_at_ns: int = 0
    completed_at_ns: int = 0
    cancel_reason: str = ""
    trap_reason: str = ""
    fallback_action: str = ""
    resource_handles: tuple[str, ...] = ()
    workspace_dirs: tuple[str, ...] = ()
    validator_report_hashes: tuple[str, ...] = ()

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "step_id": self.step_id,
            "attempt_id": self.attempt_id,
            "owner_role": self.owner_role,
            "state": self.state,
            "cancel_reason": self.cancel_reason,
            "trap_reason": self.trap_reason,
            "fallback_action": self.fallback_action,
            **_audit_list_payload(prefix="resource_handle", items=self.resource_handles),
            **_audit_list_payload(prefix="workspace_dir", items=self.workspace_dirs),
            **_audit_list_payload(prefix="validator_report_hash", items=self.validator_report_hashes),
            }
        )


@dataclass(frozen=True)
class RuntimeReplanRecord:
    replan_id: str
    task_id: str
    source_step_id: str
    attempt_id: str
    trigger_state: str
    trigger_reason: str
    fallback_action: str
    selected_capability: str
    downgraded_execution_goal: bool = False
    fallback_dag_hash: str = ""
    created_at_ns: int = field(default_factory=time.time_ns)
    schema_version: str = RUNTIME_REPLAN_RECORD_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "replan_id": self.replan_id,
            "task_id": self.task_id,
            "source_step_id": self.source_step_id,
            "attempt_id": self.attempt_id,
            "trigger_state": self.trigger_state,
            "trigger_reason": self.trigger_reason,
            "fallback_action": self.fallback_action,
            "selected_capability": self.selected_capability,
            "downgraded_execution_goal": self.downgraded_execution_goal,
            "fallback_dag_hash": self.fallback_dag_hash,
            "created_at_ns": self.created_at_ns,
            "schema_version": self.schema_version,
            }
        )


@dataclass(frozen=True)
class RuntimeLeaseConfig:
    ack_timeout_ms: int = 250
    heartbeat_interval_ms: int = 2000
    lease_timeout_ms: int = 6000
    max_attempts_per_step: int = 2
    teardown_grace_ms: int = 1000

    def canonical_payload(self) -> dict[str, int]:
        return {
            "ack_timeout_ms": self.ack_timeout_ms,
            "heartbeat_interval_ms": self.heartbeat_interval_ms,
            "lease_timeout_ms": self.lease_timeout_ms,
            "max_attempts_per_step": self.max_attempts_per_step,
            "teardown_grace_ms": self.teardown_grace_ms,
        }


@dataclass(frozen=True)
class RuntimeTaskSession:
    session_id: str
    trace_id: str
    task_id: str
    layer_name: str
    canonical_task_spec_hash: str
    workspace_root: str
    state_root: str
    retrieval_log_hash: str = ""
    input_manifest_hash: str = ""
    artifact_manifest_hash: str = ""
    planner_handoff_hash: str = ""
    runtime_signature_hash: str = ""
    runtime_signature_manifest_bundle_hash: str = ""
    replay_input_artifact_hashes: tuple[str, ...] = ()
    state_ref_ids: tuple[str, ...] = ()
    artifact_ref_ids: tuple[str, ...] = ()
    memory_ref_ids: tuple[str, ...] = ()
    workflow_steps: tuple[RuntimeWorkflowStep, ...] = ()
    attempt_records: tuple[StepAttemptRecord, ...] = ()
    replan_history: tuple[RuntimeReplanRecord, ...] = ()
    replay_ledger_ids: tuple[str, ...] = ()
    current_step_id: str = ""
    runtime_fallback_count: int = 0
    runtime_replan_count: int = 0
    summary_artifact_ref_id: str = ""
    memory_match_result_hash: str = ""
    workflow_mode: str = ""
    adaptive_proposal_hash: str = ""
    adaptive_approved_plan_hash: str = ""
    adaptive_plan_policy_report_hash: str = ""
    capability_grant_hashes: tuple[str, ...] = ()
    evidence_coverage_report_hashes: tuple[str, ...] = ()
    projection_report_hashes: tuple[str, ...] = ()
    capability_quality_report_hashes: tuple[str, ...] = ()
    transform_program_hashes: tuple[str, ...] = ()
    code_source_hashes: tuple[str, ...] = ()
    adaptive_decision_record_hashes: tuple[str, ...] = ()
    state_consumption_record_hashes: tuple[str, ...] = ()
    current_attempt_id: str = ""
    last_fallback_action: str = ""
    session_state: str = ""
    created_at_ns: int = field(default_factory=time.time_ns)
    updated_at_ns: int = 0
    lease_config: RuntimeLeaseConfig = field(default_factory=RuntimeLeaseConfig)
    schema_version: str = RUNTIME_TASK_SESSION_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return compact_json_payload(
            {
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "layer_name": self.layer_name,
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "workspace_root": self.workspace_root,
            "state_root": self.state_root,
            "retrieval_log_hash": self.retrieval_log_hash,
            "input_manifest_hash": self.input_manifest_hash,
            "artifact_manifest_hash": self.artifact_manifest_hash,
            "planner_handoff_hash": self.planner_handoff_hash,
            "runtime_signature_hash": self.runtime_signature_hash,
            "runtime_signature_manifest_bundle_hash": self.runtime_signature_manifest_bundle_hash,
            "replay_input_artifact_hashes": list(self.replay_input_artifact_hashes),
            "state_ref_ids": list(self.state_ref_ids),
            "artifact_ref_ids": list(self.artifact_ref_ids),
            "memory_ref_ids": list(self.memory_ref_ids),
            "workflow_steps": [step.canonical_payload() for step in self.workflow_steps],
            "attempt_records": [record.canonical_payload() for record in self.attempt_records],
            "replan_history": [record.canonical_payload() for record in self.replan_history],
            "replay_ledger_ids": list(self.replay_ledger_ids),
            "current_step_id": self.current_step_id,
            "runtime_fallback_count": self.runtime_fallback_count,
            "runtime_replan_count": self.runtime_replan_count,
            "summary_artifact_ref_id": self.summary_artifact_ref_id,
            "memory_match_result_hash": self.memory_match_result_hash,
            "workflow_mode": self.workflow_mode,
            "adaptive_proposal_hash": self.adaptive_proposal_hash,
            "adaptive_approved_plan_hash": self.adaptive_approved_plan_hash,
            "adaptive_plan_policy_report_hash": self.adaptive_plan_policy_report_hash,
            "capability_grant_hashes": list(self.capability_grant_hashes),
            "evidence_coverage_report_hashes": list(self.evidence_coverage_report_hashes),
            "projection_report_hashes": list(self.projection_report_hashes),
            "capability_quality_report_hashes": list(self.capability_quality_report_hashes),
            "transform_program_hashes": list(self.transform_program_hashes),
            "code_source_hashes": list(self.code_source_hashes),
            "adaptive_decision_record_hashes": list(self.adaptive_decision_record_hashes),
            "state_consumption_record_hashes": list(self.state_consumption_record_hashes),
            "current_attempt_id": self.current_attempt_id,
            "last_fallback_action": self.last_fallback_action,
            "session_state": self.session_state,
            "created_at_ns": self.created_at_ns,
            "updated_at_ns": self.updated_at_ns,
            "lease_config": self.lease_config.canonical_payload(),
            "schema_version": self.schema_version,
            }
        )

    @property
    def session_hash(self) -> str:
        return sha256_digest(self.canonical_payload())

    @property
    def workflow_step_count(self) -> int:
        return len(self.workflow_steps)

    @property
    def completed_workflow_step_count(self) -> int:
        terminal_states = {
            StepLifecycleState.COMPLETED.value,
            StepLifecycleState.FAILED.value,
            StepLifecycleState.TRAPPED.value,
            StepLifecycleState.CANCELLED.value,
            StepLifecycleState.GC_DONE.value,
        }
        return sum(1 for step in self.workflow_steps if step.state in terminal_states)

    @property
    def attempt_count(self) -> int:
        return len(self.attempt_records)

    @property
    def replan_count(self) -> int:
        return len(self.replan_history)


@dataclass
class RuntimeSessionManager:
    sessions: dict[str, RuntimeTaskSession] = field(default_factory=dict)

    def start(
        self,
        *,
        session_id: str,
        trace_id: str,
        task_id: str,
        layer_name: str,
        canonical_task_spec_hash: str,
        workspace_root: str,
        state_root: str,
        retrieval_log_hash: str = "",
        lease_config: RuntimeLeaseConfig | None = None,
    ) -> RuntimeTaskSession:
        session = RuntimeTaskSession(
            session_id=session_id,
            trace_id=trace_id,
            task_id=task_id,
            layer_name=layer_name,
            canonical_task_spec_hash=canonical_task_spec_hash,
            workspace_root=workspace_root,
            state_root=state_root,
            retrieval_log_hash=retrieval_log_hash,
            lease_config=lease_config or RuntimeLeaseConfig(),
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = session
        return session

    def attach_workflow(
        self,
        session_id: str,
        *,
        workflow_steps: tuple[RuntimeWorkflowStep, ...],
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        current_step_id = workflow_steps[0].step_id if workflow_steps else session.current_step_id
        updated = replace(
            session,
            workflow_steps=workflow_steps,
            current_step_id=current_step_id,
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def attach_adaptive_audit(
        self,
        session_id: str,
        *,
        workflow_mode: str,
        proposal_hash: str = "",
        approved_plan_hash: str = "",
        plan_policy_report_hash: str = "",
        capability_grant_hash: str = "",
        evidence_coverage_report_hash: str = "",
        projection_report_hash: str = "",
        capability_quality_report_hash: str = "",
        transform_program_hash: str = "",
        code_source_hash: str = "",
        adaptive_decision_record_hash: str = "",
        state_consumption_record_hash: str = "",
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]

        def append_unique(values: tuple[str, ...], value: str) -> tuple[str, ...]:
            return values if not value or value in values else values + (value,)

        updated = replace(
            session,
            workflow_mode=workflow_mode or session.workflow_mode,
            adaptive_proposal_hash=proposal_hash or session.adaptive_proposal_hash,
            adaptive_approved_plan_hash=approved_plan_hash or session.adaptive_approved_plan_hash,
            adaptive_plan_policy_report_hash=(plan_policy_report_hash or session.adaptive_plan_policy_report_hash),
            capability_grant_hashes=append_unique(session.capability_grant_hashes, capability_grant_hash),
            evidence_coverage_report_hashes=append_unique(session.evidence_coverage_report_hashes, evidence_coverage_report_hash),
            projection_report_hashes=append_unique(session.projection_report_hashes, projection_report_hash),
            capability_quality_report_hashes=append_unique(
                session.capability_quality_report_hashes, capability_quality_report_hash
            ),
            transform_program_hashes=append_unique(session.transform_program_hashes, transform_program_hash),
            code_source_hashes=append_unique(session.code_source_hashes, code_source_hash),
            adaptive_decision_record_hashes=append_unique(
                session.adaptive_decision_record_hashes,
                adaptive_decision_record_hash,
            ),
            state_consumption_record_hashes=append_unique(session.state_consumption_record_hashes, state_consumption_record_hash),
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def attach_refs(
        self,
        session_id: str,
        *,
        input_manifest_hash: str,
        artifact_manifest_hash: str,
        state_ref_ids: tuple[str, ...],
        artifact_ref_ids: tuple[str, ...],
        memory_ref_ids: tuple[str, ...],
        replay_ledger_ids: tuple[str, ...] | None = None,
        summary_artifact_ref_id: str | None = None,
        memory_match_result_hash: str | None = None,
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        updated = replace(
            session,
            input_manifest_hash=input_manifest_hash,
            artifact_manifest_hash=artifact_manifest_hash,
            state_ref_ids=state_ref_ids,
            artifact_ref_ids=artifact_ref_ids,
            memory_ref_ids=memory_ref_ids,
            replay_ledger_ids=session.replay_ledger_ids if replay_ledger_ids is None else replay_ledger_ids,
            summary_artifact_ref_id=(
                session.summary_artifact_ref_id
                if summary_artifact_ref_id is None
                else summary_artifact_ref_id
            ),
            memory_match_result_hash=(
                session.memory_match_result_hash
                if memory_match_result_hash is None
                else memory_match_result_hash
            ),
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def increment_runtime_fallback(self, session_id: str) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        updated = replace(
            session,
            runtime_fallback_count=session.runtime_fallback_count + 1,
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def increment_runtime_replan(self, session_id: str, fallback_action: str) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        updated = replace(
            session,
            runtime_replan_count=session.runtime_replan_count + 1,
            last_fallback_action=fallback_action,
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def append_replan_record(
        self,
        session_id: str,
        *,
        record: RuntimeReplanRecord,
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        updated = replace(
            session,
            replan_history=session.replan_history + (record,),
            last_fallback_action=record.fallback_action,
            runtime_replan_count=max(session.runtime_replan_count, len(session.replan_history) + 1),
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def append_attempt_record(
        self,
        session_id: str,
        *,
        record: StepAttemptRecord,
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        updated = replace(
            session,
            attempt_records=session.attempt_records + (record,),
            current_step_id=record.step_id,
            current_attempt_id=record.attempt_id,
            updated_at_ns=time.time_ns(),
        )
        self.sessions[session_id] = updated
        return updated

    def update_attempt_record(
        self,
        session_id: str,
        *,
        attempt_id: str,
        state: str,
        dispatched_at_ns: int | None = None,
        acked_at_ns: int | None = None,
        running_at_ns: int | None = None,
        heartbeat_at_ns: int | None = None,
        completed_at_ns: int | None = None,
        trap_reason: str | None = None,
        cancel_reason: str | None = None,
        fallback_action: str | None = None,
        validator_report_hashes: tuple[str, ...] | None = None,
        resource_handles: tuple[str, ...] | None = None,
        workspace_dirs: tuple[str, ...] | None = None,
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        now = time.time_ns()
        updated_records: list[StepAttemptRecord] = []
        for record in session.attempt_records:
            if record.attempt_id != attempt_id:
                updated_records.append(record)
                continue
            updated_records.append(
                replace(
                    record,
                    state=state,
                    dispatched_at_ns=(
                        record.dispatched_at_ns if dispatched_at_ns is None else dispatched_at_ns
                    ),
                    acked_at_ns=(
                        (now if state == StepLifecycleState.ACKED.value else record.acked_at_ns)
                        if acked_at_ns is None
                        else acked_at_ns
                    ),
                    running_at_ns=(
                        (now if state == StepLifecycleState.RUNNING.value else record.running_at_ns)
                        if running_at_ns is None
                        else running_at_ns
                    ),
                    heartbeat_at_ns=(
                        (now if state == StepLifecycleState.RUNNING.value else record.heartbeat_at_ns)
                        if heartbeat_at_ns is None
                        else heartbeat_at_ns
                    ),
                    completed_at_ns=(
                        (
                            now
                            if state
                            in {
                                StepLifecycleState.COMPLETED.value,
                                StepLifecycleState.FAILED.value,
                                StepLifecycleState.TRAPPED.value,
                                StepLifecycleState.CANCELLED.value,
                                StepLifecycleState.GC_DONE.value,
                            }
                            else record.completed_at_ns
                        )
                        if completed_at_ns is None
                        else completed_at_ns
                    ),
                    trap_reason=record.trap_reason if trap_reason is None else trap_reason,
                    cancel_reason=record.cancel_reason if cancel_reason is None else cancel_reason,
                    fallback_action=record.fallback_action if fallback_action is None else fallback_action,
                    validator_report_hashes=(
                        record.validator_report_hashes
                        if validator_report_hashes is None
                        else validator_report_hashes
                    ),
                    resource_handles=record.resource_handles if resource_handles is None else resource_handles,
                    workspace_dirs=record.workspace_dirs if workspace_dirs is None else workspace_dirs,
                )
            )
        updated = replace(
            session,
            attempt_records=tuple(updated_records),
            current_attempt_id=attempt_id,
            session_state=state,
            last_fallback_action=(
                session.last_fallback_action if fallback_action is None else fallback_action
            ),
            updated_at_ns=now,
        )
        self.sessions[session_id] = updated
        return updated

    def update_workflow_step(
        self,
        session_id: str,
        *,
        step_id: str,
        state: str,
        attempt_id: str | None = None,
        output_refs: tuple[str, ...] | None = None,
        metrics: dict[str, float] | None = None,
        last_error: str | None = None,
    ) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        now = time.time_ns()
        updated_steps: list[RuntimeWorkflowStep] = []
        for step in session.workflow_steps:
            if step.step_id != step_id:
                updated_steps.append(step)
                continue
            next_metrics = dict(step.metrics)
            if metrics is not None:
                next_metrics.update(metrics)
            started_at_ns = step.started_at_ns
            completed_at_ns = step.completed_at_ns
            if state in {
                StepLifecycleState.ACKED.value,
                StepLifecycleState.RUNNING.value,
                StepLifecycleState.COMPLETED.value,
                StepLifecycleState.FAILED.value,
                StepLifecycleState.TRAPPED.value,
                StepLifecycleState.CANCELLED.value,
                StepLifecycleState.GC_PENDING.value,
                StepLifecycleState.GC_DONE.value,
            } and started_at_ns == 0:
                started_at_ns = now
            if state in {
                StepLifecycleState.COMPLETED.value,
                StepLifecycleState.FAILED.value,
                StepLifecycleState.TRAPPED.value,
                StepLifecycleState.CANCELLED.value,
                StepLifecycleState.GC_DONE.value,
            }:
                completed_at_ns = now
            updated_steps.append(
                replace(
                    step,
                    state=state,
                    attempt_id=step.attempt_id if attempt_id is None else attempt_id,
                    output_refs=step.output_refs if output_refs is None else output_refs,
                    metrics=next_metrics,
                    last_error=step.last_error if last_error is None else last_error,
                    started_at_ns=started_at_ns,
                    completed_at_ns=completed_at_ns,
                    updated_at_ns=now,
                )
            )
        updated = replace(
            session,
            workflow_steps=tuple(updated_steps),
            current_step_id=step_id,
            session_state=state,
            updated_at_ns=now,
        )
        self.sessions[session_id] = updated
        return updated

    def update_state(self, session_id: str, snapshot: WorkerSessionSnapshot) -> RuntimeTaskSession:
        session = self.sessions[session_id]
        now = time.time_ns()
        updated_steps: list[RuntimeWorkflowStep] = []
        matched = False
        for step in session.workflow_steps:
            if step.step_id != snapshot.step_id:
                updated_steps.append(step)
                continue
            matched = True
            updated_steps.append(
                replace(
                    step,
                    state=snapshot.state,
                    attempt_id=snapshot.attempt_id,
                    last_error=snapshot.last_error,
                    started_at_ns=step.started_at_ns or snapshot.started_at_ns,
                    completed_at_ns=(
                        snapshot.completed_at_ns
                        or step.completed_at_ns
                        or (now if snapshot.state == StepLifecycleState.GC_DONE.value else 0)
                    ),
                    updated_at_ns=now,
                )
            )
        updated = replace(
            session,
            workflow_steps=tuple(updated_steps) if matched else session.workflow_steps,
            current_step_id=snapshot.step_id,
            session_state=snapshot.state,
            updated_at_ns=now,
        )
        self.sessions[session_id] = updated
        return updated
