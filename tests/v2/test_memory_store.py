from __future__ import annotations

import sqlite3
from pathlib import Path

from v2.contracts import CanonicalTaskSpec, ReplayClass
from v2.memory import (
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
