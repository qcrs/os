from __future__ import annotations

from dataclasses import dataclass

from statebus.contracts import (
    CanonicalTaskSpec,
    MEMORY_ADMISSION_POLICY_ID,
    MEMORY_ADMISSION_POLICY_VERSION,
    ReplayClass,
)
from statebus.memory.models import (
    MemoryCommit,
    MemoryCommitStatus,
    MemoryRef,
    MemoryType,
    MemoryValidationStatus,
)
from statebus.refs import ExecutionArtifactRef
from statebus.utils import sha256_digest


MEMORY_PROJECTION_BINDING_SCHEMA_VERSION = "statebus.memory_projection_binding.v1"


@dataclass(frozen=True)
class MemoryProjectionSpec:
    """Immutable Mainline inputs Runtime may freeze into a Memory projection."""

    task_id: str
    trace_id: str
    canonical_task_spec: CanonicalTaskSpec
    canonical_task_spec_hash: str
    executor_step_id: str
    memory_replay_class: ReplayClass
    memory_topic: str
    memory_tags: tuple[str, ...]
    input_lineage_hashes: tuple[str, ...]
    input_schema_digest: str
    validator_digest: str
    runtime_compatibility_signature: str
    created_at_ns: int
    admission_policy_id: str = MEMORY_ADMISSION_POLICY_ID
    admission_policy_version: str = MEMORY_ADMISSION_POLICY_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "canonical_task_spec": self.canonical_task_spec.canonical_payload(),
            "canonical_task_spec_hash": self.canonical_task_spec_hash,
            "executor_step_id": self.executor_step_id,
            "memory_replay_class": self.memory_replay_class.value,
            "memory_topic": self.memory_topic,
            "memory_tags": list(self.memory_tags),
            "input_lineage_hashes": list(self.input_lineage_hashes),
            "input_schema_digest": self.input_schema_digest,
            "validator_digest": self.validator_digest,
            "runtime_compatibility_signature": self.runtime_compatibility_signature,
            "created_at_ns": self.created_at_ns,
            "admission_policy_id": self.admission_policy_id,
            "admission_policy_version": self.admission_policy_version,
        }

    @property
    def spec_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


@dataclass(frozen=True)
class MemoryProjectionBinding:
    """Runtime-issued binding for one exact downstream Memory projection."""

    projection_spec: MemoryProjectionSpec
    expected_memory_commit_hash: str
    source_artifact_id: str
    source_artifact_blob_hash: str
    artifact_verification_receipt_hash: str
    runtime_semantic_commit_receipt_hash: str
    admission_policy_id: str = MEMORY_ADMISSION_POLICY_ID
    admission_policy_version: str = MEMORY_ADMISSION_POLICY_VERSION
    schema_version: str = MEMORY_PROJECTION_BINDING_SCHEMA_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "projection_spec_hash": self.projection_spec.spec_hash,
            "expected_memory_commit_hash": self.expected_memory_commit_hash,
            "source_artifact_id": self.source_artifact_id,
            "source_artifact_blob_hash": self.source_artifact_blob_hash,
            "artifact_verification_receipt_hash": self.artifact_verification_receipt_hash,
            "runtime_semantic_commit_receipt_hash": self.runtime_semantic_commit_receipt_hash,
            "admission_policy_id": self.admission_policy_id,
            "admission_policy_version": self.admission_policy_version,
            "schema_version": self.schema_version,
        }

    @property
    def binding_hash(self) -> str:
        return sha256_digest(self.canonical_payload())


def build_memory_commit(
    *,
    spec: MemoryProjectionSpec,
    artifact: ExecutionArtifactRef,
    output_contract_version: str,
    quality_report_hash: str,
    execution_recipe: dict[str, object],
    semantic_state_ref_id: str,
    embedding_ref_id: str,
    artifact_verification_receipt_hash: str,
    runtime_semantic_commit_receipt_hash: str,
) -> MemoryCommit:
    replay_class = spec.memory_replay_class
    memory_type = {
        ReplayClass.EXACT_REPLAY: MemoryType.EXACT_REPLAY,
        ReplayClass.VALIDATED_REPLAY: MemoryType.VALIDATED_REPLAY,
    }.get(replay_class, MemoryType.STRATEGY)
    memory_id = (
        f"memory:{spec.task_id}:"
        f"{artifact.blob_hash.removeprefix('sha256:')[:16]}"
    )
    tags = tuple(dict.fromkeys((
        spec.canonical_task_spec.task_family,
        spec.canonical_task_spec.intent_op,
        *spec.canonical_task_spec.target_entities,
        *spec.memory_tags,
    )))
    recipe_hash = sha256_digest(execution_recipe)
    summary = (
        f"Verified {execution_recipe.get('execution_kind', 'analysis')} recipe for "
        f"{spec.canonical_task_spec.task_family}/"
        f"{spec.canonical_task_spec.intent_op}; artifact lineage retained."
    )
    return MemoryCommit(
        memory_ref=MemoryRef(
            memory_id=memory_id,
            memory_type=memory_type,
            replay_class=replay_class,
            score=1.0,
            source_task_id=spec.task_id,
            source_agent="executor",
            created_at_ns=spec.created_at_ns,
            task_theme=spec.memory_topic or spec.canonical_task_spec.task_family,
            tags=tags,
            source_role_path=("planner", "retriever", "executor"),
            producer_run_id=spec.trace_id,
            summary=summary,
            canonical_task_spec_hash=spec.canonical_task_spec_hash,
            artifact_ref_id=artifact.artifact_id,
            semantic_state_ref_id=semantic_state_ref_id,
            embedding_ref_id=embedding_ref_id,
            manifest_hash=artifact.manifest_hash,
            commit_status=MemoryCommitStatus.COMMITTED,
            validation_status=MemoryValidationStatus.PASSED,
            answer_adopted=True,
            metadata={
                "runtime_signature_hash": spec.runtime_compatibility_signature,
                "output_contract_version": output_contract_version,
                "validator_digest": spec.validator_digest,
                "quality_report_hash": quality_report_hash,
                "input_lineage_hashes": list(spec.input_lineage_hashes),
                "input_schema_digest": spec.input_schema_digest,
                "execution_recipe": dict(execution_recipe),
                "execution_recipe_hash": recipe_hash,
                "replay_ready": artifact.replay_ready,
                "artifact_root_id": artifact.root_id,
                "artifact_relpath": artifact.relpath,
                "artifact_blob_hash": artifact.blob_hash,
                "artifact_verification_receipt_hash": artifact_verification_receipt_hash,
                "runtime_semantic_commit_receipt_hash": runtime_semantic_commit_receipt_hash,
                "benchmark_gold_used": False,
            },
        ),
        canonical_task_spec=spec.canonical_task_spec,
        required_outputs=spec.canonical_task_spec.required_outputs,
        quality_floor_pass=True,
        created_from_artifact_hash=artifact.blob_hash,
    )
