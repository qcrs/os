"""StateGraph definition for the multi-agent research system.

Architecture:
  planner → [researcher_1 ∥ researcher_2 ∥ researcher_3] → analyst → executor → summarizer

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
from memory import create_store


# ─── Structured State Schema ───


class ResearchState(TypedDict, total=False):
    """Structured state passed between agents via Channels.

    mode="text": uses plan/sub_queries/documents/analysis/summary fields directly
    mode="structured": also uses messages and embedding_payload fields
    """
    # Input
    query: str
    source_context: str
    task_group: str
    task_topic: str
    analyst_instructions: str
    mode: str  # "text" | "structured" | "cache"

    # Planner output
    plan: str
    sub_queries: list[str]
    memory_hit: bool
    reduced_research: bool
    reused_memories: list[dict]
    reused_memory_ids: list[str]
    memory_validation: dict
    validated_memories: list[dict]
    validated_memory_ids: list[str]

    # Researcher output (accumulates via operator.add)
    documents: Annotated[list[str], operator.add]

    # Structured mode: raw document metadata for non-text ranking when compression is disabled
    document_payloads: Annotated[list[dict], operator.add]

    # Structured mode: compact context packets instead of full document passthrough
    context_packets: Annotated[list[dict], operator.add]

    # Analyst output
    analysis: str
    analysis_digest: str
    candidate_answers: dict[str, str]
    evidence: list[dict]
    task_state: dict
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
    # Each payload is {doc_key, vector, dims}; reducer accumulates parallel researchers.
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


# ─── Fan-out function for parallel research ───


def fan_out_research(state: ResearchState) -> list[Send]:
    """Dynamic fan-out: dispatch each sub-query to a parallel researcher.

    Uses Send (LangGraph primitive) for structured communication —
    each Send packet carries a typed dict, not free-form text.
    """
    sub_queries = state.get("sub_queries", [state.get("query", "")])
    query = state.get("query", "")
    source_context = state.get("source_context", "")
    task_group = state.get("task_group", "default")
    task_topic = state.get("task_topic", task_group)
    mode = state.get("mode", "text")
    return [
        Send("researcher", {
            "sub_query": sq,
            "query": query,
            "source_context": source_context,
            "task_group": task_group,
            "task_topic": task_topic,
            "mode": mode,
        })
        for sq in sub_queries
    ]


# Backward-compatible name for older docs/scripts that import it directly.
fan_out_retrieval = fan_out_research



# ─── Build the graph ───


def build_graph(mode: str = "text"):
    """Build and compile the multi-agent research graph.

    Args:
        mode: "text" for natural language passthrough,
              "structured" for AgentMessage-based protocol

    Returns a compiled graph with InMemoryStore for shared memory.
    """
    store = create_store()

    builder = StateGraph(ResearchState)

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

    builder = StateGraph(ResearchState)
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
