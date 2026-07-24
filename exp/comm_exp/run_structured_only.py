#!/usr/bin/env python3
"""Run Structured Mode 12 rounds and compare with saved Text Mode results."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from graph import build_graph
from memory import qdrant_search
from metrics import metrics as global_metrics


TASKS = [
    {"id": "R01", "query": "调研 LangGraph 框架的核心架构设计，包括 StateGraph、节点、边、条件边等基本概念", "task_group": "foundation", "desc": "LangGraph 核心概念"},
    {"id": "R02", "query": "基于之前对 LangGraph 核心架构的调研结果，深入分析其状态管理机制，包括 Channel、Reducer、Checkpoint 等", "task_group": "foundation", "desc": "状态管理机制"},
    {"id": "R03", "query": "基于之前对 LangGraph 状态管理的分析，研究其共享记忆系统的实现方式，包括 InMemoryStore、Namespace、语义搜索", "task_group": "foundation", "desc": "共享记忆系统"},
    {"id": "R04", "query": "基于之前对 LangGraph 记忆系统的调研，分析其多智能体通信机制，包括 Send 原语、fan-out/fan-in、消息传递", "task_group": "foundation", "desc": "多智能体通信"},
    {"id": "R05", "query": "调研 AutoGen 框架的多智能体协作架构，重点分析其对话管理和任务分配机制", "task_group": "comparison", "desc": "AutoGen 架构"},
    {"id": "R06", "query": "调研 CrewAI 框架的多智能体协作架构，重点分析其角色定义和工作流编排机制", "task_group": "comparison", "desc": "CrewAI 架构"},
    {"id": "R07", "query": "基于之前对 LangGraph、AutoGen、CrewAI 的调研，对比分析三个框架在状态管理、通信协议、记忆系统方面的异同", "task_group": "comparison", "desc": "三框架对比"},
    {"id": "R08", "query": "基于之前的对比分析，识别当前多智能体框架共同面临的核心技术瓶颈和未解决问题", "task_group": "comparison", "desc": "共同瓶颈识别"},
    {"id": "R09", "query": "基于之前识别的技术瓶颈，设计一个改进的多智能体协作系统架构，包含结构化通信协议、语义记忆、非文本状态传递", "task_group": "synthesis", "desc": "改进架构设计"},
    {"id": "R10", "query": "基于之前的架构设计方案，设计具体的实验方案来验证结构化协议相比纯文本协作在 token 效率和任务质量上的优势", "task_group": "synthesis", "desc": "实验方案设计"},
    {"id": "R11", "query": "基于之前的实验方案和所有调研结果，实现一个最小可行的多智能体协作原型系统的核心模块", "task_group": "synthesis", "desc": "原型实现"},
    {"id": "R12", "query": "基于之前所有轮次的调研、分析、设计和实现结果，生成一份完整的多智能体协作系统技术报告，包含架构设计、对比分析、改进方案和实验结论", "task_group": "synthesis", "desc": "最终技术报告"},
]


def run_single_task(graph, store, task, mode):
    t0 = time.perf_counter()
    result = graph.invoke({"query": task["query"], "task_group": task["task_group"], "mode": mode})
    duration = time.perf_counter() - t0
    global_metrics.record_timing(f"task_{task['id']}", duration)
    return {
        "task_id": task["id"],
        "desc": task["desc"],
        "duration": duration,
        "plan": result.get("plan", "")[:200],
        "sub_queries": result.get("sub_queries", []),
        "doc_count": len(result.get("documents", [])),
        "analysis_len": len(result.get("analysis", "")),
        "summary_len": len(result.get("summary", "")),
        "key_findings_count": len(result.get("key_findings", [])),
        "key_findings": result.get("key_findings", [])[:5],
        "messages_count": len(result.get("messages", [])),
    }


def main():
    print("=" * 80)
    print("Structured Mode 12-Round Test")
    print("Comparing with saved Text Mode results")
    print("=" * 80)

    # Check API keys
    if os.getenv("CHAT_BACKEND", "").lower() != "transformers":
        if not os.getenv("CHAT_API_KEY") and not os.getenv("DEEPSEEK_API_KEY"):
            print("[ERROR] CHAT_API_KEY/DEEPSEEK_API_KEY not set. Exiting.")
            sys.exit(1)

    # Load saved text results
    text_results_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_12rounds.json")
    if os.path.exists(text_results_path):
        with open(text_results_path, "r") as f:
            saved = json.load(f)
        text_results = saved.get("text_mode", {}).get("per_round", [])
        text_summary = saved.get("text_mode", {}).get("summary", {})
        text_total_time = saved.get("text_mode", {}).get("total_time", 0)
        print(f"\n  Loaded Text Mode results: {len(text_results)} rounds, {text_total_time:.1f}s total")
    else:
        print("[WARNING] No saved Text Mode results found. Will only run Structured Mode.")
        text_results = []
        text_summary = {}
        text_total_time = 0

    # Run Structured Mode
    print(f"\n\n{'#'*80}")
    print("# STRUCTURED MODE — 12 Rounds")
    print(f"{'#'*80}")

    graph, store = build_graph(mode="structured")
    struct_results = []
    struct_start = time.perf_counter()

    for i, task in enumerate(TASKS):
        print(f"\n  [STRUCTURED] Round {i+1}/12: {task['desc']} ...", end="", flush=True)
        r = run_single_task(graph, store, task, "structured")
        struct_results.append(r)
        global_metrics.increment("memory_reuse_attempts")
        prior_summaries = qdrant_search(task["query"], memory_type="summary", top_k=1)
        if prior_summaries and i > 0:
            global_metrics.increment("memory_reuse_hits")
        print(f" {r['duration']:.1f}s | findings={r['key_findings_count']} | analysis={r['analysis_len']}chars")

    struct_total_time = time.perf_counter() - struct_start
    struct_summary = global_metrics.summary_dict()
    struct_report = global_metrics.report()

    print(f"\n  Structured Mode Total: {struct_total_time:.1f}s")
    print(f"  Structured Mode Tokens: {struct_summary['total_tokens']}")

    # Comparison Report
    print(f"\n\n{'#'*80}")
    print("# COMPARISON REPORT")
    print(f"{'#'*80}")

    print("\n--- Structured Mode Full Report ---")
    print(struct_report)

    # Per-round comparison
    if text_results:
        print(f"\n{'='*100}")
        print("PER-ROUND COMPARISON")
        print(f"{'='*100}")
        headers = ["Round", "Task", "Text Time", "Struct Time", "Text Findings", "Struct Findings"]
        col_widths = [6, 14, 10, 11, 14, 15]
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(f"  {header_line}")
        print(f"  {'-+-'.join('-' * w for w in col_widths)}")
        for tr, sr in zip(text_results, struct_results):
            row = [
                tr["task_id"].ljust(6),
                tr["desc"][:14].ljust(14),
                f"{tr['duration']:.1f}s".ljust(10),
                f"{sr['duration']:.1f}s".ljust(11),
                str(tr["key_findings_count"]).ljust(14),
                str(sr["key_findings_count"]).ljust(15),
            ]
            print(f"  {' | '.join(row)}")

    # Token & Time comparison
    if text_summary:
        print(f"\n{'='*70}")
        print("TOKEN & TIME COMPARISON")
        print(f"{'='*70}")
        token_diff = struct_summary["total_tokens"] - text_summary.get("total_tokens", 0)
        token_pct = (token_diff / text_summary["total_tokens"] * 100) if text_summary.get("total_tokens") else 0
        time_diff = struct_total_time - text_total_time
        time_pct = (time_diff / text_total_time * 100) if text_total_time else 0

        headers = ["Metric", "Text Mode", "Structured Mode", "Difference"]
        rows = [
            ("LLM calls", str(text_summary.get("llm_calls", 0)), str(struct_summary["llm_calls"]), f"{struct_summary['llm_calls'] - text_summary.get('llm_calls', 0):+d}"),
            ("Input tokens", f"{text_summary.get('input_tokens', 0):,}", f"{struct_summary['input_tokens']:,}", f"{struct_summary['input_tokens'] - text_summary.get('input_tokens', 0):+,}"),
            ("Output tokens", f"{text_summary.get('output_tokens', 0):,}", f"{struct_summary['output_tokens']:,}", f"{struct_summary['output_tokens'] - text_summary.get('output_tokens', 0):+,}"),
            ("Total tokens", f"{text_summary.get('total_tokens', 0):,}", f"{struct_summary['total_tokens']:,}", f"{token_diff:+,} ({token_pct:+.1f}%)"),
            ("Wall-clock time", f"{text_total_time:.1f}s", f"{struct_total_time:.1f}s", f"{time_diff:+.1f}s ({time_pct:+.1f}%)"),
        ]
        col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
        header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
        print(f"  {header_line}")
        print(f"  {'-+-'.join('-' * w for w in col_widths)}")
        for row in rows:
            print(f"  {' | '.join(v.ljust(w) for v, w in zip(row, col_widths))}")

    # Save structured results
    output = {
        "structured_mode": {
            "total_time": struct_total_time,
            "summary": struct_summary,
            "per_round": struct_results,
        }
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_structured_only.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
