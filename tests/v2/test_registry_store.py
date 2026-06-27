from __future__ import annotations

from pathlib import Path

from v2.contracts import RefStatus, StorageKind
from v2.provenance import DeterministicFanInBuilder, EvidenceCandidate
from v2.refs import (
    ExecutionArtifactRef,
    HydrateManifest,
    HydrateManifestEntry,
    SemanticStateRef,
    TextSpanLocator,
)
from v2.runtime import ArtifactManifestItem, ArtifactOutputManifest
from v2.state import JsonContractStore


def test_json_contract_store_persists_registry_and_sidecars(tmp_path: Path) -> None:
    locator = TextSpanLocator(
        source_doc_hash="sha256:doc1",
        canonical_text_id="chunk-1",
        start_char=0,
        end_char=20,
        extractor_version="chunker-v1",
    )
    hydrate_manifest = HydrateManifest(
        manifest_id="manifest-1",
        source_doc_hashes=("sha256:doc1",),
        entries=(
            HydrateManifestEntry(
                row_idx=0,
                stable_key="text-span-1",
                byte_hint=20,
                locator=locator,
            ),
        ),
        canonicalizer_version="canon-v1",
        extractor_version="chunker-v1",
    )
    evidence_pack = DeterministicFanInBuilder().build(
        pack_id="pack-1",
        task_id="task-1",
        text_candidates=[
            EvidenceCandidate(
                item_id="ctx-1",
                bucket="semantic_context",
                locator=locator,
                rendered_text="Quarterly revenue improved.",
                source_name="semantic",
                rank=1,
            )
        ],
    )
    semantic_ref = SemanticStateRef(
        state_id="state-1",
        state_kind="DENSE_SEMANTIC_STATE",
        storage_kind=StorageKind.MMAP_FILE,
        length=32,
        blob_hash="sha256:state",
        manifest_id=hydrate_manifest.manifest_hash,
    )
    artifact_ref = ExecutionArtifactRef(
        artifact_id="artifact-1",
        task_id="task-1",
        step_id="step-1",
        artifact_type="json",
        root_id="workspace-root",
        relpath="outputs/result.json",
        blob_hash="sha256:artifact",
        size_bytes=64,
        produced_by="executor",
        verification_state=RefStatus.VERIFIED,
    )
    artifact_manifest = ArtifactOutputManifest(
        task_id="task-1",
        step_id="step-1",
        outputs=(
            ArtifactManifestItem(
                artifact_name="result",
                artifact_type="json",
                relpath="outputs/result.json",
                size_bytes=64,
                sha256="sha256:artifact",
            ),
        ),
    )

    store = JsonContractStore(tmp_path / "contracts")
    persisted = store.persist_contract_bundle(
        registry_entries=[semantic_ref.registry_entry(), artifact_ref.registry_entry()],
        hydrate_manifest=hydrate_manifest,
        evidence_pack=evidence_pack,
        artifact_manifest=artifact_manifest,
    )

    reloaded_semantic = store.get_ref_registry_entry("state-1")
    reloaded_artifact = store.get_ref_registry_entry("artifact-1")
    reloaded_manifest = store.read_hydrate_manifest(hydrate_manifest.manifest_hash)
    reloaded_pack = store.read_evidence_pack(evidence_pack.pack_hash)
    reloaded_output_manifest = store.read_artifact_output_manifest(artifact_manifest.manifest_hash)

    assert persisted.registry_path.exists()
    assert persisted.hydrate_manifest_path is not None and persisted.hydrate_manifest_path.exists()
    assert persisted.evidence_pack_path is not None and persisted.evidence_pack_path.exists()
    assert persisted.artifact_manifest_path is not None and persisted.artifact_manifest_path.exists()
    assert reloaded_semantic.ref_id == "state-1"
    assert reloaded_artifact.ref_id == "artifact-1"
    assert reloaded_manifest.manifest_id == "manifest-1"
    assert reloaded_pack.pack_id == "pack-1"
    assert reloaded_output_manifest.outputs[0].artifact_name == "result"
