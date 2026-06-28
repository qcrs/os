#!/usr/bin/env python3
"""Deterministic cross-task shared-memory reuse experiment.

The experiment uses the real shared-memory implementation in `src/memory.py`
and the repository's local LangGraph source tree. It intentionally avoids LLM
calls and external embedding APIs so that it can run reproducibly inside the
`SynapseX-wmw` container.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Callable

# Force the offline embedding fallback before importing project config/memory.
os.environ.pop("DASHSCOPE_API_KEY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)
os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)

ROOT = Path(__file__).resolve().parent
for path in (
    ROOT / "src",
    ROOT / "langgraph" / "libs" / "langgraph",
    ROOT / "langgraph" / "libs" / "checkpoint",
):
    sys.path.insert(0, str(path))

from config import NS_ANALYSIS, NS_DOCS, NS_PLANS, NS_SUMMARIES  # noqa: E402
from memory import (  # noqa: E402
    create_store,
    store_get,
    store_put,
    store_search,
    store_search_by_keywords,
    store_search_by_tags,
    store_search_memories,
)

OUTPUT_JSON = ROOT / "docs" / "openos" / "memory_reuse_experiment_results.json"
CONTAINER_NAME = "SynapseX-wmw"
CONTAINER_IMAGE = "hub.oepkgs.net/openeuler/openeuler:24.03-lts-sp3"
REPEATS = 50
WARMUPS = 5
REQUIRED_MEMORY_FIELDS = [
    "memory_id",
    "memory_type",
    "source_agent",
    "created_at",
    "created_at_iso",
    "task_group",
    "task_topic",
    "summary_description",
    "tags",
    "payload",
]


MemoryWrite = tuple[tuple[str, ...], str, dict[str, Any], dict[str, Any]]


def package_version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not-installed"


def seed_memories(store: Any) -> list[MemoryWrite]:
    task_topic = "Task A: 设计统一共享记忆模块并支持跨任务复用"
    records: list[MemoryWrite] = [
        (
            NS_PLANS,
            "plan_A_memory_schema",
            {
                "query": task_topic,
                "task_group": "A_memory_schema",
                "plan": (
                    "Implement a unified MemoryUnit schema. Required metadata: "
                    "memory_id, source_agent, created_at, task_topic, "
                    "summary_description, tags, payload, and evidence_refs. "
                    "Retrieval must support semantic, keyword, tag, and hybrid search."
                ),
                "text": (
                    "Task A plan: MemoryUnit schema metadata plus retrieval modes "
                    "for cross-task memory reuse."
                ),
            },
            {
                "memory_type": "plan",
                "source_agent": "planner",
                "task_group": "A_memory_schema",
                "task_topic": task_topic,
                "summary": "统一记忆单元 schema 与跨任务检索计划。",
                "tags": ["task-a", "shared-memory", "memoryunit", "schema", "metadata", "memory-reuse"],
            },
        ),
        (
            NS_DOCS,
            "doc_memory_schema",
            {
                "sub_query": "统一记忆单元 MemoryUnit schema 元数据字段",
                "task_group": "A_memory_schema",
                "text": (
                    "MemoryUnit record must contain explicit memory_id, source_agent, "
                    "created_at, created_at_iso, task_topic, summary_description, "
                    "tags, payload, and evidence_refs. Evidence chain references use "
                    "doc_key and span_id."
                ),
                "source_ref": "design-note#memory-schema",
                "hash": "schema-note-001",
            },
            {
                "memory_type": "document",
                "source_agent": "researcher",
                "task_group": "A_memory_schema",
                "task_topic": task_topic,
                "summary": "MemoryUnit 必备元数据字段与证据链引用格式。",
                "tags": ["task-a", "shared-memory", "memoryunit", "schema", "evidence-chain"],
            },
        ),
        (
            NS_DOCS,
            "doc_retrieval_methods",
            {
                "sub_query": "跨任务记忆检索方式 semantic keyword tag hybrid",
                "task_group": "A_memory_schema",
                "text": (
                    "Retrieval supports semantic store_search, keyword search, tag search, "
                    "and hybrid store_search_memories. Later agents can reuse existing "
                    "MemoryUnit records before recomputing analysis."
                ),
                "source_ref": "design-note#retrieval",
                "hash": "retrieval-note-001",
            },
            {
                "memory_type": "document",
                "source_agent": "researcher",
                "task_group": "A_memory_schema",
                "task_topic": task_topic,
                "summary": "语义、关键词、标签和混合检索支持后续 Agent 复用记忆。",
                "tags": ["task-a", "retrieval", "semantic", "keyword", "tag", "hybrid", "memory-reuse"],
            },
        ),
        (
            NS_ANALYSIS,
            "analysis_A_memory_schema",
            {
                "plan": "Evaluate the MemoryUnit schema and reuse strategy.",
                "task_group": "A_memory_schema",
                "analysis": (
                    "Conclusion: use unified MemoryUnit schema with explicit metadata. "
                    "Reuse strategy: later agents query summaries by MemoryUnit keywords "
                    "and tags, then fetch analysis evidence_refs to support conclusions."
                ),
                "text": (
                    "Analysis memory: MemoryUnit schema is complete when memory_id, "
                    "source_agent, created_at, task_topic, summary_description, tags, "
                    "payload, and evidence_refs are present."
                ),
                "evidence": [
                    {
                        "doc_key": "doc_memory_schema",
                        "span_id": "schema-fields",
                        "claim": "MemoryUnit schema fields are explicitly recorded.",
                    },
                    {
                        "doc_key": "doc_retrieval_methods",
                        "span_id": "retrieval-modes",
                        "claim": "Semantic, keyword, tag, and hybrid retrieval enable reuse.",
                    },
                ],
                "selected_doc_keys": ["doc_memory_schema", "doc_retrieval_methods"],
            },
            {
                "memory_type": "analysis",
                "source_agent": "analyst",
                "task_group": "A_memory_schema",
                "task_topic": task_topic,
                "summary": "结论：统一 MemoryUnit 元数据完整，后续任务应先检索摘要再复用证据链。",
                "tags": ["task-a", "analysis", "memoryunit", "metadata", "evidence-chain", "memory-reuse"],
            },
        ),
        (
            NS_SUMMARIES,
            "summary_A_memory_schema",
            {
                "query": task_topic,
                "task_group": "A_memory_schema",
                "summary": (
                    "MemoryUnit schema unifies cross-task memories with explicit "
                    "memory_id, source_agent, created_at, task_topic, summary_description, "
                    "tags, payload, and evidence_refs. Follow-up agents should reuse this "
                    "memory via semantic, keyword, tag, or hybrid search before recomputing."
                ),
                "text": (
                    "Cross-task reuse summary: MemoryUnit metadata includes memory_id, "
                    "source_agent, created_at, task_topic, summary_description, tags, "
                    "payload, and evidence_refs so later agents can reuse Task A conclusions."
                ),
            },
            {
                "memory_type": "summary",
                "source_agent": "summarizer",
                "task_group": "A_memory_schema",
                "task_topic": task_topic,
                "summary": "MemoryUnit 统一元数据包含 created_at、source_agent 和 evidence_refs，可被后续任务直接复用。",
                "tags": [
                    "task-a",
                    "summary",
                    "shared-memory",
                    "memoryunit",
                    "schema",
                    "memory-reuse",
                    "created_at",
                    "evidence_refs",
                    "source_agent",
                ],
            },
        ),
        (
            NS_SUMMARIES,
            "summary_autogen_runtime",
            {
                "query": "AutoGen 多 Agent 对话运行时",
                "task_group": "distractor_autogen",
                "summary": "AutoGen focuses on conversational agent orchestration, speaker selection, and tool calling.",
                "text": "AutoGen runtime distractor memory unrelated to MemoryUnit schema reuse.",
            },
            {
                "memory_type": "summary",
                "source_agent": "summarizer",
                "task_group": "distractor_autogen",
                "task_topic": "AutoGen runtime",
                "summary": "AutoGen 对话编排干扰项。",
                "tags": ["distractor", "autogen", "runtime", "conversation"],
            },
        ),
        (
            NS_SUMMARIES,
            "summary_crewai_roles",
            {
                "query": "CrewAI 角色协作",
                "task_group": "distractor_crewai",
                "summary": "CrewAI organizes role-based agents, tasks, and process flows for collaboration.",
                "text": "CrewAI role orchestration distractor memory.",
            },
            {
                "memory_type": "summary",
                "source_agent": "summarizer",
                "task_group": "distractor_crewai",
                "task_topic": "CrewAI roles",
                "summary": "CrewAI 角色协作干扰项。",
                "tags": ["distractor", "crewai", "roles", "workflow"],
            },
        ),
        (
            NS_DOCS,
            "doc_vector_db_benchmark",
            {
                "sub_query": "向量数据库吞吐量测试",
                "task_group": "distractor_vector_db",
                "text": "Benchmark vector database ingestion throughput, index build time, and disk usage.",
                "source_ref": "benchmark#vector-db",
                "hash": "vector-db-001",
            },
            {
                "memory_type": "document",
                "source_agent": "researcher",
                "task_group": "distractor_vector_db",
                "task_topic": "Vector database benchmark",
                "summary": "向量数据库性能干扰文档。",
                "tags": ["distractor", "vector-db", "benchmark"],
            },
        ),
        (
            NS_ANALYSIS,
            "analysis_graph_scheduling",
            {
                "plan": "Analyze graph scheduling only.",
                "task_group": "distractor_scheduling",
                "analysis": "StateGraph scheduling controls node order and fan-out execution.",
                "text": "Scheduling distractor analysis without shared-memory schema conclusions.",
                "evidence": [{"doc_key": "doc_graph_runtime", "span_id": "fanout", "claim": "Send supports fan-out."}],
            },
            {
                "memory_type": "analysis",
                "source_agent": "analyst",
                "task_group": "distractor_scheduling",
                "task_topic": "Graph scheduling",
                "summary": "图调度分析干扰项。",
                "tags": ["distractor", "graph", "scheduling"],
            },
        ),
    ]

    for namespace, key, value, kwargs in records:
        store_put(store, namespace, key, value, **kwargs)
    return records


def result_keys(items: list[Any]) -> list[str]:
    return [item.key for item in items]


def result_scores(items: list[Any]) -> list[float | None]:
    return [None if item.score is None else round(float(item.score), 6) for item in items]


def evaluate_retrieval(store: Any) -> dict[str, Any]:
    tests: list[dict[str, Any]] = [
        {
            "name": "semantic_summary_reuse",
            "mode": "semantic",
            "namespace": NS_SUMMARIES,
            "expected_key": "summary_A_memory_schema",
            "call": lambda: store_search(
                store,
                NS_SUMMARIES,
                "Task B reuse MemoryUnit schema memory_id source_agent created_at evidence_refs tags",
                limit=3,
            ),
        },
        {
            "name": "keyword_summary_reuse",
            "mode": "keyword",
            "namespace": NS_SUMMARIES,
            "expected_key": "summary_A_memory_schema",
            "call": lambda: store_search_by_keywords(
                store,
                NS_SUMMARIES,
                ["MemoryUnit", "created_at", "evidence_refs"],
                limit=3,
                match_all=True,
            ),
        },
        {
            "name": "tag_summary_reuse",
            "mode": "tag",
            "namespace": NS_SUMMARIES,
            "expected_key": "summary_A_memory_schema",
            "call": lambda: store_search_by_tags(
                store,
                NS_SUMMARIES,
                ["memoryunit", "memory-reuse"],
                limit=3,
                match_all=True,
            ),
        },
        {
            "name": "hybrid_summary_reuse",
            "mode": "hybrid",
            "namespace": NS_SUMMARIES,
            "expected_key": "summary_A_memory_schema",
            "call": lambda: store_search_memories(
                store,
                NS_SUMMARIES,
                query="reuse MemoryUnit schema explicit created_at source_agent evidence_refs",
                keywords=["created_at"],
                tags=["memoryunit", "memory-reuse"],
                limit=3,
                match_all_keywords=True,
                match_all_tags=True,
            ),
        },
        {
            "name": "semantic_doc_retrieval_modes",
            "mode": "semantic",
            "namespace": NS_DOCS,
            "expected_key": "doc_retrieval_methods",
            "call": lambda: store_search(
                store,
                NS_DOCS,
                "semantic keyword tag hybrid store_search_memories retrieval reuse",
                limit=3,
            ),
        },
        {
            "name": "hybrid_analysis_evidence_chain",
            "mode": "hybrid",
            "namespace": NS_ANALYSIS,
            "expected_key": "analysis_A_memory_schema",
            "call": lambda: store_search_memories(
                store,
                NS_ANALYSIS,
                query="MemoryUnit evidence_refs reuse strategy source_agent created_at",
                keywords=["evidence_refs"],
                tags=["analysis", "memoryunit"],
                limit=3,
                match_all_keywords=True,
                match_all_tags=True,
            ),
        },
    ]

    rows = []
    hits_at_1 = []
    hits_at_3 = []
    reciprocal_ranks = []
    for test in tests:
        items = test["call"]()
        keys = result_keys(items)
        expected = test["expected_key"]
        rank = keys.index(expected) + 1 if expected in keys else None
        hit_at_1 = 1 if rank == 1 else 0
        hit_at_3 = 1 if rank is not None and rank <= 3 else 0
        rr = 1 / rank if rank else 0.0
        hits_at_1.append(hit_at_1)
        hits_at_3.append(hit_at_3)
        reciprocal_ranks.append(rr)
        rows.append(
            {
                "name": test["name"],
                "mode": test["mode"],
                "namespace": "/".join(test["namespace"]),
                "expected_key": expected,
                "top_keys": keys,
                "scores": result_scores(items),
                "rank": rank,
                "hit_at_1": hit_at_1,
                "hit_at_3": hit_at_3,
            }
        )

    return {
        "overall": {
            "test_count": len(rows),
            "precision_at_1": sum(hits_at_1) / len(hits_at_1),
            "recall_at_3": sum(hits_at_3) / len(hits_at_3),
            "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
        },
        "tests": rows,
    }


def validate_schema(store: Any, records: list[MemoryWrite]) -> dict[str, Any]:
    missing_by_key: dict[str, list[str]] = {}
    invalid_by_key: dict[str, list[str]] = {}
    source_agents = Counter()
    memory_types = Counter()
    tags_by_key: dict[str, list[str]] = {}

    for namespace, key, _value, _kwargs in records:
        item = store_get(store, namespace, key)
        value = item.value if item else {}
        missing = [field for field in REQUIRED_MEMORY_FIELDS if field not in value]
        invalid = []
        if not isinstance(value.get("memory_id"), str) or not value.get("memory_id"):
            invalid.append("memory_id")
        if not isinstance(value.get("source_agent"), str) or not value.get("source_agent"):
            invalid.append("source_agent")
        if not isinstance(value.get("created_at"), (int, float)):
            invalid.append("created_at")
        if not isinstance(value.get("created_at_iso"), str) or "T" not in value.get("created_at_iso", ""):
            invalid.append("created_at_iso")
        if not isinstance(value.get("tags"), list) or not value.get("tags"):
            invalid.append("tags")
        if not isinstance(value.get("payload"), dict):
            invalid.append("payload")
        if missing:
            missing_by_key[key] = missing
        if invalid:
            invalid_by_key[key] = invalid
        source_agents[str(value.get("source_agent", ""))] += 1
        memory_types[str(value.get("memory_type", ""))] += 1
        tags_by_key[key] = list(value.get("tags", []))

    analysis = store_get(store, NS_ANALYSIS, "analysis_A_memory_schema").value
    evidence_refs = analysis.get("evidence_refs", [])
    evidence_refs_complete = bool(evidence_refs) and all(ref.get("doc_key") for ref in evidence_refs)

    return {
        "required_fields": REQUIRED_MEMORY_FIELDS,
        "total_memory_units": len(records),
        "valid_memory_units": len(records) - len(set(missing_by_key) | set(invalid_by_key)),
        "schema_pass_rate": (len(records) - len(set(missing_by_key) | set(invalid_by_key))) / len(records),
        "missing_by_key": missing_by_key,
        "invalid_by_key": invalid_by_key,
        "source_agents": dict(source_agents),
        "memory_types": dict(memory_types),
        "evidence_refs_complete": evidence_refs_complete,
        "evidence_refs": evidence_refs,
        "sample_tags": {
            "summary_A_memory_schema": tags_by_key.get("summary_A_memory_schema", []),
            "analysis_A_memory_schema": tags_by_key.get("analysis_A_memory_schema", []),
        },
    }


def latency_stats(samples_ms: list[float]) -> dict[str, float | int]:
    sorted_samples = sorted(samples_ms)
    p50 = statistics.median(sorted_samples)
    p95 = sorted_samples[int(0.95 * (len(sorted_samples) - 1))]
    return {
        "count": len(samples_ms),
        "avg_ms": round(statistics.mean(samples_ms), 4),
        "min_ms": round(min(samples_ms), 4),
        "p50_ms": round(p50, 4),
        "p95_ms": round(p95, 4),
        "max_ms": round(max(samples_ms), 4),
    }


def measure_latency(call: Callable[[], Any]) -> dict[str, Any]:
    for _ in range(WARMUPS):
        call()
    samples = []
    last_keys: list[str] = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        items = call()
        samples.append((time.perf_counter() - started) * 1000)
        last_keys = result_keys(items)
    stats = latency_stats(samples)
    stats["last_top_keys"] = last_keys[:3]
    return stats


def measure_efficiency(store: Any) -> dict[str, Any]:
    calls: dict[str, Callable[[], Any]] = {
        "semantic_summary": lambda: store_search(
            store,
            NS_SUMMARIES,
            "Task B reuse MemoryUnit schema memory_id source_agent created_at evidence_refs tags",
            limit=3,
        ),
        "keyword_summary": lambda: store_search_by_keywords(
            store,
            NS_SUMMARIES,
            ["MemoryUnit", "created_at", "evidence_refs"],
            limit=3,
            match_all=True,
        ),
        "tag_summary": lambda: store_search_by_tags(
            store,
            NS_SUMMARIES,
            ["memoryunit", "memory-reuse"],
            limit=3,
            match_all=True,
        ),
        "hybrid_summary": lambda: store_search_memories(
            store,
            NS_SUMMARIES,
            query="reuse MemoryUnit schema explicit created_at source_agent evidence_refs",
            keywords=["created_at"],
            tags=["memoryunit", "memory-reuse"],
            limit=3,
            match_all_keywords=True,
            match_all_tags=True,
        ),
        "hybrid_analysis": lambda: store_search_memories(
            store,
            NS_ANALYSIS,
            query="MemoryUnit evidence_refs reuse strategy source_agent created_at",
            keywords=["evidence_refs"],
            tags=["analysis", "memoryunit"],
            limit=3,
            match_all_keywords=True,
            match_all_tags=True,
        ),
    }
    return {name: measure_latency(call) for name, call in calls.items()}


def compute_reuse_context_savings(store: Any, records: list[MemoryWrite]) -> dict[str, Any]:
    all_chars_by_namespace: dict[str, int] = defaultdict(int)
    for namespace, key, _value, _kwargs in records:
        item = store_get(store, namespace, key)
        value = item.value
        namespace_name = "/".join(namespace)
        all_chars_by_namespace[namespace_name] += len(str(value.get("text", ""))) + len(
            str(value.get("summary_description", ""))
        )

    summary_item = store_get(store, NS_SUMMARIES, "summary_A_memory_schema").value
    analysis_item = store_get(store, NS_ANALYSIS, "analysis_A_memory_schema").value
    reused_chars = len(summary_item.get("summary_description", "")) + len(
        analysis_item.get("summary_description", "")
    )
    full_context_chars = sum(all_chars_by_namespace.values())
    reduction = 1 - reused_chars / max(full_context_chars, 1)
    return {
        "full_seeded_memory_context_chars": full_context_chars,
        "reused_summary_plus_analysis_chars": reused_chars,
        "estimated_context_reduction_ratio": round(reduction, 4),
        "estimated_context_reduction_percent": round(reduction * 100, 2),
        "namespace_context_chars": dict(sorted(all_chars_by_namespace.items())),
    }


def build_environment() -> dict[str, Any]:
    return {
        "container": CONTAINER_NAME,
        "image": CONTAINER_IMAGE,
        "code_path": str(ROOT),
        "python": sys.version.split()[0],
        "embedding_backend": "LocalHashEmbeddings",
        "dashscope_api_key_set": bool(os.environ.get("DASHSCOPE_API_KEY")),
        "packages": {
            "dashscope": package_version("dashscope"),
            "langchain-core": package_version("langchain-core"),
            "langchain-openai": package_version("langchain-openai"),
            "numpy": package_version("numpy"),
            "langgraph": "local-source: third_party/langgraph/libs/langgraph",
        },
    }


def main() -> None:
    store = create_store()
    records = seed_memories(store)

    by_namespace = Counter("/".join(namespace) for namespace, _key, _value, _kwargs in records)
    result = {
        "experiment": {
            "name": "cross_task_memory_reuse_accuracy_efficiency",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "task_a": "设计统一共享记忆模块并保存 MemoryUnit 记忆。",
            "task_b": "后续任务检索并复用 Task A 的摘要、证据链和结论。",
            "distractors": "AutoGen、CrewAI、vector-db、graph scheduling 等非目标记忆。",
            "repeats": REPEATS,
            "warmups": WARMUPS,
        },
        "environment": build_environment(),
        "seeded_memories": {
            "total": len(records),
            "by_namespace": dict(sorted(by_namespace.items())),
            "keys": [key for _namespace, key, _value, _kwargs in records],
        },
        "schema_validation": validate_schema(store, records),
        "retrieval_accuracy": evaluate_retrieval(store),
        "efficiency": {
            "latency": measure_efficiency(store),
            "context_savings": compute_reuse_context_savings(store, records),
        },
        "reuse_example": {},
    }

    summary_hit = store_search_memories(
        store,
        NS_SUMMARIES,
        query="Task B reuse MemoryUnit schema explicit metadata evidence_refs",
        keywords=["MemoryUnit"],
        tags=["memoryunit", "memory-reuse"],
        limit=1,
        match_all_keywords=True,
        match_all_tags=True,
    )[0]
    analysis_hit = store_search_memories(
        store,
        NS_ANALYSIS,
        query="MemoryUnit evidence_refs reuse conclusion",
        keywords=["evidence_refs"],
        tags=["analysis", "memoryunit"],
        limit=1,
        match_all_keywords=True,
        match_all_tags=True,
    )[0]
    result["reuse_example"] = {
        "task_b_query": "如何基于上一任务的 MemoryUnit schema 继续优化跨任务记忆复用？",
        "summary_memory_id": summary_hit.value["memory_id"],
        "summary_source_agent": summary_hit.value["source_agent"],
        "summary_description": summary_hit.value["summary_description"],
        "analysis_memory_id": analysis_hit.value["memory_id"],
        "analysis_source_agent": analysis_hit.value["source_agent"],
        "evidence_refs": analysis_hit.value.get("evidence_refs", []),
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    overall = result["retrieval_accuracy"]["overall"]
    latency = result["efficiency"]["latency"]
    print(json.dumps({
        "output_json": str(OUTPUT_JSON),
        "schema_pass_rate": result["schema_validation"]["schema_pass_rate"],
        "precision_at_1": overall["precision_at_1"],
        "recall_at_3": overall["recall_at_3"],
        "mrr": overall["mrr"],
        "latency_avg_ms": {name: stats["avg_ms"] for name, stats in latency.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
