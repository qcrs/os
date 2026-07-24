"""Embedding adapters and Qdrant-backed reusable long-term memory."""

import hashlib
import json
import math
import re
import time
from collections.abc import Sequence
from functools import lru_cache
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import dashscope
except ImportError:
    dashscope = None

from langchain_core.embeddings import Embeddings
from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_HTTP_API_URL,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_BACKEND,
    EMBEDDING_DIMS,
    EMBEDDING_MODEL,
    LOCAL_EMBEDDING_API_BASE_URL,
    LOCAL_EMBEDDING_API_TIMEOUT_S,
    LOCAL_EMBEDDING_DOCUMENT_MODEL,
    LOCAL_EMBEDDING_QUERY_MODEL,
    LONG_TERM_MEMORY_ADD_LOG_PATH,
    LONG_TERM_MEMORY_BM25_MODEL_PATH,
    LONG_TERM_MEMORY_COLLECTION,
    LONG_TERM_MEMORY_DENSE_SCORE_THRESHOLD,
    LONG_TERM_MEMORY_ENABLED,
    LONG_TERM_MEMORY_FILTER_HYBRID_BY_DENSE,
    LONG_TERM_MEMORY_QDRANT_PATH,
    LONG_TERM_MEMORY_SEARCH_MODE,
    LONG_TERM_MEMORY_TOP_K,
)
from metrics import metrics


MAX_MEMORY_SUMMARY_CHARS = 360
MAX_MEMORY_TAGS = 12


class DashScopeEmbeddings(Embeddings):
    """LangChain-compatible wrapper for DashScope text-embedding-v4."""

    def __init__(
        self,
        model: str = EMBEDDING_MODEL,
        dims: int = EMBEDDING_DIMS,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        api_key: str = DASHSCOPE_API_KEY,
    ):
        if dashscope is None:
            raise ImportError("dashscope is not installed.")
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


class LocalEmbeddingApiEmbeddings(Embeddings):
    """OpenAI-compatible adapter for the loopback Qwen3 embedding service.

    The server exposes different model aliases for documents and queries so it
    can apply the model's retrieval instruction only to query embeddings.
    """

    def __init__(
        self,
        dims: int = EMBEDDING_DIMS,
        batch_size: int = EMBEDDING_BATCH_SIZE,
        base_url: str = LOCAL_EMBEDDING_API_BASE_URL,
        document_model: str = LOCAL_EMBEDDING_DOCUMENT_MODEL,
        query_model: str = LOCAL_EMBEDDING_QUERY_MODEL,
        timeout_s: float = LOCAL_EMBEDDING_API_TIMEOUT_S,
    ):
        self.dims = dims
        self.batch_size = batch_size
        self.endpoint = f"{base_url.rstrip('/')}/embeddings"
        self.document_model = document_model
        self.query_model = query_model
        self.timeout_s = timeout_s

    def _embed_batch(self, texts: list[str], model: str) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            payload = json.dumps({
                "input": batch,
                "model": model,
                "encoding_format": "float",
                "dimensions": self.dims,
            }).encode("utf-8")
            request = Request(
                self.endpoint,
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer EMPTY",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=self.timeout_s) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                raise RuntimeError(
                    f"Local embedding API returned HTTP {exc.code}: {detail}"
                ) from exc
            except (URLError, OSError, TimeoutError) as exc:
                raise RuntimeError(
                    f"Local embedding API is unavailable at {self.endpoint}: {exc}"
                ) from exc

            data = response_payload.get("data", []) if isinstance(response_payload, dict) else []
            if not isinstance(data, list) or len(data) != len(batch):
                raise RuntimeError("Local embedding API returned an invalid embedding batch.")
            ordered = sorted(data, key=lambda item: int(item.get("index", -1)))
            for item in ordered:
                vector = item.get("embedding") if isinstance(item, dict) else None
                if not isinstance(vector, list) or len(vector) != self.dims:
                    raise RuntimeError(
                        f"Local embedding API returned a vector with unexpected dimension; "
                        f"expected {self.dims}."
                    )
                vectors.append([float(value) for value in vector])
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed_batch(texts, self.document_model)

    def embed_query(self, text: str) -> list[float]:
        return self._embed_batch([text], self.query_model)[0]


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
    if backend in {"local_api", "local_embedding_api", "qwen3_local"}:
        return LocalEmbeddingApiEmbeddings(dims=dims)
    if backend in {"local", "local_hash", "hash"}:
        return LocalHashEmbeddings(dims=dims)
    if backend in {"dashscope", "api"}:
        return DashScopeEmbeddings(dims=dims)
    if DASHSCOPE_API_KEY:
        return DashScopeEmbeddings(dims=dims)
    return LocalHashEmbeddings(dims=dims)


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



def _compact_text(value: object, max_chars: int = MAX_MEMORY_SUMMARY_CHARS) -> str:
    """Normalize and shorten text stored in a long-term memory record."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _normalize_tags(tags: Sequence | None) -> list[str]:
    """Normalize Qdrant keyword hints while preserving order."""
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
