"""
规划Agent - 负责任务分解和规划
"""

from typing import Dict, Any
from ..core.agent import Agent
from ..core.message import MessageBuilder


class PlannerAgent(Agent):
    """
    规划Agent: 负责接收高层任务，进行分解和规划
    """

    def __init__(self, agent_id: str = None, **kwargs):
        super().__init__(agent_id=agent_id or "planner_001", **kwargs)

        # 注册能力
        self.register_capability(
            name="plan_task",
            func=self._plan_task,
            input_schema={"type": "object", "properties": {"task_description": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"subtasks": {"type": "array"}}},
        )

    async def _plan_task(self, task_description: str) -> Dict[str, Any]:
        """
        规划任务，将其分解为子任务

        Args:
            task_description: 任务描述

        Returns:
            包含子任务的字典
        """
        self.logger.info(f"Planning task: {task_description}")

        # 简化示例：任务分解逻辑
        subtasks = [
            {
                "id": "subtask_001",
                "description": "Retrieve relevant information",
                "assigned_to": "retriever",
                "priority": 1,
            },
            {
                "id": "subtask_002",
                "description": "Process and analyze retrieved information",
                "assigned_to": "executor",
                "priority": 2,
            },
            {
                "id": "subtask_003",
                "description": "Summarize results",
                "assigned_to": "summarizer",
                "priority": 3,
            },
        ]

        return {
            "plan_id": "plan_001",
            "task": task_description,
            "subtasks": subtasks,
            "status": "planned",
        }

    async def execute_task(self, task: Dict) -> Dict:
        """
        执行规划任务

        Args:
            task: 任务定义

        Returns:
            执行结果
        """
        task_description = task.get("description", "No description")
        result = await self._plan_task(task_description)
        return result
