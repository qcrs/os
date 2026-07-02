"""
执行Agent - 负责任务执行和工具调用
"""

from typing import Dict, Any
from ..core.agent import Agent


class ExecutorAgent(Agent):
    """
    执行Agent: 负责执行具体任务、调用工具
    """

    def __init__(self, agent_id: str = None, **kwargs):
        super().__init__(agent_id=agent_id or "executor_001", **kwargs)

        # 注册能力
        self.register_capability(
            name="execute_code",
            func=self._execute_code,
            input_schema={"type": "object", "properties": {"code": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        )

        self.register_capability(
            name="process_data",
            func=self._process_data,
            input_schema={"type": "object", "properties": {"data": {"type": "array"}}},
            output_schema={"type": "object", "properties": {"processed_data": {"type": "array"}}},
        )

    async def _execute_code(self, code: str) -> Dict[str, Any]:
        """
        执行代码片段

        Args:
            code: Python代码

        Returns:
            执行结果
        """
        self.logger.info(f"Executing code: {code[:100]}...")

        # 简化示例：不真正执行代码，而是返回模拟结果
        return {
            "status": "success",
            "output": f"Code executed successfully",
            "result": "dummy_result",
        }

    async def _process_data(self, data: list) -> Dict[str, Any]:
        """
        处理数据

        Args:
            data: 数据列表

        Returns:
            处理结果
        """
        self.logger.info(f"Processing {len(data)} data items")

        # 简单的数据处理逻辑
        processed = [str(item).upper() for item in data]

        return {
            "status": "success",
            "original_count": len(data),
            "processed_count": len(processed),
            "processed_data": processed,
        }

    async def execute_task(self, task: Dict) -> Dict:
        """
        执行执行任务

        Args:
            task: 任务定义

        Returns:
            执行结果
        """
        action = task.get("action", "process_data")

        if action == "execute_code":
            code = task.get("code", "")
            return await self._execute_code(code)
        else:
            data = task.get("data", [])
            return await self._process_data(data)
