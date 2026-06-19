#!/usr/bin/env python3
"""Multi-Agent Research System Demo

Demonstrates 6 requirements using LangGraph + DeepSeek V4:

1. 3+ Agents: planner, retriever (parallel), executor, summarizer
2. Structured communication: AgentMessage protocol with action types
3. Non-text state: embedding vectors passed directly between agents
4. Shared memory: InMemoryStore with semantic search
5. 2 related task groups: B reuses A's memory
6. Performance metrics: dual-mode comparison (text vs structured)

Usage:
    export DEEPSEEK_API_KEY="your-deepseek-key-here"
    export DASHSCOPE_API_KEY="your-dashscope-key-here"
    python run_demo.py
"""

import json
import os
import sys
import time

# Add src directory to path for local imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config import EMBEDDING_DIMS, EMBEDDING_MODEL, NS_SUMMARIES, TASK_GROUP_A, TASK_GROUP_B
from graph import build_graph
from memory import store_search
from metrics import metrics
from protocol import create_default_registry


def run_task_group(graph, store, task_group: str, query: str, mode: str = "text") -> dict:
    """Run a single task group and collect metrics."""
    print(f"\n{'='*70}")
    print(f"[{mode.upper()} MODE] Task Group {task_group}: {query}")
    print(f"{'='*70}")

    t0 = time.perf_counter()
    result = graph.invoke({
        "query": query,
        "task_group": task_group,
        "mode": mode,
    })
    duration = time.perf_counter() - t0

    metrics.record_timing(f"task_{task_group}", duration)

    print(f"\n  [Planner]")
    print(f"    Plan: {result.get('plan', 'N/A')[:120]}...")
    print(f"    Sub-queries: {result.get('sub_queries', [])}")

    print(f"\n  [Retrievers] (parallel fan-out)")
    docs = result.get("documents", [])
    print(f"    Retrieved {len(docs)} document(s)")
    for i, doc in enumerate(docs[:2]):
        print(f"    Doc {i+1}: {doc[:80]}...")

    print(f"\n  [Executor]")
    print(f"    Analysis: {result.get('analysis', 'N/A')[:120]}...")
    evidence = result.get("evidence", [])
    print(f"    Evidence: {len(evidence)} item(s)")

    print(f"\n  [Summarizer]")
    print(f"    Summary: {result.get('summary', 'N/A')[:120]}...")
    findings = result.get("key_findings", [])
    print(f"    Key findings: {len(findings)}")
    for f in findings[:3]:
        print(f"      - {f[:80]}")

    print(f"\n  Task duration: {duration:.2f}s")

    # Show structured messages if in structured mode
    if mode == "structured":
        msgs = result.get("messages", [])
        print(f"\n  [Structured Messages] {len(msgs)} AgentMessage(s)")
        for m in msgs:
            action = m.get("action", "?")
            src = m.get("source", "?")
            tgt = m.get("target", "?")
            emb = "✓embedding" if m.get("embedding") else ""
            print(f"    {src} →{tgt} [{action}] {emb}")

    return result


def demonstrate_memory_reuse(graph, store, query: str):
    """Show that the store contains reusable memories."""
    print(f"\n{'='*70}")
    print(f"Memory Reuse Demonstration")
    print(f"{'='*70}")

    print(f"\n  Searching store for: '{query}'")
    results = store_search(store, NS_SUMMARIES, query, limit=3)

    if results:
        print(f"  Found {len(results)} relevant memory item(s):")
        for r in results:
            print(f"    - [{r.key}] score={r.score:.4f}")
            text = r.value.get("text", "")
            print(f"      {text[:100]}...")
    else:
        print("  No relevant memories found.")

    # List all namespaces in the store
    print(f"\n  All stored memories:")
    for ns in [NS_SUMMARIES, ("plans",), ("docs",), ("analysis",)]:
        items = list(store.search(ns, limit=10))
        print(f"    namespace {ns}: {len(items)} item(s)")


def print_comparison(text_summary: dict, struct_summary: dict):
    """Print side-by-side comparison of text vs structured mode."""
    print(f"\n{'='*70}")
    print("DUAL-MODE COMPARISON: Text vs Structured")
    print(f"{'='*70}")

    headers = ["Metric", "Text Mode", "Structured Mode", "Difference"]
    rows = [
        ("LLM calls", str(text_summary["llm_calls"]),
         str(struct_summary["llm_calls"]),
         f"{struct_summary['llm_calls'] - text_summary['llm_calls']:+d}"),
        ("Input tokens", str(text_summary["input_tokens"]),
         str(struct_summary["input_tokens"]),
         f"{struct_summary['input_tokens'] - text_summary['input_tokens']:+d}"),
        ("Output tokens", str(text_summary["output_tokens"]),
         str(struct_summary["output_tokens"]),
         f"{struct_summary['output_tokens'] - text_summary['output_tokens']:+d}"),
        ("Total tokens", str(text_summary["total_tokens"]),
         str(struct_summary["total_tokens"]),
         f"{struct_summary['total_tokens'] - text_summary['total_tokens']:+d}"),
        ("Agent messages", str(text_summary["message_count"]),
         str(struct_summary["message_count"]),
         f"+{struct_summary['message_count'] - text_summary['message_count']}"),
        ("Protocol chars", str(text_summary["param_chars"] + text_summary["result_chars"]),
         str(struct_summary["param_chars"] + struct_summary["result_chars"]),
         f"{(struct_summary['param_chars'] + struct_summary['result_chars']) - (text_summary['param_chars'] + text_summary['result_chars']):+d}"),
        ("Embedding transfers", str(text_summary["embedding_transfers"]),
         str(struct_summary["embedding_transfers"]),
         f"+{struct_summary['embedding_transfers']}"),
        ("Context original chars", str(text_summary.get("context_original_chars", 0)),
         str(struct_summary.get("context_original_chars", 0)),
         f"+{struct_summary.get('context_original_chars', 0) - text_summary.get('context_original_chars', 0)}"),
        ("Context compressed chars", str(text_summary.get("context_compressed_chars", 0)),
         str(struct_summary.get("context_compressed_chars", 0)),
         f"+{struct_summary.get('context_compressed_chars', 0) - text_summary.get('context_compressed_chars', 0)}"),
        ("Context saved chars", str(text_summary.get("context_saved_chars", 0)),
         str(struct_summary.get("context_saved_chars", 0)),
         f"+{struct_summary.get('context_saved_chars', 0)}"),
        ("Memory reuse hits", str(text_summary["memory_reuse_hits"]),
         str(struct_summary["memory_reuse_hits"]),
         f"{struct_summary['memory_reuse_hits'] - text_summary['memory_reuse_hits']:+d}"),
        ("Total task time", f"{text_summary['total_task_time']:.2f}s",
         f"{struct_summary['total_task_time']:.2f}s",
         f"{struct_summary['total_task_time'] - text_summary['total_task_time']:+.2f}s"),
    ]

    # Print table
    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(f"  {header_line}")
    print(f"  {'-+-'.join('-' * w for w in col_widths)}")
    for row in rows:
        print(f"  {' | '.join(v.ljust(w) for v, w in zip(row, col_widths))}")


def main():
    """Run the full multi-agent demo with dual-mode comparison."""
    print("=" * 70)
    print("Multi-Agent Research System Demo")
    print("LangGraph + DeepSeek V4 | Dual-Mode Comparison")
    print("=" * 70)

    # Check API key
    deepseek_api_key = os.getenv("DEEPSEEK_API_KEY", "")
    if not deepseek_api_key:
        print("\n[WARNING] DEEPSEEK_API_KEY not set.")
        print("  The demo will run but LLM calls will fail.")
        print("  Set it with: export DEEPSEEK_API_KEY='your-key'")
        print()
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY", "")
    if not dashscope_api_key:
        print("\n[WARNING] DASHSCOPE_API_KEY not set.")
        print("  The demo requires it for text-embedding-v4 semantic memory.")
        print("  Set it with: export DASHSCOPE_API_KEY='your-key'")
        print()

    # Show agent registry (capability discovery)
    registry = create_default_registry()
    print(f"\n{registry.summary()}")

    query_a = "分析 LangGraph 框架的多智能体协作机制、状态管理和记忆系统"
    query_b = "基于之前的分析结果，设计一个改进的多智能体协作系统架构"

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: Text Mode (natural language passthrough)
    # ═══════════════════════════════════════════════════════════════

    print(f"\n{'#'*70}")
    print("# PHASE 1: TEXT MODE (natural language passthrough)")
    print(f"{'#'*70}")

    graph_text, store_text = build_graph(mode="text")

    result_a_text = run_task_group(graph_text, store_text, TASK_GROUP_A, query_a, mode="text")
    metrics.increment("memory_reuse_attempts")
    result_b_text = run_task_group(graph_text, store_text, TASK_GROUP_B, query_b, mode="text")

    demonstrate_memory_reuse(graph_text, store_text, "多智能体")
    text_report = metrics.report()
    text_summary = metrics.summary_dict()

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: Structured Mode (AgentMessage protocol)
    # ═══════════════════════════════════════════════════════════════

    print(f"\n\n{'#'*70}")
    print("# PHASE 2: STRUCTURED MODE (AgentMessage protocol)")
    print(f"{'#'*70}")

    metrics.reset()

    graph_struct, store_struct = build_graph(mode="structured")

    result_a_struct = run_task_group(graph_struct, store_struct, TASK_GROUP_A, query_a, mode="structured")
    metrics.increment("memory_reuse_attempts")
    result_b_struct = run_task_group(graph_struct, store_struct, TASK_GROUP_B, query_b, mode="structured")

    demonstrate_memory_reuse(graph_struct, store_struct, "多智能体")
    struct_report = metrics.report()
    struct_summary = metrics.summary_dict()

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: Comparison
    # ═══════════════════════════════════════════════════════════════

    print(f"\n\n{'#'*70}")
    print("# PHASE 3: COMPARISON REPORT")
    print(f"{'#'*70}")

    print("\n--- Text Mode Metrics ---")
    print(text_report)
    print("\n--- Structured Mode Metrics ---")
    print(struct_report)

    print_comparison(text_summary, struct_summary)

    # Protocol summary
    print(f"\n{'='*70}")
    print("Structured Communication Protocol Summary")
    print(f"{'='*70}")
    print("""
  Protocol: A2A-inspired AgentMessage
  - ActionType enum: plan, retrieve, analyze, summarize, query_memory, store_memory
  - AgentMessage: {msg_id, timestamp, source, target, action, params, result, embedding}
  - AgentCard: {name, description, actions, input_schema, output_schema}
  - AgentRegistry: capability discovery via discover(action)

  Text Mode:
    Agent → LLM → natural language → state field → next Agent
    (no action type, no structured params, no embedding)

  Structured Mode:
    Agent → LLM → code wraps into AgentMessage → state.messages → next Agent
    + action type: what to do (ActionType enum)
    + structured params/result: key-value dicts (not free text)
    + embedding: retriever → executor via embedding_payloads field
    + Store reference: large text stored, only key passed in message
    """)


if __name__ == "__main__":
    main()
