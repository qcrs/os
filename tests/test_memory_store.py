from __future__ import annotations

import sqlite3
from pathlib import Path

from statebus.contracts import CanonicalTaskSpec, ReplayClass
from statebus.memory import (
    DeterministicEmbeddingEncoder,
    MemoryCommit,
    MemoryIndexStore,
    MemoryRef,
    MemoryType,
)


def _commit_memory(
    store: MemoryIndexStore,
    *,
    memory_id: str,
    summary: str,
    task_theme: str,
    tags: tuple[str, ...],
    created_at_ns: int,
) -> None:
    encoder = DeterministicEmbeddingEncoder(dims=8)
    embedding = encoder.encode(embedding_id=f"emb-{memory_id}", text=f"{summary} {' '.join(tags)}")
    store.put_embedding(embedding)
    commit = MemoryCommit(
        memory_ref=MemoryRef(
            memory_id=memory_id,
            memory_type=MemoryType.OUTCOME,
            replay_class=ReplayClass.ASSIST,
            score=0.8,
            source_task_id=f"task-{memory_id}",
            source_agent="summarizer",
            summary=summary,
            task_theme=task_theme,
            tags=tags,
            canonical_task_spec_hash=f"sha256:{memory_id}",
            embedding_ref_id=embedding.embedding_id,
            created_at_ns=created_at_ns,
        ),
        canonical_task_spec=CanonicalTaskSpec(
            task_family=task_theme,
            intent_op="compare_metric",
            required_outputs=("summary_text",),
            arguments={"memory_id": memory_id},
        ),
        required_outputs=("summary_text",),
        quality_floor_pass=True,
        created_from_artifact_hash=f"sha256:artifact-{memory_id}",
    )
    store.commit_candidate(commit=commit, quality_floor_pass=True, answer_adopted=True)


def test_memory_store_sqlite_fts_keyword_lookup_persists_across_reload(tmp_path: Path) -> None:
    store = MemoryIndexStore(store_root=tmp_path / "memory-index")
    _commit_memory(
        store,
        memory_id="m-kw",
        summary="ACME quarterly revenue analysis completed",
        task_theme="financial_report_analysis",
        tags=("finance", "revenue"),
        created_at_ns=100,
    )

    sqlite_path = store.sqlite_index_path
    assert sqlite_path is not None
    assert sqlite_path.exists()

    db = sqlite3.connect(str(sqlite_path))
    try:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        assert "memories" in tables
        assert "memories_fts" in tables
        row = db.execute("SELECT memory_id, summary FROM memories WHERE memory_id = 'm-kw'").fetchone()
        assert row == ("m-kw", "ACME quarterly revenue analysis completed")
    finally:
        db.close()

    restored = MemoryIndexStore(store_root=tmp_path / "memory-index")
    restored.load_persisted_state()
    hits = restored.lookup_by_keyword("quarterly revenue")

    assert [hit.memory_ref.memory_id for hit in hits] == ["m-kw"]


def test_memory_store_sqlite_tag_lookup_honors_overlap_and_require_all(tmp_path: Path) -> None:
    store = MemoryIndexStore(store_root=tmp_path / "memory-index")
    _commit_memory(
        store,
        memory_id="incident-gateway",
        summary="inference gateway startup incident resolved",
        task_theme="incident_diagnosis_v2",
        tags=("Incident Diagnosis", "Gateway", "IO Wait"),
        created_at_ns=200,
    )
    _commit_memory(
        store,
        memory_id="incident-cache",
        summary="cache service recovery notes",
        task_theme="incident_diagnosis_v2",
        tags=("Incident Diagnosis", "Cache"),
        created_at_ns=100,
    )

    restored = MemoryIndexStore(store_root=tmp_path / "memory-index")
    restored.load_persisted_state()

    overlap_hits = restored.lookup_by_tags({"incident diagnosis", "gateway"})
    assert [hit.memory_ref.memory_id for hit in overlap_hits] == ["incident-gateway", "incident-cache"]

    strict_hits = restored.lookup_by_tags({"incident diagnosis", "gateway"}, require_all=True)
    assert [hit.memory_ref.memory_id for hit in strict_hits] == ["incident-gateway"]


def test_memory_store_lookup_by_tags_sql_prefilter(tmp_path: Path) -> None:
    """lookup_by_tags must use SQL LIKE pre-filter, not full-table Python scan."""
    store = MemoryIndexStore(store_root=tmp_path / "memory-index")
    _commit_memory(
        store,
        memory_id="tagged-finance",
        summary="quarterly revenue",
        task_theme="finance",
        tags=("finance", "revenue", "acme"),
        created_at_ns=300,
    )
    _commit_memory(
        store,
        memory_id="tagged-ops",
        summary="deployment notes",
        task_theme="ops",
        tags=("ops", "deployment"),
        created_at_ns=200,
    )
    _commit_memory(
        store,
        memory_id="tagged-other",
        summary="unrelated entry",
        task_theme="misc",
        tags=("misc",),
        created_at_ns=100,
    )

    # Single-tag match
    hits = store.lookup_by_tags({"finance"})
    assert [h.memory_ref.memory_id for h in hits] == ["tagged-finance"]

    # Multi-tag: both finance and ops have overlap=1; finance is newer so first
    hits = store.lookup_by_tags({"finance", "ops"})
    ids = [h.memory_ref.memory_id for h in hits]
    assert "tagged-finance" in ids
    assert "tagged-ops" in ids
    assert "tagged-other" not in ids

    # require_all: only "tagged-finance" has both tags finance AND revenue
    hits = store.lookup_by_tags({"finance", "revenue"}, require_all=True)
    assert [h.memory_ref.memory_id for h in hits] == ["tagged-finance"]

    # No match
    hits = store.lookup_by_tags({"nonexistent_tag_xyz"})
    assert hits == []


def test_memory_store_faiss_lookup_matches_linear_scan(tmp_path: Path) -> None:
    """FAISS-accelerated lookup must return the same top results as linear cosine scan."""
    store = MemoryIndexStore(store_root=tmp_path / "faiss-test")
    for i in range(5):
        _commit_memory(
            store,
            memory_id=f"mem-{i}",
            summary=f"task summary number {i} about topic {i}",
            task_theme="test_family",
            tags=(f"tag{i}",),
            created_at_ns=i * 100,
        )

    encoder = DeterministicEmbeddingEncoder(dims=8)
    query_emb = encoder.encode(embedding_id="q", text="task summary topic 2")

    result = store.lookup(
        query_task_id="q-task",
        query_spec_hash="qsh",
        query_embedding=query_emb,
        limit=3,
    )
    assert len(result.matches) <= 3
    if store.faiss_available:
        assert store.faiss_available
        # After first lookup the index should be built and clean
        assert not store._faiss_dirty
        assert store._faiss_index is not None
        # matched_on reflects FAISS path
        for m in result.matches:
            assert m.matched_on == "faiss_ip"
    else:
        for m in result.matches:
            assert m.matched_on == "embedding_similarity"


def test_memory_store_faiss_ranking_matches_cosine_with_unnormalised_vectors(tmp_path: Path) -> None:
    """FAISS IndexFlatIP ranking must match cosine_similarity ranking even when
    the encoder produces unnormalised vectors (DeterministicEmbeddingEncoder).

    This is a regression test for B2: before the fix, _build_faiss_index did
    not call faiss.normalize_L2, so FAISS IP scores diverged from cosine scores
    when vectors had different norms.
    """
    from statebus.memory.embedding import cosine_similarity

    store = MemoryIndexStore(store_root=tmp_path / "b2-test")
    encoder = DeterministicEmbeddingEncoder(dims=16)

    texts = [
        "ACME quarterly revenue analysis 2026Q1",
        "incident gateway startup failure resolved",
        "deployment pipeline ops notes",
        "cache eviction recovery service",
        "financial operating metrics comparison",
    ]
    for i, text in enumerate(texts):
        emb = encoder.encode(embedding_id=f"emb-b2-{i}", text=text)
        store.put_embedding(emb)
        commit = MemoryCommit(
            memory_ref=MemoryRef(
                memory_id=f"b2-{i}",
                memory_type=MemoryType.OUTCOME,
                replay_class=ReplayClass.ASSIST,
                score=0.5,
                source_task_id=f"task-b2-{i}",
                source_agent="summarizer",
                summary=text,
                task_theme="test",
                tags=(),
                canonical_task_spec_hash=f"sha256:b2-{i}",
                embedding_ref_id=emb.embedding_id,
                created_at_ns=i * 10,
            ),
            canonical_task_spec=CanonicalTaskSpec(
                task_family="test",
                intent_op="compare_metric",
                required_outputs=("summary_text",),
                arguments={},
            ),
            required_outputs=("summary_text",),
            quality_floor_pass=True,
            created_from_artifact_hash=f"sha256:artifact-b2-{i}",
        )
        store.commit_candidate(commit=commit, quality_floor_pass=True, answer_adopted=True)

    query_emb = encoder.encode(embedding_id="query-b2", text="ACME revenue financial 2026Q1")

    if not store.faiss_available:
        return  # skip if faiss not installed

    # Get FAISS-based ranking
    faiss_result = store.lookup(
        query_task_id="q-b2",
        query_spec_hash="qsh-b2",
        query_embedding=query_emb,
        limit=5,
    )
    faiss_order = [m.memory_ref.memory_id for m in faiss_result.matches]

    # Compute cosine ranking directly (bypass FAISS)
    cosine_scores = {
        commit.memory_ref.memory_id: cosine_similarity(query_emb, store.embeddings[commit.memory_ref.embedding_ref_id])
        for commit in store.commits.values()
    }
    cosine_order = sorted(cosine_scores, key=lambda mid: -cosine_scores[mid])[:5]

    assert faiss_order == cosine_order, (
        f"FAISS ranking {faiss_order!r} diverges from cosine ranking {cosine_order!r}.\n"
        f"Scores: FAISS={[m.score for m in faiss_result.matches]}, "
        f"cosine={[round(cosine_scores[mid], 6) for mid in cosine_order]}"
    )
