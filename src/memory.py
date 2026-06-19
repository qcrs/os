"""Shared memory module: InMemoryStore with semantic search."""

import hashlib
import math
import re
import time
from collections.abc import Sequence
from http import HTTPStatus

import dashscope

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_HTTP_API_URL,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
)
from metrics import metrics


class DashScopeEmbeddings(Embeddings):
    """LangChain-compatible wrapper for DashScope text-embedding-v4."""

    def __init__(
        self,
        model: str = EMBEDDING_MODEL,
        dims: int = EMBEDDING_DIMS,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        api_key: str = DASHSCOPE_API_KEY,
    ):
        if not api_key:
            raise ValueError("DASHSCOPE_API_KEY must be set to use DashScope embeddings.")
        self.model = model
        self.dims = dims
        self.batch_size = batch_size
        dashscope.api_key = api_key
        dashscope.base_http_api_url = DASHSCOPE_BASE_HTTP_API_URL

    @staticmethod
    def _field(value, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    def _embed_batch(self, texts: list[str], text_type: str) -> list[list[float]]:
        response = dashscope.TextEmbedding.call(
            model=self.model,
            input=texts,
            dimension=self.dims,
            text_type=text_type,
        )
        if response.status_code != HTTPStatus.OK:
            code = self._field(response, "code", "unknown")
            message = self._field(response, "message", "unknown error")
            raise RuntimeError(f"DashScope embedding failed: {code}: {message}")

        output = self._field(response, "output", {})
        embeddings = self._field(output, "embeddings", [])
        embeddings = sorted(embeddings, key=lambda item: self._field(item, "text_index", 0))
        vectors = [self._field(item, "embedding", []) for item in embeddings]

        if len(vectors) != len(texts):
            raise RuntimeError(
                f"DashScope returned {len(vectors)} embeddings for {len(texts)} texts."
            )
        return [list(vector) for vector in vectors]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(
                self._embed_batch(texts[start:start + self.batch_size], text_type="document")
            )
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], text_type="query")[0]


class LocalHashEmbeddings(Embeddings):
    """Deterministic local embedding fallback for offline demos.

    This is a lightweight hashed bag-of-words vector. It is not a replacement for
    semantic embedding quality, but it keeps Store search and non-text state
    transfer local when no DashScope key is configured.
    """

    def __init__(self, dims: int = EMBEDDING_DIMS):
        self.dims = dims

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dims
        tokens = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dims
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm:
            vector = [value / norm for value in vector]
        return vector

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def get_embeddings(dims: int = EMBEDDING_DIMS) -> Embeddings:
    """Return DashScope embeddings when configured, otherwise local fallback."""
    if DASHSCOPE_API_KEY:
        return DashScopeEmbeddings(dims=dims)
    return LocalHashEmbeddings(dims=dims)


def create_store() -> InMemoryStore:
    """Create an InMemoryStore with semantic search enabled."""
    embeddings = get_embeddings(dims=EMBEDDING_DIMS)
    store = InMemoryStore(
        index={
            "dims": EMBEDDING_DIMS,
            "embed": embeddings,
            "fields": ["text"],  # index the "text" field of stored items
        }
    )
    return store


# ─── Store operation wrappers with metrics ───


def store_put(store: BaseStore, namespace: tuple, key: str, value: dict):
    """Put an item into the store and record timing."""
    t0 = time.perf_counter()
    store.put(namespace, key, value)
    duration = time.perf_counter() - t0
    metrics.record_store_op("put", namespace, key, duration)


def store_get(store: BaseStore, namespace: tuple, key: str):
    """Get an item from the store and record timing."""
    t0 = time.perf_counter()
    item = store.get(namespace, key)
    duration = time.perf_counter() - t0
    metrics.record_store_op("get", namespace, key, duration)
    return item


def store_search(store: BaseStore, namespace: tuple, query: str, limit: int = 5):
    """Search the store and record timing with scores."""
    t0 = time.perf_counter()
    results = store.search(namespace, query=query, limit=limit)
    duration = time.perf_counter() - t0

    for r in results:
        metrics.record_store_op(
            "search", namespace, r.key, duration,
            score=r.score, query=query,
        )
    if not results:
        metrics.record_store_op("search", namespace, "(no results)", duration, query=query)

    return results
