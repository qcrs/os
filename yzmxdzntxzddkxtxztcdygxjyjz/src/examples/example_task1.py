"""
示例任务1 - RAG（检索增强生成）任务演示

演示多Agent协作执行复杂任务：
1. 规划Agent分解任务
2. 检索Agent获取信息
3. 执行Agent处理信息
4. 总结Agent生成结果
"""

import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.agent import AgentFactory
from src.core.runtime import AgentRuntime, TaskScheduler
from src.memory.memory_manager import MemoryManager
from src.evaluation.metrics import MetricsCollector


async def main():
    print("=" * 60)
    print("Example Task 1: Multi-Agent RAG (Retrieval-Augmented Gen)")
    print("=" * 60)

    # 初始化运行时
    runtime = AgentRuntime(max_agents=4)
    memory_manager = MemoryManager()
    metrics_collector = MetricsCollector()

    # 创建Agent
    print("\n[1] Creating agents...")
    planner = AgentFactory.create_agent("planner", agent_id="planner_001")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_001")
    executor = AgentFactory.create_agent("executor", agent_id="executor_001")
    summarizer = AgentFactory.create_agent("summarizer", agent_id="summarizer_001")

    # 注册Agent到运行时
    print("[2] Registering agents to runtime...")
    runtime.register_agent(planner)
    runtime.register_agent(retriever)
    runtime.register_agent(executor)
    runtime.register_agent(summarizer)

    # 连接Agent
    print("[3] Connecting agents...")
    runtime.connect_agents("planner_001", "retriever_001")
    runtime.connect_agents("planner_001", "executor_001")
    runtime.connect_agents("retriever_001", "executor_001")
    runtime.connect_agents("executor_001", "summarizer_001")

    # 执行握手
    print("[4] Handshake between agents...")
    try:
        await planner.handshake_with_agent(retriever)
        await retriever.handshake_with_agent(executor)
        await executor.handshake_with_agent(summarizer)
        print("✓ Handshake successful")
    except Exception as e:
        print(f"✗ Handshake failed: {e}")

    # 执行任务
    print("\n[5] Executing task...")
    task_id = "task_rag_001"
    metrics_collector.start_task(task_id, mode="structured")

    # 任务定义
    task_description = "Analyze machine learning optimization techniques from multiple sources"

    # 第1步: 规划
    print("\n  Step 1: Planning (Planner Agent)")
    plan_result = await planner._plan_task(task_description)
    metrics_collector.record_message(task_id, "text", tokens=len(task_description.split()))
    print(f"    ✓ Plan ID: {plan_result['plan_id']}")
    print(f"    ✓ Subtasks: {len(plan_result['subtasks'])}")

    # 保存规划记忆
    memory_manager.save_result(
        source_agent="planner_001",
        task_id=task_id,
        task_topic="planning",
        result=plan_result,
        tags=["planning", "ml", "optimization"],
    )

    # 第2步: 检索
    print("\n  Step 2: Retrieval (Retriever Agent)")
    retrieval_query = "machine learning optimization techniques"
    retrieval_result = await retriever._retrieve_documents(retrieval_query, top_k=3)
    metrics_collector.record_message(task_id, "text", tokens=retrieval_result.get("token_cost", 10))
    print(f"    ✓ Retrieved {retrieval_result['retrieved_count']} documents")
    print(f"    ✓ Total docs: {retrieval_result['total_count']}")

    # 保存检索记忆
    memory_manager.save_result(
        source_agent="retriever_001",
        task_id=task_id,
        task_topic="retrieval",
        result=retrieval_result,
        tags=["retrieval", "ml", "optimization", "documents"],
    )

    # 第3步: 执行
    print("\n  Step 3: Processing (Executor Agent)")
    processing_task = {
        "action": "process_data",
        "data": [f"doc_{i}" for i in range(retrieval_result["retrieved_count"])],
    }
    processing_result = await executor.execute_task(processing_task)
    metrics_collector.record_message(task_id, "state", size_bytes=1024)
    print(f"    ✓ Processed {processing_result['processed_count']} items")

    # 保存处理记忆
    memory_manager.save_result(
        source_agent="executor_001",
        task_id=task_id,
        task_topic="processing",
        result=processing_result,
        tags=["processing", "analysis"],
    )

    # 通过记忆检索验证共享记忆是否可用
    print("\n  Step 3.5: Memory Retrieval Validation")
    query_text = "machine learning optimization"
    related_memories = memory_manager.retrieve_relevant(query_text, top_k=3)
    print(f"    ✓ Retrieved {len(related_memories)} related memories for query '{query_text}'")
    for idx, mem in enumerate(related_memories, start=1):
        score = getattr(mem, "similarity_score", None)
        score_text = f"{score:.3f}" if score is not None else "N/A"
        print(f"      {idx}. [{mem.memory_id}] topic={mem.task_topic} score={score_text} summary={mem.summary[:60]}...")

    # 第4步: 总结
    print("\n  Step 4: Summarization (Summarizer Agent)")
    summarization_task = {
        "action": "generate_report",
        "data": {
            "plan": plan_result,
            "retrieved_docs": retrieval_result,
            "processed_data": processing_result,
        },
        "report_type": "comprehensive",
    }
    final_result = await summarizer.execute_task(summarization_task)
    metrics_collector.record_message(task_id, "text", tokens=100)
    print(f"    ✓ Report generated ({final_result['report_length']} chars)")

    # 保存最终结果记忆
    memory_manager.save_result(
        source_agent="summarizer_001",
        task_id=task_id,
        task_topic="summary",
        result=final_result,
        tags=["summary", "report", "final"],
    )

    metrics_collector.end_task(task_id)

    # 显示结果
    print("\n" + "=" * 60)
    print("TASK EXECUTION COMPLETED")
    print("=" * 60)

    # 显示指标
    print("\nPerformance Metrics:")
    metrics = metrics_collector.get_task_metrics(task_id)
    print(f"  Duration: {metrics['duration_ms']:.2f}ms")
    print(f"  Messages: {metrics['message_count']}")
    print(f"  Tokens: {metrics['text_tokens']}")
    print(f"  State Transfers: {metrics['state_transfer_count']}")

    # 显示记忆
    print("\nShared Memories:")
    all_memories = memory_manager.store.list_all_memories()
    for memory in all_memories:
        print(f"  - {memory.memory_id}")
        print(f"    Agent: {memory.source_agent}")
        print(f"    Topic: {memory.task_topic}")
        print(f"    Summary: {memory.summary[:60]}...")

    print("\nMemory Statistics:")
    stats = memory_manager.get_hit_stats()
    print(f"  Total Memories: {stats['total_memories']}")
    print(f"  Avg Confidence: {stats['avg_confidence']:.2f}")

    # 显示Agent状态
    print("\nAgent Statistics:")
    for agent_id, agent in runtime.agents.items():
        agent_stats = agent.get_stats()
        print(f"  {agent_id}:")
        print(f"    Messages: {agent_stats['message_count']}")
        print(f"    Errors: {agent_stats['error_count']}")
        print(f"    Capabilities: {agent_stats['capabilities_count']}")

    print("\n✓ Example task 1 completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
