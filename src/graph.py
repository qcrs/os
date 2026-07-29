"""StateGraph definition for the multi-agent research system.

Architecture:
  planner → researcher → analyst → executor → summarizer

Supports two communication modes:
  - "text": natural language passthrough (original behavior)
  - "structured": AgentMessage-based protocol with action types,
    structured params/results, and non-text embedding transfer
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agent import analyst, executor, planner, researcher, summarizer
from agent.cache_agents import (
    analyst_cache,
    context_prefill,
    executor_cache,
    planner_cache,
    researcher_cache,
    summarizer_cache,
)
from agent.shared import _normalize_sub_queries
from memory import create_store


# ─── Structured State Schema ───


class AgentWorkflowState(TypedDict, total=False):
    """Structured workflow state passed between agents via Channels.

    mode="text": uses plan/sub_queries/documents/analysis/summary fields directly
    mode="structured": also uses messages and embedding_payload fields
    """
    # Input
    query: str
    source_context: str
    task_group: str
    mode: str  # "text" | "structured" | "cache" | "latent_kv"

    # Planner output
    plan: str
    sub_queries: list[str]

    # Researcher output (accumulates via operator.add)
    documents: Annotated[list[str], operator.add]
    research_evidence: Annotated[list[dict], operator.add]

    # Structured mode: raw document metadata for non-text ranking when compression is disabled
    document_payloads: Annotated[list[dict], operator.add]

    # Structured mode: compact context packets instead of full document passthrough
    context_packets: Annotated[list[dict], operator.add]

    # Analyst output
    analysis: str
    analysis_digest: str
    candidate_answers: dict[str, str]
    evidence: list[dict]
    selected_context_packets: list[dict]

    # Executor output
    execution_code: str
    execution_result: dict
    execution_summary: str
    final_answer: str
    extracted_answers: dict[str, str]

    # Summarizer output
    summary: str
    key_findings: list[str]

    # Structured mode: AgentMessage stream (accumulates via operator.add)
    messages: Annotated[list[dict], operator.add]

    # Structured mode: non-text embedding transfer (researcher → analyst)
    # Each payload is {doc_key, vector, dims}; StateGraph accumulates parallel researchers.
    embedding_payloads: Annotated[list[dict], operator.add]


    # Cache mode: vLLM prefix-cache handoff state. The actual KV tensors stay
    # inside vLLM; agents pass only lightweight cache handles and trace metadata.
    active_cache: dict
    source_cache: dict
    planner_cache: dict
    researcher_cache: dict
    analyst_cache: dict
    executor_cache: dict
    summary_cache: dict
    cache_trace: Annotated[list[dict], operator.add]

    # Latent KV mode: handle ID for non-text KV state transfer (D mode)
    latent_kv_handle_id: str


# Backward-compatible name for older docs/scripts that import it directly.
ResearchState = AgentWorkflowState


# ─── Fan-out function for parallel research ───


def fan_out_research(state: AgentWorkflowState) -> list[Send]:
    """Dynamic fan-out: dispatch each sub-query to a parallel researcher.

    Uses Send (LangGraph primitive) for structured communication —
    each Send packet carries a typed dict, not free-form text.
    """
    sub_queries = _normalize_sub_queries(
        state.get("query", ""),
        state.get("sub_queries", [state.get("query", "")]),
    )
    task_group = state.get("task_group", "default")
    mode = state.get("mode", "text")
    return [
        Send("researcher", {
            "query": state.get("query", ""),
            "sub_query": sq,
            "plan": state.get("plan", ""),
            "task_group": task_group,
            "mode": mode,
            "source_context": state.get("source_context", ""),
            "latent_kv_handle_id": state.get("latent_kv_handle_id", ""),
        })
        for sq in sub_queries
    ]


# Backward-compatible name for older docs/scripts that import it directly.
fan_out_retrieval = fan_out_research


def fan_out_latent_explicit_research(state: AgentWorkflowState) -> list[Send]:
    """D-mode explicit research fan-out before latent KV starts.

    Research remains explicit structured data, so multiple researcher branches
    can fan in as context packets without requiring KV fork/merge.
    """
    clean_sub_queries = _normalize_sub_queries(
        state.get("query", ""),
        state.get("sub_queries", [state.get("query", "")]),
    )
    task_group = state.get("task_group", "latent_kv")
    return [
        Send("researcher", {
            "query": state.get("query", ""),
            "sub_query": sub_query,
            "plan": state.get("plan", ""),
            "task_group": task_group,
            "mode": "structured",
            "source_context": state.get("source_context", ""),
        })
        for sub_query in clean_sub_queries
    ]



# ─── Build the graph ───


def build_graph(mode: str = "text"):
    """Build and compile the multi-agent research graph.

    Args:
        mode: "text" for natural language passthrough,
              "structured" for AgentMessage-based protocol

    Returns a compiled graph with InMemoryStore for shared memory.
    """
    store = create_store()

    builder = StateGraph(AgentWorkflowState)

    # Add 5 agent nodes
    builder.add_node("planner", planner)
    builder.add_node("researcher", researcher)
    builder.add_node("analyst", analyst)
    builder.add_node("executor", executor)
    builder.add_node("summarizer", summarizer)

    # Wire the graph
    builder.add_edge(START, "planner")

    # Planner → parallel researchers (via Send fan-out)
    builder.add_conditional_edges("planner", fan_out_research, ["researcher"])

    # All researchers → analyst (fan-in via Annotated[list, operator.add])
    builder.add_edge("researcher", "analyst")

    # Analyst → executor → summarizer → END
    builder.add_edge("analyst", "executor")
    builder.add_edge("executor", "summarizer")
    builder.add_edge("summarizer", END)

    # Compile with shared store
    graph = builder.compile(store=store)

    return graph, store


def build_cache_graph():
    """Build a linear vLLM prefix-cache handoff graph.

    The cache graph is intentionally linear because vLLM KV cache state is tied
    to a single token prefix and cannot be merged across parallel branches.
    """
    store = create_store()

    builder = StateGraph(AgentWorkflowState)
    builder.add_node("context_prefill", context_prefill)
    builder.add_node("planner", planner_cache)
    builder.add_node("researcher", researcher_cache)
    builder.add_node("analyst", analyst_cache)
    builder.add_node("executor", executor_cache)
    builder.add_node("summarizer", summarizer_cache)

    builder.add_edge(START, "context_prefill")
    builder.add_edge("context_prefill", "planner")
    builder.add_edge("planner", "researcher")
    builder.add_edge("researcher", "analyst")
    builder.add_edge("analyst", "executor")
    builder.add_edge("executor", "summarizer")
    builder.add_edge("summarizer", END)

    graph = builder.compile(store=store)
    return graph, store


def build_latent_kv_graph():
    """Build latent KV graph (D mode) for non-text state transfer.

    Topology:
      planner(explicit structured) → researcher(explicit structured)
      → analyst_latent → executor_latent → summarizer_latent

    Planner/researcher communicate through explicit structured fields and
    compact context packets. Analyst performs the first latent KV prefill from
    those packets, then analyst/executor/summarizer pass Delta KV sequentially.
    """
    from agent.latent_kv_agents import (
        analyst_latent,
        executor_latent,
        planner_explicit_for_latent,
        researcher_explicit_for_latent,
        summarizer_latent,
    )

    store = create_store()
    builder = StateGraph(AgentWorkflowState)

    builder.add_node("planner", planner_explicit_for_latent)
    builder.add_node("researcher", researcher_explicit_for_latent)
    builder.add_node("analyst", analyst_latent)
    builder.add_node("executor", executor_latent)
    builder.add_node("summarizer", summarizer_latent)

    builder.add_edge(START, "planner")
    builder.add_conditional_edges("planner", fan_out_latent_explicit_research, ["researcher"])
    builder.add_edge("researcher", "analyst")
    builder.add_edge("analyst", "executor")
    builder.add_edge("executor", "summarizer")
    builder.add_edge("summarizer", END)

    graph = builder.compile(store=store)
    return graph, store
