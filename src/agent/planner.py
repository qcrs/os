"""Planner agent for decomposing research tasks."""

import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langgraph.store.base import BaseStore

from config import NS_PLANS, NS_SUMMARIES
from memory import store_put, store_search
from metrics import metrics
from models import get_model
from protocol import ActionType, hash_text, make_message

from .shared import _get_mode, _normalize_sub_queries


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

    # Check if there's relevant prior knowledge in memory
    prior_results = store_search(store, NS_SUMMARIES, query, limit=2)
    prior_context = ""
    if prior_results:
        prior_context = "\n\n".join(
            f"[Prior knowledge from {r.key}]: {r.value.get('text', '')}"
            for r in prior_results
        )
        metrics.increment("memory_reuse_hits")

    model = get_model(temperature=0.5)
    parser = JsonOutputParser()

    messages = [
        SystemMessage(content="""You are a research planner. Given a research query,
break it down into a structured plan with exactly 3 specific sub-queries for information retrieval.
The 3 sub-queries should cover complementary aspects for downstream context
packet ranking and pruning.

Return ONLY valid JSON with this exact format:
{
  "plan": "A concise research plan describing the approach",
  "sub_queries": ["sub-query 1", "sub-query 2", "sub-query 3"]
}"""),
        HumanMessage(content=f"Research query: {query}"
                     + (f"\n\nPrior context:\n{prior_context}" if prior_context else "")),
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
        }

    plan = parsed.get("plan", "")
    sub_queries = _normalize_sub_queries(query, parsed.get("sub_queries", []))
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
        task_topic=query,
        summary=plan,
        tags=["plan", "planner", task_group],
    )

    duration = time.perf_counter() - t0
    metrics.record_timing("node_planner", duration)

    result = {
        "plan": plan,
        "sub_queries": sub_queries,
    }
    if mode == "structured":
        msg = make_message(
            source="planner", target="researcher",
            action=ActionType.PLAN,
            params={"query": query, "task_group": task_group},
            result={
                "plan": plan,
                "sub_queries": sub_queries,
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
