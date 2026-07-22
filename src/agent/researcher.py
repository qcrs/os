"""Researcher agent for generating and packaging source material."""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from config import ENABLE_CONTEXT_PACKETS, ENABLE_EMBEDDING_TRANSFER, NS_DOCS
from memory import store_put, store_search
from metrics import metrics
from models import get_model
from protocol import ActionType, build_context_packet, hash_text, make_document_key, make_message, summarize_text

from .shared import _get_mode


# ─── Researcher Agent ───


def researcher(state: dict, store: BaseStore) -> dict:
    """Generate and package research material for a sub-query.

    Role: Source material generation and context packaging
    Input: sub_query (str) — received via Send
    Output: documents (list[str])
    Memory: writes documents to Store under ("docs", task_group)
    """
    t0 = time.perf_counter()
    mode = _get_mode(state)

    sub_query = state.get("sub_query", state.get("query", ""))
    query = state.get("query", "")
    source_context = state.get("source_context", "")
    task_group = state.get("task_group", "default")
    task_topic = state.get("task_topic") or task_group
    model = get_model(temperature=0.3)

    if source_context:
        messages = [
            SystemMessage(content="""You are a source-material extractor. Given a sub-query
and source context, extract only the source facts needed by downstream analysis.
Use the provided source context only; do not invent facts. Preserve exact row
labels, column years, numbers, units/scales, and any text snippets needed for
calculation. If arithmetic is implied, include the formula and operands but keep
the response concise."""),
            HumanMessage(content=(
                f"Original question:\n{query}\n\n"
                f"Sub-query:\n{sub_query}\n\n"
                f"Source context:\n{source_context}"
            )),
        ]
    else:
        messages = [
            SystemMessage(content="""You are a research source-material generator. Given a sub-query,
produce comprehensive, factual source material with key findings.
Return your response as plain text (3-5 paragraphs)."""),
            HumanMessage(content=f"Sub-query: {sub_query}"),
        ]

    response = model.invoke(messages)
    # Record LLM token usage
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        metrics.record_tokens("researcher", um.get("input_tokens", 0), um.get("output_tokens", 0))
    doc_text = response.content

    # Generate embedding for the document (independent non-text state transfer).
    embedding = None
    if mode == "structured" and ENABLE_EMBEDDING_TRANSFER:
        try:
            from config import EMBEDDING_DIMS
            from memory import get_embeddings
            embedder = get_embeddings(dims=EMBEDDING_DIMS)
            embedding = embedder.embed_query(doc_text[:500])
        except Exception:
            embedding = None

    # Store document
    doc_key = make_document_key(task_group, sub_query, doc_text)
    store_put(store, NS_DOCS, doc_key, {
        "text": doc_text,
        "sub_query": sub_query,
        "query": query,
        "task_group": task_group,
        "has_source_context": bool(source_context),
    },
        memory_type="document",
        source_agent="researcher",
        task_group=task_group,
        task_topic=task_topic,
        summary=summarize_text(doc_text, 240),
        tags=["document", "researcher", task_group, *sub_query.split()[:6]],
    )

    document_payload = {
        "doc_key": doc_key,
        "sub_query": sub_query,
        "text": doc_text,
        "text_hash": hash_text(doc_text),
        "original_chars": len(doc_text),
    }
    # Search for related prior documents (memory reuse)
    related = store_search(store, NS_DOCS, sub_query, limit=3)
    related_docs = [r.value.get("text", "") for r in related if r.key != doc_key]
    if related_docs:
        metrics.increment("document_memory_reuse_hits")

    duration = time.perf_counter() - t0
    metrics.record_timing("node_researcher", duration)

    if mode == "structured":
        embedding_payload = None
        if embedding:
            embedding_payload = {
                "doc_key": doc_key,
                "embedding_ref": doc_key,
                "dims": len(embedding),
                "vector": embedding,
            }

        result_payload = {
            "doc_key": doc_key,
            "document_chars": len(doc_text),
        }
        result = {"messages": []}
        result_chars = len(doc_text) + len(doc_key)

        if ENABLE_CONTEXT_PACKETS:
            metrics.increment("context_packets_enabled")
            context_packet = build_context_packet(
                doc_key=doc_key,
                sub_query=sub_query,
                doc_text=doc_text,
                task_group=task_group,
                embedding_ref=doc_key,
            )
            result_payload.update({
                "summary": context_packet["summary"],
                "evidence_count": len(context_packet["evidence_spans"]),
                "query_coverage": context_packet["verification"]["query_coverage"],
                "reliable": context_packet["verification"]["reliable"],
                "original_chars": context_packet["original_chars"],
                "compressed_chars": context_packet["compressed_chars"],
                "compression_ratio": context_packet["compression_ratio"],
                "context_packets_enabled": True,
            })
            result["context_packets"] = [context_packet]
            result_chars = len(context_packet["summary"]) + len(doc_key)
            metrics.record_context_compression(
                original_chars=context_packet["original_chars"],
                compressed_chars=context_packet["compressed_chars"],
                source="researcher",
            )
        else:
            metrics.increment("context_packets_disabled")
            result_payload["context_packets_enabled"] = False
            result["documents"] = [doc_text] + related_docs[:1]
            result["document_payloads"] = [document_payload]

        msg = make_message(
            source="researcher", target="analyst",
            action=ActionType.RESEARCH,
            params={"sub_query": sub_query, "doc_key": doc_key},
            result=result_payload,
            task_group=task_group,
            embedding=embedding,
        )
        metrics.record_message(
            source="researcher", target="analyst", action="research",
            param_chars=len(sub_query) + len(doc_key),
            result_chars=result_chars,
            has_embedding=embedding is not None,
            embedding_dims=len(embedding) if embedding else 0,
        )
        result["messages"] = [msg.to_dict()]
        if embedding_payload:
            result["embedding_payloads"] = [embedding_payload]
        return result

    return {
        "documents": [doc_text] + related_docs[:1],
    }


# Backward-compatible alias for older scripts.
retriever = researcher
