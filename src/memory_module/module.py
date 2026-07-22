from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .add_logger import AddLogger, JsonlAddLogger
from .embedders import BM25Encoder, DenseEmbedder
from .qdrant_store import QdrantMemoryStore
from .schemas import (
    AddMemoryRequest,
    DeleteMemoryResult,
    Memory,
    MemoryPayload,
    PayloadFilters,
    SearchMode,
    SearchResult,
)


class MemoryModule:
    """Public long-term shared-memory API for Swarm tools and other callers."""

    def __init__(
        self,
        *,
        dense_embedder: DenseEmbedder,
        qdrant_path: str | Path = "memory_module/data/qdrant",
        collection_name: str = "shared_memories",
        bm25_encoder: BM25Encoder | None = None,
        store: QdrantMemoryStore | None = None,
        add_logger: AddLogger | None = None,
        add_log_path: str | Path = "memory_module/logs/memory_add.jsonl",
    ) -> None:
        self.dense_embedder = dense_embedder
        self.bm25_encoder = bm25_encoder or BM25Encoder()
        self.store = store or QdrantMemoryStore(
            path=qdrant_path,
            collection_name=collection_name,
            dense_dimension=dense_embedder.dimension,
        )
        self.add_logger = add_logger or JsonlAddLogger(add_log_path)

    def add(
        self,
        content: str,
        *,
        keywords: list[str] | None = None,
        memory_type: str,
        source_agent: str,
        source_task_id: str,
        task_topic: str,
        infer: bool = False,
    ) -> Memory:
        request = AddMemoryRequest(
            content=content,
            keywords=keywords or [],
            memory_type=memory_type,
            source_agent=source_agent,
            source_task_id=source_task_id,
            task_topic=task_topic,
            infer=infer,
        )
        if request.infer:
            raise NotImplementedError(
                "infer=True is reserved for the future Mem0-style memory extractor"
            )
        content_hash = hashlib.md5(
            request.content.encode("utf-8"),
            usedforsecurity=False,
        ).hexdigest()
        existing = self.store.find_by_content_hash(content_hash)
        if existing is not None:
            return existing

        dense_vector = self.dense_embedder.embed(request.content)
        bm25_text = self._build_bm25_text(request.content, request.keywords)
        bm25_indices, bm25_values = self.bm25_encoder.encode(bm25_text)
        payload = MemoryPayload(
            content=request.content,
            keywords=request.keywords,
            memory_type=request.memory_type,
            source_agent=request.source_agent,
            source_task_id=request.source_task_id,
            task_topic=request.task_topic,
            content_hash=content_hash,
            created_at=datetime.now(timezone.utc),
        )
        memory = self.store.insert(
            memory_id=str(uuid.uuid4()),
            dense_vector=dense_vector,
            bm25_indices=bm25_indices,
            bm25_values=bm25_values,
            payload=payload,
        )
        self.add_logger.log_add(memory)
        return memory

    def search(
        self,
        query: str,
        *,
        mode: SearchMode | str = SearchMode.HYBRID,
        filters: PayloadFilters | None = None,
        top_k: int = 5,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            raise ValueError("query must not be empty")
        search_mode = SearchMode(mode)

        dense_vector = None
        bm25_indices = None
        bm25_values = None
        if search_mode in (SearchMode.DENSE, SearchMode.HYBRID):
            dense_vector = self.dense_embedder.embed(query)
        if search_mode in (SearchMode.BM25, SearchMode.HYBRID):
            bm25_indices, bm25_values = self.bm25_encoder.encode(query)

        return self.store.search(
            mode=search_mode,
            dense_vector=dense_vector,
            bm25_indices=bm25_indices,
            bm25_values=bm25_values,
            filters=filters,
            top_k=top_k,
            score_threshold=score_threshold,
        )

    def list(
        self,
        *,
        filters: PayloadFilters | None = None,
        limit: int = 100,
        offset: Any | None = None,
    ) -> list[Memory]:
        return self.store.list(filters=filters, limit=limit, offset=offset)

    def get(self, memory_id: str) -> Memory | None:
        return self.store.get(self._validate_memory_id(memory_id))

    def delete(self, memory_id: str) -> DeleteMemoryResult:
        memory_id = self._validate_memory_id(memory_id)
        return DeleteMemoryResult(
            memory_id=memory_id,
            deleted=self.store.delete(memory_id),
        )

    @staticmethod
    def _build_bm25_text(content: str, keywords: list[str]) -> str:
        if not keywords:
            return content
        return f"{content}\n{' '.join(keywords)}"

    @staticmethod
    def _validate_memory_id(memory_id: str) -> str:
        memory_id = memory_id.strip()
        if not memory_id:
            raise ValueError("memory_id must not be empty")
        return memory_id
