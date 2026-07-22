"""Planner agent for decomposing research tasks."""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.store.base import BaseStore

from config import (
    LONG_TERM_MEMORY_TOP_K,
    NS_ANALYSIS,
    NS_PLANS,
    NS_SUMMARIES,
    PERSISTENT_MEMORY_ENABLED,
    PLANNER_MEMORY_CONFIDENCE_THRESHOLD,
    REDUCE_RESEARCH_ON_MEMORY_HIT,
)
from memory import qdrant_search, store_put, store_search
from metrics import metrics
from models import get_model
from protocol import ActionType, hash_text, make_message, summarize_text

from .shared import _get_mode, _memory_lookup_query, _normalize_sub_queries


# ─── Planner Agent ───

def planner(state: dict, store: BaseStore) -> dict:
    """Break down a research query into structured sub-queries.

    Role: Planning
    Input: query (str)
    Output: plan (str), sub_queries (list[str])
    Memory: writes plan to Store under ("plans",)
    """
    t0 = time.perf_counter()
    mode = _get_mode(state)

    query = state["query"]
    task_group = state.get("task_group", "default")
    task_topic = state.get("task_topic") or task_group
    memory_query = _memory_lookup_query(query)

    prior_context = ""
    reused_memories = []

    # Check if there's relevant prior knowledge in Qdrant-backed memory.
    for memory_type in ("summary", "analysis"):
        prior_results = qdrant_search(
            memory_query,
            memory_type=memory_type,
            top_k=LONG_TERM_MEMORY_TOP_K,
        )
        if not prior_results:
            continue
        prior_context = "\n\n".join(
            part for part in (
                prior_context,
                _format_qdrant_memory_context(prior_results, memory_type),
            )
            if part
        )
        reused_memories.extend(
            _memory_handoff_item(
                memory_id=r.id,
                memory_type=r.payload.memory_type,
                source_agent=r.payload.source_agent,
                source_task_id=r.payload.source_task_id,
                task_topic=r.payload.task_topic,
                content=r.payload.content,
                score=r.score,
                source="qdrant",
            )
            for r in prior_results
        )
    if PERSISTENT_MEMORY_ENABLED:
        for namespace, memory_type in (
            (NS_SUMMARIES, "summary"),
            (NS_ANALYSIS, "analysis"),
        ):
            store_results = store_search(store, namespace, memory_query, limit=2)
            if not store_results:
                continue
            store_context = "\n\n".join(
                f"[Memory id={r.key}; source=store; type={memory_type}; score={r.score:.4f}]: "
                f"{r.value.get('text', '')}"
                for r in store_results
            )
            prior_context = "\n\n".join(part for part in (prior_context, store_context) if part)
            reused_memories.extend(
                _memory_handoff_item(
                    memory_id=r.key,
                    memory_type=memory_type,
                    source_agent=str(r.value.get("source_agent", memory_type)),
                    source_task_id=r.key,
                    task_topic=str(r.value.get("task_topic", task_topic)),
                    content=r.value.get("text", ""),
                    score=r.score,
                    source="store",
                )
                for r in store_results
            )
    if reused_memories:
        metrics.increment("memory_reuse_attempts")
        metrics.increment("memory_candidates_found", len(reused_memories))

    model = get_model(temperature=0.5)
    parser = JsonOutputParser()

    messages = [
        SystemMessage(content="""You are a research planner. Given a research query,
break it down into a structured plan with specific sub-queries for information retrieval.
You may receive candidate memories. First decide whether any candidate memory is
actually reusable for the current task. Mark memory reusable only when it matches
the same task family/entity/table pattern or contains a directly reusable method.
Summary memories describe prior final outcomes. Analysis memories describe prior
reasoning, calculation methods, selected evidence, or answer patterns. Use either
only when it can reduce repeated work without replacing current source evidence.
Do not mark a memory reusable merely because some keywords overlap.

If no memory is reusable, return exactly 3 complementary sub-queries for
downstream context ranking and pruning. If memory is reusable, return exactly
1 sub-query focused on verifying missing details or resolving uncertainty.

Return ONLY valid JSON with this exact format:
{
  "plan": "A concise research plan describing the approach",
  "sub_queries": ["sub-query 1", "sub-query 2", "sub-query 3"],
  "memory_validation": {
    "usable": false,
    "confidence": 0.0,
    "reason": "why the candidate memories are or are not reusable",
    "reused_memory_ids": []
  }
}"""),
        HumanMessage(content=f"Research query: {query}"
                     + (f"\n\nCandidate memories:\n{prior_context}" if prior_context else "")),
    ]

    response = model.invoke(messages)
    # Record LLM token usage
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        um = response.usage_metadata
        metrics.record_tokens("planner", um.get("input_tokens", 0), um.get("output_tokens", 0))
    try:
        parsed = parser.invoke(response)
    except Exception:
        parsed = {
            "plan": f"Research plan for: {query}",
            "sub_queries": [
                f"What is {query}?",
                f"What are the key features of {query}?",
                f"What are the applications of {query}?",
            ],
            "memory_validation": {
                "usable": False,
                "confidence": 0.0,
                "reason": "planner output could not be parsed",
                "reused_memory_ids": [],
            },
        }

    plan = parsed.get("plan", "")
    sub_queries = _normalize_sub_queries(query, parsed.get("sub_queries", []))
    memory_validation, validated_memories = _normalize_memory_validation(parsed, reused_memories)
    memory_hit = bool(validated_memories)
    if reused_memories and memory_hit:
        metrics.increment("memory_reuse_hits")
        metrics.increment("planner_memory_validated")
    elif reused_memories:
        metrics.increment("planner_memory_rejected")
    reduced_research = bool(memory_hit and REDUCE_RESEARCH_ON_MEMORY_HIT)
    original_sub_query_count = len(sub_queries)
    if reduced_research:
        sub_queries = sub_queries[:1]
        saved = max(original_sub_query_count - len(sub_queries), 0)
        metrics.increment("research_fanout_reduced")
        metrics.increment("research_subqueries_saved", saved)
    plan_memory_id = f"plan_{task_group}_{hash_text(query)}"

    # Write plan to shared memory
    store_put(store, NS_PLANS, plan_memory_id, {
        "text": plan,
        "sub_queries": sub_queries,
        "query": query,
    },
        memory_type="plan",
        source_agent="planner",
        task_group=task_group,
        task_topic=task_topic,
        summary=plan,
        tags=["plan", "planner", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_planner", duration)

    result = {
        "plan": plan,
        "sub_queries": sub_queries,
        "memory_hit": memory_hit,
        "reduced_research": reduced_research,
        "reused_memories": reused_memories,
        "reused_memory_ids": [item["id"] for item in reused_memories],
        "memory_validation": memory_validation,
        "validated_memories": validated_memories,
        "validated_memory_ids": [item["id"] for item in validated_memories],
    }
    if mode == "structured":
        msg = make_message(
            source="planner", target="researcher",
            action=ActionType.PLAN,
            params={"query": query, "task_group": task_group},
            result={
                "plan": plan,
                "sub_queries": sub_queries,
                "memory_hit": memory_hit,
                "reduced_research": reduced_research,
                "reused_memory_ids": [item["id"] for item in reused_memories],
                "validated_memory_ids": [item["id"] for item in validated_memories],
                "memory_validation": memory_validation,
            },
            task_group=task_group,
        )
        metrics.record_message(
            source="planner", target="researcher", action="plan",
            param_chars=len(query), result_chars=len(plan) + sum(len(s) for s in sub_queries),
            has_embedding=False,
        )
        result["messages"] = [msg.to_dict()]

    return result


def _normalize_memory_validation(parsed: dict, candidates: list[dict]) -> tuple[dict, list[dict]]:
    """Validate planner-selected memories and return only reusable candidates."""
    raw = parsed.get("memory_validation", {})
    if not isinstance(raw, dict):
        raw = {}

    candidate_by_id = {str(item.get("id")): item for item in candidates if item.get("id")}
    raw_ids = raw.get("reused_memory_ids", [])
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    selected_ids = [
        str(memory_id)
        for memory_id in raw_ids
        if str(memory_id) in candidate_by_id
    ] if isinstance(raw_ids, list) else []

    confidence = _as_float(raw.get("confidence"), 0.0)
    usable = _as_bool(raw.get("usable")) and confidence >= PLANNER_MEMORY_CONFIDENCE_THRESHOLD
    if not usable:
        selected_ids = []

    validation = {
        "usable": bool(usable and selected_ids),
        "confidence": round(confidence, 4),
        "reason": summarize_text(str(raw.get("reason", "") or ""), 240),
        "reused_memory_ids": selected_ids if usable else [],
        "threshold": PLANNER_MEMORY_CONFIDENCE_THRESHOLD,
    }
    validated = [candidate_by_id[memory_id] for memory_id in selected_ids] if validation["usable"] else []
    return validation, validated


def _as_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _format_qdrant_memory_context(results: list, memory_type: str) -> str:
    return "\n\n".join(
        f"[Memory id={r.id}; source=qdrant; type={memory_type}; "
        f"source_task={r.payload.source_task_id}; score={r.score:.4f}]: "
        f"{r.payload.content}"
        for r in results
    )


def _memory_handoff_item(
    *,
    memory_id: str,
    memory_type: str,
    source_agent: str,
    source_task_id: str,
    task_topic: str,
    content: object,
    score: float,
    source: str,
) -> dict:
    """Compact planner-selected memory for downstream agents."""
    return {
        "id": str(memory_id),
        "memory_type": str(memory_type),
        "source": source,
        "source_agent": str(source_agent),
        "source_task_id": str(source_task_id),
        "task_topic": summarize_text(str(task_topic or ""), 160),
        "score": round(float(score or 0.0), 4),
        "content": summarize_text(str(content or ""), 420),
    }
