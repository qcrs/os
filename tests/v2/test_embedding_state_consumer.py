from __future__ import annotations

import os
from pathlib import Path

import pytest

from v2.control import (
    ControlHeader,
    ErrorResult,
    EventType,
    ExecRequest,
    RefHandle,
    SubprocessExecutorTransport,
    SuccessResult,
)
from v2.memory import DeterministicEmbeddingEncoder
from v2.refs import FragmentLocator, HydrateManifest, HydrateManifestEntry
from v2.state import (
    LayeredStateStore,
    LayeredStoragePolicy,
    SemanticStateValidationError,
    publish_dense_semantic_state,
    resolve_dense_semantic_state,
    select_dense_semantic_state,
)


def _semantic_state(tmp_path: Path, *, mode: str = "shared_memory"):
    encoder = DeterministicEmbeddingEncoder(dims=16)
    query = encoder.encode(embedding_id="query", text="revenue growth outlook")
    texts = (
        "revenue growth outlook",
        "network timeout incident",
        "revenue forecast improved",
    )
    candidates = tuple(
        encoder.encode(embedding_id=f"candidate-{index}", text=text)
        for index, text in enumerate(texts, start=1)
    )
    manifest = HydrateManifest(
        manifest_id="manifest-cross-process",
        source_doc_hashes=("doc-hash",),
        entries=tuple(
            HydrateManifestEntry(
                row_idx=index,
                candidate_id=f"candidate-{index}",
                bucket="semantic_context",
                locator=FragmentLocator(
                    source_doc_hash="doc-hash",
                    fragment_id=f"fragment-{index}",
                    extractor_version="test-v1",
                ),
                stable_key=f"fragment-{index}",
                byte_hint=(40, 60, 50)[index - 1],
                importance_score=0.9,
            )
            for index in range(1, 4)
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
        state_id="dense-cross-process",
        query_embedding=query,
        candidate_embeddings=candidates,
        hydrate_manifest=manifest,
        owner_session_id="session-cross-process",
        encoder_revision="deterministic-v1",
    )
    return store, publication


@pytest.mark.parametrize("mode", ["shared_memory", "mmap"])
def test_typed_uds_worker_resolves_and_consumes_dense_state_in_another_pid(
    tmp_path: Path,
    mode: str,
) -> None:
    store, publication = _semantic_state(tmp_path, mode=mode)
    try:
        reference = select_dense_semantic_state(
            state_root=store.root,
            ref=publication.ref,
            manifest_id=publication.ref.manifest_id,
            top_k=2,
            evidence_budget_bytes=100,
            expected_encoder_signature=publication.ref.compatibility_hint,
        )
        request = ExecRequest(
            header=ControlHeader(
                trace_id="trace-semantic",
                task_id="task-semantic",
                step_id="semantic-consumer",
                attempt_id="attempt-1",
                target_role="executor",
                timeout_ms=20_000,
                event_type=EventType.REQ_EXEC,
            ),
            state_refs=(RefHandle(ref_id=publication.ref.state_id, ref_kind="semantic_state"),),
            runtime_reuse_contract="semantic_state_required",
            output_contract_version="statebus.evidence_selection.v1",
            workspace_root=str(tmp_path / "workspace"),
            input_manifest_hash="sha256:manifest",
            operation="semantic_select_v1",
            state_root=str(store.root),
            hydrate_manifest_id=publication.ref.manifest_id,
            semantic_top_k=2,
            evidence_budget_bytes=100,
            expected_encoder_signature=publication.ref.compatibility_hint,
            capability_grant_hash="grant-semantic-consume",
        )
        responses = SubprocessExecutorTransport(
            socket_path=tmp_path / f"semantic-{mode}.sock",
            timeout_s=20.0,
        ).exchange_sequence(request)
        assert [response.header.event_type.name for response in responses] == [
            "ACK_RECV",
            "RUN_START",
            "HEARTBEAT",
            "RES_SUCC",
        ]
        result = responses[-1]
        assert isinstance(result, SuccessResult)
        assert result.consumed_state_ref_id == publication.ref.state_id
        assert result.selected_candidate_ids == reference.selected_candidate_ids
        assert result.selected_scores == reference.selected_scores
        assert result.selected_row_indices == reference.selected_row_indices
        assert result.consumer_pid != os.getpid()
        assert result.consumer_pid != result.producer_pid
        assert result.producer_pid == os.getpid()
        assert result.encoder_signature == publication.ref.compatibility_hint

        # A consumer only closes its mapping. The producer remains owner and
        # can resolve the state again until explicit release.
        with resolve_dense_semantic_state(state_root=store.root, ref=publication.ref) as resolved:
            assert resolved.matrix.shape == (4, 16)
    finally:
        store.teardown()


def test_semantic_consumer_rejects_wrong_encoder_and_owner_release_removes_payload(
    tmp_path: Path,
) -> None:
    store, publication = _semantic_state(tmp_path)
    request = ExecRequest(
        header=ControlHeader(
            trace_id="trace-semantic-error",
            task_id="task-semantic-error",
            step_id="semantic-consumer",
            attempt_id="attempt-1",
            target_role="executor",
            timeout_ms=20_000,
            event_type=EventType.REQ_EXEC,
        ),
        state_refs=(RefHandle(ref_id=publication.ref.state_id, ref_kind="semantic_state"),),
        runtime_reuse_contract="semantic_state_required",
        output_contract_version="statebus.evidence_selection.v1",
        workspace_root=str(tmp_path / "workspace"),
        input_manifest_hash="sha256:manifest",
        operation="semantic_select_v1",
        state_root=str(store.root),
        hydrate_manifest_id=publication.ref.manifest_id,
        semantic_top_k=1,
        expected_encoder_signature="wrong-encoder",
        capability_grant_hash="grant-semantic-consume",
    )
    try:
        result = SubprocessExecutorTransport(
            socket_path=tmp_path / "semantic-error.sock",
            timeout_s=20.0,
        ).execute(request)
        assert isinstance(result, ErrorResult)
        assert result.error_code == "semantic_state_consume_failed"
        assert "encoder_signature_mismatch" in result.error_detail
    finally:
        store.release(publication.ref.state_id)

    with pytest.raises(SemanticStateValidationError, match="payload_missing"):
        resolve_dense_semantic_state(state_root=store.root, ref=publication.ref)
