from __future__ import annotations

from pathlib import Path

from v2.contracts import CanonicalTaskSpec, ReplayClass
from v2.memory import (
    DeterministicEmbeddingEncoder,
    MemoryCommit,
    MemoryIndexStore,
    MemoryQuery,
    MemoryRef,
    MemoryType,
)


def _put_memory(
    store: MemoryIndexStore,
    encoder: DeterministicEmbeddingEncoder,
    *,
    memory_id: str,
    text: str,
    tags: tuple[str, ...],
    spec_hash: str,
    replay_class: ReplayClass = ReplayClass.ASSIST,
    runtime_signature: str = "",
) -> None:
    embedding = encoder.encode(embedding_id=f"embedding-{memory_id}", text=text)
    store.put_embedding(embedding)
    spec = CanonicalTaskSpec(
        task_family="financial_report_analysis",
        intent_op="compare_metric",
        required_outputs=("summary_text",),
        required_tools=("finance",),
        arguments={"memory_id": memory_id},
    )
    commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id=memory_id,
            memory_type=(
                MemoryType.EXACT_REPLAY
                if replay_class == ReplayClass.EXACT_REPLAY
                else MemoryType.EVIDENCE
            ),
            replay_class=replay_class,
            score=0.8,
            source_task_id=f"source-{memory_id}",
            summary=text,
            canonical_task_spec_hash=spec_hash,
            tags=tags,
            embedding_ref_id=embedding.embedding_id,
            metadata={
                "runtime_signature_hash": runtime_signature,
                "output_contract_version": "output-v1",
            },
        ),
        canonical_task_spec=spec,
        required_outputs=spec.required_outputs,
        quality_floor_pass=True,
        created_from_artifact_hash=f"sha256:{memory_id}",
    )
    store.commit_candidate(commit=commit, quality_floor_pass=True, answer_adopted=True)


def test_hybrid_memory_query_uses_three_rank_sources_and_stable_rrf(tmp_path: Path) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=16)
    store = MemoryIndexStore(store_root=tmp_path / "memory")
    spec_hash = "sha256:query-spec"
    _put_memory(
        store,
        encoder,
        memory_id="memory-all-signals",
        text="quarterly revenue outlook",
        tags=("finance", "revenue"),
        spec_hash=spec_hash,
    )
    _put_memory(
        store,
        encoder,
        memory_id="memory-tag",
        text="operating margin notes",
        tags=("finance",),
        spec_hash=spec_hash,
    )
    _put_memory(
        store,
        encoder,
        memory_id="memory-vector",
        text="quarterly revenue trend",
        tags=("operations",),
        spec_hash=spec_hash,
    )
    query = MemoryQuery(
        query_task_id="task-current",
        query_spec_hash=spec_hash,
        query_text="quarterly revenue outlook",
        tags=("finance",),
        query_embedding=encoder.encode(
            embedding_id="embedding-query",
            text="quarterly revenue outlook",
        ),
        limit=3,
    )

    first = store.lookup_hybrid(query)
    second = store.lookup_hybrid(query)

    assert all(first.source_ranks[source] for source in ("keyword", "tags", "vector"))
    assert first.matches[0].memory_ref.memory_id == "memory-all-signals"
    assert first.canonical_payload() == second.canonical_payload()
    assert first.matches[0].matched_on == "hybrid_rrf:keyword+tags+vector"


def test_hybrid_memory_query_applies_compatibility_gate_after_fusion(tmp_path: Path) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=16)
    store = MemoryIndexStore(store_root=tmp_path / "memory")
    _put_memory(
        store,
        encoder,
        memory_id="incompatible-high-rank",
        text="revenue exact result",
        tags=("finance",),
        spec_hash="sha256:other-spec",
        replay_class=ReplayClass.EXACT_REPLAY,
        runtime_signature="runtime-other",
    )
    _put_memory(
        store,
        encoder,
        memory_id="compatible-replay",
        text="revenue prior result",
        tags=("finance",),
        spec_hash="sha256:query-spec",
        replay_class=ReplayClass.EXACT_REPLAY,
        runtime_signature="runtime-current",
    )
    result = store.lookup_hybrid(MemoryQuery(
        query_task_id="task-current",
        query_spec_hash="sha256:query-spec",
        query_text="revenue exact result",
        tags=("finance",),
        query_embedding=encoder.encode(
            embedding_id="embedding-query",
            text="revenue exact result",
        ),
        limit=3,
        allow_assist=False,
        allow_validated_replay=True,
        allow_exact_replay=True,
        compatibility_signature="runtime-current",
        output_contract_version="output-v1",
    ))

    assert result.candidate_pool is not None
    assert result.candidate_pool.candidate_memory_ids[0] == "incompatible-high-rank"
    assert [match.memory_ref.memory_id for match in result.matches] == ["compatible-replay"]
    assert result.matches[0].replay_class == ReplayClass.EXACT_REPLAY
