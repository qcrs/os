from __future__ import annotations

from v2.contracts import CanonicalTaskSpec, ReplayClass
from pathlib import Path

from v2.memory import (
    DeterministicEmbeddingEncoder,
    MemoryCommit,
    MemoryCommitStatus,
    MemoryIndexStore,
    MemoryMatch,
    MemoryType,
    MemoryRef,
)


def test_memory_index_store_commit_lookup_and_invalidate() -> None:
    encoder = DeterministicEmbeddingEncoder(dims=8)
    query_embedding = encoder.encode(embedding_id="embedding-query", text="ACME revenue increased in APAC.")
    memory_embedding = encoder.encode(embedding_id="embedding-memory", text="ACME revenue increased in APAC.")

    store = MemoryIndexStore()
    store.put_embedding(query_embedding)
    store.put_embedding(memory_embedding)
    commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id="memory-1",
            memory_type=MemoryType.EXACT_REPLAY,
            replay_class=ReplayClass.EXACT_REPLAY,
            score=0.9,
            source_task_id="task-1",
            summary="replayable result",
            canonical_task_spec_hash="sha256:spec-1",
            artifact_ref_id="artifact-1",
            embedding_ref_id="embedding-memory",
        ),
        canonical_task_spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
        required_outputs=("summary_text",),
        quality_floor_pass=True,
        created_from_artifact_hash="sha256:artifact-1",
    )
    committed = store.commit_candidate(commit=commit, quality_floor_pass=True, answer_adopted=True)
    assert committed.memory_ref.commit_status == MemoryCommitStatus.COMMITTED

    match_result = store.lookup(
        query_task_id="task-2",
        query_spec_hash="sha256:spec-2",
        query_embedding=query_embedding,
        allow_replay=True,
    )
    assert match_result.retrieval_decision == "memory_match_found"
    assert match_result.matches[0].replay_class == ReplayClass.EXACT_REPLAY
    assert match_result.candidate_pool_hash
    assert match_result.rerank_result_hash
    assert match_result.candidate_pool is not None
    assert match_result.candidate_pool.candidate_taxonomy["exact_replay"] == 1
    assert match_result.rerank_result is not None
    assert match_result.rerank_result.selected_taxonomy["exact_replay"] == 1

    invalidated = store.invalidate("memory-1")
    assert invalidated.memory_ref.commit_status == MemoryCommitStatus.INVALIDATED
    post_invalidation = store.lookup(
        query_task_id="task-3",
        query_spec_hash="sha256:spec-3",
        query_embedding=query_embedding,
        allow_replay=True,
    )
    assert post_invalidation.matches == ()


def test_memory_index_store_persists_embedding_and_commit_registry(tmp_path: Path) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=8)
    embedding = encoder.encode(embedding_id="embedding-memory", text="ACME APAC revenue improved.")
    commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id="memory-1",
            memory_type=MemoryType.EXACT_REPLAY,
            replay_class=ReplayClass.EXACT_REPLAY,
            score=0.9,
            source_task_id="task-1",
            summary="persisted replay memory",
            canonical_task_spec_hash="sha256:spec-1",
            artifact_ref_id="artifact-1",
            embedding_ref_id="embedding-memory",
        ),
        canonical_task_spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
        required_outputs=("summary_text",),
        quality_floor_pass=True,
        created_from_artifact_hash="sha256:artifact-1",
    )

    store = MemoryIndexStore(store_root=tmp_path / "memory-index")
    store.put_embedding(embedding)
    store.put_commit(commit)

    restored = MemoryIndexStore(store_root=tmp_path / "memory-index")
    restored.load_persisted_state()
    assert len(restored.list_embeddings()) == 1
    assert len(restored.list_commits()) == 1
    assert restored.list_commits()[0].memory_ref.summary == "persisted replay memory"


def test_memory_match_payload_keeps_hashes_but_omits_large_runtime_bundle() -> None:
    memory_ref = MemoryRef(
        memory_id="memory-1",
        memory_type=MemoryType.EXACT_REPLAY,
        replay_class=ReplayClass.EXACT_REPLAY,
        score=0.9,
        source_task_id="task-1",
        summary="replayable result",
        canonical_task_spec_hash="sha256:spec-1",
        artifact_ref_id="artifact-1",
        metadata={
            "runtime_signature_manifest_bundle": {"prompt_manifests": [{"role": "planner"}]},
            "runtime_signature_manifest_bundle_hash": "sha256:bundle",
            "runtime_signature_manifest_bundle_relpath": "inputs/runtime_signature_manifest_bundle.json",
            "runtime_signature_hash": "sha256:runtime",
            "planner_handoff_hash": "sha256:planner",
            "input_artifact_hashes": ["sha256:a"],
            "workspace_root": "/tmp/task-1",
            "output_relpath": "outputs/result.json",
            "output_sha256": "sha256:result",
            "output_contract_version": "output-v1",
        },
    )

    payload = MemoryMatch(
        memory_ref=memory_ref,
        matched_on="embedding_similarity",
        score=0.9,
        replay_class=ReplayClass.EXACT_REPLAY,
    ).canonical_payload()

    assert payload["memory_ref"]["metadata"]["runtime_signature_manifest_bundle_hash"] == "sha256:bundle"
    assert (
        payload["memory_ref"]["metadata"]["runtime_signature_manifest_bundle_relpath"]
        == "inputs/runtime_signature_manifest_bundle.json"
    )
    assert "replay_class" not in payload["memory_ref"]
    assert "score" not in payload["memory_ref"]
    assert "embedding_ref_id" not in payload["memory_ref"]
    assert "commit_status" not in payload["memory_ref"]
    assert "validation_status" not in payload["memory_ref"]
    assert "answer_adopted" not in payload["memory_ref"]
    assert "runtime_signature_manifest_bundle" not in payload["memory_ref"]["metadata"]
    assert "planner_handoff_hash" not in payload["memory_ref"]["metadata"]
    assert "input_artifact_hashes" not in payload["memory_ref"]["metadata"]
    assert "workspace_root" not in payload["memory_ref"]["metadata"]
    assert "output_relpath" not in payload["memory_ref"]["metadata"]
    assert "output_sha256" not in payload["memory_ref"]["metadata"]
