from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import numpy as np
try:
    import faiss  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - exercised in host envs without faiss
    faiss = None

from protocol.messages import MemoryCommit, MemoryHit, MemoryQuery, StateRef


DEFAULT_EMBEDDING_MODEL_PATH = Path("/home/qcrs/statebus/models/Qwen3-Embedding-0.6B")
DEFAULT_EMBED_DEVICE = "auto"


class EmbeddingProvider(Protocol):
    @property
    def encoder_id(self) -> str: ...

    @property
    def vector_dim(self) -> int: ...

    def embed_text(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbeddingProvider:
    def __init__(
        self,
        model_path: str | Path = DEFAULT_EMBEDDING_MODEL_PATH,
        *,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"embedding model not found: {self.model_path}")
        from sentence_transformers import SentenceTransformer

        self.device = resolve_embed_device(device)
        self._model = SentenceTransformer(str(self.model_path), device=self.device)
        self._vector_dim: int | None = None

    @property
    def encoder_id(self) -> str:
        return f"sentence-transformers:{self.model_path.name}"

    @property
    def vector_dim(self) -> int:
        if self._vector_dim is None:
            self._vector_dim = int(self.embed_text("statebus warmup").shape[0])
        return self._vector_dim

    def embed_text(self, text: str) -> np.ndarray:
        vector = self._model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        vector = np.asarray(vector, dtype="float32")
        if vector.ndim != 1:
            raise ValueError(f"expected 1D embedding vector, got shape={vector.shape}")
        return vector


def resolve_embed_device(device: str | None = None) -> str:
    candidate = (device or os.getenv("STATEBUS_EMBED_DEVICE") or DEFAULT_EMBED_DEVICE).strip()
    if not candidate or candidate.lower() == DEFAULT_EMBED_DEVICE:
        return "cuda:0" if _torch_cuda_available() else "cpu"
    return candidate


def _torch_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


class DeterministicEmbeddingProvider:
    def __init__(self, *, encoder_id: str = "deterministic-v1", vector_dim: int = 32) -> None:
        self._encoder_id = encoder_id
        self._vector_dim = vector_dim

    @property
    def encoder_id(self) -> str:
        return self._encoder_id

    @property
    def vector_dim(self) -> int:
        return self._vector_dim

    def embed_text(self, text: str) -> np.ndarray:
        buckets = np.zeros(self._vector_dim, dtype="float32")
        for token in text.lower().split():
            digest = token.encode("utf-8")
            for idx, byte in enumerate(digest):
                buckets[(byte + idx) % self._vector_dim] += 1.0
        norm = float(np.linalg.norm(buckets)) or 1.0
        return buckets / norm


class _NumpyVectorIndex:
    def __init__(self, vector_dim: int) -> None:
        self.vector_dim = vector_dim
        self._vectors: dict[int, np.ndarray] = {}

    @property
    def ntotal(self) -> int:
        return len(self._vectors)

    def add_with_ids(self, vectors: np.ndarray, ids: np.ndarray) -> None:
        normalized_vectors = np.asarray(vectors, dtype="float32")
        normalized_ids = np.asarray(ids, dtype="int64")
        for vector, embedding_id in zip(normalized_vectors, normalized_ids, strict=False):
            if vector.shape != (self.vector_dim,):
                raise ValueError(
                    f"embedding dim mismatch for {int(embedding_id)}:"
                    f" {vector.shape} != {(self.vector_dim,)}"
                )
            self._vectors[int(embedding_id)] = np.asarray(vector, dtype="float32")

    def remove_ids(self, ids: np.ndarray) -> None:
        normalized_ids = np.asarray(ids, dtype="int64")
        for embedding_id in normalized_ids:
            self._vectors.pop(int(embedding_id), None)

    def search(self, vectors: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
        queries = np.asarray(vectors, dtype="float32")
        if not self._vectors:
            return (
                np.zeros((queries.shape[0], top_k), dtype="float32"),
                -np.ones((queries.shape[0], top_k), dtype="int64"),
            )
        ids = np.asarray(sorted(self._vectors), dtype="int64")
        matrix = np.asarray([self._vectors[int(embedding_id)] for embedding_id in ids], dtype="float32")
        scores = queries @ matrix.T
        top_scores = np.zeros((queries.shape[0], top_k), dtype="float32")
        top_ids = -np.ones((queries.shape[0], top_k), dtype="int64")
        for row_index in range(queries.shape[0]):
            ordering = np.argsort(scores[row_index])[::-1][:top_k]
            limit = len(ordering)
            if limit == 0:
                continue
            top_scores[row_index, :limit] = scores[row_index, ordering]
            top_ids[row_index, :limit] = ids[ordering]
        return top_scores, top_ids


def _build_vector_index(vector_dim: int) -> object:
    if faiss is not None:
        return faiss.IndexIDMap2(faiss.IndexFlatIP(vector_dim))
    return _NumpyVectorIndex(vector_dim)


class MemoryStore:
    """SQLite metadata + FAISS retrieval store for host-side StateBus memory."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        embedder: EmbeddingProvider | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._fts_enabled = False
        self.embedder = embedder or SentenceTransformerEmbeddingProvider()
        self._index = _build_vector_index(self.embedder.vector_dim)
        self._index_vectors: dict[int, np.ndarray] = {}

    def init_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_id TEXT NOT NULL UNIQUE,
                source_agent_id TEXT NOT NULL,
                source_task_id TEXT NOT NULL,
                task_theme TEXT NOT NULL,
                summary TEXT NOT NULL,
                tags_json TEXT NOT NULL,
                evidence_state_ids_json TEXT NOT NULL,
                reusable_steps_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS memory_embeddings (
                embedding_id INTEGER PRIMARY KEY,
                memory_id TEXT NOT NULL UNIQUE,
                encoder_id TEXT NOT NULL,
                vector_dim INTEGER NOT NULL,
                embedding_text TEXT NOT NULL,
                embedding_state_id TEXT,
                state_ref_json TEXT,
                faiss_status TEXT NOT NULL,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL,
                FOREIGN KEY(memory_id) REFERENCES memories(memory_id)
            );

            CREATE TABLE IF NOT EXISTS faiss_outbox (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                embedding_id INTEGER NOT NULL,
                op TEXT NOT NULL,
                vector_json TEXT NOT NULL,
                status TEXT NOT NULL,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at_ns INTEGER NOT NULL,
                updated_at_ns INTEGER NOT NULL,
                FOREIGN KEY(embedding_id) REFERENCES memories(embedding_id)
            );
            """
        )
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(memory_id, task_theme, summary, tags)
                """
            )
            self._fts_enabled = True
        except sqlite3.OperationalError:
            self._fts_enabled = False
        self.conn.commit()
        self.rebuild_index()

    def commit_memory(self, commit: MemoryCommit) -> None:
        created_at_ns = commit.created_at_ns or time.time_ns()
        updated_at_ns = created_at_ns
        embedding_text = (commit.embedding_text or commit.summary).strip()
        if not embedding_text:
            raise ValueError(f"memory {commit.memory_id} missing embedding_text and summary")
        encoder_id = commit.encoder_id or self.embedder.encoder_id
        vector = self._embed_commit_text(embedding_text, encoder_id)
        vector_json = json.dumps(vector.tolist(), ensure_ascii=True)
        metadata_json = json.dumps(commit.metadata, ensure_ascii=True, sort_keys=True)
        evidence_state_ids_json = json.dumps(
            commit.evidence_state_ids,
            ensure_ascii=True,
            sort_keys=True,
        )
        reusable_steps_json = json.dumps(
            commit.reusable_steps,
            ensure_ascii=True,
            sort_keys=True,
        )
        state_ref_json = json.dumps(
            [asdict(ref) for ref in commit.evidence_state_refs],
            ensure_ascii=True,
            sort_keys=True,
        )
        tags_json = json.dumps(commit.tags, ensure_ascii=True, sort_keys=True)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO memories (
                    embedding_id,
                    memory_id,
                    source_agent_id,
                    source_task_id,
                    task_theme,
                    summary,
                    tags_json,
                    evidence_state_ids_json,
                    reusable_steps_json,
                    confidence,
                    status,
                    metadata_json,
                    created_at_ns,
                    updated_at_ns
                )
                VALUES (
                    COALESCE((SELECT embedding_id FROM memories WHERE memory_id = ?), NULL),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    commit.memory_id,
                    commit.memory_id,
                    commit.source_agent_id,
                    commit.source_task_id,
                    commit.task_theme,
                    commit.summary,
                    tags_json,
                    evidence_state_ids_json,
                    reusable_steps_json,
                    float(commit.confidence),
                    "pending",
                    metadata_json,
                    created_at_ns,
                    updated_at_ns,
                ),
            )
            embedding_row = self.conn.execute(
                "SELECT embedding_id FROM memories WHERE memory_id = ?",
                (commit.memory_id,),
            ).fetchone()
            if embedding_row is None:
                raise RuntimeError(f"failed to resolve embedding_id for {commit.memory_id}")
            embedding_id = int(embedding_row["embedding_id"])
            self.conn.execute(
                """
                INSERT OR REPLACE INTO memory_embeddings (
                    embedding_id,
                    memory_id,
                    encoder_id,
                    vector_dim,
                    embedding_text,
                    embedding_state_id,
                    state_ref_json,
                    faiss_status,
                    created_at_ns,
                    updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    embedding_id,
                    commit.memory_id,
                    encoder_id,
                    int(vector.shape[0]),
                    embedding_text,
                    commit.embedding_state_id,
                    state_ref_json,
                    "pending",
                    created_at_ns,
                    updated_at_ns,
                ),
            )
            self.conn.execute(
                """
                INSERT INTO faiss_outbox (
                    embedding_id,
                    op,
                    vector_json,
                    status,
                    retry_count,
                    created_at_ns,
                    updated_at_ns
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    embedding_id,
                    "ADD",
                    vector_json,
                    "pending",
                    0,
                    created_at_ns,
                    updated_at_ns,
                ),
            )
            if self._fts_enabled:
                self.conn.execute(
                    """
                    INSERT OR REPLACE INTO memories_fts (
                        rowid,
                        memory_id,
                        task_theme,
                        summary,
                        tags
                    ) VALUES (
                        (SELECT embedding_id FROM memories WHERE memory_id = ?),
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        commit.memory_id,
                        commit.memory_id,
                        commit.task_theme,
                        commit.summary,
                        " ".join(commit.tags),
                    ),
                )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self._flush_outbox()

    def search(self, query: MemoryQuery) -> list[MemoryHit]:
        encoder_id = query.encoder_id or self.embedder.encoder_id
        query_vector = self._embed_query_text(query.query_text, encoder_id)
        candidate_hits = self._search_semantic(query, query_vector, encoder_id)
        if candidate_hits:
            return candidate_hits
        return self._search_keyword(query)

    def replay_candidates(
        self,
        *,
        task_theme: str,
        encoder_id: str | None = None,
        required_metadata: dict[str, object] | None = None,
    ) -> list[MemoryHit]:
        rows = self.conn.execute(
            """
            SELECT m.embedding_id, m.memory_id, m.source_task_id, m.task_theme,
                   m.source_agent_id, m.summary, m.tags_json, m.evidence_state_ids_json,
                   m.reusable_steps_json, m.confidence, m.metadata_json, m.created_at_ns,
                   me.state_ref_json
            FROM memories m
            JOIN memory_embeddings me USING(embedding_id)
            WHERE m.task_theme = ?
              AND m.status = 'active'
              AND me.faiss_status = 'active'
              AND me.encoder_id = ?
            ORDER BY m.created_at_ns DESC
            """,
            (task_theme, encoder_id or self.embedder.encoder_id),
        ).fetchall()
        hits: list[MemoryHit] = []
        for row in rows:
            metadata = json.loads(row["metadata_json"])
            if not _metadata_matches(metadata, required_metadata or {}):
                continue
            hits.append(
                MemoryHit(
                    memory_id=row["memory_id"],
                    embedding_id=int(row["embedding_id"]),
                    confidence=float(row["confidence"]),
                    reuse_source="replay_memory",
                    reusable_steps=json.loads(row["reusable_steps_json"]),
                    evidence_state_ids=json.loads(row["evidence_state_ids_json"]),
                    evidence_state_refs=_state_refs_from_json(row["state_ref_json"]),
                    summary=row["summary"],
                    tags=json.loads(row["tags_json"]),
                    task_theme=row["task_theme"],
                    created_at_ns=int(row["created_at_ns"]),
                    source_task_id=row["source_task_id"],
                    metadata=metadata,
                )
            )
        return hits

    def list_memories(self) -> list[dict[str, object]]:
        rows = self.conn.execute(
            """
            SELECT m.embedding_id, m.memory_id, m.source_agent_id, m.source_task_id,
                   m.task_theme, m.summary, m.tags_json, m.evidence_state_ids_json,
                   m.reusable_steps_json, m.confidence, m.status, m.metadata_json,
                   me.encoder_id, me.vector_dim, me.embedding_text, me.embedding_state_id,
                   me.faiss_status, m.created_at_ns, m.updated_at_ns
            FROM memories m
            JOIN memory_embeddings me USING(embedding_id)
            ORDER BY m.created_at_ns ASC
            """
        ).fetchall()
        return [
            {
                "embedding_id": int(row["embedding_id"]),
                "memory_id": row["memory_id"],
                "source_agent_id": row["source_agent_id"],
                "source_task_id": row["source_task_id"],
                "task_theme": row["task_theme"],
                "summary": row["summary"],
                "tags": json.loads(row["tags_json"]),
                "evidence_state_ids": json.loads(row["evidence_state_ids_json"]),
                "reusable_steps": json.loads(row["reusable_steps_json"]),
                "confidence": float(row["confidence"]),
                "status": row["status"],
                "metadata": json.loads(row["metadata_json"]),
                "encoder_id": row["encoder_id"],
                "vector_dim": int(row["vector_dim"]),
                "embedding_text": row["embedding_text"],
                "embedding_state_id": row["embedding_state_id"],
                "faiss_status": row["faiss_status"],
                "created_at_ns": int(row["created_at_ns"]),
                "updated_at_ns": int(row["updated_at_ns"]),
            }
            for row in rows
        ]

    def rebuild_index(self) -> None:
        self._index = _build_vector_index(self.embedder.vector_dim)
        self._index_vectors = {}
        rows = self.conn.execute(
            """
            SELECT m.embedding_id, outbox.vector_json
            FROM faiss_outbox outbox
            JOIN (
                SELECT embedding_id, MAX(event_id) AS event_id
                FROM faiss_outbox
                WHERE status = 'done'
                GROUP BY embedding_id
            ) latest ON latest.event_id = outbox.event_id
            JOIN memory_embeddings me ON me.embedding_id = outbox.embedding_id
            JOIN memories m ON m.embedding_id = outbox.embedding_id
            WHERE me.encoder_id = ?
              AND me.faiss_status = 'active'
              AND m.status = 'active'
            ORDER BY m.embedding_id ASC
            """,
            (self.embedder.encoder_id,),
        ).fetchall()
        for row in rows:
            embedding_id = int(row["embedding_id"])
            vector = np.asarray(json.loads(row["vector_json"]), dtype="float32")
            self._add_to_index(embedding_id, vector)

    def close(self) -> None:
        self.conn.close()

    def _flush_outbox(self) -> None:
        rows = self.conn.execute(
            """
            SELECT event_id, embedding_id, vector_json, retry_count
            FROM faiss_outbox
            WHERE status = 'pending'
            ORDER BY event_id ASC
            """
        ).fetchall()
        for row in rows:
            event_id = int(row["event_id"])
            embedding_id = int(row["embedding_id"])
            retry_count = int(row["retry_count"])
            vector = np.asarray(json.loads(row["vector_json"]), dtype="float32")
            now_ns = time.time_ns()
            try:
                self._replace_index_vector(embedding_id, vector)
                self.conn.execute("BEGIN IMMEDIATE")
                self.conn.execute(
                    """
                    UPDATE memory_embeddings
                    SET faiss_status = 'active', updated_at_ns = ?
                    WHERE embedding_id = ?
                    """,
                    (now_ns, embedding_id),
                )
                self.conn.execute(
                    """
                    UPDATE memories
                    SET status = 'active', updated_at_ns = ?
                    WHERE embedding_id = ?
                    """,
                    (now_ns, embedding_id),
                )
                self.conn.execute(
                    """
                    UPDATE faiss_outbox
                    SET status = 'done', updated_at_ns = ?
                    WHERE event_id = ?
                    """,
                    (now_ns, event_id),
                )
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                self.conn.execute(
                    """
                    UPDATE faiss_outbox
                    SET retry_count = ?, updated_at_ns = ?
                    WHERE event_id = ?
                    """,
                    (retry_count + 1, now_ns, event_id),
                )
                self.conn.commit()
                raise

    def _search_semantic(
        self,
        query: MemoryQuery,
        query_vector: np.ndarray,
        encoder_id: str,
    ) -> list[MemoryHit]:
        if self._index.ntotal == 0:
            return []
        candidate_limit = min(
            int(self._index.ntotal),
            max(query.top_k, query.top_k * 8),
        )
        scores, ids = self._index.search(
            np.asarray([query_vector], dtype="float32"),
            candidate_limit,
        )
        ordered_hits: list[MemoryHit] = []
        for faiss_score, embedding_id in zip(scores[0], ids[0], strict=False):
            if embedding_id < 0:
                continue
            row = self.conn.execute(
                """
                SELECT m.embedding_id, m.memory_id, m.source_task_id, m.task_theme,
                       m.source_agent_id, m.summary, m.tags_json, m.evidence_state_ids_json,
                       m.reusable_steps_json, m.confidence, m.status, m.metadata_json,
                       m.created_at_ns, me.encoder_id, me.faiss_status, me.state_ref_json
                FROM memories m
                JOIN memory_embeddings me USING(embedding_id)
                WHERE m.embedding_id = ?
                """,
                (int(embedding_id),),
            ).fetchone()
            if row is None:
                continue
            if query.limit_active_only and (
                row["status"] != "active" or row["faiss_status"] != "active"
            ):
                continue
            if row["encoder_id"] != encoder_id:
                continue
            if row["task_theme"] != query.task_theme:
                continue
            confidence = float(row["confidence"])
            if confidence < query.min_confidence:
                continue
            if query.created_after_ns is not None and int(row["created_at_ns"]) < query.created_after_ns:
                continue
            tags = json.loads(row["tags_json"])
            if query.tags and not any(tag in tags for tag in query.tags):
                continue
            if query.tags_any and not any(tag in tags for tag in query.tags_any):
                continue
            if query.tags_all and not all(tag in tags for tag in query.tags_all):
                continue
            metadata = json.loads(row["metadata_json"])
            if query.source_agent_id and row["source_agent_id"] != query.source_agent_id:
                continue
            if not _metadata_matches(metadata, query.required_metadata):
                continue
            ordered_hits.append(
                MemoryHit(
                    memory_id=row["memory_id"],
                    embedding_id=int(row["embedding_id"]),
                    confidence=confidence,
                    faiss_score=float(faiss_score),
                    reuse_source="semantic_memory",
                    reusable_steps=json.loads(row["reusable_steps_json"]),
                    evidence_state_ids=json.loads(row["evidence_state_ids_json"]),
                    evidence_state_refs=_state_refs_from_json(row["state_ref_json"]),
                    summary=row["summary"],
                    tags=tags,
                    task_theme=row["task_theme"],
                    created_at_ns=int(row["created_at_ns"]),
                    source_task_id=row["source_task_id"],
                    metadata=metadata,
                )
            )
            if len(ordered_hits) >= query.top_k:
                break
        return ordered_hits

    def _search_keyword(self, query: MemoryQuery) -> list[MemoryHit]:
        rows = []
        if self._fts_enabled:
            try:
                rows = self.conn.execute(
                    """
                SELECT m.embedding_id, m.memory_id, m.source_task_id, m.task_theme,
                       m.source_agent_id, m.summary, m.tags_json, m.evidence_state_ids_json,
                       m.reusable_steps_json, m.confidence, m.metadata_json, m.created_at_ns,
                       me.state_ref_json
                FROM memories_fts f
                JOIN memories m ON m.embedding_id = f.rowid
                JOIN memory_embeddings me ON me.embedding_id = m.embedding_id
                    WHERE memories_fts MATCH ?
                      AND m.status = 'active'
                      AND me.faiss_status = 'active'
                      AND me.encoder_id = ?
                    LIMIT ?
                    """,
                    (
                        self._fts_query(query),
                        query.encoder_id or self.embedder.encoder_id,
                        query.top_k,
                    ),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
        if not rows:
            like_text = f"%{query.query_text.strip()}%"
            rows = self.conn.execute(
                """
                SELECT m.embedding_id, m.memory_id, m.source_task_id, m.task_theme,
                       m.source_agent_id, m.summary, m.tags_json, m.evidence_state_ids_json,
                       m.reusable_steps_json, m.confidence, m.metadata_json, m.created_at_ns,
                       me.state_ref_json
                FROM memories m
                JOIN memory_embeddings me USING(embedding_id)
                WHERE m.task_theme = ?
                  AND m.status = 'active'
                  AND me.faiss_status = 'active'
                  AND me.encoder_id = ?
                  AND (m.summary LIKE ? OR m.memory_id LIKE ? OR me.embedding_text LIKE ?)
                ORDER BY m.created_at_ns DESC
                LIMIT ?
                """,
                (
                    query.task_theme,
                    query.encoder_id or self.embedder.encoder_id,
                    like_text,
                    like_text,
                    like_text,
                    query.top_k,
                ),
            ).fetchall()
        hits: list[MemoryHit] = []
        for row in rows:
            confidence = float(row["confidence"])
            if confidence < query.min_confidence:
                continue
            if query.created_after_ns is not None and int(row["created_at_ns"]) < query.created_after_ns:
                continue
            tags = json.loads(row["tags_json"])
            if query.tags and not any(tag in tags for tag in query.tags):
                continue
            if query.tags_any and not any(tag in tags for tag in query.tags_any):
                continue
            if query.tags_all and not all(tag in tags for tag in query.tags_all):
                continue
            metadata = json.loads(row["metadata_json"])
            if query.source_agent_id and row["source_agent_id"] != query.source_agent_id:
                continue
            if not _metadata_matches(metadata, query.required_metadata):
                continue
            hits.append(
                MemoryHit(
                    memory_id=row["memory_id"],
                    embedding_id=int(row["embedding_id"]),
                    confidence=confidence,
                    reuse_source="keyword_memory",
                    reusable_steps=json.loads(row["reusable_steps_json"]),
                    evidence_state_ids=json.loads(row["evidence_state_ids_json"]),
                    evidence_state_refs=_state_refs_from_json(row["state_ref_json"]),
                    summary=row["summary"],
                    tags=tags,
                    task_theme=row["task_theme"],
                    created_at_ns=int(row["created_at_ns"]),
                    source_task_id=row["source_task_id"],
                    metadata=metadata,
                )
            )
        return hits

    def _replace_index_vector(self, embedding_id: int, vector: np.ndarray) -> None:
        existing = self._index_vectors.get(embedding_id)
        if existing is not None:
            self._index.remove_ids(np.asarray([embedding_id], dtype="int64"))
        self._add_to_index(embedding_id, vector)

    def _add_to_index(self, embedding_id: int, vector: np.ndarray) -> None:
        vector = np.asarray(vector, dtype="float32")
        if vector.shape[0] != self.embedder.vector_dim:
            raise ValueError(
                f"embedding dim mismatch for {embedding_id}: {vector.shape[0]} != {self.embedder.vector_dim}"
            )
        self._index.add_with_ids(
            np.asarray([vector], dtype="float32"),
            np.asarray([embedding_id], dtype="int64"),
        )
        self._index_vectors[embedding_id] = vector

    def _embed_commit_text(self, embedding_text: str, encoder_id: str) -> np.ndarray:
        if encoder_id != self.embedder.encoder_id:
            raise ValueError(
                f"unsupported encoder_id {encoder_id}; active embedder is {self.embedder.encoder_id}"
            )
        return self.embedder.embed_text(embedding_text)

    def _embed_query_text(self, query_text: str, encoder_id: str) -> np.ndarray:
        if encoder_id != self.embedder.encoder_id:
            raise ValueError(
                f"unsupported encoder_id {encoder_id}; active embedder is {self.embedder.encoder_id}"
            )
        return self.embedder.embed_text(query_text)

    @staticmethod
    def _fts_query(query: MemoryQuery) -> str:
        parts = [
            query.query_text.strip(),
            query.task_theme.strip(),
            *query.tags,
            *query.tags_any,
            *query.tags_all,
        ]
        tokens: list[str] = []
        for part in parts:
            if not part.strip():
                continue
            for raw_token in part.split():
                token = "".join(
                    ch for ch in raw_token if ch.isalnum() or ch in {"_", "-"}
                ).strip("-_")
                if not token:
                    continue
                tokens.append(f'"{token}"')
        return " OR ".join(tokens) if tokens else "*"


def _state_refs_from_json(payload: str | None) -> list[StateRef]:
    if not payload:
        return []
    rows = json.loads(payload)
    return [StateRef(**item) for item in rows]


def _metadata_matches(
    metadata: dict[str, object],
    required_metadata: dict[str, object],
) -> bool:
    for key, expected in required_metadata.items():
        if expected in (None, ""):
            continue
        if metadata.get(key) != expected:
            return False
    return True
