from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .schemas import Memory, MemoryPayload, PayloadFilters, SearchMode, SearchResult


class QdrantMemoryStore:
    DENSE_VECTOR_NAME = "dense"
    BM25_VECTOR_NAME = "bm25"

    def __init__(
        self,
        *,
        path: str | Path,
        collection_name: str,
        dense_dimension: int,
        client: Any | None = None,
        rrf_k: int = 60,
    ) -> None:
        if dense_dimension <= 0:
            raise ValueError("dense_dimension must be greater than zero")
        if rrf_k <= 0:
            raise ValueError("rrf_k must be greater than zero")

        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise RuntimeError(
                "Qdrant storage requires qdrant-client. Install memory_module requirements first."
            ) from exc

        self.models = models
        self.collection_name = collection_name
        self.dense_dimension = dense_dimension
        self.rrf_k = rrf_k
        self.client = client or QdrantClient(path=str(path))
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        collections = self.client.get_collections().collections
        if not any(collection.name == self.collection_name for collection in collections):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config={
                    self.DENSE_VECTOR_NAME: self.models.VectorParams(
                        size=self.dense_dimension,
                        distance=self.models.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    self.BM25_VECTOR_NAME: self.models.SparseVectorParams(
                        modifier=self.models.Modifier.IDF
                    )
                },
            )
            return

        info = self.client.get_collection(self.collection_name)
        vectors_config = info.config.params.vectors
        dense_config = (
            vectors_config.get(self.DENSE_VECTOR_NAME)
            if isinstance(vectors_config, dict)
            else None
        )
        if dense_config is None:
            raise ValueError(
                f"Collection '{self.collection_name}' has no named dense vector"
            )
        if dense_config.size != self.dense_dimension:
            raise ValueError(
                f"Collection dense dimension is {dense_config.size}, "
                f"configured embedder dimension is {self.dense_dimension}"
            )

        sparse_config = info.config.params.sparse_vectors or {}
        if self.BM25_VECTOR_NAME not in sparse_config:
            raise ValueError(
                f"Collection '{self.collection_name}' has no BM25 sparse vector"
            )

    def _field_condition(self, key: str, value: Any) -> Any:
        if isinstance(value, list):
            return self.models.FieldCondition(
                key=key,
                match=self.models.MatchAny(any=value),
            )
        return self.models.FieldCondition(
            key=key,
            match=self.models.MatchValue(value=value),
        )

    def _build_filter(self, filters: PayloadFilters | None) -> Any | None:
        if not filters:
            return None
        return self.models.Filter(
            must=[
                self._field_condition(key, value)
                for key, value in filters.items()
            ]
        )

    def find_by_content_hash(self, content_hash: str) -> Memory | None:
        memories = self.list(filters={"content_hash": content_hash}, limit=1)
        return memories[0] if memories else None

    def insert(
        self,
        *,
        memory_id: str,
        dense_vector: list[float],
        bm25_indices: list[int],
        bm25_values: list[float],
        payload: MemoryPayload,
    ) -> Memory:
        point = self.models.PointStruct(
            id=memory_id,
            vector={
                self.DENSE_VECTOR_NAME: dense_vector,
                self.BM25_VECTOR_NAME: self.models.SparseVector(
                    indices=bm25_indices,
                    values=bm25_values,
                ),
            },
            payload=payload.model_dump(mode="json"),
        )
        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
            wait=True,
        )
        return Memory(id=memory_id, payload=payload)

    def search(
        self,
        *,
        mode: SearchMode,
        dense_vector: list[float] | None,
        bm25_indices: list[int] | None,
        bm25_values: list[float] | None,
        filters: PayloadFilters | None,
        top_k: int,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero")

        if mode is SearchMode.DENSE:
            hits = self._search_dense(
                dense_vector, filters, top_k, score_threshold
            )
            return [self._to_search_result(hit, dense_score=hit.score) for hit in hits]
        if mode is SearchMode.BM25:
            hits = self._search_bm25(
                bm25_indices, bm25_values, filters, top_k, score_threshold
            )
            return [self._to_search_result(hit, bm25_score=hit.score) for hit in hits]
        return self._search_hybrid(
            dense_vector=dense_vector,
            bm25_indices=bm25_indices,
            bm25_values=bm25_values,
            filters=filters,
            top_k=top_k,
            score_threshold=score_threshold,
        )

    def _search_dense(
        self,
        vector: list[float] | None,
        filters: PayloadFilters | None,
        top_k: int,
        score_threshold: float | None,
    ) -> list[Any]:
        if vector is None:
            raise ValueError("dense_vector is required for dense search")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector,
            using=self.DENSE_VECTOR_NAME,
            query_filter=self._build_filter(filters),
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return response.points

    def _search_bm25(
        self,
        indices: list[int] | None,
        values: list[float] | None,
        filters: PayloadFilters | None,
        top_k: int,
        score_threshold: float | None,
    ) -> list[Any]:
        if indices is None or values is None:
            raise ValueError("BM25 sparse vector is required for BM25 search")
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=self.models.SparseVector(indices=indices, values=values),
            using=self.BM25_VECTOR_NAME,
            query_filter=self._build_filter(filters),
            limit=top_k,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return response.points

    def _search_hybrid(
        self,
        *,
        dense_vector: list[float] | None,
        bm25_indices: list[int] | None,
        bm25_values: list[float] | None,
        filters: PayloadFilters | None,
        top_k: int,
        score_threshold: float | None,
    ) -> list[SearchResult]:
        candidate_limit = max(top_k * 4, 20)
        dense_hits = self._search_dense(
            dense_vector, filters, candidate_limit, score_threshold
        )
        bm25_hits = self._search_bm25(
            bm25_indices, bm25_values, filters, candidate_limit, None
        )

        fused_scores: dict[str, float] = defaultdict(float)
        points: dict[str, Any] = {}
        dense_scores: dict[str, float] = {}
        bm25_scores: dict[str, float] = {}

        for rank, hit in enumerate(dense_hits, start=1):
            memory_id = str(hit.id)
            fused_scores[memory_id] += 1.0 / (self.rrf_k + rank)
            dense_scores[memory_id] = hit.score
            points[memory_id] = hit

        for rank, hit in enumerate(bm25_hits, start=1):
            memory_id = str(hit.id)
            fused_scores[memory_id] += 1.0 / (self.rrf_k + rank)
            bm25_scores[memory_id] = hit.score
            points[memory_id] = hit

        ranked_ids = sorted(
            fused_scores,
            key=fused_scores.__getitem__,
            reverse=True,
        )[:top_k]
        return [
            self._to_search_result(
                points[memory_id],
                score=fused_scores[memory_id],
                dense_score=dense_scores.get(memory_id),
                bm25_score=bm25_scores.get(memory_id),
            )
            for memory_id in ranked_ids
        ]

    def list(
        self,
        *,
        filters: PayloadFilters | None = None,
        limit: int = 100,
        offset: Any | None = None,
    ) -> list[Memory]:
        if limit <= 0:
            raise ValueError("limit must be greater than zero")
        points, _ = self.client.scroll(
            collection_name=self.collection_name,
            scroll_filter=self._build_filter(filters),
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        return [self._to_memory(point) for point in points]

    def get(self, memory_id: str) -> Memory | None:
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=[memory_id],
            with_payload=True,
            with_vectors=False,
        )
        return self._to_memory(points[0]) if points else None

    def delete(self, memory_id: str) -> bool:
        if self.get(memory_id) is None:
            return False
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=self.models.PointIdsList(points=[memory_id]),
            wait=True,
        )
        return True

    def close(self) -> None:
        close = getattr(self.client, "close", None)
        if close is not None:
            close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def _to_memory(self, point: Any) -> Memory:
        return Memory(
            id=str(point.id),
            payload=MemoryPayload.model_validate(point.payload),
        )

    def _to_search_result(
        self,
        point: Any,
        *,
        score: float | None = None,
        dense_score: float | None = None,
        bm25_score: float | None = None,
    ) -> SearchResult:
        return SearchResult(
            id=str(point.id),
            payload=MemoryPayload.model_validate(point.payload),
            score=point.score if score is None else score,
            dense_score=dense_score,
            bm25_score=bm25_score,
        )
