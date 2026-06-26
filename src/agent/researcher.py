"""Researcher agent for generating and packaging source material."""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from config import ENABLE_CONTEXT_PACKETS, ENABLE_EMBEDDING_TRANSFER, ENABLE_HIDDEN_STATE_TRANSFER, NS_DOCS
from memory import store_put, store_search
from metrics import metrics
from models import get_model
from protocol import ActionType, build_context_packet, hash_text, make_document_key, make_message, summarize_text

from .shared import (
    _extract_hidden_state,
    _get_mode,
    _hidden_state_alignment,
    _hidden_state_summary,
    _record_hidden_state_received,
)


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
    task_group = state.get("task_group", "default")
    planner_hidden_state = state.get("planner_hidden_state")
    _record_hidden_state_received("researcher", planner_hidden_state)

    capture_hidden = mode == "structured" and ENABLE_HIDDEN_STATE_TRANSFER
    model = get_model(temperature=0.3, capture_hidden=capture_hidden)

    messages = [
        SystemMessage(content="""You are a research source-material generator. Given a sub-query,
produce comprehensive, factual source material with key findings.
Return your response as plain text (3-5 paragraphs)."""),
        HumanMessage(content=f"Sub-query: {sub_query}"),
    ]

    response = model.invoke(messages)
    researcher_intent_hidden_state = _extract_hidden_state(response)
    intent_alignment = _hidden_state_alignment(planner_hidden_state, researcher_intent_hidden_state)
    if researcher_intent_hidden_state:
        metrics.increment("hidden_state_produced_researcher")
    if intent_alignment is not None:
        metrics.increment("hidden_state_alignment_scored_researcher")
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
        "task_group": task_group,
    },
        memory_type="document",
        source_agent="researcher",
        task_group=task_group,
        task_topic=sub_query,
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
    hidden_state_payload = None
    if researcher_intent_hidden_state:
        hidden_state_payload = {
            "ref_id": doc_key,
            "doc_key": doc_key,
            "source_agent": "researcher",
            "target_agent": "analyst",
            "scope": "research_intent",
            "sub_query": sub_query,
            "intent_alignment": intent_alignment,
            "hidden_state": researcher_intent_hidden_state,
        }
        document_payload["hidden_state_ref"] = doc_key
        document_payload["intent_alignment"] = intent_alignment

    # Search for related prior documents (memory reuse)
    related = store_search(store, NS_DOCS, sub_query, limit=3)
    related_docs = [r.value.get("text", "") for r in related if r.key != doc_key]
    if related_docs:
        metrics.increment("memory_reuse_hits")

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
            "planner_hidden_state": _hidden_state_summary(planner_hidden_state),
            "researcher_intent_hidden_state": _hidden_state_summary(researcher_intent_hidden_state),
            "intent_alignment": intent_alignment,
        }
        if hidden_state_payload:
            result_payload["hidden_state_ref"] = doc_key
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
            if hidden_state_payload:
                context_packet["hidden_state_ref"] = doc_key
                context_packet["intent_alignment"] = intent_alignment
                context_packet["retrieval_diagnostics"]["intent_alignment"] = intent_alignment
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
            hidden_state=planner_hidden_state,
        )
        metrics.record_message(
            source="researcher", target="analyst", action="research",
            param_chars=len(sub_query) + len(doc_key),
            result_chars=result_chars,
            has_embedding=embedding is not None,
            embedding_dims=len(embedding) if embedding else 0,
            has_hidden_state=planner_hidden_state is not None,
            hidden_state_dims=planner_hidden_state.get("dims", 0) if planner_hidden_state else 0,
        )
        result["messages"] = [msg.to_dict()]
        if embedding_payload:
            result["embedding_payloads"] = [embedding_payload]
        if hidden_state_payload:
            result["hidden_state_payloads"] = [hidden_state_payload]
            metrics.increment("hidden_state_payloads_sent")
        return result

    return {
        "documents": [doc_text] + related_docs[:1],
    }


# Backward-compatible alias for older scripts.
retriever = researcher
