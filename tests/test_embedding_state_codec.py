from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from statebus.contracts import StorageKind
from statebus.memory import DeterministicEmbeddingEncoder
from statebus.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from statebus.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    SemanticStateValidationError,
    encoder_signature_for,
    publish_dense_semantic_state,
    resolve_dense_semantic_state,
)


def _publication(tmp_path: Path, *, mode: str = "shared_memory", lease_ttl_ms: int = 60_000):
    encoder = DeterministicEmbeddingEncoder(dims=16)
    query = encoder.encode(embedding_id="query", text="revenue growth outlook")
    candidates = (
        encoder.encode(embedding_id="candidate-a", text="revenue growth improved"),
        encoder.encode(embedding_id="candidate-b", text="network incident timeout"),
    )
    manifest = HydrateManifest(
        manifest_id="manifest-dense",
        source_doc_hashes=("doc-hash",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=f"candidate-{index}",
                locator=FragmentLocator(
                    source_doc_hash="doc-hash",
                    fragment_id=f"fragment-{index}",
                    extractor_version="test-v1",
                ),
                stable_key=f"fragment-{index}",
                byte_hint=32,
                importance_score=0.8,
            )
            for index in (1, 2)
        ),
        canonicalizer_version="canon-v1",
        extractor_version="test-v1",
    )
    store = LayeredStateStore(
        root=tmp_path / "state",
        policy=LayeredStoragePolicy.for_state_pool_mode(mode),
    )
    publication = publish_dense_semantic_state(
        store=store,
        state_id="dense-state",
        query_embedding=query,
        candidate_embeddings=candidates,
        hydrate_manifest=manifest,
        owner_session_id="session-test",
        encoder_revision="deterministic-v1",
        lease_ttl_ms=lease_ttl_ms,
    )
    return store, publication, query, candidates


@pytest.mark.parametrize("mode", ["shared_memory", "mmap"])
def test_dense_embedding_codec_is_binary_float32_and_registry_resolvable(
    tmp_path: Path,
    mode: str,
) -> None:
    store, publication, query, candidates = _publication(tmp_path, mode=mode)
    try:
        assert publication.ref.length == 3 * 16 * 4
        assert publication.ref.metadata["dtype"] == "float32"
        assert publication.ref.metadata["byte_order"] == "little"
        assert publication.ref.metadata["shape"] == [3, 16]
        assert publication.ref.metadata["row_layout"] == "query_then_candidates"
        payload = store.load(publication.ref.state_id)
        assert len(payload) == publication.ref.length
        with pytest.raises((UnicodeDecodeError, json.JSONDecodeError)):
            json.loads(payload.decode("utf-8"))

        with resolve_dense_semantic_state(
            state_root=store.root,
            ref=publication.ref,
            expected_encoder_signature=encoder_signature_for(
                encoder_id=query.encoding,
                encoder_revision="deterministic-v1",
                dims=16,
            ),
        ) as resolved:
            observed = resolved.matrix.copy()
            assert not resolved.matrix.flags.writeable
        expected = np.asarray(
            [query.vector, *(candidate.vector for candidate in candidates)],
            dtype="<f4",
        )
        np.testing.assert_allclose(observed, expected, atol=1e-6)
    finally:
        store.teardown()


def test_dense_state_resolver_fails_closed_for_shape_encoder_expiry_and_corruption(tmp_path: Path) -> None:
    store, publication, query, _ = _publication(tmp_path)
    try:
        wrong_shape = replace(
            publication.ref,
            metadata={**publication.ref.metadata, "shape": [99, 16]},
        )
        with pytest.raises(SemanticStateValidationError, match="ref_contract_mismatch|size_shape"):
            resolve_dense_semantic_state(state_root=store.root, ref=wrong_shape)

        with pytest.raises(SemanticStateValidationError, match="encoder_signature_mismatch"):
            resolve_dense_semantic_state(
                state_root=store.root,
                ref=publication.ref,
                expected_encoder_signature="wrong-encoder",
            )

        with pytest.raises(SemanticStateValidationError, match="expired"):
            resolve_dense_semantic_state(
                state_root=store.root,
                ref=publication.ref,
                now_ns=int(publication.ref.metadata["lease_expires_at_ns"]) + 1,
            )

        shared = store._shared_segments[publication.ref.state_id]
        shared.buf[0] = (int(shared.buf[0]) + 1) % 256
        with pytest.raises(SemanticStateValidationError, match="blob_hash_mismatch"):
            resolve_dense_semantic_state(state_root=store.root, ref=publication.ref)
    finally:
        store.teardown()


def test_dense_state_shared_memory_is_unlinked_only_by_owner_release(tmp_path: Path) -> None:
    from multiprocessing.shared_memory import SharedMemory

    store, publication, _, _ = _publication(tmp_path)
    assert publication.handle.storage_kind == StorageKind.SHARED_MEMORY
    probe = SharedMemory(name=publication.handle.shared_memory_name)
    probe.close()
    store.release(publication.ref.state_id)
    with pytest.raises(FileNotFoundError):
        SharedMemory(name=publication.handle.shared_memory_name)
