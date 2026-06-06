from __future__ import annotations

import tempfile
from pathlib import Path

from memory.store import DeterministicEmbeddingProvider, MemoryStore, resolve_embed_device
from protocol.messages import MemoryCommit, MemoryQuery, StateRef


def test_memory_store_schema_and_filters() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-") as tmpdir:
        db_path = Path(tmpdir) / "memory.sqlite3"
        store = MemoryStore(db_path, embedder=DeterministicEmbeddingProvider())
        store.init_schema()
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-1",
                source_agent_id="summarizer",
                source_task_id="task-1",
                task_theme="repo_local_latency_triage",
                summary="Database pool saturation after release-17 rollout.",
                tags=["latency", "database"],
                evidence_state_ids=["state-1"],
                reusable_steps=["retrieve", "execute"],
                confidence=0.9,
                embedding_text="database saturation release-17 latency",
                embedding_state_id="state-embedding-1",
                metadata={"source_agent_id": "summarizer"},
                evidence_state_refs=[
                    StateRef(
                        state_id="state-evidence-1",
                        kind="DENSE_EVIDENCE",
                        storage="MMAP_FILE",
                        handle="/tmp/state-evidence-1.bin",
                        length=16,
                        metadata={"task": "task-1"},
                    ),
                    StateRef(
                        state_id="state-embedding-1",
                        kind="EMBEDDING",
                        storage="MMAP_FILE",
                        handle="/tmp/state-embedding-1.bin",
                        length=128,
                        metadata={
                            "encoder_id": "deterministic-v1",
                            "vector_dim": 32,
                            "dtype": "float32",
                        },
                    ),
                ],
            )
        )
        rows = store.list_memories()
        assert rows[0]["status"] == "active"
        assert rows[0]["faiss_status"] == "active"
        assert rows[0]["embedding_state_id"] == "state-embedding-1"

        hits = store.search(
            MemoryQuery(
                task_theme="repo_local_latency_triage",
                query_text="latency database saturation",
                top_k=3,
                tags_all=["latency"],
                min_confidence=0.8,
                encoder_id=store.embedder.encoder_id,
            )
        )
        assert hits
        assert hits[0].memory_id == "mem-1"
        assert hits[0].embedding_id is not None
        assert hits[0].reuse_source == "semantic_memory"
        assert len(hits[0].evidence_state_refs) == 2
        assert hits[0].evidence_state_refs[1].kind == "EMBEDDING"

        no_hits = store.search(
            MemoryQuery(
                task_theme="repo_local_latency_triage",
                query_text="latency database saturation",
                top_k=3,
                min_confidence=0.95,
                encoder_id=store.embedder.encoder_id,
            )
        )
        assert not no_hits
        store.close()


def test_resolve_embed_device_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_EMBED_DEVICE", "cuda:0")
    assert resolve_embed_device() == "cuda:0"
    assert resolve_embed_device("cpu") == "cpu"
