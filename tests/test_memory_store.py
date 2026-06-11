from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

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

        signature_miss = store.search(
            MemoryQuery(
                task_theme="repo_local_latency_triage",
                query_text="latency database saturation",
                top_k=3,
                min_confidence=0.8,
                encoder_id=store.embedder.encoder_id,
                required_metadata={"reuse_signature": "repo_local_latency_triage:cache|invalidation"},
            )
        )
        assert not signature_miss
        store.close()


def test_memory_store_supports_memory_purpose_layers() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-") as tmpdir:
        db_path = Path(tmpdir) / "memory.sqlite3"
        store = MemoryStore(db_path, embedder=DeterministicEmbeddingProvider())
        store.init_schema()
        common_refs = [
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
        ]
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-1-assist",
                source_agent_id="summarizer",
                source_task_id="task-1",
                task_theme="repo_local_latency_triage",
                summary="Assist summary for latency regression.",
                tags=["latency", "database"],
                evidence_state_ids=[ref.state_id for ref in common_refs],
                reusable_steps=["retrieve"],
                confidence=0.9,
                embedding_text="latency regression assist summary",
                embedding_state_id="state-embedding-1",
                metadata={"memory_purpose": "assist", "memory_layer": "summary"},
                evidence_state_refs=common_refs,
            )
        )
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-1-replay",
                source_agent_id="summarizer",
                source_task_id="task-1",
                task_theme="repo_local_latency_triage",
                summary="Replay summary for latency regression.",
                tags=["latency", "database"],
                evidence_state_ids=[*([ref.state_id for ref in common_refs]), "state-artifact-1"],
                reusable_steps=["retrieve", "execute"],
                confidence=0.9,
                embedding_text="latency regression replay summary",
                embedding_state_id="state-embedding-1",
                metadata={"memory_purpose": "replay", "memory_layer": "episode"},
                evidence_state_refs=[
                    *common_refs,
                    StateRef(
                        state_id="state-artifact-1",
                        kind="TOOL_ARTIFACT",
                        storage="MMAP_FILE",
                        handle="/tmp/state-artifact-1.bin",
                        length=32,
                        metadata={"tool_name": "tool.db_pool_triage"},
                    ),
                ],
            )
        )

        assist_hits = store.search(
            MemoryQuery(
                task_theme="repo_local_latency_triage",
                query_text="latency regression",
                top_k=3,
                encoder_id=store.embedder.encoder_id,
                required_metadata={"memory_purpose": "assist"},
            )
        )
        assert assist_hits
        assert all(hit.metadata.get("memory_purpose") == "assist" for hit in assist_hits)
        assert assist_hits[0].memory_id == "mem-1-assist"

        replay_hits = store.replay_candidates(
            task_theme="repo_local_latency_triage",
            encoder_id=store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        assert replay_hits
        assert all(hit.metadata.get("memory_purpose") == "replay" for hit in replay_hits)
        assert replay_hits[0].memory_id == "mem-1-replay"
        assert replay_hits[0].replay_class == ""
        store.close()


def test_memory_store_replay_episode_v2_fields_roundtrip() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-") as tmpdir:
        db_path = Path(tmpdir) / "memory.sqlite3"
        store = MemoryStore(db_path, embedder=DeterministicEmbeddingProvider())
        store.init_schema()
        refs = [
            StateRef(
                state_id="state-feature-1",
                kind="FEATURE_BUNDLE",
                storage="CAS_BLOB",
                handle="/tmp/blob-a",
                length=64,
                checksum="a" * 64,
                metadata={"channel_name": "features"},
            )
        ]
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-replay-v2",
                source_agent_id="summarizer",
                source_task_id="task-replay-v2",
                task_theme="repo_local_latency_triage",
                summary="Validated replay episode.",
                tags=["latency"],
                evidence_state_ids=["state-feature-1"],
                reusable_steps=["retrieve", "execute"],
                confidence=0.95,
                embedding_text="validated replay latency route",
                metadata={"memory_purpose": "replay", "memory_layer": "episode"},
                evidence_state_refs=refs,
                memory_purpose="replay",
                memory_layer="episode",
                replay_class="validated",
                route="db_pool_saturation",
                route_source="hint_consensus",
                route_provenance=["corpus_metadata", "lexical"],
                route_confidence=0.92,
                retrieved_doc_ids=["doc-1", "doc-2"],
                fresh_evidence_sha256="b" * 64,
                reuse_signature="repo_local_latency_triage:latency",
                step_output_state_ids=["state-feature-1"],
                step_output_state_refs=refs,
                tool_name="tool.db_pool_triage",
                source_session_id="session-v2",
            )
        )
        hits = store.replay_candidates(
            task_theme="repo_local_latency_triage",
            encoder_id=store.embedder.encoder_id,
            required_metadata={"memory_purpose": "replay"},
        )
        assert hits
        hit = hits[0]
        assert hit.memory_id == "mem-replay-v2"
        assert hit.replay_class == "validated"
        assert hit.route == "db_pool_saturation"
        assert hit.route_source == "hint_consensus"
        assert hit.route_provenance == ["corpus_metadata", "lexical"]
        assert hit.retrieved_doc_ids == ["doc-1", "doc-2"]
        assert hit.fresh_evidence_sha256 == "b" * 64
        assert hit.reuse_signature == "repo_local_latency_triage:latency"
        assert hit.tool_name == "tool.db_pool_triage"
        assert hit.source_session_id == "session-v2"
        assert len(hit.step_output_state_refs) == 1
        assert hit.step_output_state_refs[0].metadata["channel_name"] == "features"
        store.close()


def test_memory_store_exposes_combined_score_and_session_tier(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_MEM_WORKING_TIER", "2.0")
    with tempfile.TemporaryDirectory(prefix="statebus-memory-") as tmpdir:
        db_path = Path(tmpdir) / "memory.sqlite3"
        store = MemoryStore(db_path, embedder=DeterministicEmbeddingProvider())
        store.init_schema()
        created_at_ns = 1_700_000_000_000_000_000
        common_payload = {
            "source_agent_id": "summarizer",
            "source_task_id": "task-shared",
            "task_theme": "repo_local_latency_triage",
            "summary": "Database pool saturation after release-17 rollout.",
            "tags": ["latency", "database"],
            "evidence_state_ids": ["state-1"],
            "reusable_steps": ["retrieve"],
            "confidence": 0.9,
            "embedding_text": "database saturation release-17 latency",
            "created_at_ns": created_at_ns,
            "evidence_state_refs": [
                StateRef(
                    state_id="state-evidence-1",
                    kind="DENSE_EVIDENCE",
                    storage="MMAP_FILE",
                    handle="/tmp/state-evidence-1.bin",
                    length=16,
                    metadata={"task": "task-shared"},
                )
            ],
        }
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-session-a",
                metadata={"memory_purpose": "assist", "session_id": "session-a"},
                **common_payload,
            )
        )
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-session-b",
                metadata={"memory_purpose": "assist", "session_id": "session-b"},
                **common_payload,
            )
        )

        hits = store.search(
            MemoryQuery(
                task_theme="repo_local_latency_triage",
                query_text="latency database saturation",
                top_k=2,
                encoder_id=store.embedder.encoder_id,
                required_metadata={"memory_purpose": "assist"},
                session_id="session-a",
            )
        )

        assert [hit.memory_id for hit in hits] == ["mem-session-a", "mem-session-b"]
        assert hits[0].faiss_score == pytest.approx(hits[1].faiss_score)
        assert hits[0].combined_score > hits[0].faiss_score
        assert hits[0].combined_score > hits[1].combined_score
        store.close()


def test_memory_store_keyword_fallback_can_match_embedding_text() -> None:
    with tempfile.TemporaryDirectory(prefix="statebus-memory-") as tmpdir:
        db_path = Path(tmpdir) / "memory.sqlite3"
        store = MemoryStore(db_path, embedder=DeterministicEmbeddingProvider())
        store.init_schema()
        store.commit_memory(
            MemoryCommit(
                memory_id="mem-embedding-keyword",
                source_agent_id="summarizer",
                source_task_id="task-keyword",
                task_theme="repo_local_cache_staleness",
                summary="Generic cache incident summary.",
                tags=["cache"],
                evidence_state_ids=["state-1"],
                reusable_steps=["retrieve"],
                confidence=0.9,
                embedding_text=(
                    "route: cache_replica_stale_read\n"
                    "tool_name: tool.replica_stale_read_triage\n"
                    "retrieved_doc_ids: cache-invalid-anchor"
                ),
                metadata={"memory_purpose": "assist"},
                evidence_state_refs=[
                    StateRef(
                        state_id="state-evidence-1",
                        kind="DENSE_EVIDENCE",
                        storage="MMAP_FILE",
                        handle="/tmp/state-evidence-1.bin",
                        length=16,
                        metadata={"task": "task-keyword"},
                    )
                ],
            )
        )
        store._fts_enabled = False
        store._search_semantic = lambda query, query_vector, encoder_id: []  # type: ignore[method-assign]

        hits = store.search(
            MemoryQuery(
                task_theme="repo_local_cache_staleness",
                query_text="cache_replica_stale_read",
                top_k=3,
                encoder_id=store.embedder.encoder_id,
                required_metadata={"memory_purpose": "assist"},
            )
        )

        assert hits
        assert hits[0].memory_id == "mem-embedding-keyword"
        assert hits[0].reuse_source == "keyword_memory"
        store.close()


def test_resolve_embed_device_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("STATEBUS_EMBED_DEVICE", "cuda:0")
    assert resolve_embed_device() == "cuda:0"
    assert resolve_embed_device("cpu") == "cpu"
