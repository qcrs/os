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
