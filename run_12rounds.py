#!/usr/bin/env python3
"""12-Round Continuous Task Dual-Mode Comparison

Runs 12 chained research tasks where each round reads memories from
previous rounds. Compares text mode vs structured mode on:
  - Total LLM token usage (input/output)
  - Total execution time
  - Task completion quality (key findings count, analysis depth, memory reuse)

Usage:
    cd /demo
    unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
    python run_12rounds.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from config import NS_SUMMARIES
from graph import build_graph
from memory import store_search
from metrics import metrics as global_metrics


# ═══════════════════════════════════════════════════════════════════════
# 12 Chained Research Tasks — each reads previous rounds' memories
# ═══════════════════════════════════════════════════════════════════════

TASKS = [
    # ── Phase 1: Foundation (R1-R4) ──
    {
        "id": "R01",
        "query": "调研 LangGraph 框架的核心架构设计，包括 StateGraph、节点、边、条件边等基本概念",
        "task_group": "foundation",
        "desc": "LangGraph 核心概念",
    },
    {
        "id": "R02",
        "query": "基于之前对 LangGraph 核心架构的调研结果，深入分析其状态管理机制，包括 Channel、Reducer、Checkpoint 等",
        "task_group": "foundation",
        "desc": "状态管理机制",
    },
    {
        "id": "R03",
        "query": "基于之前对 LangGraph 状态管理的分析，研究其共享记忆系统的实现方式，包括 InMemoryStore、Namespace、语义搜索",
        "task_group": "foundation",
        "desc": "共享记忆系统",
    },
    {
        "id": "R04",
        "query": "基于之前对 LangGraph 记忆系统的调研，分析其多智能体通信机制，包括 Send 原语、fan-out/fan-in、消息传递",
        "task_group": "foundation",
        "desc": "多智能体通信",
    },
    # ── Phase 2: Comparative Analysis (R5-R8) ──
    {
        "id": "R05",
        "query": "调研 AutoGen 框架的多智能体协作架构，重点分析其对话管理和任务分配机制",
        "task_group": "comparison",
        "desc": "AutoGen 架构",
    },
    {
        "id": "R06",
        "query": "调研 CrewAI 框架的多智能体协作架构，重点分析其角色定义和工作流编排机制",
        "task_group": "comparison",
        "desc": "CrewAI 架构",
    },
    {
        "id": "R07",
        "query": "基于之前对 LangGraph、AutoGen、CrewAI 的调研，对比分析三个框架在状态管理、通信协议、记忆系统方面的异同",
        "task_group": "comparison",
        "desc": "三框架对比",
    },
    {
        "id": "R08",
        "query": "基于之前的对比分析，识别当前多智能体框架共同面临的核心技术瓶颈和未解决问题",
        "task_group": "comparison",
        "desc": "共同瓶颈识别",
    },
    # ── Phase 3: Synthesis (R9-R12) ──
    {
        "id": "R09",
        "query": "基于之前识别的技术瓶颈，设计一个改进的多智能体协作系统架构，包含结构化通信协议、语义记忆、非文本状态传递",
        "task_group": "synthesis",
        "desc": "改进架构设计",
    },
    {
        "id": "R10",
        "query": "基于之前的架构设计方案，设计具体的实验方案来验证结构化协议相比纯文本协作在 token 效率和任务质量上的优势",
        "task_group": "synthesis",
        "desc": "实验方案设计",
    },
    {
        "id": "R11",
        "query": "基于之前的实验方案和所有调研结果，实现一个最小可行的多智能体协作原型系统的核心模块",
        "task_group": "synthesis",
        "desc": "原型实现",
    },
    {
        "id": "R12",
        "query": "基于之前所有轮次的调研、分析、设计和实现结果，生成一份完整的多智能体协作系统技术报告，包含架构设计、对比分析、改进方案和实验结论",
        "task_group": "synthesis",
        "desc": "最终技术报告",
    },
]


def run_single_task(graph, store, task: dict, mode: str) -> dict:
    """Run a single task and collect metrics."""
    t0 = time.perf_counter()
    result = graph.invoke({
        "query": task["query"],
        "task_group": task["task_group"],
        "mode": mode,
    })
    duration = time.perf_counter() - t0
    global_metrics.record_timing(f"task_{task['id']}", duration)

    # Count quality indicators
    findings = result.get("key_findings", [])
    analysis = result.get("analysis", "")
    summary = result.get("summary", "")

    return {
        "task_id": task["id"],
        "desc": task["desc"],
        "duration": duration,
        "plan": result.get("plan", "")[:200],
        "sub_queries": result.get("sub_queries", []),
        "doc_count": len(result.get("documents", [])),
        "analysis_len": len(analysis),
        "summary_len": len(summary),
        "key_findings_count": len(findings),
        "key_findings": findings[:5],
        "messages_count": len(result.get("messages", [])),
    }


def run_all_tasks(mode: str) -> tuple[list[dict], dict]:
    """Run all 12 tasks in sequence with the given mode."""
    graph, store = build_graph(mode=mode)

    results = []
    for i, task in enumerate(TASKS):
        print(f"\n  [{mode.upper()}] Round {i+1}/12: {task['desc']} ...", end="", flush=True)
        r = run_single_task(graph, store, task, mode)
        results.append(r)
        # Record memory reuse
        global_metrics.increment("memory_reuse_attempts")
        # Check if store has relevant memories
        store_items = list(store.search(NS_SUMMARIES, limit=5))
        if len(store_items) > 0 and i > 0:
            global_metrics.increment("memory_reuse_hits")
        print(f" {r['duration']:.1f}s | findings={r['key_findings_count']} | analysis={r['analysis_len']}chars")

    summary = global_metrics.summary_dict()
    return results, summary


def print_round_by_round(text_results: list[dict], struct_results: list[dict]):
    """Print per-round comparison table."""
    print(f"\n{'='*100}")
    print("PER-ROUND COMPARISON")
    print(f"{'='*100}")

    headers = ["Round", "Task", "Text Time", "Struct Time", "Text Findings", "Struct Findings", "Text Analysis", "Struct Analysis"]
    col_widths = [6, 14, 10, 11, 14, 15, 14, 15]

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
            f"{tr['analysis_len']}".ljust(14),
            f"{sr['analysis_len']}".ljust(15),
        ]
        print(f"  {' | '.join(row)}")


def print_quality_comparison(text_results: list[dict], struct_results: list[dict]):
    """Compare task completion quality."""
    print(f"\n{'='*70}")
    print("TASK COMPLETION QUALITY COMPARISON")
    print(f"{'='*70}")

    # Aggregate quality metrics
    text_total_findings = sum(r["key_findings_count"] for r in text_results)
    struct_total_findings = sum(r["key_findings_count"] for r in struct_results)
    text_total_analysis = sum(r["analysis_len"] for r in text_results)
    struct_total_analysis = sum(r["analysis_len"] for r in struct_results)
    text_total_summary = sum(r["summary_len"] for r in text_results)
    struct_total_summary = sum(r["summary_len"] for r in struct_results)
    text_total_docs = sum(r["doc_count"] for r in text_results)
    struct_total_docs = sum(r["doc_count"] for r in struct_results)

    rows = [
        ("Total key findings", str(text_total_findings), str(struct_total_findings)),
        ("Avg findings/round", f"{text_total_findings/12:.1f}", f"{struct_total_findings/12:.1f}"),
        ("Total analysis chars", str(text_total_analysis), str(struct_total_analysis)),
        ("Avg analysis chars/round", f"{text_total_analysis/12:.0f}", f"{struct_total_analysis/12:.0f}"),
        ("Total summary chars", str(text_total_summary), str(struct_total_summary)),
        ("Avg summary chars/round", f"{text_total_summary/12:.0f}", f"{struct_total_summary/12:.0f}"),
        ("Total docs retrieved", str(text_total_docs), str(struct_total_docs)),
        ("Avg docs/round", f"{text_total_docs/12:.1f}", f"{struct_total_docs/12:.1f}"),
    ]

    headers = ["Quality Metric", "Text Mode", "Structured Mode"]
    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(f"  {header_line}")
    print(f"  {'-+-'.join('-' * w for w in col_widths)}")
    for row in rows:
        print(f"  {' | '.join(v.ljust(w) for v, w in zip(row, col_widths))}")

    # Print key findings from last round (R12) for both modes
    print(f"\n  --- R12 (Final Report) Key Findings ---")
    text_r12 = text_results[-1]
    struct_r12 = struct_results[-1]
    print(f"  Text Mode ({text_r12['key_findings_count']} findings):")
    for f in text_r12["key_findings"]:
        print(f"    • {f[:80]}")
    print(f"  Structured Mode ({struct_r12['key_findings_count']} findings):")
    for f in struct_r12["key_findings"]:
        print(f"    • {f[:80]}")


def main():
    print("=" * 80)
    print("12-Round Continuous Task Dual-Mode Comparison")
    print("LangGraph + DeepSeek V4 | Chained Memory Tasks")
    print("=" * 80)

    # Check API keys (skip for local transformers backend)
    if os.getenv("CHAT_BACKEND", "").lower() != "transformers":
        if not os.getenv("DEEPSEEK_API_KEY"):
            print("[ERROR] DEEPSEEK_API_KEY not set. Exiting.")
            sys.exit(1)
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("[WARNING] DASHSCOPE_API_KEY not set. Embedding will use fallback.")

    # Print task plan
    print(f"\n  12 Chained Tasks:")
    phases = {"foundation": "Phase 1: Foundation", "comparison": "Phase 2: Comparison", "synthesis": "Phase 3: Synthesis"}
    current_phase = ""
    for t in TASKS:
        if t["task_group"] != current_phase:
            current_phase = t["task_group"]
            print(f"\n    {phases[current_phase]}:")
        print(f"      {t['id']}: {t['desc']}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 1: Text Mode — 12 rounds
    # ═══════════════════════════════════════════════════════════════

    print(f"\n\n{'#'*80}")
    print("# PHASE 1: TEXT MODE — 12 Rounds")
    print(f"{'#'*80}")

    text_start = time.perf_counter()
    text_results, text_summary = run_all_tasks("text")
    text_total_time = time.perf_counter() - text_start
    text_report = global_metrics.report()

    print(f"\n  Text Mode Total: {text_total_time:.1f}s")
    print(f"  Text Mode Tokens: {text_summary['total_tokens']}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 2: Structured Mode — 12 rounds
    # ═══════════════════════════════════════════════════════════════

    print(f"\n\n{'#'*80}")
    print("# PHASE 2: STRUCTURED MODE — 12 Rounds")
    print(f"{'#'*80}")

    global_metrics.reset()

    struct_start = time.perf_counter()
    struct_results, struct_summary = run_all_tasks("structured")
    struct_total_time = time.perf_counter() - struct_start
    struct_report = global_metrics.report()

    print(f"\n  Structured Mode Total: {struct_total_time:.1f}s")
    print(f"  Structured Mode Tokens: {struct_summary['total_tokens']}")

    # ═══════════════════════════════════════════════════════════════
    # Phase 3: Comparison Report
    # ═══════════════════════════════════════════════════════════════

    print(f"\n\n{'#'*80}")
    print("# PHASE 3: COMPARISON REPORT")
    print(f"{'#'*80}")

    # Metrics reports
    print("\n--- Text Mode Full Report ---")
    print(text_report)
    print("\n--- Structured Mode Full Report ---")
    print(struct_report)

    # Per-round comparison
    print_round_by_round(text_results, struct_results)

    # Token & Time comparison
    print(f"\n{'='*70}")
    print("TOKEN & TIME COMPARISON")
    print(f"{'='*70}")

    token_diff = struct_summary["total_tokens"] - text_summary["total_tokens"]
    token_pct = (token_diff / text_summary["total_tokens"] * 100) if text_summary["total_tokens"] else 0
    time_diff = struct_total_time - text_total_time
    time_pct = (time_diff / text_total_time * 100) if text_total_time else 0

    headers = ["Metric", "Text Mode", "Structured Mode", "Difference"]
    rows = [
        ("LLM calls (12 rounds)", str(text_summary["llm_calls"]),
         str(struct_summary["llm_calls"]),
         f"{struct_summary['llm_calls'] - text_summary['llm_calls']:+d}"),
        ("Input tokens", f"{text_summary['input_tokens']:,}",
         f"{struct_summary['input_tokens']:,}",
         f"{struct_summary['input_tokens'] - text_summary['input_tokens']:+,}"),
        ("Output tokens", f"{text_summary['output_tokens']:,}",
         f"{struct_summary['output_tokens']:,}",
         f"{struct_summary['output_tokens'] - text_summary['output_tokens']:+,}"),
        ("Total tokens", f"{text_summary['total_tokens']:,}",
         f"{struct_summary['total_tokens']:,}",
         f"{token_diff:+,} ({token_pct:+.1f}%)"),
        ("Wall-clock time", f"{text_total_time:.1f}s",
         f"{struct_total_time:.1f}s",
         f"{time_diff:+.1f}s ({time_pct:+.1f}%)"),
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
    ]

    col_widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    header_line = " | ".join(h.ljust(w) for h, w in zip(headers, col_widths))
    print(f"  {header_line}")
    print(f"  {'-+-'.join('-' * w for w in col_widths)}")
    for row in rows:
        print(f"  {' | '.join(v.ljust(w) for v, w in zip(row, col_widths))}")

    # Quality comparison
    print_quality_comparison(text_results, struct_results)

    # Save results to JSON
    output = {
        "task_count": 12,
        "text_mode": {
            "total_time": text_total_time,
            "summary": text_summary,
            "per_round": text_results,
        },
        "structured_mode": {
            "total_time": struct_total_time,
            "summary": struct_summary,
            "per_round": struct_results,
        },
        "comparison": {
            "token_diff": token_diff,
            "token_pct": token_pct,
            "time_diff": time_diff,
            "time_pct": time_pct,
        },
    }
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_12rounds.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  Results saved to: {out_path}")


if __name__ == "__main__":
    main()
