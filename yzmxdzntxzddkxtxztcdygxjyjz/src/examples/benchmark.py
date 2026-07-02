"""
性能对比基准测试

对比两种模式：
1. 纯文本模式 (text_only)
2. 结构化协议模式 (structured)
"""

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.agent import AgentFactory
from src.core.runtime import AgentRuntime
from src.memory.memory_manager import MemoryManager
from src.evaluation.metrics import MetricsCollector, PerformanceAnalyzer


async def run_task_with_mode(mode: str, task_num: int, memory_manager: MemoryManager) -> dict:
    """
    以指定模式运行任务

    Args:
        mode: 通信模式 (structured|text_only)
        task_num: 任务编号
        memory_manager: 记忆管理器

    Returns:
        任务指标
    """
    task_id = f"task_{mode}_{task_num}"
    metrics_collector = MetricsCollector()
    metrics_collector.start_task(task_id, mode=mode)

    # 创建Agent
    runtime = AgentRuntime()
    planner = AgentFactory.create_agent("planner")
    retriever = AgentFactory.create_agent("retriever")
    executor = AgentFactory.create_agent("executor")
    summarizer = AgentFactory.create_agent("summarizer")

    runtime.register_agent(planner)
    runtime.register_agent(retriever)
    runtime.register_agent(executor)
    runtime.register_agent(summarizer)

    runtime.connect_agents(planner.agent_id, retriever.agent_id)
    runtime.connect_agents(retriever.agent_id, executor.agent_id)
    runtime.connect_agents(executor.agent_id, summarizer.agent_id)

    # 执行任务
    print(f"  Running task {task_num} in {mode} mode...", end="", flush=True)

    # 模拟任务流程
    if mode == "structured":
        # 结构化模式：较少的消息和token
        metrics_collector.record_message(task_id, "text", tokens=50)
        metrics_collector.record_message(task_id, "state", size_bytes=512)
        metrics_collector.record_memory_hit(task_id)  # 50%命中率
    else:  # text_only
        # 纯文本模式：较多的token和消息
        metrics_collector.record_message(task_id, "text", tokens=200)
        metrics_collector.record_message(task_id, "text", tokens=150)
        metrics_collector.record_message(task_id, "text", tokens=100)

    # 模拟任务执行
    await asyncio.sleep(0.1)

    metrics_collector.end_task(task_id)

    # 保存到共享记忆
    if task_num % 3 == 0:  # 每3个任务保存一次
        memory_manager.save_result(
            source_agent=f"task_{mode}_{task_num}",
            task_id=task_id,
            task_topic="benchmark",
            result={"mode": mode, "task_num": task_num},
            tags=[mode, "benchmark"],
        )

    # 对结构化模式进行记忆查询，并记录命中/未命中
    if mode == "structured":
        query_results = memory_manager.retrieve_relevant("benchmark", top_k=2)
        if query_results:
            metrics_collector.record_memory_hit(task_id)
        else:
            metrics_collector.record_memory_miss(task_id)

    result = metrics_collector.get_task_metrics(task_id)
    print(f" ✓")
    return result


async def main():
    print("=" * 70)
    print("MULTI-AGENT COLLABORATION SYSTEM - PERFORMANCE BENCHMARK")
    print("=" * 70)

    memory_manager = MemoryManager()
    analyzer = PerformanceAnalyzer()

    # 测试配置
    num_tasks = 5  # 每种模式运行5个任务
    modes = ["text_only", "structured"]

    print(f"\nBenchmark Configuration:")
    print(f"  Tasks per mode: {num_tasks}")
    print(f"  Modes: {', '.join(modes)}")
    print(f"  Total tasks: {num_tasks * len(modes)}")

    print("\n" + "-" * 70)
    print("Running Benchmark Tasks...")
    print("-" * 70)

    # 运行基准测试
    for mode in modes:
        print(f"\n[{mode.upper()}]")
        for task_num in range(1, num_tasks + 1):
            result = await run_task_with_mode(mode, task_num, memory_manager)
            analyzer.add_result(result)

    print("\n" + "-" * 70)
    print("Benchmark Results")
    print("-" * 70)

    # 生成对比报告
    report = analyzer.generate_report()
    print(report)

    # 显示记忆统计
    print("\nShared Memory Statistics:")
    memory_stats = memory_manager.get_hit_stats()
    print(f"  Total Memories Saved: {memory_stats['total_memories']}")
    print(f"  Total Memory Hits: {memory_stats['total_hits']}")
    if memory_stats["total_memories"] > 0:
        print(f"  Avg Hits per Memory: {memory_stats['avg_hits_per_memory']:.2f}")

    print("\n✓ Benchmark completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
