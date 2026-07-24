"""Ephemeral document storage shared by nodes within one graph run."""

import time
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from config import NS_DOCS
from metrics import metrics


def create_runtime_store() -> InMemoryStore:
    """Create an unindexed store for current-run document rehydration.

    Documents are addressed by ``doc_key`` and are never semantically searched,
    so configuring an embedding index would only add latency and API calls.
    """
    return InMemoryStore()


def put_document(store: BaseStore, doc_key: str, document: dict[str, Any]) -> None:
    """Store one complete researcher document for packet verification."""
    t0 = time.perf_counter()
    store.put(NS_DOCS, doc_key, document)
    metrics.record_store_op("runtime_document_put", NS_DOCS, doc_key, time.perf_counter() - t0)


def get_document(store: BaseStore, doc_key: str):
    """Load a complete researcher document by its stable document key."""
    t0 = time.perf_counter()
    item = store.get(NS_DOCS, doc_key)
    metrics.record_store_op("runtime_document_get", NS_DOCS, doc_key, time.perf_counter() - t0)
    return item
