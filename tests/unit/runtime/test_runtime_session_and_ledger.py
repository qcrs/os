from __future__ import annotations

from statebus.benchmark.models import QualityFloorResult
from statebus.contracts import CanonicalTaskSpec, CompatibilityVerdict, RefStatus, ReplayClass
from statebus.memory import MemoryCommit, MemoryIndexStore, MemoryRef, MemoryType
from statebus.runtime import (
    ArtifactLifecycleManager,
    ReplayLedger,
    ReplayLedgerEntry,
    RuntimeCommitGate,
    RuntimeLeaseConfig,
    RuntimeReplanRecord,
    RuntimeSessionManager,
)
from statebus.runtime.session import RuntimeWorkflowStep, StepAttemptRecord
from statebus.runtime.supervisor import WorkerSessionSnapshot
from statebus.refs import ExecutionArtifactRef


def test_runtime_session_manager_tracks_refs_and_state() -> None:
    manager = RuntimeSessionManager()
    session = manager.start(
        session_id="session-1",
        trace_id="trace-1",
        task_id="task-1",
        layer_name="L3",
        canonical_task_spec_hash="sha256:spec",
        workspace_root="/tmp/workspace",
        state_root="/tmp/state",
        retrieval_log_hash="sha256:retrieval",
    )
    session = manager.attach_refs(
        "session-1",
        input_manifest_hash="sha256:input",
        artifact_manifest_hash="sha256:artifact",
        state_ref_ids=("state-1",),
        artifact_ref_ids=("artifact-1",),
        memory_ref_ids=("memory-1",),
    )
    session = manager.attach_workflow(
        "session-1",
        workflow_steps=(
            RuntimeWorkflowStep(
                step_id="step-1",
                role="executor",
                capability="materialize_and_execute",
            ),
        ),
    )
    session = manager.append_attempt_record(
        "session-1",
        record=StepAttemptRecord(
            task_id="task-1",
            step_id="step-1",
            attempt_id="attempt-1",
            owner_role="executor",
            state="DISPATCHED",
            attempt_index=0,
        ),
    )
    session = manager.update_workflow_step(
        "session-1",
        step_id="step-1",
        state="RUNNING",
        attempt_id="attempt-1",
        metrics={"control_bytes": 12.0},
    )
    session = manager.update_attempt_record(
        "session-1",
        attempt_id="attempt-1",
        state="RUNNING",
        fallback_action="retry_same_step",
    )
    session = manager.increment_runtime_fallback("session-1")
    session = manager.increment_runtime_replan("session-1", "retry_same_step")
    session = manager.append_replan_record(
        "session-1",
        record=RuntimeReplanRecord(
            replan_id="replan-1",
            task_id="task-1",
            source_step_id="step-1",
            attempt_id="attempt-1",
            trigger_state="TRAPPED",
            trigger_reason="simulated_executor_runtime_error",
            fallback_action="retry_same_step",
            selected_capability="materialize_and_execute",
            fallback_dag_hash="sha256:fallback",
        ),
    )
    session = manager.update_state(
        "session-1",
        WorkerSessionSnapshot(
            task_id="task-1",
            step_id="step-1",
            attempt_id="attempt-1",
            role="executor",
            state="GC_DONE",
            dispatched_at_ns=0,
            acked_at_ns=0,
            started_at_ns=0,
            last_heartbeat_ns=0,
            completed_at_ns=0,
            cancelled_at_ns=0,
            trapped_at_ns=0,
            last_error="",
        ),
    )
    assert session.state_ref_ids == ("state-1",)
    assert session.session_state == "GC_DONE"
    assert session.workflow_step_count == 1
    assert session.attempt_count == 1
    assert session.current_attempt_id == "attempt-1"
    assert session.runtime_fallback_count == 1
    assert session.runtime_replan_count == 1
    assert session.replan_count == 1
    assert session.workflow_steps[0].metrics["control_bytes"] == 12.0


def test_runtime_commit_gate_and_replay_ledger_promote_verified_outputs() -> None:
    lifecycle = ArtifactLifecycleManager()
    lifecycle.register_candidate(
        ExecutionArtifactRef(
            artifact_id="artifact-1",
            task_id="task-1",
            step_id="step-1",
            artifact_type="json",
            root_id="workspace-root",
            relpath="outputs/result.json",
            blob_hash="sha256:artifact",
            size_bytes=12,
            produced_by="executor",
        )
    )
    memory_commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id="memory-1",
            memory_type=MemoryType.EXACT_REPLAY,
            replay_class=ReplayClass.EXACT_REPLAY,
            score=1.0,
            source_task_id="task-1",
            summary="summary",
            canonical_task_spec_hash="sha256:spec",
            artifact_ref_id="artifact-1",
        ),
        canonical_task_spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
        required_outputs=("summary_text",),
        quality_floor_pass=True,
        created_from_artifact_hash="sha256:artifact",
    )
    artifact, committed, decision, settlement, invalidation = RuntimeCommitGate().finalize(
        artifact_lifecycle=lifecycle,
        memory_store=MemoryIndexStore(),
        artifact_id="artifact-1",
        memory_commit=memory_commit,
        quality_floor=QualityFloorResult(
            quality_floor_pass=True,
            deterministic_checks_passed=True,
            fact_coverage_passed=True,
        ),
        answer_adopted=True,
        replay_class=ReplayClass.EXACT_REPLAY,
    )
    assert artifact.verification_state == RefStatus.VERIFIED
    assert committed.memory_ref.replay_class == ReplayClass.EXACT_REPLAY
    assert decision.reason == "quality_floor_passed"
    assert settlement.to_state == RefStatus.VERIFIED.value
    assert invalidation is None

    ledger = ReplayLedger()
    entry = ledger.append(
        ReplayLedgerEntry(
            ledger_id="ledger-1",
            session_id="session-1",
            task_id="task-1",
            candidate_id="candidate-1",
            memory_id=committed.memory_ref.memory_id,
            artifact_ref_id=artifact.artifact_id,
            replay_class=ReplayClass.EXACT_REPLAY,
            decision_reason="exact_replay_key_match",
            compatibility_verdict=CompatibilityVerdict.COMPATIBLE,
            runtime_signature_hash="sha256:runtime",
            runtime_signature_manifest_bundle_hash="sha256:bundle",
            canonical_task_spec_hash="sha256:spec",
            planner_handoff_hash="sha256:planner",
            input_artifact_hashes=("sha256:planner", "sha256:input", "sha256:manifest"),
            output_contract_version="output-v1",
            code_template_version="code-v1",
            extractor_version="extract-v1",
            runtime_signature={"tool_registry_digest": "sha256:tools"},
            exact_key="sha256:exact",
            skipped_step_count=2,
        )
    )
    assert entry.replay_class == ReplayClass.EXACT_REPLAY
    assert entry.ledger_hash
    assert entry.runtime_signature_manifest_bundle_hash == "sha256:bundle"
    assert entry.planner_handoff_hash == "sha256:planner"
    assert entry.code_template_version == "code-v1"
    assert entry.extractor_version == "extract-v1"
