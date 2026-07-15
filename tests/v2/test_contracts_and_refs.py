from __future__ import annotations

from v2.contracts import (
    CanonicalTaskSpec,
    CompatibilityVerdict,
    RefKind,
    RefRegistryEntry,
    RefStatus,
    ReplayClass,
    RuntimeCompatibilitySignature,
    StorageKind,
)
from v2.memory import MemoryCommitStatus, MemoryRef, MemoryType, MemoryValidationStatus
from v2.refs import ExecutionArtifactRef, LogitStateRef, SemanticStateRef
from v2.utils import stable_json_dumps


def test_canonical_task_spec_hash_is_stable_for_key_order() -> None:
    spec_a = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text", "metric_table"),
        arguments={"quarter": "2026Q1", "metric": "revenue"},
    )
    spec_b = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text", "metric_table"),
        arguments={"metric": "revenue", "quarter": "2026Q1"},
    )
    assert spec_a.spec_hash == spec_b.spec_hash


def test_runtime_compatibility_signature_structured_compare_degrades_on_os_only() -> None:
    base = RuntimeCompatibilitySignature(
        os_digest="os-a",
        python_digest="py-a",
        dependency_digest="dep-a",
        tool_registry_digest="tool-a",
        prompt_bundle_digest="prompt-a",
        extractor_bundle_digest="extract-a",
    )
    other = RuntimeCompatibilitySignature(
        os_digest="os-b",
        python_digest="py-a",
        dependency_digest="dep-a",
        tool_registry_digest="tool-a",
        prompt_bundle_digest="prompt-a",
        extractor_bundle_digest="extract-a",
    )
    assert base.compare(other) == CompatibilityVerdict.DEGRADED


def test_execution_artifact_ref_is_separate_ref_family_from_semantic_state() -> None:
    state_ref = SemanticStateRef(
        state_id="state-1",
        state_kind="EMBEDDING_STATE",
        storage_kind=StorageKind.SHARED_MEMORY,
        length=128,
        blob_hash="sha256:state",
    )
    artifact_ref = ExecutionArtifactRef(
        artifact_id="artifact-1",
        task_id="task-1",
        step_id="step-1",
        artifact_type="json",
        root_id="workspace-root",
        relpath="outputs/result.json",
        blob_hash="sha256:artifact",
        size_bytes=512,
        produced_by="executor",
    )

    assert state_ref.registry_entry().ref_kind == RefKind.SEMANTIC_STATE
    assert artifact_ref.registry_entry().ref_kind == RefKind.EXECUTION_ARTIFACT
    assert artifact_ref.registry_entry().status == RefStatus.CANDIDATE


def test_logit_state_ref_is_separate_ref_family_from_semantic_state() -> None:
    logit_ref = LogitStateRef(
        state_id="logit-1",
        producer_role="executor",
        consumer_role="summarizer",
        storage_kind=StorageKind.MEMFD,
        length=80,
        blob_hash="sha256:logit",
        entropy=0.42,
        confidence_proxy=0.73,
    )

    registry_entry = logit_ref.registry_entry()
    assert registry_entry.ref_kind == RefKind.LOGIT_STATE
    assert registry_entry.status == RefStatus.ACTIVE
    assert registry_entry.storage_kind == StorageKind.MEMFD


def test_ref_registry_entry_exposes_small_index_payload() -> None:
    entry = RefRegistryEntry(
        ref_id="artifact-1",
        ref_kind=RefKind.EXECUTION_ARTIFACT,
        storage_kind=StorageKind.WORKSPACE_ROOT,
        status=RefStatus.VERIFIED,
        blob_hash="sha256:x",
        manifest_hash="sha256:m",
        root_id="artifact-root",
        relpath="outputs/result.json",
    )
    payload = entry.small_index_payload()
    assert payload["ref_kind"] == "execution_artifact"
    assert payload["status"] == "verified"


def test_memory_ref_is_separate_ref_family_and_tracks_commit_gate_fields() -> None:
    memory_ref = MemoryRef(
        memory_id="memory-1",
        memory_type=MemoryType.VALIDATED_REPLAY,
        replay_class=ReplayClass.VALIDATED_REPLAY,
        score=0.88,
        source_task_id="task-1",
        summary="validated replay candidate",
        canonical_task_spec_hash="sha256:spec",
        artifact_ref_id="artifact-1",
        embedding_ref_id="embedding-1",
        commit_status=MemoryCommitStatus.COMMITTED,
        validation_status=MemoryValidationStatus.PASSED,
        answer_adopted=True,
    )
    registry_entry = memory_ref.registry_entry()
    assert registry_entry.ref_kind == RefKind.MEMORY
    assert registry_entry.status == RefStatus.VERIFIED
    assert registry_entry.storage_kind == StorageKind.CAS_SIDECAR


def test_stable_json_dumps_is_order_stable_without_pre_sorting() -> None:
    payload_a = {"outer": {"b": 2, "a": 1}, "items": [{"z": 3, "y": 2}]}
    payload_b = {"items": [{"y": 2, "z": 3}], "outer": {"a": 1, "b": 2}}
    assert stable_json_dumps(payload_a) == stable_json_dumps(payload_b)
