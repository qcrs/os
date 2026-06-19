"""StateGraph definition for the multi-agent research system.

Architecture:
  planner → [retriever_1 ∥ retriever_2 ∥ retriever_3] → executor → summarizer

Supports two communication modes:
  - "text": natural language passthrough (original behavior)
  - "structured": AgentMessage-based protocol with action types,
    structured params/results, and non-text embedding transfer
"""

import operator
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents import executor, planner, retriever, summarizer
from memory import create_store


# ─── Structured State Schema ───


class ResearchState(TypedDict, total=False):
    """Structured state passed between agents via Channels.

    mode="text": uses plan/sub_queries/documents/analysis/summary fields directly
    mode="structured": also uses messages and embedding_payload fields
    """
    # Input
    query: str
    task_group: str
    mode: str  # "text" | "structured"

    # Planner output
    plan: str
    sub_queries: list[str]
    planner_hidden_state: dict
    planner_hidden_state_summary: dict

    # Retriever output (accumulates via operator.add)
    documents: Annotated[list[str], operator.add]

    # Structured mode: raw document metadata for non-text ranking when compression is disabled
    document_payloads: Annotated[list[dict], operator.add]

    # Structured mode: compact context packets instead of full document passthrough
    context_packets: Annotated[list[dict], operator.add]

    # Executor output
    analysis: str
    evidence: list[dict]
    selected_context_packets: list[dict]
    hidden_guidance: dict

    # Summarizer output
    summary: str
    key_findings: list[str]

    # Structured mode: AgentMessage stream (accumulates via operator.add)
    messages: Annotated[list[dict], operator.add]

    # Structured mode: non-text embedding transfer (retriever → executor)
    # Each payload is {doc_key, vector, dims}; reducer accumulates parallel retrievers.
    embedding_payloads: Annotated[list[dict], operator.add]

    # Structured mode: non-text hidden-state transfer (retriever → executor)
    # Each payload is {ref_id, doc_key, source_agent, scope, hidden_state}.
    hidden_state_payloads: Annotated[list[dict], operator.add]


# ─── Fan-out function for parallel retrieval ───


def fan_out_retrieval(state: ResearchState) -> list[Send]:
    """Dynamic fan-out: dispatch each sub-query to a parallel retriever.

    Uses Send (LangGraph primitive) for structured communication —
    each Send packet carries a typed dict, not free-form text.
    """
    sub_queries = state.get("sub_queries", [state.get("query", "")])
    task_group = state.get("task_group", "default")
    mode = state.get("mode", "text")
    planner_hidden_state = state.get("planner_hidden_state")

    return [
        Send("retriever", {
            "sub_query": sq,
            "task_group": task_group,
            "mode": mode,
            "planner_hidden_state": planner_hidden_state,
        })
        for sq in sub_queries
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

    builder = StateGraph(ResearchState)

    # Add 4 agent nodes
    builder.add_node("planner", planner)
    builder.add_node("retriever", retriever)
    builder.add_node("executor", executor)
    builder.add_node("summarizer", summarizer)

    # Wire the graph
    builder.add_edge(START, "planner")

    # Planner → parallel retrievers (via Send fan-out)
    builder.add_conditional_edges("planner", fan_out_retrieval, ["retriever"])

    # All retrievers → executor (fan-in via Annotated[list, operator.add])
    builder.add_edge("retriever", "executor")

    # Executor → summarizer → END
    builder.add_edge("executor", "summarizer")
    builder.add_edge("summarizer", END)

    # Compile with shared store
    graph = builder.compile(store=store)

    return graph, store
