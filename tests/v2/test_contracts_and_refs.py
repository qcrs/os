from __future__ import annotations

from v2.contracts import (
    CanonicalTaskSpec,
    CompatibilityVerdict,
    RefKind,
    RefRegistryEntry,
    RefStatus,
    RuntimeCompatibilitySignature,
    StorageKind,
)
from v2.refs import ExecutionArtifactRef, SemanticStateRef


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

