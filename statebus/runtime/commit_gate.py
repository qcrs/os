from __future__ import annotations

from dataclasses import dataclass

from statebus.benchmark.models import QualityFloorResult
from statebus.contracts import RefStatus, ReplayClass
from statebus.memory import MemoryCommit, MemoryIndexStore
from statebus.refs import ExecutionArtifactRef
from statebus.runtime.workspace import (
    ArtifactInvalidationRecord,
    ArtifactLifecycleManager,
    ArtifactSettlementRecord,
    ArtifactValidatorReport,
    InputValidatorReport,
)


@dataclass(frozen=True)
class CommitGateDecision:
    artifact_verified: bool
    memory_committed: bool
    replay_class: ReplayClass
    reason: str
    validator_report_hashes: tuple[str, ...] = ()
    input_validator_hashes: tuple[str, ...] = ()
    invalidation_reasons: tuple[str, ...] = ()
    previous_artifact_state: str = RefStatus.CANDIDATE.value


@dataclass
class RuntimeCommitGate:
    def finalize(
        self,
        *,
        artifact_lifecycle: ArtifactLifecycleManager,
        memory_store: MemoryIndexStore,
        artifact_id: str,
        memory_commit: MemoryCommit,
        quality_floor: QualityFloorResult,
        answer_adopted: bool,
        replay_class: ReplayClass,
        validator_reports: tuple[ArtifactValidatorReport, ...] = (),
        input_validator_reports: tuple[InputValidatorReport, ...] = (),
    ) -> tuple[
        ExecutionArtifactRef,
        MemoryCommit,
        CommitGateDecision,
        ArtifactSettlementRecord,
        ArtifactInvalidationRecord | None,
    ]:
        validator_reports_passed = all(report.passed for report in validator_reports)
        input_validators_passed = all(report.passed for report in input_validator_reports)
        candidate_artifact = artifact_lifecycle.artifacts[artifact_id]
        previous_state = candidate_artifact.verification_state.value
        validator_hashes = tuple(report.report_hash for report in validator_reports)
        input_validator_hashes = tuple(report.report_hash for report in input_validator_reports)
        if quality_floor.quality_floor_pass and answer_adopted and validator_reports_passed and input_validators_passed:
            artifact = artifact_lifecycle.mark_verified(artifact_id)
            committed = memory_store.commit_candidate(
                commit=memory_commit,
                quality_floor_pass=True,
                answer_adopted=True,
            )
            settlement = artifact_lifecycle.record_settlement(
                ArtifactSettlementRecord(
                    artifact_id=artifact.artifact_id,
                    task_id=artifact.task_id,
                    step_id=artifact.step_id,
                    from_state=previous_state,
                    to_state=artifact.verification_state.value,
                    commit_gate_reason="quality_floor_passed",
                    quality_floor_pass=True,
                    validator_report_hashes=validator_hashes,
                    input_validator_hashes=input_validator_hashes,
                    replay_ready=artifact.replay_ready,
                )
            )
            return artifact, committed, CommitGateDecision(
                artifact_verified=True,
                memory_committed=True,
                replay_class=replay_class,
                reason="quality_floor_passed",
                validator_report_hashes=validator_hashes,
                input_validator_hashes=input_validator_hashes,
                previous_artifact_state=previous_state,
            ), settlement, None

        invalidation_reason = (
            "input_validator_failed"
            if not input_validators_passed
            else "validator_failed"
            if not validator_reports_passed
            else "quality_floor_failed"
        )
        artifact = artifact_lifecycle.mark_invalidated(artifact_id)
        committed = memory_store.commit_candidate(
            commit=memory_commit,
            quality_floor_pass=False,
            answer_adopted=answer_adopted,
        )
        settlement = artifact_lifecycle.record_settlement(
            ArtifactSettlementRecord(
                artifact_id=artifact.artifact_id,
                task_id=artifact.task_id,
                step_id=artifact.step_id,
                from_state=previous_state,
                to_state=artifact.verification_state.value,
                commit_gate_reason=invalidation_reason,
                quality_floor_pass=False,
                validator_report_hashes=validator_hashes,
                input_validator_hashes=input_validator_hashes,
                replay_ready=False,
            )
        )
        invalidation_record = artifact_lifecycle.record_invalidation(
            ArtifactInvalidationRecord(
                artifact_id=artifact.artifact_id,
                task_id=artifact.task_id,
                step_id=artifact.step_id,
                invalidation_reason=invalidation_reason,
                invalidated_from_state=previous_state,
                validator_report_hashes=validator_hashes,
                input_validator_hashes=input_validator_hashes,
            )
        )
        return artifact, committed, CommitGateDecision(
            artifact_verified=False,
            memory_committed=False,
            replay_class=ReplayClass.ASSIST,
            reason=invalidation_reason,
            validator_report_hashes=validator_hashes,
            input_validator_hashes=input_validator_hashes,
            invalidation_reasons=(invalidation_reason,),
            previous_artifact_state=previous_state,
        ), settlement, invalidation_record
