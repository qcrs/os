"""Analyst agent for ranking context and producing evidence-based analysis."""

import re
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.store.base import BaseStore

from config import (
    ENABLE_CONTEXT_PACKETS,
    ENABLE_EMBEDDING_TRANSFER,
    NS_ANALYSIS,
    NS_DOCS,
)
from memory import store_get, store_put, store_search
from metrics import metrics
from models import get_model
from protocol import (
    ActionType,
    format_context_for_prompt,
    hash_text,
    make_message,
    select_context_packets,
    select_document_payloads,
    summarize_text,
    verify_context_packet,
)

from .shared import _get_mode


# ─── Analyst Agent ───


def analyst(state: dict, store: BaseStore) -> dict:
    """Analyze retrieved context and produce structured analysis.

    Text mode consumes full documents. Structured mode consumes compact context
    packets selected by the protocol using lexical and vector scores.
    """
    t0 = time.perf_counter()
    mode = _get_mode(state)

    query = state.get("query", "")
    plan = state.get("plan", "")
    documents = state.get("documents", [])
    document_payloads = state.get("document_payloads", [])
    context_packets = state.get("context_packets", [])
    embedding_payloads = state.get("embedding_payloads", [])
    task_group = state.get("task_group", "default")

    use_embeddings = mode == "structured" and ENABLE_EMBEDDING_TRANSFER and bool(embedding_payloads)
    if use_embeddings:
        metrics.increment("embedding_received", len(embedding_payloads))
    # Search for prior analyses (memory reuse)
    prior_analyses = store_search(store, NS_ANALYSIS, plan, limit=2)
    prior_context = ""
    if prior_analyses:
        prior_context = "\n\n".join(
            f"[Prior analysis {r.key}]: {summarize_text(r.value.get('text', ''), 360)}"
            for r in prior_analyses
        )
        metrics.increment("memory_reuse_hits")

    selected_packets = []
    verified_packets = []
    selected_documents = []
    verification_summary = {
        "checked": 0,
        "reliable": 0,
        "rehydrated": 0,
        "failed": 0,
        "missing_docs": [],
    }
    query_text = f"{query}\n{plan}"
    query_embedding = None
    if use_embeddings:
        try:
            from config import EMBEDDING_DIMS
            from memory import get_embeddings
            embedder = get_embeddings(dims=EMBEDDING_DIMS)
            query_embedding = embedder.embed_query(query_text[:500])
        except Exception:
            query_embedding = None

    use_context_packets = mode == "structured" and ENABLE_CONTEXT_PACKETS and bool(context_packets)
    if use_context_packets:
        selected_packets = select_context_packets(
            packets=context_packets,
            query_text=query_text,
            query_embedding=query_embedding,
            embedding_payloads=embedding_payloads if use_embeddings else None,
            top_k=3,
        )
        verified_packets, verification_summary = _verify_and_rehydrate_packets(
            selected_packets,
            store=store,
            query_text=query_text,
        )
        metrics.increment("context_packets_checked", verification_summary["checked"])
        metrics.increment("context_packets_reliable", verification_summary["reliable"])
        metrics.increment("context_packets_rehydrated", verification_summary["rehydrated"])
        metrics.increment("context_packets_failed", verification_summary["failed"])
        docs_text = format_context_for_prompt(verified_packets)
        original_chars = sum(p.get("original_chars", 0) for p in selected_packets)
        compressed_chars = len(docs_text)
        if original_chars:
            metrics.record_context_compression(
                original_chars=original_chars,
                compressed_chars=compressed_chars,
                source="analyst_prompt",
            )
        context_label = "Verified compact context packets"
    else:
        if mode == "structured":
            metrics.increment("context_packet_fallback_documents")
            selected_documents = select_document_payloads(
                documents=documents,
                document_payloads=document_payloads,
                query_text=query_text,
                query_embedding=query_embedding,
                embedding_payloads=embedding_payloads if use_embeddings else None,
                top_k=3,
            )
            if selected_documents:
                docs_text = "\n---\n".join(doc.get("text", "") for doc in selected_documents)
            else:
                docs_text = "\n---\n".join(documents) if documents else "No documents available."
            context_label = "Ranked documents" if selected_documents else "Documents"
        else:
            docs_text = "\n---\n".join(documents) if documents else "No documents available."
            context_label = "Documents"

    model = get_model(temperature=0.4)
    parser = JsonOutputParser()

    answer_format = _extract_answer_format(query)
    required_answer_fields = _required_answer_fields(answer_format)
    answer_instruction = (
        "\nIf the original query specifies an Expected answer format, populate "
        "candidate_answers as a JSON object whose keys are exactly those @field "
        "names and whose values are scalar strings. Do not wrap these values in "
        "@field[...] tags."
        if required_answer_fields else
        "\nNo machine-graded @field[value] answer format is required for this query."
    )

    messages = [
        SystemMessage(content=f"""You are a research analyst. Given a research plan
and selected context, produce a structured analysis. Use only evidence marked reliable
or rehydrated from Store. Cite `doc_key#span_id` for each claim. If coverage is
insufficient, explicitly state the limitation instead of guessing.
The evidence list contains extractive source spans in `[doc_key#span_id] text` format.{answer_instruction}

Return ONLY valid JSON:
{{
  "analysis": "A comprehensive analysis paragraph",
  "candidate_answers": {{"field_name": "scalar_value"}},
  "evidence": [
    {{"claim": "Key claim 1", "support": "Supporting evidence", "doc_key": "doc id", "span_id": "ev1"}},
    {{"claim": "Key claim 2", "support": "Supporting evidence", "doc_key": "doc id", "span_id": "ev2"}}
  ],
  "confidence": 0.85
}}"""),
        HumanMessage(content=f"Original query: {query}\nRequired answer fields: {required_answer_fields}\nExpected answer format: {answer_format or 'N/A'}\nPlan: {plan}\n\n{context_label}:\n{docs_text}"
                     + (f"\n\nPrior analyses:\n{prior_context}" if prior_context else "")),
    ]

    response = model.invoke(messages)
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        metrics.record_tokens("analyst", um.get("input_tokens", 0), um.get("output_tokens", 0))
    try:
        parsed = parser.invoke(response)
    except Exception:
        parsed = {
            "analysis": f"Analysis based on: {plan}",
            "candidate_answers": {},
            "evidence": [{"claim": "Key finding", "support": "From selected context"}],
            "confidence": 0.7,
        }

    analysis = parsed.get("analysis", "")
    candidate_answers = _clean_candidate_answers(
        parsed.get("candidate_answers", {}),
        required_answer_fields,
    )
    evidence = parsed.get("evidence", [])
    analysis_digest = summarize_text(analysis, 520)
    analysis_memory_id = f"analysis_{task_group}_{hash_text(query or plan)}"
    selected_doc_keys = [
        item.get("doc_key")
        for item in (verified_packets if verified_packets else selected_documents)
    ]

    store_put(store, NS_ANALYSIS, analysis_memory_id, {
        "text": analysis,
        "digest": analysis_digest,
        "candidate_answers": candidate_answers,
        "evidence": evidence,
        "plan": plan,
        "selected_doc_keys": selected_doc_keys,
        "context_verification": verification_summary,
    },
        memory_type="analysis",
        source_agent="analyst",
        task_group=task_group,
        task_topic=query,
        summary=analysis_digest,
        tags=["analysis", "analyst", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_analyst", duration)

    result = {
        "analysis": analysis,
        "analysis_digest": analysis_digest,
        "candidate_answers": candidate_answers,
        "evidence": evidence,
    }
    if mode == "structured":
        msg = make_message(
            source="analyst", target="executor",
            action=ActionType.ANALYZE,
            params={
                "plan": plan,
                "selected_doc_keys": selected_doc_keys,
                "context_packet_count": len(context_packets),
                "verified_packet_count": len(verified_packets),
                "answer_fields": required_answer_fields,
            },
            result={
                "analysis_digest": analysis_digest,
                "analysis_chars": len(analysis),
                "evidence_count": len(evidence),
                "context_reliable": verification_summary["reliable"],
                "context_rehydrated": verification_summary["rehydrated"],
            },
            task_group=task_group,
        )
        metrics.record_message(
            source="analyst", target="executor", action="analyze",
            param_chars=len(plan) + sum(len(str(doc_key)) for doc_key in selected_doc_keys),
            result_chars=len(analysis_digest) + len(str(len(evidence))),
            has_embedding=False,
        )
        result["messages"] = [msg.to_dict()]
        result["selected_context_packets"] = verified_packets
        if selected_documents:
            result["selected_documents"] = [
                {key: doc.get(key) for key in ("doc_key", "score", "score_components", "original_chars")}
                for doc in selected_documents
            ]
        result["context_verification"] = verification_summary

    return result

def _verify_and_rehydrate_packets(
    packets: list[dict],
    *,
    store: BaseStore,
    query_text: str,
) -> tuple[list[dict], dict]:
    """Verify packet refs against Store and add fallback evidence when needed."""
    verified_packets = []
    summary = {
        "checked": 0,
        "reliable": 0,
        "rehydrated": 0,
        "failed": 0,
        "missing_docs": [],
    }

    for packet in packets:
        summary["checked"] += 1
        doc_key = packet.get("doc_key", "")
        doc_item = store_get(store, NS_DOCS, doc_key) if doc_key else None
        if doc_item is None:
            failed_packet = dict(packet)
            failed_packet["verification"] = {
                "reliable": False,
                "requires_full_doc_lookup": True,
                "reason": "missing_full_document",
            }
            verified_packets.append(failed_packet)
            summary["failed"] += 1
            summary["missing_docs"].append(doc_key)
            continue

        doc_text = doc_item.value.get("text", "")
        enriched_packet = dict(packet)
        verification = verify_context_packet(
            enriched_packet,
            doc_text,
            query_text=query_text,
        )
        enriched_packet["verification"] = verification

        if verification["reliable"]:
            summary["reliable"] += 1
            verified_packets.append(enriched_packet)
            continue

        rehydrated_packet = _rehydrate_packet_from_store(enriched_packet, doc_text)
        summary["rehydrated"] += 1
        verified_packets.append(rehydrated_packet)

    return verified_packets, summary


def _rehydrate_packet_from_store(packet: dict, doc_text: str) -> dict:
    """Attach a bounded full-document fallback when compact evidence is insufficient."""
    rehydrated = dict(packet)
    fallback_chars = 360
    fallback_source = doc_text[:fallback_chars]
    fallback_text = summarize_text(fallback_source, fallback_chars)
    fallback_ref = {
        "doc_key": packet.get("doc_key"),
        "char_start": 0,
        "char_end": len(fallback_source),
        "text_hash": hash_text(fallback_text),
    }
    rehydrated["evidence_spans"] = list(packet.get("evidence_spans", [])) + [{
        "span_id": "rehydrated_full_doc_head",
        "text": fallback_text,
        "score": 0.0,
        "matched_terms": [],
        "source_ref": fallback_ref,
        "retrieval_method": "store_rehydration",
    }]
    rehydrated["summary"] = (
        f"{packet.get('summary', '')}\n"
        "Fallback from Store because compact evidence did not pass verification: "
        f"{fallback_text}"
    ).strip()
    rehydrated["verification"] = dict(packet.get("verification", {}), rehydrated=True)
    return rehydrated


def _extract_answer_format(query: str) -> str:
    """Extract the expected @field[value] format from the task query."""
    marker = "Expected answer format:"
    if marker not in query:
        return ""
    tail = query.split(marker, 1)[1]
    stop_marker = "\nSample data"
    if stop_marker in tail:
        tail = tail.split(stop_marker, 1)[0]
    return " ".join(tail.strip().split())


def _required_answer_fields(answer_format: str) -> list[str]:
    """Return field names required by an @field[...] answer format."""
    fields = []
    seen = set()
    for field in re.findall(r"@(\w+)\[", answer_format or ""):
        if field in seen:
            continue
        seen.add(field)
        fields.append(field)
    return fields


def _clean_candidate_answers(value: object, required_fields: list[str]) -> dict[str, str]:
    """Normalize analyst-proposed answer fields to scalar strings."""
    if not isinstance(value, dict):
        text = str(value or "")
        extracted = dict(re.findall(r"@(\w+)\[([^\]]*)\]", text))
        value = extracted
    allowed = set(required_fields) if required_fields else set(value)
    cleaned = {}
    for key, raw in value.items():
        field = str(key).strip().lstrip("@").split("[", 1)[0]
        if not field or field not in allowed:
            continue
        if isinstance(raw, (list, dict)):
            text = str(raw)
        else:
            text = str(raw).strip()
        tag_match = re.fullmatch(r"@(\w+)\[([^\]]*)\]", text)
        cleaned[field] = tag_match.group(2).strip() if tag_match else text
    return cleaned
