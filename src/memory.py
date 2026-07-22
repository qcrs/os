"""Shared memory module: InMemoryStore with semantic search."""

import hashlib
import json
import math
import re
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from functools import lru_cache
from http import HTTPStatus
from pathlib import Path
from typing import Any

try:
    import dashscope
except ImportError:
    dashscope = None

from langchain_core.embeddings import Embeddings
from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_HTTP_API_URL,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_BACKEND,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    LONG_TERM_MEMORY_ADD_LOG_PATH,
    LONG_TERM_MEMORY_BM25_MODEL_PATH,
    LONG_TERM_MEMORY_COLLECTION,
    LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD,
    LONG_TERM_MEMORY_ENABLED,
    LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE,
    LONG_TERM_MEMORY_QDRANT_PATH,
    LONG_TERM_MEMORY_SEARCH_MODE,
    LONG_TERM_MEMORY_TOP_K,
    PERSISTENT_MEMORY_ENABLED,
    PERSISTENT_MEMORY_PATH,
)
from metrics import metrics


MEMORY_SCHEMA_VERSION = 1
PERSISTED_MEMORY_FILE_VERSION = 1
MAX_MEMORY_SUMMARY_CHARS = 360
MAX_MEMORY_TAGS = 12
NAMESPACE_MEMORY_DEFAULTS = {
    ("plans",): ("plan", "planner"),
    ("docs",): ("document", "researcher"),
    ("analysis",): ("analysis", "analyst"),
    ("executions",): ("execution", "executor"),
    ("summaries",): ("summary", "summarizer"),
}


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
        if dashscope is None:
            raise RuntimeError("dashscope must be installed to use DashScope embeddings.")
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
    """Return the configured embedding backend."""
    backend = (EMBEDDING_BACKEND or "auto").lower()
    if backend in {"local", "local_hash", "hash"}:
        return LocalHashEmbeddings(dims=dims)
    if backend in {"dashscope", "api"}:
        return DashScopeEmbeddings(dims=dims)
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
    loaded_count = load_persisted_memories(store)
    if loaded_count:
        metrics.increment("persistent_memory_loaded", loaded_count)
    return store


# ─── Qdrant-backed reusable memory helpers ───


class _QdrantDenseEmbedder:
    """Adapter from this project's embedding helper to memory_module's API."""

    def __init__(self, dims: int = EMBEDDING_DIMS):
        self._dims = dims
        self._embeddings = get_embeddings(dims=dims)

    @property
    def dimension(self) -> int:
        return self._dims

    def embed(self, text: str) -> list[float]:
        return self._embeddings.embed_query(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._embeddings.embed_documents(texts)


@lru_cache(maxsize=1)
def get_qdrant_memory():
    """Return the Qdrant-backed memory module, or None if disabled/unavailable."""
    if not LONG_TERM_MEMORY_ENABLED:
        return None

    try:
        from memory_module.embedders import BM25Encoder
        from memory_module.module import MemoryModule
    except Exception as exc:
        metrics.increment("qdrant_memory_import_errors")
        metrics.record_store_op(
            "qdrant_import_error",
            ("qdrant", "init"),
            "(import)",
            0.0,
            error=repr(exc),
        )
        return None

    try:
        bm25_kwargs: dict[str, Any] = {}
        if LONG_TERM_MEMORY_BM25_MODEL_PATH:
            bm25_kwargs["model_path"] = LONG_TERM_MEMORY_BM25_MODEL_PATH

        return MemoryModule(
            dense_embedder=_QdrantDenseEmbedder(dims=EMBEDDING_DIMS),
            bm25_encoder=BM25Encoder(**bm25_kwargs),
            qdrant_path=LONG_TERM_MEMORY_QDRANT_PATH,
            collection_name=LONG_TERM_MEMORY_COLLECTION,
            add_log_path=LONG_TERM_MEMORY_ADD_LOG_PATH,
        )
    except Exception as exc:
        metrics.increment("qdrant_memory_init_errors")
        metrics.record_store_op(
            "qdrant_init_error",
            ("qdrant", "init"),
            "(init)",
            0.0,
            error=repr(exc),
        )
        return None


def qdrant_memory_available() -> bool:
    """Return whether the Qdrant memory module is configured and available."""
    return get_qdrant_memory() is not None


def qdrant_search(
    query: str,
    *,
    memory_type: str | None = None,
    top_k: int = LONG_TERM_MEMORY_TOP_K,
    mode: str = LONG_TERM_MEMORY_SEARCH_MODE,
    dense_score_threshold: float | None = None,
):
    """Search Qdrant-backed reusable memory.

    Hybrid scores are RRF ranking scores, not cosine similarities.
    """
    query = str(query or "").strip()
    if not query:
        return []
    memory = get_qdrant_memory()
    if memory is None:
        return []

    filters = {"memory_type": memory_type} if memory_type else None
    search_mode = str(mode or LONG_TERM_MEMORY_SEARCH_MODE).lower()
    threshold = (
        dense_score_threshold
        if dense_score_threshold is not None
        else LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD
    )
    threshold = threshold if threshold and threshold > 0 else None
    qdrant_threshold = threshold if search_mode == "dense" else None
    try:
        results = memory.search(
            query,
            mode=search_mode,
            filters=filters,
            top_k=top_k,
            score_threshold=qdrant_threshold,
        )
    except Exception as exc:
        metrics.increment("qdrant_memory_search_errors")
        metrics.record_store_op(
            "qdrant_search_error",
            ("qdrant", memory_type or "all"),
            "(error)",
            0.0,
            query=query,
            mode=search_mode,
            error=repr(exc),
        )
        return []

    if threshold is not None and search_mode == "hybrid" and LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE:
        before_count = len(results)
        results = [
            result
            for result in results
            if result.dense_score is not None and result.dense_score >= threshold
        ]
        if len(results) < before_count:
            metrics.increment("qdrant_dense_threshold_filtered", before_count - len(results))

    for result in results:
        metrics.record_store_op(
            "qdrant_search",
            ("qdrant", memory_type or "all"),
            result.id,
            0.0,
            score=result.score,
            dense_score=result.dense_score,
            bm25_score=result.bm25_score,
            dense_score_threshold=threshold,
            query=query,
            mode=search_mode,
        )
    if not results:
        metrics.record_store_op(
            "qdrant_search",
            ("qdrant", memory_type or "all"),
            "(no results)",
            0.0,
            query=query,
            mode=search_mode,
            dense_score_threshold=threshold,
        )
    return results


def qdrant_add(
    *,
    source_task_id: str,
    content: str,
    memory_type: str,
    source_agent: str,
    task_topic: str,
    keywords: Sequence | None = None,
):
    """Add a reusable memory to Qdrant."""
    content = str(content or "").strip()
    source_task_id = str(source_task_id or "").strip()
    memory_type = str(memory_type or "").strip()
    source_agent = str(source_agent or "").strip()
    task_topic = str(task_topic or "").strip()
    if not all([content, source_task_id, memory_type, source_agent, task_topic]):
        metrics.increment("qdrant_memory_add_skipped")
        return None

    memory = get_qdrant_memory()
    if memory is None:
        metrics.increment("qdrant_memory_add_unavailable")
        return None

    try:
        stored = memory.add(
            content,
            keywords=_normalize_tags(keywords or []),
            memory_type=memory_type,
            source_agent=source_agent,
            source_task_id=source_task_id,
            task_topic=task_topic,
            infer=False,
        )
        metrics.record_store_op(
            "qdrant_add",
            ("qdrant", memory_type),
            stored.id,
            0.0,
            source_task_id=source_task_id,
        )
        return stored
    except Exception as exc:
        metrics.increment("qdrant_memory_add_errors")
        metrics.record_store_op(
            "qdrant_add_error",
            ("qdrant", memory_type),
            source_task_id,
            0.0,
            error=repr(exc),
        )
        return None


def _compact_task_topic(value: object, max_chars: int = 180) -> str:
    """Convert a full task prompt into a short human-readable topic."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""

    round_match = re.search(r"\bRound:\s*([^\s]+)", text, flags=re.IGNORECASE)
    question_match = re.search(
        r"\bQuestion:\s*(.*?)(?:\s+Constraints:|\s+Expected answer format:|\s+Depends on prior rounds:|$)",
        text,
        flags=re.IGNORECASE,
    )
    if round_match and question_match:
        question = question_match.group(1).strip()
        topic = f"Round {round_match.group(1)}: {question}"
        return _compact_text(topic, max_chars)

    for marker in ("Question:", "Task:", "Topic:"):
        if marker in text:
            tail = text.split(marker, 1)[1].strip()
            for stop in ("Constraints:", "Expected answer format:", "Depends on prior rounds:"):
                if stop in tail:
                    tail = tail.split(stop, 1)[0].strip()
            return _compact_text(tail, max_chars)

    first_line = str(value or "").strip().splitlines()[0] if str(value or "").strip() else text
    return _compact_text(first_line, max_chars)


def _json_content(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _compact_json_content(value: object, max_chars: int = 1200) -> str:
    """Serialize structured reusable content without letting one field dominate."""
    return _compact_text(_json_content(value), max_chars)


def _format_memory_sections(sections: Sequence[tuple[str, object]], *, max_chars: int = 2200) -> str:
    """Join selected reusable fields into one retrieval document."""
    rendered = []
    for title, value in sections:
        if value is None:
            continue
        if isinstance(value, str):
            text = value.strip()
        elif isinstance(value, (dict, list, tuple)):
            if not value:
                continue
            text = _compact_json_content(value)
        else:
            text = str(value).strip()
        if not text:
            continue
        rendered.append(f"{title}:\n{text}")
    return _compact_text("\n\n".join(rendered), max_chars)


def _evidence_claims(payload: dict, max_items: int = 4) -> list[dict]:
    """Keep only evidence fields useful for later retrieval."""
    claims = []
    for item in payload.get("evidence", []) or []:
        if not isinstance(item, dict):
            continue
        claim = _compact_text(item.get("claim", ""), 160)
        support = _compact_text(item.get("support", ""), 220)
        source = "#".join(
            str(part)
            for part in (item.get("doc_key"), item.get("span_id"))
            if part
        )
        if claim or support or source:
            claims.append({
                "claim": claim,
                "support": support,
                "source": source,
            })
        if len(claims) >= max_items:
            break
    return claims


def _content_for_qdrant_memory(
    *,
    payload: dict,
    memory_type: str,
    summary: str | None,
    fallback_topic: str,
) -> str:
    """Select stable content according to memory_type-specific schema."""
    memory_type = str(memory_type or "").strip().lower()

    if memory_type == "task_state":
        task_state = payload.get("task_state")
        if isinstance(task_state, dict):
            return _format_memory_sections([
                ("Task state", task_state),
                ("Analysis digest", payload.get("analysis_digest") or summary),
            ])
        return str(payload.get("text") or summary or fallback_topic or "")

    if memory_type == "design_state":
        design_state = payload.get("design_state")
        if isinstance(design_state, dict):
            return _json_content(design_state)
        return str(payload.get("text") or summary or fallback_topic or "")

    if memory_type == "analysis":
        return _format_memory_sections([
            ("Analysis", payload.get("analysis") or payload.get("text") or summary),
            ("Candidate answers", payload.get("candidate_answers")),
            ("Evidence claims", _evidence_claims(payload)),
            ("Verification", payload.get("context_verification")),
        ])

    if memory_type == "summary":
        return _format_memory_sections([
            ("Summary", payload.get("summary") or payload.get("text") or summary),
            ("Key findings", payload.get("key_findings")),
            ("Recommendations", payload.get("recommendations")),
            ("Execution summary", payload.get("execution_summary")),
            ("Final answer", payload.get("final_answer")),
        ])

    if memory_type == "execution":
        return str(
            payload.get("execution_summary")
            or summary
            or payload.get("text")
            or payload.get("final_answer")
            or fallback_topic
            or ""
        )

    if memory_type == "plan":
        return str(payload.get("plan") or payload.get("text") or summary or fallback_topic or "")

    if memory_type == "document":
        return str(payload.get("text") or payload.get("summary") or summary or fallback_topic or "")

    return str(
        summary
        or payload.get("summary")
        or payload.get("digest")
        or payload.get("text")
        or payload.get("analysis")
        or fallback_topic
        or ""
    )


def _qdrant_keyword_hints(*, payload: dict, memory_type: str) -> list[str]:
    """Build compact keyword hints without copying full prompts into metadata."""
    hints: list[str] = []
    for field_name in ("task_topic", "sub_query", "plan", "summary", "digest"):
        value = payload.get(field_name)
        if value:
            hints.extend(str(value).split()[:6])

    task_state = payload.get("task_state")
    if str(memory_type).lower() == "task_state" and isinstance(task_state, dict):
        hints.extend(task_state.keys())
        for section in ("entities", "interfaces"):
            section_value = task_state.get(section)
            if isinstance(section_value, dict):
                hints.extend(str(key) for key in section_value.keys())
        for section in ("decisions", "constraints", "invariants", "next_requirements"):
            hints.extend(_compact_text(item, 80) for item in task_state.get(section, [])[:4])

    return hints


def qdrant_add_from_payload(
    *,
    key: str,
    value: dict,
    memory_type: str,
    source_agent: str,
    task_group: str,
    task_topic: str,
    summary: str | None = None,
    tags: Sequence | None = None,
):
    """Map an agent payload to memory_module's long-term memory schema."""
    payload = dict(value or {})
    resolved_memory_type = str(memory_type or payload.get("memory_type") or "memory")
    resolved_task_topic = _compact_task_topic(
        task_topic
        or payload.get("task_topic")
        or task_group
        or payload.get("topic")
        or payload.get("sub_query")
        or payload.get("query")
    )
    payload.setdefault("task_topic", resolved_task_topic)
    content = _content_for_qdrant_memory(
        payload=payload,
        memory_type=resolved_memory_type,
        summary=summary,
        fallback_topic=resolved_task_topic,
    )
    keywords = [
        resolved_memory_type,
        source_agent,
        task_group,
        resolved_task_topic,
        *(tags or []),
        *(payload.get("tags", []) or []),
        *_qdrant_keyword_hints(payload=payload, memory_type=resolved_memory_type),
    ]
    for evidence_item in payload.get("evidence", []) or []:
        if not isinstance(evidence_item, dict):
            continue
        for field_name in ("doc_key", "span_id", "claim"):
            value = evidence_item.get(field_name)
            if value:
                keywords.append(str(value))

    return qdrant_add(
        source_task_id=key,
        content=str(content),
        memory_type=resolved_memory_type,
        source_agent=source_agent,
        task_topic=resolved_task_topic,
        keywords=keywords,
    )


# ─── Unified memory unit helpers ───


def _compact_text(value: object, max_chars: int = MAX_MEMORY_SUMMARY_CHARS) -> str:
    """Normalize and shorten text for memory metadata fields."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _namespace_defaults(namespace: tuple) -> tuple[str, str]:
    """Return default memory_type/source_agent for a namespace."""
    return NAMESPACE_MEMORY_DEFAULTS.get(tuple(namespace), ("memory", "unknown"))


def _infer_task_group(memory_id: str, payload: dict) -> str:
    """Infer task group from payload or well-known Store key prefixes."""
    task_group = payload.get("task_group")
    if task_group:
        return str(task_group)
    for prefix in ("plan_", "analysis_", "summary_"):
        if memory_id.startswith(prefix):
            return memory_id[len(prefix):]
    return "default"


def _infer_task_topic(payload: dict) -> str:
    """Infer a task topic from common agent payload fields."""
    for field_name in ("task_topic", "query", "sub_query", "topic"):
        value = payload.get(field_name)
        if value:
            return _compact_text(value)
    if payload.get("plan"):
        return _compact_text(payload["plan"])
    return ""


def _infer_summary(payload: dict) -> str:
    """Infer a short summary description from common payload fields."""
    for field_name in ("summary", "summary_description", "digest", "text", "plan"):
        value = payload.get(field_name)
        if value:
            return _compact_text(value)
    return _infer_task_topic(payload)


def _normalize_tags(tags: Sequence | None) -> list[str]:
    """Normalize tags while preserving order."""
    normalized = []
    seen = set()
    for tag in tags or []:
        text = str(tag).strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= MAX_MEMORY_TAGS:
            break
    return normalized


def _derive_tags(*, payload: dict, memory_type: str, source_agent: str, task_group: str) -> list[str]:
    """Derive lightweight tags from memory metadata and content."""
    seed_tags = [memory_type, source_agent, task_group]
    content = " ".join(
        str(payload.get(field_name, ""))
        for field_name in ("query", "sub_query", "summary", "digest", "text")
    )
    tokens = re.findall(r"[A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,4}", content.lower())
    return _normalize_tags([*seed_tags, *tokens])


def _extract_evidence_refs(payload: dict) -> list[dict]:
    """Extract compact evidence references from analysis payloads."""
    evidence_refs = []
    seen = set()

    for evidence_item in payload.get("evidence", []) or []:
        if not isinstance(evidence_item, dict):
            continue
        doc_key = evidence_item.get("doc_key")
        span_id = evidence_item.get("span_id")
        if not doc_key and not span_id:
            continue
        ref_key = (doc_key, span_id)
        if ref_key in seen:
            continue
        seen.add(ref_key)
        evidence_refs.append({
            "doc_key": doc_key,
            "span_id": span_id,
            "claim": _compact_text(evidence_item.get("claim", ""), 120),
        })

    for doc_key in payload.get("selected_doc_keys", []) or []:
        ref_key = (doc_key, None)
        if not doc_key or ref_key in seen:
            continue
        seen.add(ref_key)
        evidence_refs.append({"doc_key": doc_key, "span_id": None})

    return evidence_refs


def make_memory_unit(
    *,
    namespace: tuple,
    key: str,
    value: dict,
    memory_type: str | None = None,
    source_agent: str | None = None,
    task_group: str | None = None,
    task_topic: str | None = None,
    summary: str | None = None,
    tags: Sequence | None = None,
    evidence_refs: Sequence[dict] | None = None,
) -> dict:
    """Wrap arbitrary agent output in the unified MemoryUnit schema.

    The returned dict keeps legacy payload fields at top level for backward
    compatibility, while guaranteeing standard metadata fields on every memory.
    """
    payload = dict(value or {})
    default_memory_type, default_source_agent = _namespace_defaults(namespace)
    resolved_memory_type = memory_type or payload.get("memory_type") or default_memory_type
    resolved_source_agent = source_agent or payload.get("source_agent") or default_source_agent
    resolved_task_group = task_group or _infer_task_group(key, payload)
    resolved_task_topic = task_topic or _infer_task_topic(payload)
    resolved_summary = _compact_text(summary or _infer_summary(payload))
    resolved_text = str(payload.get("text") or resolved_summary or resolved_task_topic)
    resolved_tags = _normalize_tags(
        [
            *(tags or []),
            *(payload.get("tags", []) or []),
            *_derive_tags(
                payload=payload,
                memory_type=str(resolved_memory_type),
                source_agent=str(resolved_source_agent),
                task_group=str(resolved_task_group),
            ),
        ]
    )
    resolved_evidence_refs = list(evidence_refs or payload.get("evidence_refs") or [])
    if not resolved_evidence_refs:
        resolved_evidence_refs = _extract_evidence_refs(payload)

    created_at = time.time()
    memory_unit = {
        "memory_schema_version": MEMORY_SCHEMA_VERSION,
        "memory_id": key,
        "memory_type": str(resolved_memory_type),
        "source_agent": str(resolved_source_agent),
        "created_at": created_at,
        "created_at_iso": datetime.fromtimestamp(created_at, tz=timezone.utc).isoformat(),
        "task_group": str(resolved_task_group),
        "task_topic": resolved_task_topic,
        "summary": resolved_summary,
        "summary_description": resolved_summary,
        "text": resolved_text,
        "tags": resolved_tags,
        "evidence_refs": resolved_evidence_refs,
        "payload": payload,
    }

    for field_name, field_value in payload.items():
        memory_unit.setdefault(field_name, field_value)
    return memory_unit


def _jsonable(value):
    """Convert memory values to JSON-serializable data for persistence."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return repr(value)


def _persistent_memory_path() -> Path | None:
    """Return configured persistent-memory path, or None when disabled."""
    if not PERSISTENT_MEMORY_ENABLED or not PERSISTENT_MEMORY_PATH:
        return None
    return Path(PERSISTENT_MEMORY_PATH)


def _persist_memory_unit(namespace: tuple, key: str, memory_value: dict):
    """Append a MemoryUnit record to the persistent JSONL store."""
    path = _persistent_memory_path()
    if path is None:
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "file_schema_version": PERSISTED_MEMORY_FILE_VERSION,
        "namespace": list(namespace),
        "key": key,
        "value": memory_value,
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(_jsonable(record), ensure_ascii=False) + "\n")


def load_persisted_memories(store: BaseStore) -> int:
    """Load latest persisted MemoryUnits into a newly created Store."""
    path = _persistent_memory_path()
    if path is None or not path.exists():
        return 0

    latest_records = {}
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                metrics.increment("persistent_memory_load_errors")
                continue

            namespace = tuple(record.get("namespace") or ())
            key = record.get("key")
            value = record.get("value")
            if not namespace or not key or not isinstance(value, dict):
                metrics.increment("persistent_memory_load_errors")
                continue
            latest_records[(namespace, str(key))] = value

    for (namespace, key), value in latest_records.items():
        if "memory_id" not in value or "payload" not in value:
            value = make_memory_unit(namespace=namespace, key=key, value=value)
        store.put(namespace, key, value)

    return len(latest_records)


def _contains_keywords(memory_value: dict, keywords: Sequence[str], *, match_all: bool) -> bool:
    """Return whether a memory contains the requested keywords."""
    normalized_keywords = [str(keyword).strip().lower() for keyword in keywords if str(keyword).strip()]
    if not normalized_keywords:
        return True
    haystack = " ".join([
        str(memory_value.get("text", "")),
        str(memory_value.get("summary", "")),
        str(memory_value.get("task_topic", "")),
        " ".join(memory_value.get("tags", []) or []),
    ]).lower()
    matches = [keyword in haystack for keyword in normalized_keywords]
    return all(matches) if match_all else any(matches)


def _contains_tags(memory_value: dict, tags: Sequence[str], *, match_all: bool) -> bool:
    """Return whether a memory has the requested tags."""
    normalized_tags = _normalize_tags(tags)
    if not normalized_tags:
        return True
    memory_tags = set(_normalize_tags(memory_value.get("tags", []) or []))
    matches = [tag in memory_tags for tag in normalized_tags]
    return all(matches) if match_all else any(matches)


# ─── Store operation wrappers with metrics ───


def store_put(
    store: BaseStore,
    namespace: tuple,
    key: str,
    value: dict,
    *,
    memory_type: str | None = None,
    source_agent: str | None = None,
    task_group: str | None = None,
    task_topic: str | None = None,
    summary: str | None = None,
    tags: Sequence | None = None,
    evidence_refs: Sequence[dict] | None = None,
):
    """Put a unified MemoryUnit into the store and record timing."""
    memory_value = make_memory_unit(
        namespace=namespace,
        key=key,
        value=value,
        memory_type=memory_type,
        source_agent=source_agent,
        task_group=task_group,
        task_topic=task_topic,
        summary=summary,
        tags=tags,
        evidence_refs=evidence_refs,
    )
    t0 = time.perf_counter()
    store.put(namespace, key, memory_value)
    duration = time.perf_counter() - t0
    metrics.record_store_op("put", namespace, key, duration)
    _persist_memory_unit(namespace, key, memory_value)


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


def store_search_by_keywords(
    store: BaseStore,
    namespace: tuple,
    keywords: Sequence[str],
    limit: int = 5,
    *,
    match_all: bool = False,
):
    """Search memories by exact keyword containment over text/summary/topic/tags."""
    t0 = time.perf_counter()
    candidates = list(store.search(namespace, limit=max(limit * 5, limit)))
    results = [
        item for item in candidates
        if _contains_keywords(item.value, keywords, match_all=match_all)
    ][:limit]
    duration = time.perf_counter() - t0
    if results:
        for item in results:
            metrics.record_store_op("search_keywords", namespace, item.key, duration)
    else:
        metrics.record_store_op("search_keywords", namespace, "(no results)", duration)
    return results


def store_search_by_tags(
    store: BaseStore,
    namespace: tuple,
    tags: Sequence[str],
    limit: int = 5,
    *,
    match_all: bool = True,
):
    """Search memories by normalized tags."""
    t0 = time.perf_counter()
    candidates = list(store.search(namespace, limit=max(limit * 5, limit)))
    results = [
        item for item in candidates
        if _contains_tags(item.value, tags, match_all=match_all)
    ][:limit]
    duration = time.perf_counter() - t0
    if results:
        for item in results:
            metrics.record_store_op("search_tags", namespace, item.key, duration)
    else:
        metrics.record_store_op("search_tags", namespace, "(no results)", duration)
    return results


def store_search_memories(
    store: BaseStore,
    namespace: tuple,
    *,
    query: str | None = None,
    keywords: Sequence[str] | None = None,
    tags: Sequence[str] | None = None,
    limit: int = 5,
    match_all_keywords: bool = False,
    match_all_tags: bool = True,
):
    """Search memories with optional semantic query, keyword filter, and tag filter."""
    t0 = time.perf_counter()
    candidate_limit = max(limit * 5, limit)
    if query:
        candidates = list(store.search(namespace, query=query, limit=candidate_limit))
    else:
        candidates = list(store.search(namespace, limit=candidate_limit))

    results = []
    for item in candidates:
        if not _contains_keywords(item.value, keywords or [], match_all=match_all_keywords):
            continue
        if not _contains_tags(item.value, tags or [], match_all=match_all_tags):
            continue
        results.append(item)
        if len(results) >= limit:
            break

    duration = time.perf_counter() - t0
    if results:
        for item in results:
            metrics.record_store_op("search_memory", namespace, item.key, duration)
    else:
        metrics.record_store_op("search_memory", namespace, "(no results)", duration)
    return results
