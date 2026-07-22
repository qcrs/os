"""Analyst agent for ranking context and producing evidence-based analysis."""

import json
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
    LONG_TERM_TASK_STATE_ENABLED,
    PERSISTENT_MEMORY_ENABLED,
)
from memory import qdrant_add_from_payload, store_get, store_put
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


DEFAULT_TASK_STATE = {
    "entities": {},
    "interfaces": {},
    "decisions": [],
    "constraints": [],
    "invariants": [],
    "next_requirements": [],
}


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
    analyst_instructions = str(state.get("analyst_instructions", "") or "").strip()
    validated_memories = state.get("validated_memories", []) or []
    planner_memory_context = _format_validated_memories(validated_memories)
    task_group = state.get("task_group", "default")
    task_topic = state.get("task_topic") or task_group
    query_text = f"{task_topic}\n{query}\n{plan}"

    use_embeddings = mode == "structured" and ENABLE_EMBEDDING_TRANSFER and bool(embedding_payloads)
    if use_embeddings:
        metrics.increment("embedding_received", len(embedding_payloads))

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
        "@field[...] tags. Each value must be the final answer for that field, "
        "not an intermediate source value or unevaluated expression."
        if required_answer_fields else
        "\nNo machine-graded @field[value] answer format is required for this query."
    )
    task_state_instruction = (
        "\nIf prior task_state is provided, use it as consistency context: preserve stable "
        "entities, interfaces, decisions, constraints, and invariants unless the current "
        "task explicitly changes them. Store only stable reusable state, not transient "
        "reasoning, in task_state."
        if LONG_TERM_TASK_STATE_ENABLED else
        ""
    )
    task_state_schema = (
        """,
  "task_state": {
    "entities": {},
    "interfaces": {},
    "decisions": [],
    "constraints": [],
    "invariants": [],
    "next_requirements": []
  }"""
        if LONG_TERM_TASK_STATE_ENABLED else
        ""
    )

    messages = [
        SystemMessage(content=f"""You are a research analyst. Given a research plan
and selected context, produce a structured analysis. Use only evidence marked reliable
or rehydrated from Store. Cite `doc_key#span_id` for each claim. If coverage is
insufficient, explicitly state the limitation instead of guessing.
Planner-validated reusable memories are hints for reusable methods, known stable
decisions, or prior answer patterns. They are not evidence; current selected
context overrides memory for source values and citations.
The evidence list contains extractive source spans in `[doc_key#span_id] text` format.{task_state_instruction}{answer_instruction}
{f'''
Task-specific analyst instructions:
{analyst_instructions}
''' if analyst_instructions else ''}

Return ONLY valid JSON:
{{
  "analysis": "A comprehensive analysis paragraph",
  "candidate_answers": {{"field_name": "scalar_value"}},
  "evidence": [
    {{"claim": "Key claim 1", "support": "Supporting evidence", "doc_key": "doc id", "span_id": "ev1"}},
    {{"claim": "Key claim 2", "support": "Supporting evidence", "doc_key": "doc id", "span_id": "ev2"}}
  ]{task_state_schema},
  "confidence": 0.85
}}"""),
        HumanMessage(content=f"Original query: {query}\nRequired answer fields: {required_answer_fields}\nExpected answer format: {answer_format or 'N/A'}\nPlan: {plan}\n\n{context_label}:\n{docs_text}"
                     + (f"\n\nPlanner-validated reusable memories:\n{planner_memory_context}" if planner_memory_context else "")),
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
            "task_state": dict(DEFAULT_TASK_STATE),
            "confidence": 0.7,
        }

    analysis = parsed.get("analysis", "")
    candidate_answers = _clean_candidate_answers(
        parsed.get("candidate_answers", {}),
        required_answer_fields,
    )
    evidence = parsed.get("evidence", [])
    task_state = (
        _clean_task_state(parsed.get("task_state", {}))
        if LONG_TERM_TASK_STATE_ENABLED else
        {}
    )
    analysis_digest = summarize_text(analysis, 520)
    analysis_memory_id = f"analysis_{task_group}_{hash_text(query or plan)}"
    selected_doc_keys = [
        item.get("doc_key")
        for item in (verified_packets if verified_packets else selected_documents)
    ]

    analysis_memory_payload = {
        "text": analysis,
        "digest": analysis_digest,
        "candidate_answers": candidate_answers,
        "evidence": evidence,
        "plan": plan,
        "selected_doc_keys": selected_doc_keys,
        "context_verification": verification_summary,
        "query": query,
        "task_topic": task_topic,
    }
    qdrant_add_from_payload(
        key=analysis_memory_id,
        value=analysis_memory_payload,
        memory_type="analysis",
        source_agent="analyst",
        task_group=task_group,
        task_topic=task_topic,
        summary=analysis_digest,
        tags=["analysis", "analyst", task_group],
    )
    if PERSISTENT_MEMORY_ENABLED:
        store_put(
            store,
            NS_ANALYSIS,
            analysis_memory_id,
            analysis_memory_payload,
            memory_type="analysis",
            source_agent="analyst",
            task_group=task_group,
            task_topic=task_topic,
            summary=analysis_digest,
            tags=["analysis", "analyst", task_group],
        )
    if LONG_TERM_TASK_STATE_ENABLED:
        task_state_text = json.dumps(task_state, ensure_ascii=False, sort_keys=True)
        task_state_memory_payload = {
            "text": task_state_text,
            "task_state": task_state,
            "query": query,
            "task_topic": task_topic,
            "plan": plan,
            "analysis_digest": analysis_digest,
            "selected_doc_keys": selected_doc_keys,
        }
        qdrant_add_from_payload(
            key=f"task_state_{task_group}_{hash_text(query or plan)}",
            value=task_state_memory_payload,
            memory_type="task_state",
            source_agent="analyst",
            task_group=task_group,
            task_topic=task_topic,
            summary=summarize_text(task_state_text, 900),
            tags=["task_state", "analyst", task_group],
        )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_analyst", duration)

    result = {
        "analysis": analysis,
        "analysis_digest": analysis_digest,
        "candidate_answers": candidate_answers,
        "evidence": evidence,
    }
    if LONG_TERM_TASK_STATE_ENABLED:
        result["task_state"] = task_state
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


def _format_validated_memories(memories: list[dict], limit: int = 2) -> str:
    """Format planner-approved memories as compact downstream hints."""
    lines = []
    for item in memories[:limit]:
        memory_id = str(item.get("id", ""))
        memory_type = str(item.get("memory_type", "memory"))
        source_task_id = str(item.get("source_task_id", ""))
        score = item.get("score", 0.0)
        content = summarize_text(item.get("content", ""), 320)
        lines.append(
            f"[{memory_type} id={memory_id}; source_task={source_task_id}; "
            f"retrieval_score={score}] {content}"
        )
    return "\n".join(lines)

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


def _clean_task_state(value: object) -> dict:
    """Normalize model-provided reusable task state to the expected schema."""
    if not isinstance(value, dict):
        value = {}
    return {
        "entities": value.get("entities") if isinstance(value.get("entities"), dict) else {},
        "interfaces": value.get("interfaces") if isinstance(value.get("interfaces"), dict) else {},
        "decisions": _string_list(value.get("decisions")),
        "constraints": _string_list(value.get("constraints")),
        "invariants": _string_list(value.get("invariants")),
        "next_requirements": _string_list(value.get("next_requirements")),
    }


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


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
