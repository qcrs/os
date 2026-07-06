from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
import json
from pathlib import Path
import time

from v2.benchmark.models import QualityFloorResult
from v2.control import (
    AckReceived,
    ControlHeader,
    ControlPlaneLoopbackServer,
    ErrorResult,
    EventType,
    ExecRequest,
    Heartbeat,
    RefHandle,
    ReusePolicy,
    RunStart,
    SuccessResult,
    TrapFatal,
    frame_control_message,
)
from v2.contracts import (
    PlannerHandoff,
    RefKind,
    RefStatus,
    ReplayClass,
    RuntimeCompatibilitySignature,
    RuntimeSignatureManifestBundle,
    StepLifecycleState,
    StorageKind,
)
from v2.memory import MemoryCommit, MemoryIndexStore, MemoryMatchResult
from v2.refs import ExecutionArtifactRef, SemanticStateRef
from v2.retrieval import RetrievalBundle
from v2.runtime.codeact import CodeActExecutionRecord, CodeActPlan
from v2.runtime.commit_gate import CommitGateDecision, RuntimeCommitGate
from v2.runtime.execution import ExecutionLogCapture, ExecutionStepRecord
from v2.runtime.fallback import FallbackDag, FallbackPlanner, FallbackResolutionRecord
from v2.runtime.ledger import ReplayLedger, ReplayLedgerEntry
from v2.runtime.lineage import TaskLineageView, build_task_lineage_view
from v2.runtime.replay import ReplayCandidate, ReplayDecision
from v2.runtime.session import (
    RuntimeLeaseConfig,
    RuntimeReplanRecord,
    RuntimeSessionManager,
    RuntimeTaskSession,
    RuntimeWorkflowStep,
    StepAttemptRecord,
)
from v2.runtime.supervisor import RuntimeSupervisor, WorkerSessionSnapshot
from v2.runtime.telemetry import TelemetryEmitter, TelemetryEvent
from v2.runtime.workspace import (
    ArtifactInvalidationRecord,
    ArtifactLifecycleManager,
    ArtifactManifestItem,
    ArtifactOutputManifest,
    ArtifactSettlementRecord,
    ArtifactValidatorReport,
    InputValidatorReport,
    InputManifest,
    MaterializedOutputBundle,
    WorkspaceLayout,
    WorkspaceManager,
)
from v2.state import JsonContractStore, LayeredStateStore, MaterializedStateHandle, PersistedContractPaths
from v2.utils import sha256_digest


def _sum_role_hydration_bytes(role_hydration_bytes: dict[str, int]) -> int:
    return sum(int(value) for value in role_hydration_bytes.values())


@dataclass(frozen=True)
class RuntimeDriverProfile:
    layer_name: str = "L3"
    handoff_mode: str = "structured_collaboration"
    structured_control_enabled: bool = True
    semantic_pruning_enabled: bool = True
    semantic_state_transfer_enabled: bool = True
    replay_enabled: bool = True
    multi_attempt_enabled: bool = True
    force_first_attempt_trap: bool = True
    simulate_ack_timeout: bool = False
    simulate_lease_timeout: bool = False
    persistence_verification_level: str = "strict_roundtrip"
    persistence_profile: str = "audit_full"


class PersistenceVerificationLevel(StrEnum):
    STRICT_ROUNDTRIP = "strict_roundtrip"
    CORE_ROUNDTRIP = "core_roundtrip"


@dataclass(frozen=True)
class RuntimeDriverInput:
    trace_id: str
    task_id: str
    step_id: str
    artifact_id: str
    runtime_root: Path
    socket_path: Path
    state_store: LayeredStateStore
    workspace: WorkspaceManager
    layout: WorkspaceLayout
    layer_profile: RuntimeDriverProfile
    compiler_status: str
    canonical_task_spec_hash: str
    task_family: str
    required_outputs: tuple[str, ...]
    planner_handoff: PlannerHandoff
    planner_retrieval_objective: dict[str, object]
    planner_plan_payload: dict[str, object]
    retrieval: RetrievalBundle
    raw_evidence_bytes_seen_by_llm: int
    role_handoff_bytes: dict[str, int]
    role_hydration_bytes: dict[str, int]
    role_hydration_item_count: dict[str, int]
    semantic_state_handle: MaterializedStateHandle | None
    semantic_ref: SemanticStateRef | None
    input_manifest: InputManifest
    artifact_manifest: ArtifactOutputManifest
    log_capture: ExecutionLogCapture
    materialized_outputs: MaterializedOutputBundle
    output_payload: dict[str, object]
    output_rendered: bytes
    output_artifact_hash: str
    output_contract_version: str
    runtime_signature: RuntimeCompatibilitySignature
    runtime_signature_manifest_bundle: RuntimeSignatureManifestBundle
    memory_store: MemoryIndexStore
    current_memory_commit: MemoryCommit
    memory_match_result: MemoryMatchResult
    exact_replay_candidate_count: int
    history_artifact_reuse_count: int
    history_strategy_reuse_count: int
    history_step_reduction_count: int
    history_reuse_gain: float
    replay_candidate: ReplayCandidate | None
    replay_decision: ReplayDecision
    replay_input_artifact_hashes: tuple[str, ...]
    validator_reports: tuple[ArtifactValidatorReport, ...]
    input_validator_reports: tuple[InputValidatorReport, ...]
    quality_floor: QualityFloorResult
    planner_artifact_ref_id: str = "planner-handoff"
    workspace_file_count: int = 0
    code_template_version: str = ""
    extractor_version: str = ""
    codeact_plan: CodeActPlan | None = None
    codeact_record: CodeActExecutionRecord | None = None
    runtime_signature_manifest_bundle_relpath: str = ""
    materialized_json_by_hash: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimeDriverResult:
    session: RuntimeTaskSession
    session_snapshot: WorkerSessionSnapshot
    response_sequence: tuple[str, ...]
    finalized_artifact: ExecutionArtifactRef
    committed_memory: MemoryCommit
    commit_gate_decision: CommitGateDecision
    settlement_record: ArtifactSettlementRecord
    invalidation_record: ArtifactInvalidationRecord | None
    telemetry: TelemetryEmitter
    task_metrics: dict[str, float]
    lineage_view: TaskLineageView
    replay_ledger_entry: ReplayLedgerEntry
    execution_step_record: ExecutionStepRecord
    fallback_dag: FallbackDag | None
    persisted_paths: PersistedContractPaths
    reloaded_manifest_id: str
    reloaded_pack_id: str
    reloaded_input_manifest_hash: str
    reloaded_artifact_manifest_hash: str
    reloaded_memory_replay_class: str
    reloaded_memory_match_count: int
    reloaded_execution_goal: str
    reloaded_fallback_dag_id: str
    reloaded_replan_count: int
    output_payload: dict[str, object]
    output_artifact_hash: str
    materialized_outputs: MaterializedOutputBundle
    workspace_file_count: int
    codeact_record: CodeActExecutionRecord | None = None


def _elapsed_ms(start_ns: int) -> float:
    return (time.perf_counter_ns() - start_ns) / 1_000_000.0


def _fallback_action_for_attempt(
    *,
    layer_profile: RuntimeDriverProfile,
    attempt_index: int,
) -> str:
    if layer_profile.multi_attempt_enabled and layer_profile.force_first_attempt_trap and attempt_index == 0:
        return "retry_same_step"
    return "none"


def build_default_workflow(*, step_id: str, artifact_id: str) -> tuple[RuntimeWorkflowStep, ...]:
    return (
        RuntimeWorkflowStep(
            step_id="planner.plan",
            role="planner",
            capability="plan_retrieval_and_execution",
            output_refs=("planner_retrieval_objective", "canonical_task_spec"),
        ),
        RuntimeWorkflowStep(
            step_id="retriever.fanout",
            role="retriever",
            capability="fanout_retrieval",
            depends_on=("planner.plan",),
            output_refs=("evidence_pack", "hydrate_manifest", "retrieval_log", "query_embedding"),
        ),
        RuntimeWorkflowStep(
            step_id=step_id,
            role="executor",
            capability="materialize_and_execute",
            depends_on=("retriever.fanout",),
            input_refs=("evidence_pack", "hydrate_manifest", "retrieval_log"),
            output_refs=(artifact_id,),
            can_skip_if="memory.exact_replay_hit",
            max_retries=1,
        ),
        RuntimeWorkflowStep(
            step_id="summarizer.commit",
            role="summarizer",
            capability="quality_floor_and_memory_commit",
            depends_on=(step_id,),
            input_refs=(artifact_id,),
            output_refs=("memory_commit", "replay_ledger"),
        ),
    )


@dataclass
class RuntimeDriver:
    _last_persist_and_reload_stage_ms: float = 0.0
    _last_persist_and_reload_breakdown: dict[str, float] = field(default_factory=dict)

    def run(self, runtime_input: RuntimeDriverInput) -> RuntimeDriverResult:
        session_manager = RuntimeSessionManager()
        session = session_manager.start(
            session_id=f"session-{runtime_input.task_id}",
            trace_id=runtime_input.trace_id,
            task_id=runtime_input.task_id,
            layer_name=runtime_input.layer_profile.layer_name,
            canonical_task_spec_hash=runtime_input.canonical_task_spec_hash,
            workspace_root=str(runtime_input.layout.root),
            state_root=str(runtime_input.state_store.root),
            retrieval_log_hash=runtime_input.retrieval.log_hash,
            lease_config=RuntimeLeaseConfig(
                max_attempts_per_step=2 if runtime_input.layer_profile.multi_attempt_enabled else 1,
            ),
        )
        session = replace(
            session,
            planner_handoff_hash=runtime_input.planner_handoff.handoff_hash,
            runtime_signature_hash=runtime_input.runtime_signature.combined_digest,
            runtime_signature_manifest_bundle_hash=(
                runtime_input.runtime_signature_manifest_bundle.manifest_bundle_hash
            ),
            replay_input_artifact_hashes=runtime_input.replay_input_artifact_hashes,
        )
        session_manager.sessions[session.session_id] = session
        session = session_manager.attach_workflow(
            session.session_id,
            workflow_steps=build_default_workflow(
                step_id=runtime_input.step_id,
                artifact_id=runtime_input.artifact_id,
            ),
        )
        supervisor = RuntimeSupervisor()
        telemetry = TelemetryEmitter(
            runtime_event_log_path=runtime_input.runtime_root / "telemetry" / "runtime_events.jsonl",
            runtime_fact_log_path=(
                None
                if runtime_input.layer_profile.persistence_profile == "benchmark_balanced"
                else runtime_input.runtime_root / "telemetry" / "runtime_facts.jsonl"
            ),
            flush_interval=10 if runtime_input.layer_profile.persistence_profile == "benchmark_balanced" else 1,
        )
        fallback_planner = FallbackPlanner()
        control_plane_exchange_stage_ms = 0.0
        executor_state_machine_stage_ms = 0.0
        runtime_data_plane_event_stage_ms = 0.0
        runtime_commit_finalize_stage_ms = 0.0
        runtime_post_executor_stage_ms = 0.0
        runtime_replay_ledger_stage_ms = 0.0
        effective_skipped_step_count = float(runtime_input.replay_decision.skipped_step_count)
        effective_reuse_gain = 1.0 if runtime_input.replay_decision.skipped_step_count > 0 else 0.0
        effective_artifact_reuse_count = max(
            1.0 if runtime_input.replay_decision.replay_class == ReplayClass.EXACT_REPLAY else 0.0,
            float(runtime_input.history_artifact_reuse_count),
        )
        session, planner_runtime_stage_ms = self._run_non_executor_step(
            session_manager=session_manager,
            session_id=session.session_id,
            telemetry=telemetry,
            supervisor=supervisor,
            trace_id=runtime_input.trace_id,
            task_id=runtime_input.task_id,
            step_id="planner.plan",
            role="planner",
            output_refs=("planner_retrieval_objective", "canonical_task_spec", runtime_input.planner_artifact_ref_id),
            payload={
                "compiler_status": runtime_input.compiler_status,
                "canonical_task_spec_hash": runtime_input.canonical_task_spec_hash,
                "runtime_signature": runtime_input.runtime_signature.structured_payload(),
                "runtime_signature_manifest_bundle_hash": (
                    runtime_input.runtime_signature_manifest_bundle.manifest_bundle_hash
                ),
                "retrieval_objective": dict(sorted(runtime_input.planner_retrieval_objective.items())),
                "planner_plan_payload": dict(sorted(runtime_input.planner_plan_payload.items())),
            },
            metrics={
                "compiler_success_count": 1.0,
                "planner_generated_retrieval_objective_count": 1.0,
            },
            completion_channel="planner_handoff",
        )
        session, retriever_runtime_stage_ms = self._run_non_executor_step(
            session_manager=session_manager,
            session_id=session.session_id,
            telemetry=telemetry,
            supervisor=supervisor,
            trace_id=runtime_input.trace_id,
            task_id=runtime_input.task_id,
            step_id="retriever.fanout",
            role="retriever",
            output_refs=("evidence_pack", "hydrate_manifest", "retrieval_log", "query_embedding"),
            payload={
                "pack_id": runtime_input.retrieval.evidence_pack.pack_id,
                "pack_hash": runtime_input.retrieval.evidence_pack.pack_hash,
                "locator_count": len(runtime_input.retrieval.hydrate_manifest.entries),
            },
            metrics={
                "retrieval_candidate_count": float(
                    sum(output.log_entry.candidate_count for output in runtime_input.retrieval.outputs)
                ),
                "retrieval_selected_count": float(
                    sum(output.log_entry.selected_count for output in runtime_input.retrieval.outputs)
                ),
            },
        )
        data_plane_stage_start_ns = time.perf_counter_ns()
        self._emit_data_plane_events(
            telemetry=telemetry,
            runtime_input=runtime_input,
        )
        runtime_data_plane_event_stage_ms = _elapsed_ms(data_plane_stage_start_ns)

        artifacts = ArtifactLifecycleManager()
        candidate_artifact = artifacts.register_candidate(
            ExecutionArtifactRef(
                artifact_id=runtime_input.artifact_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                artifact_type="json",
                root_id="workspace-root",
                relpath="outputs/result.json",
                blob_hash=runtime_input.output_artifact_hash,
                size_bytes=len(runtime_input.output_rendered),
                produced_by="executor",
                manifest_hash=runtime_input.artifact_manifest.manifest_hash,
                metadata={"task_family": runtime_input.task_family},
            )
        )

        response_sequence: list[str] = []
        fallback_dag = None
        control_bytes = 0.0
        output_payload = dict(runtime_input.output_payload)
        output_rendered = runtime_input.output_rendered
        output_artifact_hash = runtime_input.output_artifact_hash
        output_manifest = runtime_input.artifact_manifest
        materialized_outputs = runtime_input.materialized_outputs
        current_memory_commit = runtime_input.current_memory_commit
        downgraded_execution_goal = bool(output_payload.get("downgraded_execution_goal", False))
        execution_step_record: ExecutionStepRecord | None = None
        settlement_record: ArtifactSettlementRecord | None = None
        invalidation_record: ArtifactInvalidationRecord | None = None
        fallback_resolution: FallbackResolutionRecord | None = None

        attempt_total = 2 if runtime_input.layer_profile.multi_attempt_enabled else 1
        for attempt_index in range(attempt_total):
            current_attempt_id = f"attempt-{attempt_index + 1}"
            supervisor.register(
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                attempt_id=current_attempt_id,
                role="executor",
            )
            supervisor.dispatch(runtime_input.step_id)
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id=runtime_input.trace_id,
                    task_id=runtime_input.task_id,
                    step_id=runtime_input.step_id,
                    attempt_id=current_attempt_id,
                    event_type="STEP_DISPATCHED",
                    role="runtime_supervisor",
                    payload={
                        "target_role": "executor",
                        "runtime_reuse_contract": "benchmark_strict",
                        "state_ref_count": 0 if runtime_input.semantic_ref is None else 1,
                        "artifact_ref_count": 1,
                    },
                    metrics={"timeout_ms": 5000.0},
                )
            )
            session = session_manager.append_attempt_record(
                session.session_id,
                record=StepAttemptRecord(
                    task_id=runtime_input.task_id,
                    step_id=runtime_input.step_id,
                    attempt_id=current_attempt_id,
                    owner_role="executor",
                    state=StepLifecycleState.DISPATCHED.value,
                    attempt_index=attempt_index,
                    dispatched_at_ns=supervisor.snapshot(runtime_input.step_id).dispatched_at_ns,
                    workspace_dirs=(str(runtime_input.layout.root / "steps" / runtime_input.step_id),),
                    resource_handles=(
                        "" if runtime_input.semantic_ref is None else runtime_input.semantic_ref.state_id,
                        candidate_artifact.artifact_id,
                    ),
                ),
            )
            exchange_stage_start_ns = time.perf_counter_ns()
            responses, current_control_bytes = self._exchange_loopback_messages(
                runtime_input=runtime_input,
                current_attempt_id=current_attempt_id,
                candidate_artifact=candidate_artifact,
                current_memory_commit=current_memory_commit,
            )
            control_plane_exchange_stage_ms += _elapsed_ms(exchange_stage_start_ns)
            control_bytes += current_control_bytes
            executor_stage_start_ns = time.perf_counter_ns()
            saw_ack = False
            saw_run_start = False
            saw_success = False
            for response in responses:
                response_sequence.append(response.header.event_type.name)
                if isinstance(response, AckReceived):
                    saw_ack = True
                    supervisor.ack(runtime_input.step_id)
                    snapshot = supervisor.snapshot(runtime_input.step_id)
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.ACKED.value,
                        acked_at_ns=snapshot.acked_at_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_ACKED",
                            role="executor",
                            metrics={"ack_count": 1.0},
                        )
                    )
                elif isinstance(response, RunStart):
                    saw_run_start = True
                    supervisor.run_start(runtime_input.step_id)
                    snapshot = supervisor.snapshot(runtime_input.step_id)
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.RUNNING.value,
                        running_at_ns=snapshot.started_at_ns,
                        heartbeat_at_ns=snapshot.last_heartbeat_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_RUNNING",
                            role="executor",
                            metrics={"run_start_count": 1.0},
                        )
                    )
                elif isinstance(response, Heartbeat):
                    supervisor.heartbeat(runtime_input.step_id)
                    snapshot = supervisor.snapshot(runtime_input.step_id)
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=supervisor.steps[runtime_input.step_id].state.value,
                        heartbeat_at_ns=snapshot.last_heartbeat_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_HEARTBEAT",
                            role="executor",
                            payload={"worker_state": response.worker_state},
                            metrics={"heartbeat_count": 1.0},
                        )
                    )
                elif isinstance(response, TrapFatal):
                    trapped = supervisor.trap(runtime_input.step_id, response.trap_reason)
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.TRAPPED.value,
                        trap_reason=response.trap_reason,
                        completed_at_ns=trapped.completed_at_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_TRAPPED",
                            role="executor",
                            severity="error",
                            payload={"trap_reason": response.trap_reason},
                            metrics={
                                "trap_count": 1.0,
                                "control_bytes": current_control_bytes,
                                "control_message_count": float(len(responses)),
                            },
                        )
                    )
                elif isinstance(response, ErrorResult):
                    failed = supervisor.fail(runtime_input.step_id, response.error_code)
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.FAILED.value,
                        completed_at_ns=failed.completed_at_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_FAILED",
                            role="executor",
                            severity="error",
                            payload={
                                "error_code": response.error_code,
                                "error_detail": response.error_detail,
                            },
                            metrics={
                                "failed_count": 1.0,
                                "control_bytes": current_control_bytes,
                                "control_message_count": float(len(responses)),
                            },
                        )
                    )
                elif isinstance(response, SuccessResult):
                    saw_success = True

            if not saw_ack:
                trapped = supervisor.trap_if_ack_timed_out(
                    runtime_input.step_id,
                    ack_timeout_ms=session.lease_config.ack_timeout_ms,
                    now_ns=supervisor.snapshot(runtime_input.step_id).dispatched_at_ns
                    + (session.lease_config.ack_timeout_ms + 1) * 1_000_000,
                )
                if trapped is not None:
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.TRAPPED.value,
                        trap_reason="ack_timeout",
                        completed_at_ns=trapped.completed_at_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_TRAPPED",
                            role="runtime_supervisor",
                            severity="error",
                            payload={"trap_reason": "ack_timeout"},
                            metrics={
                                "trap_count": 1.0,
                                "control_bytes": current_control_bytes,
                                "control_message_count": float(len(responses)),
                            },
                        )
                    )
                session = session_manager.update_state(session.session_id, supervisor.snapshot(runtime_input.step_id))
                executor_state_machine_stage_ms += _elapsed_ms(executor_stage_start_ns)
                continue

            if saw_run_start and not any(isinstance(response, Heartbeat) for response in responses):
                trapped = supervisor.trap_if_lease_expired(
                    runtime_input.step_id,
                    lease_timeout_ms=session.lease_config.lease_timeout_ms,
                    now_ns=supervisor.snapshot(runtime_input.step_id).started_at_ns
                    + (session.lease_config.lease_timeout_ms + 1) * 1_000_000,
                )
                if trapped is not None:
                    session = session_manager.update_attempt_record(
                        session.session_id,
                        attempt_id=current_attempt_id,
                        state=StepLifecycleState.TRAPPED.value,
                        trap_reason="heartbeat_timeout",
                        completed_at_ns=trapped.completed_at_ns,
                    )
                    telemetry.emit(
                        TelemetryEvent.create(
                            trace_id=runtime_input.trace_id,
                            task_id=runtime_input.task_id,
                            step_id=runtime_input.step_id,
                            attempt_id=current_attempt_id,
                            event_type="STEP_TRAPPED",
                            role="runtime_supervisor",
                            severity="error",
                            payload={"trap_reason": "heartbeat_timeout"},
                            metrics={
                                "trap_count": 1.0,
                                "control_bytes": current_control_bytes,
                                "control_message_count": float(len(responses)),
                            },
                        )
                    )
                session = session_manager.update_state(session.session_id, supervisor.snapshot(runtime_input.step_id))
                executor_state_machine_stage_ms += _elapsed_ms(executor_stage_start_ns)
                continue

            if not saw_success:
                session = session_manager.update_state(session.session_id, supervisor.snapshot(runtime_input.step_id))
                fallback_action = _fallback_action_for_attempt(
                    layer_profile=runtime_input.layer_profile,
                    attempt_index=attempt_index,
                )
                if fallback_action == "none":
                    executor_state_machine_stage_ms += _elapsed_ms(executor_stage_start_ns)
                    continue

            fallback_action = _fallback_action_for_attempt(
                layer_profile=runtime_input.layer_profile,
                attempt_index=attempt_index,
            )
            if fallback_action != "none":
                fallback_dag = fallback_planner.plan_for_trap(
                    task_id=runtime_input.task_id,
                    source_step_id=runtime_input.step_id,
                    requested_outputs=runtime_input.required_outputs,
                    fallback_action=fallback_action,
                )
                selected_action = fallback_dag.actions[0]
                fallback_resolution = FallbackResolutionRecord(
                    resolution_id=f"resolution-{runtime_input.task_id}-{current_attempt_id}",
                    task_id=runtime_input.task_id,
                    source_step_id=runtime_input.step_id,
                    attempt_id=current_attempt_id,
                    selected_action_name=selected_action.action_name,
                    selected_reason=selected_action.reason,
                    downgraded_execution_goal=False,
                    skipped_downstream_step_ids=selected_action.skip_downstream_step_ids,
                )
                session = session_manager.increment_runtime_fallback(session.session_id)
                session = session_manager.append_replan_record(
                    session.session_id,
                    record=RuntimeReplanRecord(
                        replan_id=f"replan-{runtime_input.task_id}-{current_attempt_id}",
                        task_id=runtime_input.task_id,
                        source_step_id=runtime_input.step_id,
                        attempt_id=current_attempt_id,
                        trigger_state=StepLifecycleState.TRAPPED.value,
                        trigger_reason="simulated_executor_runtime_error",
                        fallback_action=fallback_action,
                        selected_capability=selected_action.next_capability or "materialize_and_execute",
                        downgraded_execution_goal=False,
                        fallback_dag_hash=fallback_dag.dag_hash,
                    ),
                )
                telemetry.emit(
                    TelemetryEvent.create(
                        trace_id=runtime_input.trace_id,
                        task_id=runtime_input.task_id,
                        step_id=runtime_input.step_id,
                        attempt_id=current_attempt_id,
                        event_type="STEP_TRAPPED",
                        role="executor",
                        severity="error",
                        payload={"trap_reason": "simulated_executor_runtime_error"},
                        metrics={"trap_count": 1.0},
                    )
                )
                telemetry.emit(
                    TelemetryEvent.create(
                        trace_id=runtime_input.trace_id,
                        task_id=runtime_input.task_id,
                        step_id=runtime_input.step_id,
                        attempt_id=current_attempt_id,
                        event_type="STEP_REPLAN_REQUESTED",
                        role="runtime_supervisor",
                        payload={
                            "fallback_action": fallback_action,
                            "fallback_dag_hash": fallback_dag.dag_hash,
                            "fallback_actions": [action.action_name for action in fallback_dag.actions],
                            "selected_capability": selected_action.next_capability or "materialize_and_execute",
                        },
                        metrics={"runtime_replan_count": 1.0},
                    )
                )
                executor_state_machine_stage_ms += _elapsed_ms(executor_stage_start_ns)
                continue

            if attempt_index > 0:
                downgraded_execution_goal = True
                if fallback_resolution is not None:
                    fallback_resolution = FallbackResolutionRecord(
                        resolution_id=fallback_resolution.resolution_id,
                        task_id=fallback_resolution.task_id,
                        source_step_id=fallback_resolution.source_step_id,
                        attempt_id=fallback_resolution.attempt_id,
                        selected_action_name=fallback_resolution.selected_action_name,
                        selected_reason=fallback_resolution.selected_reason,
                        downgraded_execution_goal=True,
                        skipped_downstream_step_ids=fallback_resolution.skipped_downstream_step_ids,
                    )
                output_payload = {
                    **output_payload,
                    "downgraded_execution_goal": True,
                }
                output_rendered = (
                    json.dumps(output_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
                ).encode("utf-8")
                output_artifact_hash = sha256_digest(output_rendered)
                output_manifest = self._rebuild_output_manifest(
                    runtime_input=runtime_input,
                    output_artifact_hash=output_artifact_hash,
                    output_rendered=output_rendered,
                )
                materialized_outputs = runtime_input.workspace.materialize_output_bundle(
                    runtime_input.layout,
                    output_manifest,
                    payload_by_name={"summary_json": output_payload},
                    materialized_by_name={
                        "stdout_log": runtime_input.log_capture.stdout_artifact,
                        "stderr_log": runtime_input.log_capture.stderr_artifact,
                    },
                )
                artifacts.artifacts[runtime_input.artifact_id] = replace(
                    artifacts.artifacts[runtime_input.artifact_id],
                    blob_hash=output_artifact_hash,
                    size_bytes=len(output_rendered),
                    manifest_hash=output_manifest.manifest_hash,
                    metadata={
                        **artifacts.artifacts[runtime_input.artifact_id].metadata,
                        "downgraded_execution_goal": True,
                    },
                )
                current_memory_commit = replace(
                    current_memory_commit,
                    created_from_artifact_hash=output_artifact_hash,
                    memory_ref=replace(
                        current_memory_commit.memory_ref,
                        metadata={
                            **current_memory_commit.memory_ref.metadata,
                            "downgraded_execution_goal": True,
                        },
                    ),
                )

            supervisor.complete(runtime_input.step_id)
            completed_snapshot = supervisor.snapshot(runtime_input.step_id)
            session = session_manager.update_attempt_record(
                session.session_id,
                attempt_id=current_attempt_id,
                state=StepLifecycleState.COMPLETED.value,
                completed_at_ns=completed_snapshot.completed_at_ns,
            )
            for report in runtime_input.validator_reports:
                telemetry.emit(
                    TelemetryEvent.create(
                        trace_id=runtime_input.trace_id,
                        task_id=runtime_input.task_id,
                        step_id=runtime_input.step_id,
                        attempt_id=current_attempt_id,
                        event_type="ARTIFACT_VALIDATED",
                        role="runtime_supervisor",
                        payload={
                            "validation_scope": report.validation_scope,
                            "passed": report.passed,
                            "fail_reason": report.fail_reason,
                        },
                        metrics={f"{report.validation_scope}_validator_pass": 1.0 if report.passed else 0.0},
                    )
                )
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id=runtime_input.trace_id,
                    task_id=runtime_input.task_id,
                    step_id=runtime_input.step_id,
                    attempt_id=current_attempt_id,
                    event_type="STEP_COMPLETED",
                    role="executor",
                    metrics={
                        "control_bytes": current_control_bytes,
                        "control_message_count": float(len(responses)),
                        "output_bytes": float(len(output_rendered)),
                    },
                )
            )
            execution_step_record = ExecutionStepRecord(
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                attempt_id=current_attempt_id,
                workspace_root=str(runtime_input.layout.root),
                execution_goal="downgrade_execution_goal" if downgraded_execution_goal else "full_execution_goal",
                exit_code=0,
                output_manifest=output_manifest,
                log_capture=runtime_input.log_capture,
                input_validator_reports=runtime_input.input_validator_reports,
                validator_reports=runtime_input.validator_reports,
                invalidation_reasons=(),
                codeact_plan=runtime_input.codeact_plan,
                codeact_record=runtime_input.codeact_record,
            )
            executor_state_machine_stage_ms += _elapsed_ms(executor_stage_start_ns)
            break

        if execution_step_record is None:
            raise RuntimeError("execution step record missing")

        commit_finalize_start_ns = time.perf_counter_ns()
        active_attempt_id = session.current_attempt_id or "attempt-1"
        current_memory_commit = replace(
            current_memory_commit,
            memory_ref=replace(
                current_memory_commit.memory_ref,
                metadata={
                    **current_memory_commit.memory_ref.metadata,
                    "runtime_signature_hash": runtime_input.runtime_signature.combined_digest,
                    "runtime_signature_manifest_bundle_hash": (
                        runtime_input.runtime_signature_manifest_bundle.manifest_bundle_hash
                    ),
                    "runtime_signature_manifest_bundle_relpath": (
                        runtime_input.runtime_signature_manifest_bundle_relpath
                    ),
                    "output_contract_version": runtime_input.output_contract_version,
                    "code_template_version": runtime_input.code_template_version,
                    "extractor_version": runtime_input.extractor_version,
                },
            ),
        )
        finalized_artifact, committed_memory, commit_gate_decision, settlement_record, invalidation_record = RuntimeCommitGate().finalize(
            artifact_lifecycle=artifacts,
            memory_store=runtime_input.memory_store,
            artifact_id=runtime_input.artifact_id,
            memory_commit=current_memory_commit,
            quality_floor=runtime_input.quality_floor,
            answer_adopted=runtime_input.quality_floor.quality_floor_pass,
            replay_class=runtime_input.replay_decision.replay_class,
            validator_reports=runtime_input.validator_reports,
            input_validator_reports=runtime_input.input_validator_reports,
        )
        committed_memory = replace(
            committed_memory,
            memory_ref=replace(
                committed_memory.memory_ref,
                metadata={
                    **committed_memory.memory_ref.metadata,
                    "replay_ready": finalized_artifact.replay_ready,
                },
            ),
        )
        execution_step_record = replace(
            execution_step_record,
            settlement_record=settlement_record,
            invalidation_record=invalidation_record,
            invalidation_reasons=commit_gate_decision.invalidation_reasons,
        )
        runtime_commit_finalize_stage_ms = _elapsed_ms(commit_finalize_start_ns)
        post_executor_stage_start_ns = time.perf_counter_ns()
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                attempt_id=active_attempt_id,
                event_type="REPLAY_DECIDED",
                role="runtime_supervisor",
                payload={
                    "replay_class": runtime_input.replay_decision.replay_class.value,
                    "decision_source": runtime_input.replay_decision.reason,
                    "canonical_task_spec_hash": runtime_input.canonical_task_spec_hash,
                    "runtime_compatibility_signature": runtime_input.runtime_signature.combined_digest,
                    "runtime_signature_manifest_bundle_hash": (
                        runtime_input.runtime_signature_manifest_bundle.manifest_bundle_hash
                    ),
                    "planner_handoff_hash": runtime_input.planner_handoff.handoff_hash,
                    "memory_candidate_pool_hash": runtime_input.memory_match_result.candidate_pool_hash,
                    "memory_rerank_result_hash": runtime_input.memory_match_result.rerank_result_hash,
                    "history_artifact_reuse_count": runtime_input.history_artifact_reuse_count,
                    "history_strategy_reuse_count": runtime_input.history_strategy_reuse_count,
                    "history_step_reduction_count": runtime_input.history_step_reduction_count,
                    "replan_count": session.replan_count,
                },
                metrics={
                    "skipped_step_count": effective_skipped_step_count,
                    "reuse_gain": effective_reuse_gain,
                    "history_step_reduction_count": float(runtime_input.history_step_reduction_count),
                    "history_reuse_gain": float(runtime_input.history_reuse_gain),
                    "memory_match_count": float(len(runtime_input.memory_match_result.matches)),
                    "replay_ledger_entry_count": 1.0,
                },
            )
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                event_type="MEMORY_COMMIT_VERIFIED",
                role="summarizer",
                channel="memory",
                payload={
                    "memory_id": committed_memory.memory_ref.memory_id,
                    "commit_status": committed_memory.memory_ref.commit_status.value,
                    "validation_status": committed_memory.memory_ref.validation_status.value,
                    "answer_adopted": committed_memory.memory_ref.answer_adopted,
                    "commit_gate_reason": commit_gate_decision.reason,
                },
                metrics={
                    "artifact_reuse_count": effective_artifact_reuse_count,
                    "memory_commit_count": 1.0,
                },
            )
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                attempt_id=active_attempt_id,
                event_type="ARTIFACT_PUBLISHED",
                role="runtime_supervisor",
                channel="execution_artifact",
                payload={
                    "artifact_id": finalized_artifact.artifact_id,
                    "from_state": commit_gate_decision.previous_artifact_state,
                    "to_state": finalized_artifact.verification_state.value,
                    "commit_gate_reason": commit_gate_decision.reason,
                },
                metrics={
                    "verified_artifact_count": (
                        1.0 if finalized_artifact.verification_state == RefStatus.VERIFIED else 0.0
                    ),
                    "candidate_artifact_count": 0.0,
                },
            )
        )
        if invalidation_record is not None:
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id=runtime_input.trace_id,
                    task_id=runtime_input.task_id,
                    step_id=runtime_input.step_id,
                    attempt_id=active_attempt_id,
                    event_type="ARTIFACT_INVALIDATED",
                    role="runtime_supervisor",
                    channel="execution_artifact",
                    severity="warning",
                    payload={
                        "artifact_id": invalidation_record.artifact_id,
                        "invalidation_reason": invalidation_record.invalidation_reason,
                    },
                    metrics={"invalidation_reason_count": 1.0},
                )
            )

        supervisor.gc_pending(runtime_input.step_id)
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                attempt_id=active_attempt_id,
                event_type="GC_ISSUED",
                role="runtime_supervisor",
                payload={
                    "workspace_root": str(runtime_input.layout.root),
                    "state_ref_id": "" if runtime_input.semantic_ref is None else runtime_input.semantic_ref.state_id,
                },
                metrics={"gc_issue_count": 1.0},
            )
        )
        supervisor.gc_done(runtime_input.step_id)
        session = session_manager.update_attempt_record(
            session.session_id,
            attempt_id=active_attempt_id,
            state=StepLifecycleState.GC_DONE.value,
            validator_report_hashes=tuple(report.report_hash for report in runtime_input.validator_reports),
        )
        session = session_manager.update_workflow_step(
            session.session_id,
            step_id=runtime_input.step_id,
            state=StepLifecycleState.GC_DONE.value,
            attempt_id=active_attempt_id,
            output_refs=(finalized_artifact.artifact_id,),
            metrics={
                "control_bytes": control_bytes,
                "output_bytes": float(len(output_rendered)),
                "artifact_reuse_count": effective_artifact_reuse_count,
                "attempt_count": float(session.attempt_count),
            },
        )
        runtime_post_executor_stage_ms = _elapsed_ms(post_executor_stage_start_ns)
        session, summarizer_runtime_stage_ms = self._run_non_executor_step(
            session_manager=session_manager,
            session_id=session.session_id,
            telemetry=telemetry,
            supervisor=supervisor,
            trace_id=runtime_input.trace_id,
            task_id=runtime_input.task_id,
            step_id="summarizer.commit",
            role="summarizer",
            output_refs=(committed_memory.memory_ref.memory_id, f"ledger-{runtime_input.task_id}"),
            payload={
                "quality_floor_pass": runtime_input.quality_floor.quality_floor_pass,
                "replay_class": runtime_input.replay_decision.replay_class.value,
                "memory_id": committed_memory.memory_ref.memory_id,
            },
            metrics={
                "quality_floor_pass": 1.0 if runtime_input.quality_floor.quality_floor_pass else 0.0,
                "memory_commit_count": 1.0,
            },
        )
        session = session_manager.update_state(session.session_id, supervisor.snapshot(runtime_input.step_id))

        replay_ledger_stage_start_ns = time.perf_counter_ns()
        replay_ledger = ReplayLedger()
        ledger_entry = replay_ledger.append(
            ReplayLedgerEntry(
                ledger_id=f"ledger-{runtime_input.task_id}",
                session_id=session.session_id,
                task_id=runtime_input.task_id,
                candidate_id=(
                    "" if runtime_input.replay_candidate is None else runtime_input.replay_candidate.candidate_id
                ),
                memory_id=committed_memory.memory_ref.memory_id,
                artifact_ref_id=finalized_artifact.artifact_id,
                replay_class=runtime_input.replay_decision.replay_class,
                decision_reason=runtime_input.replay_decision.reason,
                compatibility_verdict=runtime_input.replay_decision.compatibility_verdict,
                runtime_signature_hash=runtime_input.runtime_signature.combined_digest,
                runtime_signature_manifest_bundle_hash=(
                    runtime_input.runtime_signature_manifest_bundle.manifest_bundle_hash
                ),
                canonical_task_spec_hash=runtime_input.canonical_task_spec_hash,
                planner_handoff_hash=runtime_input.planner_handoff.handoff_hash,
                input_artifact_hashes=runtime_input.replay_input_artifact_hashes,
                output_contract_version=runtime_input.output_contract_version,
                code_template_version=runtime_input.code_template_version,
                extractor_version=runtime_input.extractor_version,
                runtime_signature=runtime_input.runtime_signature.structured_payload(),
                exact_key=(
                    runtime_input.replay_candidate.exact_key
                    if runtime_input.replay_decision.replay_class == ReplayClass.EXACT_REPLAY
                    and runtime_input.replay_candidate is not None
                    else ""
                ),
                degraded=runtime_input.replay_decision.degraded,
                skipped_step_count=runtime_input.replay_decision.skipped_step_count,
            )
        )
        session = session_manager.attach_refs(
            session.session_id,
            input_manifest_hash=runtime_input.input_manifest.manifest_hash,
            artifact_manifest_hash=output_manifest.manifest_hash,
            state_ref_ids=() if runtime_input.semantic_ref is None else (runtime_input.semantic_ref.state_id,),
            artifact_ref_ids=(finalized_artifact.artifact_id,),
            memory_ref_ids=(committed_memory.memory_ref.memory_id,),
            replay_ledger_ids=(ledger_entry.ledger_id,),
            summary_artifact_ref_id=finalized_artifact.artifact_id,
                memory_match_result_hash=runtime_input.memory_match_result.result_hash,
        )
        runtime_replay_ledger_stage_ms = _elapsed_ms(replay_ledger_stage_start_ns)

        (
            persisted_paths,
            reloaded_manifest_id,
            reloaded_pack_id,
            reloaded_input_manifest_hash,
            reloaded_artifact_manifest_hash,
            reloaded_memory_replay_class,
            reloaded_memory_match_count,
            reloaded_execution_goal,
            reloaded_fallback_dag_id,
            reloaded_replan_count,
        ) = self._persist_and_reload(
            runtime_input=runtime_input,
            session=session,
            finalized_artifact=finalized_artifact,
            committed_memory=committed_memory,
            ledger_entry=ledger_entry,
            execution_step_record=execution_step_record,
            fallback_dag=fallback_dag,
            output_manifest=output_manifest,
            settlement_record=settlement_record,
            invalidation_record=invalidation_record,
        )

        if runtime_input.semantic_state_handle is not None:
            runtime_input.state_store.release(runtime_input.semantic_state_handle.ref_id)

        persist_and_reload_stage_ms = self._last_persist_and_reload_stage_ms
        persist_and_reload_breakdown = dict(self._last_persist_and_reload_breakdown)
        registry_stage_ms = 0.0
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
            event_type="TASK_SUMMARY_METRICS",
            payload={
                "state_pool_mode_requested": runtime_input.state_store.policy.state_pool_mode,
                "state_pool_mode_used": runtime_input.state_store.backend_name,
                "memfd_transfer_count": runtime_input.state_store.memfd_transfer_count,
                "memfd_bytes_transferred": runtime_input.state_store.memfd_bytes_transferred,
            },
            metrics={
                    "artifact_count": 1.0,
                    "telemetry_events": 1.0,
                    "workspace_files": float(runtime_input.workspace_file_count),
                    "candidate_artifact_count": 0.0,
                    "verified_artifact_count": (
                        1.0 if finalized_artifact.verification_state == RefStatus.VERIFIED else 0.0
                    ),
                    "invalidated_artifact_count": (
                        1.0 if finalized_artifact.verification_state == RefStatus.INVALIDATED else 0.0
                    ),
                    "raw_evidence_bytes_seen_by_llm": float(runtime_input.raw_evidence_bytes_seen_by_llm),
                    "planner_hydrated_bytes": float(runtime_input.role_hydration_bytes.get("planner", 0)),
                    "retriever_hydrated_bytes": float(runtime_input.role_hydration_bytes.get("retriever", 0)),
                    "executor_hydrated_bytes": float(runtime_input.role_hydration_bytes.get("executor", 0)),
                    "summarizer_hydrated_bytes": float(runtime_input.role_hydration_bytes.get("summarizer", 0)),
                    "planner_text_bytes": float(runtime_input.role_hydration_bytes.get("planner_text", 0)),
                    "retriever_text_bytes": float(runtime_input.role_hydration_bytes.get("retriever_text", 0)),
                    "executor_text_bytes": float(runtime_input.role_hydration_bytes.get("executor_text", 0)),
                    "summarizer_text_bytes": float(runtime_input.role_hydration_bytes.get("summarizer_text", 0)),
                    "planner_table_bytes": float(runtime_input.role_hydration_bytes.get("planner_table", 0)),
                    "retriever_table_bytes": float(runtime_input.role_hydration_bytes.get("retriever_table", 0)),
                    "executor_table_bytes": float(runtime_input.role_hydration_bytes.get("executor_table", 0)),
                    "summarizer_table_bytes": float(runtime_input.role_hydration_bytes.get("summarizer_table", 0)),
                    "planner_artifact_bytes": float(runtime_input.role_hydration_bytes.get("planner_artifact", 0)),
                    "retriever_artifact_bytes": float(runtime_input.role_hydration_bytes.get("retriever_artifact", 0)),
                    "executor_artifact_bytes": float(runtime_input.role_hydration_bytes.get("executor_artifact", 0)),
                    "summarizer_artifact_bytes": float(runtime_input.role_hydration_bytes.get("summarizer_artifact", 0)),
                    "planner_memory_bytes": float(runtime_input.role_hydration_bytes.get("planner_memory", 0)),
                    "retriever_memory_bytes": float(runtime_input.role_hydration_bytes.get("retriever_memory", 0)),
                    "executor_memory_bytes": float(runtime_input.role_hydration_bytes.get("executor_memory", 0)),
                    "summarizer_memory_bytes": float(runtime_input.role_hydration_bytes.get("summarizer_memory", 0)),
                    "planner_hydrated_item_count": float(runtime_input.role_hydration_item_count.get("planner", 0)),
                    "retriever_hydrated_item_count": float(runtime_input.role_hydration_item_count.get("retriever", 0)),
                    "executor_hydrated_item_count": float(runtime_input.role_hydration_item_count.get("executor", 0)),
                    "summarizer_hydrated_item_count": float(runtime_input.role_hydration_item_count.get("summarizer", 0)),
                    "planner_table_item_count": float(runtime_input.role_hydration_item_count.get("planner_table", 0)),
                    "retriever_table_item_count": float(runtime_input.role_hydration_item_count.get("retriever_table", 0)),
                    "executor_table_item_count": float(runtime_input.role_hydration_item_count.get("executor_table", 0)),
                    "summarizer_table_item_count": float(runtime_input.role_hydration_item_count.get("summarizer_table", 0)),
                    "planner_artifact_item_count": float(runtime_input.role_hydration_item_count.get("planner_artifact", 0)),
                    "retriever_artifact_item_count": float(runtime_input.role_hydration_item_count.get("retriever_artifact", 0)),
                    "executor_artifact_item_count": float(runtime_input.role_hydration_item_count.get("executor_artifact", 0)),
                    "summarizer_artifact_item_count": float(runtime_input.role_hydration_item_count.get("summarizer_artifact", 0)),
                    "planner_memory_item_count": float(runtime_input.role_hydration_item_count.get("planner_memory", 0)),
                    "retriever_memory_item_count": float(runtime_input.role_hydration_item_count.get("retriever_memory", 0)),
                    "executor_memory_item_count": float(runtime_input.role_hydration_item_count.get("executor_memory", 0)),
                    "summarizer_memory_item_count": float(runtime_input.role_hydration_item_count.get("summarizer_memory", 0)),
                    "embedding_dim": float(runtime_input.retrieval.query_embedding.dims),
                    "retrieval_log_count": 1.0,
                    "retrieval_candidate_pool_count": 1.0,
                    "retrieval_rerank_count": 1.0,
                    "retrieval_pruning_profile_count": 1.0,
                    "runtime_session_count": 1.0,
                    "semantic_state_transfer_count": 0.0,
                    "shared_memory_publish_count": 0.0,
                    "mmap_publish_count": 0.0,
                    "stdout_log_count": 1.0,
                    "stderr_log_count": 1.0,
                    "downgrade_execution_goal_count": 1.0 if downgraded_execution_goal else 0.0,
                    "invalidation_reason_count": float(len(commit_gate_decision.invalidation_reasons)),
                    "workflow_step_count": float(session.workflow_step_count),
                    "completed_workflow_step_count": float(session.completed_workflow_step_count),
                    "attempt_count": float(session.attempt_count),
                    "runtime_fallback_count": float(session.runtime_fallback_count),
                    "replan_history_count": float(session.replan_count),
                    "validator_report_count": float(len(runtime_input.validator_reports)),
                    "input_validator_report_count": float(len(runtime_input.input_validator_reports)),
                    "memory_candidate_count": (
                        0.0
                        if runtime_input.memory_match_result.candidate_pool is None
                        else float(len(runtime_input.memory_match_result.candidate_pool.candidate_memory_ids))
                    ),
                    "memory_rerank_selected_count": (
                        0.0
                        if runtime_input.memory_match_result.rerank_result is None
                        else float(len(runtime_input.memory_match_result.rerank_result.selected_memory_ids))
                    ),
                    "memory_exact_replay_candidate_count": (
                        float(runtime_input.exact_replay_candidate_count)
                    ),
                    "history_artifact_reuse_count": float(runtime_input.history_artifact_reuse_count),
                    "history_strategy_reuse_count": float(runtime_input.history_strategy_reuse_count),
                    "history_step_reduction_count": float(runtime_input.history_step_reduction_count),
                    "history_reuse_gain": float(runtime_input.history_reuse_gain),
                    "validated_replay_count": (
                        1.0 if runtime_input.replay_decision.replay_class == ReplayClass.VALIDATED_REPLAY else 0.0
                    ),
                    "validated_downgraded_reuse_count": (
                        1.0 if runtime_input.replay_decision.replay_class == ReplayClass.VALIDATED_REPLAY else 0.0
                    ),
                    "exact_replay_count": (
                        1.0 if runtime_input.replay_decision.replay_class == ReplayClass.EXACT_REPLAY else 0.0
                    ),
                    "answer_restoration_replay_count": 0.0,
                    "pruning_gain_bytes": float(runtime_input.retrieval.pruning_profile.pruning_gain_bytes),
                    "codeact_plan_stage_count": (
                        0.0 if runtime_input.codeact_plan is None else float(runtime_input.codeact_plan.stage_count)
                    ),
                    "codeact_plan_action_count": (
                        0.0 if runtime_input.codeact_plan is None else float(runtime_input.codeact_plan.action_count)
                    ),
                    "codeact_sandbox_bwrap_count": (
                        1.0
                        if runtime_input.codeact_record is not None
                        and runtime_input.codeact_record.sandbox_backend == "bwrap"
                        else 0.0
                    ),
                    "codeact_sandbox_resource_count": (
                        1.0
                        if runtime_input.codeact_record is not None
                        and runtime_input.codeact_record.sandbox_backend == "resource"
                        else 0.0
                    ),
                    "codeact_sandbox_none_count": (
                        1.0
                        if runtime_input.codeact_record is not None
                        and runtime_input.codeact_record.sandbox_backend == "none"
                        else 0.0
                    ),
                    "codeact_sandbox_fallback_count": (
                        1.0
                        if runtime_input.codeact_record is not None
                        and bool(runtime_input.codeact_record.sandbox_fallback_reason)
                        else 0.0
                    ),
                    "planner_runtime_stage_ms": planner_runtime_stage_ms,
                    "retriever_runtime_stage_ms": retriever_runtime_stage_ms,
                    "summarizer_runtime_stage_ms": summarizer_runtime_stage_ms,
                    "runtime_non_executor_stage_ms": (
                        planner_runtime_stage_ms + retriever_runtime_stage_ms + summarizer_runtime_stage_ms
                    ),
                    "runtime_data_plane_event_stage_ms": runtime_data_plane_event_stage_ms,
                    "control_plane_exchange_stage_ms": control_plane_exchange_stage_ms,
                    "executor_state_machine_stage_ms": executor_state_machine_stage_ms,
                    "runtime_commit_finalize_stage_ms": runtime_commit_finalize_stage_ms,
                    "runtime_post_executor_stage_ms": runtime_post_executor_stage_ms,
                    "runtime_replay_ledger_stage_ms": runtime_replay_ledger_stage_ms,
                    "persist_and_reload_stage_ms": persist_and_reload_stage_ms,
                    **persist_and_reload_breakdown,
                    "registry_query_stage_ms": registry_stage_ms,
                    "semantic_state_ref_count": 0.0 if runtime_input.semantic_ref is None else 1.0,
                    "verified_artifact_ref_count": (
                        1.0 if finalized_artifact.verification_state == RefStatus.VERIFIED else 0.0
                    ),
                    "memory_ref_count": 1.0,
                },
            )
        )
        task_metrics = telemetry.summarize_task(runtime_input.task_id)
        task_metrics.update(telemetry.task_io_metrics(runtime_input.task_id))
        task_metrics.update(
            {
                "memfd_transfer_count": float(runtime_input.state_store.memfd_transfer_count),
                "memfd_bytes_transferred": float(runtime_input.state_store.memfd_bytes_transferred),
                "state_pool_memfd_mode_count": (
                    1.0 if runtime_input.state_store.backend_name == StorageKind.MEMFD.value else 0.0
                ),
                "state_pool_shared_memory_mode_count": (
                    1.0 if runtime_input.state_store.backend_name == StorageKind.SHARED_MEMORY.value else 0.0
                ),
                "state_pool_mmap_mode_count": (
                    1.0 if runtime_input.state_store.backend_name == StorageKind.MMAP_FILE.value else 0.0
                ),
            }
        )
        telemetry.close()
        session_snapshot = supervisor.snapshot(runtime_input.step_id)
        lineage_view = build_task_lineage_view(
            task_id=runtime_input.task_id,
            semantic_states=[] if runtime_input.semantic_ref is None else [runtime_input.semantic_ref],
            artifacts=list(artifacts.artifacts.values()),
        )
        return RuntimeDriverResult(
            session=session,
            session_snapshot=session_snapshot,
            response_sequence=tuple(response_sequence),
            finalized_artifact=finalized_artifact,
            committed_memory=committed_memory,
            commit_gate_decision=commit_gate_decision,
            settlement_record=settlement_record,
            invalidation_record=invalidation_record,
            telemetry=telemetry,
            task_metrics=task_metrics,
            lineage_view=lineage_view,
            replay_ledger_entry=ledger_entry,
            execution_step_record=execution_step_record,
            fallback_dag=fallback_dag,
            persisted_paths=persisted_paths,
            reloaded_manifest_id=reloaded_manifest_id,
            reloaded_pack_id=reloaded_pack_id,
            reloaded_input_manifest_hash=reloaded_input_manifest_hash,
            reloaded_artifact_manifest_hash=reloaded_artifact_manifest_hash,
            reloaded_memory_replay_class=reloaded_memory_replay_class,
            reloaded_memory_match_count=reloaded_memory_match_count,
            reloaded_execution_goal=reloaded_execution_goal,
            reloaded_fallback_dag_id=reloaded_fallback_dag_id,
            reloaded_replan_count=reloaded_replan_count,
            output_payload=output_payload,
            output_artifact_hash=output_artifact_hash,
            materialized_outputs=materialized_outputs,
            workspace_file_count=runtime_input.workspace_file_count,
            codeact_record=execution_step_record.codeact_record,
        )

    def _emit_data_plane_events(
        self,
        *,
        telemetry: TelemetryEmitter,
        runtime_input: RuntimeDriverInput,
    ) -> None:
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                event_type="EVIDENCE_PACK_BUILT",
                role="retriever",
                channel="semantic_state",
                payload={
                    "pack_id": runtime_input.retrieval.evidence_pack.pack_id,
                    "pack_hash": runtime_input.retrieval.evidence_pack.pack_hash,
                    "locator_count": len(runtime_input.retrieval.hydrate_manifest.entries),
                    "hard_fact_count": len(runtime_input.retrieval.evidence_pack.hard_facts),
                    "semantic_context_count": len(runtime_input.retrieval.evidence_pack.semantic_contexts),
                },
                metrics={
                    "retrieval_candidate_count": float(
                        sum(output.log_entry.candidate_count for output in runtime_input.retrieval.outputs)
                    ),
                    "retrieval_selected_count": float(
                        sum(output.log_entry.selected_count for output in runtime_input.retrieval.outputs)
                    ),
                    "full_corpus_bytes": float(runtime_input.retrieval.full_corpus_bytes),
                    "selected_evidence_bytes": float(runtime_input.retrieval.selected_evidence_bytes),
                    "pruning_gain_bytes": float(runtime_input.retrieval.pruning_profile.pruning_gain_bytes),
                },
            )
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                event_type="RETRIEVAL_CANDIDATE_POOL_BUILT",
                role="retriever",
                channel="memory",
                payload={"candidate_pool_hash": runtime_input.retrieval.candidate_pool.pool_hash},
                metrics={"retrieval_candidate_count": float(len(runtime_input.retrieval.candidate_pool.candidates))},
            )
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                event_type="RETRIEVAL_RERANKED",
                role="retriever",
                channel="memory",
                payload={
                    "rerank_result_hash": runtime_input.retrieval.rerank_result.rerank_hash,
                    "selected_candidate_ids": list(runtime_input.retrieval.rerank_result.selected_candidate_ids),
                },
                metrics={
                    "retrieval_selected_count": float(
                        len(runtime_input.retrieval.rerank_result.selected_candidate_ids)
                    )
                },
            )
        )
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=runtime_input.trace_id,
                task_id=runtime_input.task_id,
                step_id=runtime_input.step_id,
                event_type="RETRIEVAL_PRUNED",
                role="retriever",
                channel="semantic_state",
                payload={
                    "pruning_profile_hash": runtime_input.retrieval.pruning_profile.profile_hash,
                    "selected_candidate_ids": list(runtime_input.retrieval.pruning_profile.selected_candidate_ids),
                },
                metrics={
                    "pruning_gain_bytes": float(runtime_input.retrieval.pruning_profile.pruning_gain_bytes),
                    "selected_evidence_bytes": float(runtime_input.retrieval.selected_evidence_bytes),
                },
            )
        )
        if runtime_input.semantic_state_handle is not None and runtime_input.semantic_ref is not None:
            telemetry.emit(
                TelemetryEvent.create(
                    trace_id=runtime_input.trace_id,
                    task_id=runtime_input.task_id,
                    step_id=runtime_input.step_id,
                    event_type="STATE_PUBLISHED",
                    role="retriever",
                    channel="semantic_state",
                    payload={
                        "ref_id": runtime_input.semantic_ref.state_id,
                        "manifest_id": runtime_input.retrieval.hydrate_manifest.manifest_id,
                        "storage_kind": runtime_input.semantic_state_handle.storage_kind.value,
                    },
                    metrics={
                        "semantic_state_transfer_count": 1.0,
                        "memfd_publish_count": (
                            1.0
                            if runtime_input.semantic_state_handle.storage_kind == StorageKind.MEMFD
                            else 0.0
                        ),
                        "shared_memory_publish_count": (
                            1.0
                            if runtime_input.semantic_state_handle.storage_kind == StorageKind.SHARED_MEMORY
                            else 0.0
                        ),
                        "mmap_publish_count": (
                            1.0
                            if runtime_input.semantic_state_handle.storage_kind == StorageKind.MMAP_FILE
                            else 0.0
                        ),
                    },
                )
            )
            for role in ("retriever", "executor", "summarizer"):
                telemetry.emit(
                    TelemetryEvent.create(
                        trace_id=runtime_input.trace_id,
                        task_id=runtime_input.task_id,
                        step_id=runtime_input.step_id,
                        event_type="STATE_HYDRATED",
                        role=role,
                        channel="semantic_state",
                        payload={
                            "manifest_id": runtime_input.retrieval.hydrate_manifest.manifest_id,
                            "evidence_pack_id": runtime_input.retrieval.evidence_pack.pack_id,
                            "locator_count": len(runtime_input.retrieval.hydrate_manifest.entries),
                            "hydrated_role": role,
                        },
                        metrics={
                            "external_evidence_bytes": float(
                                runtime_input.role_hydration_bytes.get(f"{role}_text", 0)
                                + runtime_input.role_hydration_bytes.get(f"{role}_table", 0)
                            ),
                            "prompt_visible_bytes": float(runtime_input.role_hydration_bytes.get(role, 0)),
                            "hydrated_item_count": float(runtime_input.role_hydration_item_count.get(role, 0)),
                            "text_bytes": float(runtime_input.role_hydration_bytes.get(f"{role}_text", 0)),
                            "table_bytes": float(runtime_input.role_hydration_bytes.get(f"{role}_table", 0)),
                            "artifact_bytes": float(runtime_input.role_hydration_bytes.get(f"{role}_artifact", 0)),
                            "memory_bytes": float(runtime_input.role_hydration_bytes.get(f"{role}_memory", 0)),
                        },
                    )
                )

    def _run_non_executor_step(
        self,
        *,
        session_manager: RuntimeSessionManager,
        session_id: str,
        telemetry: TelemetryEmitter,
        supervisor: RuntimeSupervisor,
        trace_id: str,
        task_id: str,
        step_id: str,
        role: str,
        output_refs: tuple[str, ...],
        payload: dict[str, object],
        metrics: dict[str, float],
        completion_event_type: str = "STEP_COMPLETED",
        completion_channel: str = "",
    ) -> tuple[RuntimeTaskSession, float]:
        stage_start_ns = time.perf_counter_ns()
        attempt_id = f"{step_id}-attempt-1"
        supervisor.register(task_id=task_id, step_id=step_id, attempt_id=attempt_id, role=role)
        supervisor.dispatch(step_id)
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=trace_id,
                task_id=task_id,
                step_id=step_id,
                attempt_id=attempt_id,
                event_type="STEP_DISPATCHED",
                role="runtime_supervisor",
                payload={
                    "target_role": role,
                    "runtime_reuse_contract": "benchmark_strict",
                    "state_ref_count": 0,
                    "artifact_ref_count": len(output_refs),
                },
                metrics={"timeout_ms": 250.0},
            )
        )
        session = session_manager.update_workflow_step(
            session_id,
            step_id=step_id,
            state=StepLifecycleState.DISPATCHED.value,
            attempt_id=attempt_id,
        )
        supervisor.ack(step_id)
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=trace_id,
                task_id=task_id,
                step_id=step_id,
                attempt_id=attempt_id,
                event_type="STEP_ACKED",
                role=role,
                metrics={"ack_count": 1.0},
            )
        )
        session = session_manager.update_workflow_step(
            session.session_id,
            step_id=step_id,
            state=StepLifecycleState.ACKED.value,
            attempt_id=attempt_id,
        )
        supervisor.run_start(step_id)
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=trace_id,
                task_id=task_id,
                step_id=step_id,
                attempt_id=attempt_id,
                event_type="STEP_RUNNING",
                role=role,
                metrics={"run_start_count": 1.0},
            )
        )
        session = session_manager.update_workflow_step(
            session.session_id,
            step_id=step_id,
            state=StepLifecycleState.RUNNING.value,
            attempt_id=attempt_id,
        )
        supervisor.complete(step_id)
        telemetry.emit(
            TelemetryEvent.create(
                trace_id=trace_id,
                task_id=task_id,
                step_id=step_id,
                attempt_id=attempt_id,
                event_type=completion_event_type,
                role=role,
                channel=completion_channel,
                payload=payload,
                metrics=metrics,
            )
        )
        session = session_manager.update_workflow_step(
            session.session_id,
            step_id=step_id,
            state=StepLifecycleState.COMPLETED.value,
            attempt_id=attempt_id,
            output_refs=output_refs,
            metrics=metrics,
        )
        return session, _elapsed_ms(stage_start_ns)

    def _exchange_loopback_messages(
        self,
        *,
        runtime_input: RuntimeDriverInput,
        current_attempt_id: str,
        candidate_artifact: ExecutionArtifactRef,
        current_memory_commit: MemoryCommit,
    ) -> tuple[list[object], float]:
        loopback_message = self._build_loopback_message(
            runtime_input=runtime_input,
            current_attempt_id=current_attempt_id,
            candidate_artifact=candidate_artifact,
            current_memory_commit=current_memory_commit,
        )
        responses = ControlPlaneLoopbackServer(runtime_input.socket_path).exchange_sequence_by_contract(
            loopback_message
        )
        control_bytes = (
            float(len(frame_control_message(loopback_message)))
            if runtime_input.layer_profile.structured_control_enabled
            else float(runtime_input.retrieval.full_corpus_bytes)
        )
        return responses, control_bytes

    def _build_loopback_message(
        self,
        *,
        runtime_input: RuntimeDriverInput,
        current_attempt_id: str,
        candidate_artifact: ExecutionArtifactRef,
        current_memory_commit: MemoryCommit,
    ) -> ExecRequest:
        header = ControlHeader(
            trace_id=runtime_input.trace_id,
            task_id=runtime_input.task_id,
            step_id=runtime_input.step_id,
            attempt_id=current_attempt_id,
            target_role="executor",
            timeout_ms=5000,
            event_type=EventType.REQ_EXEC,
        )
        runtime_contract_tokens = [runtime_input.layer_profile.layer_name.lower()]
        if runtime_input.layer_profile.replay_enabled:
            runtime_contract_tokens.append("benchmark_strict:exact_replay_allowed")
        if not runtime_input.layer_profile.semantic_pruning_enabled:
            runtime_contract_tokens.append("no_semantic_state")
        elif not runtime_input.layer_profile.semantic_state_transfer_enabled or runtime_input.semantic_ref is None:
            runtime_contract_tokens.append("no_semantic_state_transfer")
        if runtime_input.layer_profile.force_first_attempt_trap and current_attempt_id == "attempt-1":
            runtime_contract_tokens.append("force_trap")
        if runtime_input.layer_profile.simulate_ack_timeout:
            runtime_contract_tokens.append("drop_ack")
        if runtime_input.layer_profile.simulate_lease_timeout:
            runtime_contract_tokens.append("lease_timeout")
        return ExecRequest(
            header=header,
            reuse_policy=ReusePolicy(
                allow_assist=True,
                allow_validated_replay=runtime_input.layer_profile.replay_enabled,
                allow_exact_replay=runtime_input.layer_profile.replay_enabled,
            ),
            state_refs=()
            if runtime_input.semantic_ref is None
            else (RefHandle(ref_id=runtime_input.semantic_ref.state_id, ref_kind="semantic_state"),),
            artifact_refs=(RefHandle(ref_id=candidate_artifact.artifact_id, ref_kind="execution_artifact"),),
            memory_refs=(RefHandle(ref_id=current_memory_commit.memory_ref.memory_id, ref_kind="memory"),),
            runtime_reuse_contract="|".join(runtime_contract_tokens),
            output_contract_version=runtime_input.output_contract_version,
            workspace_root=str(runtime_input.layout.root),
            input_manifest_hash=runtime_input.input_manifest.manifest_hash,
        )

    def _rebuild_output_manifest(
        self,
        *,
        runtime_input: RuntimeDriverInput,
        output_artifact_hash: str,
        output_rendered: bytes,
    ) -> ArtifactOutputManifest:
        return ArtifactOutputManifest(
            task_id=runtime_input.task_id,
            step_id=runtime_input.step_id,
            outputs=(
                ArtifactManifestItem(
                    artifact_name="summary_json",
                    artifact_type="json",
                    relpath="outputs/result.json",
                    size_bytes=len(output_rendered),
                    sha256=output_artifact_hash,
                ),
                *runtime_input.artifact_manifest.outputs[1:],
            ),
        )

    def _persist_and_reload(
        self,
        *,
        runtime_input: RuntimeDriverInput,
        session: RuntimeTaskSession,
        finalized_artifact: ExecutionArtifactRef,
        committed_memory: MemoryCommit,
        ledger_entry: ReplayLedgerEntry,
        execution_step_record: ExecutionStepRecord,
        fallback_dag: FallbackDag | None,
        output_manifest: ArtifactOutputManifest,
        settlement_record: ArtifactSettlementRecord,
        invalidation_record: ArtifactInvalidationRecord | None,
    ) -> tuple[PersistedContractPaths, str, str, str, str, str, int, str, str, int]:
        persist_start_ns = time.perf_counter_ns()
        stage_start_ns = persist_start_ns
        breakdown: dict[str, float] = {}
        self._last_persist_and_reload_breakdown = {}
        store = JsonContractStore(runtime_input.runtime_root)
        verification_level = PersistenceVerificationLevel(runtime_input.layer_profile.persistence_verification_level)
        persisted = store.persist_contract_bundle(
            registry_entries=(
                [finalized_artifact.registry_entry(), committed_memory.memory_ref.registry_entry()]
                if runtime_input.semantic_ref is None
                else [
                    runtime_input.semantic_ref.registry_entry(),
                    finalized_artifact.registry_entry(),
                    committed_memory.memory_ref.registry_entry(),
                ]
            ),
            hydrate_manifest=runtime_input.retrieval.hydrate_manifest,
            evidence_pack=runtime_input.retrieval.evidence_pack,
            input_manifest=runtime_input.input_manifest,
            artifact_manifest=output_manifest,
            embedding=runtime_input.retrieval.query_embedding,
            memory_commit=committed_memory,
            memory_match_result=runtime_input.memory_match_result,
            retrieval_bundle=runtime_input.retrieval,
            runtime_session=session,
            validator_reports=runtime_input.validator_reports,
            input_validator_reports=runtime_input.input_validator_reports,
            replay_ledger_entry=ledger_entry,
            execution_step_record=execution_step_record,
            fallback_dag=fallback_dag,
            artifact_settlement_record=settlement_record,
            artifact_invalidation_record=invalidation_record,
            materialized_json_by_hash=runtime_input.materialized_json_by_hash,
        )
        breakdown["persist_bundle_write_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()

        reloaded_pack = store.read_evidence_pack(runtime_input.retrieval.evidence_pack.pack_hash)
        reloaded_input_manifest = store.read_input_manifest(runtime_input.input_manifest.manifest_hash)
        reloaded_artifact_manifest = store.read_artifact_output_manifest(output_manifest.manifest_hash)
        reloaded_embedding = store.read_embedding(runtime_input.retrieval.query_embedding.embedding_hash)
        reloaded_memory_commit = store.read_memory_commit(committed_memory.memory_ref.memory_id)
        reloaded_memory_match = store.read_memory_match_result(runtime_input.memory_match_result.result_hash)
        reloaded_retrieval_log = store.read_retrieval_log(runtime_input.retrieval.log_hash)
        reloaded_candidate_pool: dict[str, object] | None = None
        reloaded_rerank_result: dict[str, object] | None = None
        reloaded_pruning_profile = None
        breakdown["persist_core_reload_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()
        if verification_level == PersistenceVerificationLevel.STRICT_ROUNDTRIP:
            reloaded_candidate_pool = store.read_retrieval_candidate_pool(runtime_input.retrieval.candidate_pool.pool_hash)
            reloaded_rerank_result = store.read_retrieval_rerank_result(
                runtime_input.retrieval.rerank_result.rerank_hash
            )
            reloaded_pruning_profile = store.read_retrieval_pruning_profile(
                runtime_input.retrieval.pruning_profile.profile_hash
            )
        else:
            if persisted.retrieval_candidate_pool_path is None or not persisted.retrieval_candidate_pool_path.exists():
                raise RuntimeError("retrieval candidate pool sidecar missing after persist")
            if persisted.retrieval_rerank_result_path is None or not persisted.retrieval_rerank_result_path.exists():
                raise RuntimeError("retrieval rerank sidecar missing after persist")
            if persisted.retrieval_pruning_profile_path is None or not persisted.retrieval_pruning_profile_path.exists():
                raise RuntimeError("retrieval pruning sidecar missing after persist")
        breakdown["persist_retrieval_verification_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()
        reloaded_session = store.read_runtime_session(session.session_id)
        reloaded_ledger = store.read_replay_ledger_entry(ledger_entry.ledger_id)
        reloaded_execution_step = store.read_execution_step_record(
            task_id=runtime_input.task_id,
            step_id=runtime_input.step_id,
            attempt_id=session.current_attempt_id or "attempt-1",
        )
        reloaded_fallback_dag = None if fallback_dag is None else store.read_fallback_dag(fallback_dag.dag_id)
        breakdown["persist_session_ledger_reload_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()
        reloaded_validator_reports: list[dict[str, object]] = []
        reloaded_input_validator_reports: list[dict[str, object]] = []
        if verification_level == PersistenceVerificationLevel.STRICT_ROUNDTRIP:
            reloaded_validator_reports = [
                store.read_validator_report(report.report_hash) for report in runtime_input.validator_reports
            ]
            reloaded_input_validator_reports = [
                store.read_input_validator_report(report.report_hash) for report in runtime_input.input_validator_reports
            ]
        breakdown["persist_validator_reload_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()
        reloaded_manifest_id = ""
        if runtime_input.semantic_ref is not None:
            reloaded_manifest = store.read_hydrate_manifest(runtime_input.retrieval.hydrate_manifest.manifest_hash)
            if reloaded_manifest.manifest_id != runtime_input.retrieval.hydrate_manifest.manifest_id:
                raise RuntimeError("hydrate manifest mismatch after disk reload")
            reloaded_manifest_id = reloaded_manifest.manifest_id
        breakdown["persist_semantic_manifest_reload_stage_ms"] = _elapsed_ms(stage_start_ns)
        stage_start_ns = time.perf_counter_ns()

        if reloaded_pack.pack_id != runtime_input.retrieval.evidence_pack.pack_id:
            raise RuntimeError("evidence pack mismatch after disk reload")
        if reloaded_input_manifest.manifest_hash != runtime_input.input_manifest.manifest_hash:
            raise RuntimeError("input manifest mismatch after disk reload")
        if reloaded_artifact_manifest.manifest_hash != output_manifest.manifest_hash:
            raise RuntimeError("artifact manifest mismatch after disk reload")
        if reloaded_embedding.embedding_hash != runtime_input.retrieval.query_embedding.embedding_hash:
            raise RuntimeError("embedding mismatch after disk reload")
        if reloaded_memory_match.query_task_id != runtime_input.task_id:
            raise RuntimeError("memory match result mismatch after disk reload")
        if str(reloaded_retrieval_log["evidence_pack_hash"]) != runtime_input.retrieval.evidence_pack.pack_hash:
            raise RuntimeError("retrieval log mismatch after disk reload")
        if reloaded_session.session_state != StepLifecycleState.GC_DONE.value:
            raise RuntimeError("runtime session mismatch after disk reload")
        if reloaded_session.attempt_count < 1:
            raise RuntimeError("runtime session attempts missing after disk reload")
        if reloaded_ledger.replay_class != runtime_input.replay_decision.replay_class:
            raise RuntimeError("replay ledger mismatch after disk reload")
        if reloaded_execution_step.execution_goal != execution_step_record.execution_goal:
            raise RuntimeError("execution step record mismatch after disk reload")
        if runtime_input.codeact_plan is not None and reloaded_execution_step.codeact_plan is None:
            raise RuntimeError("codeact plan missing after disk reload")
        if len(reloaded_execution_step.input_validator_reports) != len(runtime_input.input_validator_reports):
            raise RuntimeError("input validator reports mismatch after disk reload")
        if fallback_dag is not None and reloaded_fallback_dag is not None:
            if reloaded_fallback_dag.dag_hash != fallback_dag.dag_hash:
                raise RuntimeError("fallback dag mismatch after disk reload")
        if verification_level == PersistenceVerificationLevel.STRICT_ROUNDTRIP:
            if reloaded_candidate_pool is None or str(reloaded_candidate_pool["task_id"]) != runtime_input.task_id:
                raise RuntimeError("retrieval candidate pool mismatch after disk reload")
            if reloaded_rerank_result is None or str(reloaded_rerank_result["task_id"]) != runtime_input.task_id:
                raise RuntimeError("retrieval rerank mismatch after disk reload")
            if reloaded_pruning_profile is None or reloaded_pruning_profile.task_id != runtime_input.task_id:
                raise RuntimeError("retrieval pruning profile mismatch after disk reload")
            if len(reloaded_validator_reports) != len(runtime_input.validator_reports):
                raise RuntimeError("validator reports mismatch after disk reload")
            if len(reloaded_input_validator_reports) != len(runtime_input.input_validator_reports):
                raise RuntimeError("input validator sidecars mismatch after disk reload")
        breakdown["persist_integrity_check_stage_ms"] = _elapsed_ms(stage_start_ns)
        self._last_persist_and_reload_stage_ms = _elapsed_ms(persist_start_ns)
        breakdown["persist_unbucketed_stage_ms"] = max(
            self._last_persist_and_reload_stage_ms - sum(breakdown.values()),
            0.0,
        )
        self._last_persist_and_reload_breakdown = breakdown
        return (
            persisted,
            reloaded_manifest_id,
            reloaded_pack.pack_id,
            reloaded_input_manifest.manifest_hash,
            reloaded_artifact_manifest.manifest_hash,
            reloaded_memory_commit.memory_ref.replay_class.value,
            len(reloaded_memory_match.matches),
            reloaded_execution_step.execution_goal,
            "" if reloaded_fallback_dag is None else reloaded_fallback_dag.dag_id,
            reloaded_session.replan_count,
        )
