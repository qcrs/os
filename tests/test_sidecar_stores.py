from __future__ import annotations

from pathlib import Path

from statebus.contracts import CanonicalTaskSpec, ReplayClass
from statebus.memory import DeterministicEmbeddingEncoder, MemoryCommit, MemoryMatchResult, MemoryRef, MemoryType
from statebus.retrieval import RetrieverFanoutPipeline
from statebus.state import MemorySidecarStore, RetrievalSidecarStore


def test_retrieval_sidecar_store_persists_candidate_pool_and_rerank(tmp_path: Path) -> None:
    bundle = RetrieverFanoutPipeline().run(
        task_id="task-1",
        spec=CanonicalTaskSpec(
            task_family="financial_report_analysis",
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"ticker": "ACME", "quarter": "2026Q1"},
        ),
    )
    store = RetrievalSidecarStore(tmp_path / "retrieval")
    store.put_bundle(bundle)
    store.load()
    candidate_pool_payload = store.get_candidate_pool(bundle.candidate_pool.pool_hash)
    assert candidate_pool_payload["task_id"] == "task-1"
    assert candidate_pool_payload["candidate_surface_hash"] == bundle.candidate_pool.candidate_surface_hash
    assert store.get_rerank_result(bundle.rerank_result.rerank_hash)["task_id"] == "task-1"


def test_memory_sidecar_store_persists_commit_and_match(tmp_path: Path) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=8)
    memory_ref = MemoryRef(
        memory_id="memory-1",
        memory_type=MemoryType.EXACT_REPLAY,
        replay_class=ReplayClass.EXACT_REPLAY,
        score=1.0,
        source_task_id="task-1",
        summary="summary",
        canonical_task_spec_hash="sha256:spec",
        embedding_ref_id=encoder.encode(embedding_id="embedding-1", text="hello").embedding_id,
    )
    commit = MemoryCommit(
        memory_ref=memory_ref,
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
    match = MemoryMatchResult(
        query_task_id="task-2",
        query_spec_hash="sha256:spec-2",
        matches=(),
        retrieval_decision="memory_match_missing",
    )
    store = MemorySidecarStore(tmp_path / "memory")
    store.put_commit(commit)
    store.put_match_result(match)
    store.load()
    assert store.get_commit("memory-1")["memory_ref"]["memory_id"] == "memory-1"
    assert store.get_match_result(match.result_hash)["query_task_id"] == "task-2"


def test_memory_sidecar_store_persists_candidate_pool_and_rerank(tmp_path: Path) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=8)
    query_embedding = encoder.encode(embedding_id="embedding-query", text="ACME revenue increased.")
    memory_embedding = encoder.encode(embedding_id="embedding-memory", text="ACME revenue increased.")
    memory_ref = MemoryRef(
        memory_id="memory-1",
        memory_type=MemoryType.EXACT_REPLAY,
        replay_class=ReplayClass.EXACT_REPLAY,
        score=1.0,
        source_task_id="task-1",
        summary="summary",
        canonical_task_spec_hash="sha256:spec",
        embedding_ref_id=memory_embedding.embedding_id,
    )
    commit = MemoryCommit(
        memory_ref=memory_ref,
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
    from statebus.memory import MemoryIndexStore

    index = MemoryIndexStore()
    index.put_embedding(query_embedding)
    index.put_embedding(memory_embedding)
    index.commit_candidate(commit=commit, quality_floor_pass=True, answer_adopted=True)
    match_result = index.lookup(
        query_task_id="task-2",
        query_spec_hash="sha256:spec-2",
        query_embedding=query_embedding,
        allow_replay=True,
    )
    store = MemorySidecarStore(tmp_path / "memory")
    store.put_match_result(match_result)
    store.load()
    assert match_result.candidate_pool is not None
    assert match_result.rerank_result is not None
    candidate_pool_payload = store.get_candidate_pool(match_result.candidate_pool.pool_hash)
    assert candidate_pool_payload["query_task_id"] == "task-2"
    assert store.get_rerank_result(match_result.rerank_result.rerank_hash)["query_task_id"] == "task-2"
