"""
待办任务调度演示

展示如何使用 AgentRuntime 的 TaskScheduler 提交、跟踪和完成待办任务。
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.agent import AgentFactory
from src.core.runtime import AgentRuntime


async def main():
    print("=" * 70)
    print("TODO SCHEDULER DEMO")
    print("=" * 70)

    runtime = AgentRuntime(max_agents=5)

    planner = AgentFactory.create_agent("planner", agent_id="planner_todo")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_todo")
    executor = AgentFactory.create_agent("executor", agent_id="executor_todo")
    summarizer = AgentFactory.create_agent("summarizer", agent_id="summarizer_todo")

    runtime.register_agent(planner)
    runtime.register_agent(retriever)
    runtime.register_agent(executor)
    runtime.register_agent(summarizer)

    runtime.connect_agents(planner.agent_id, retriever.agent_id)
    runtime.connect_agents(retriever.agent_id, executor.agent_id)
    runtime.connect_agents(executor.agent_id, summarizer.agent_id)

    runtime_task = asyncio.create_task(runtime.run())

    await asyncio.sleep(0.5)

    todo_items = [
        {
            "agent_id": planner.agent_id,
            "description": "Generate a multi-step plan for a new research paper outline",
        },
        {
            "agent_id": retriever.agent_id,
            "query": "distributed systems optimization techniques",
            "top_k": 2,
        },
        {
            "agent_id": executor.agent_id,
            "action": "process_data",
            "data": ["summary of doc_001", "summary of doc_002"],
        },
        {
            "agent_id": summarizer.agent_id,
            "action": "generate_report",
            "data": {
                "plan": {"plan_id": "plan_001", "subtasks": []},
                "retrieved_docs": {"retrieved_count": 2, "documents": []},
                "processed_data": {"processed_count": 2},
            },
            "report_type": "todo_summary",
        },
    ]

    print("[1] Submitting todo tasks to runtime scheduler...")
    task_ids = []
    for item in todo_items:
        task_id = await runtime.submit_task(item)
        task_ids.append(task_id)
        print(f"  - Submitted task {task_id} to agent {item['agent_id']}")

    print("\n[2] Waiting for todo tasks to complete...")
    while True:
        pending = [tid for tid in task_ids if runtime.get_task_status(tid) is None or runtime.get_task_status(tid)["status"] != "completed"]
        if not pending:
            break
        print(f"  Waiting for {len(pending)} tasks...")
        await asyncio.sleep(0.5)

    print("\n[3] Task Results")
    for tid in task_ids:
        status = runtime.get_task_status(tid)
        print(f"  Task {tid}: {status['status']}, result_keys={list(status.get('result', {}).keys())}")

    runtime.stop()
    await runtime_task

    print("\n✓ Todo scheduler demo completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
