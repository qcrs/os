import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.agent import AgentFactory
from src.core.runtime import AgentRuntime


async def test_runtime_task_scheduler():
    runtime = AgentRuntime(max_agents=3)

    planner = AgentFactory.create_agent("planner", agent_id="planner_test")
    retriever = AgentFactory.create_agent("retriever", agent_id="retriever_test")

    runtime.register_agent(planner)
    runtime.register_agent(retriever)

    runtime.connect_agents(planner.agent_id, retriever.agent_id)

    runtime_task = asyncio.create_task(runtime.run())
    await asyncio.sleep(0.2)

    task_id = await runtime.submit_task({"agent_id": planner.agent_id, "description": "Test task"})
    await asyncio.sleep(0.5)

    status = runtime.get_task_status(task_id)
    assert status is not None
    assert status["status"] in {"completed", "failed"}

    runtime.stop()
    await runtime_task


if __name__ == "__main__":
    asyncio.run(test_runtime_task_scheduler())
