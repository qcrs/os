"""
总结Agent - 负责结果总结和生成
"""

from typing import Dict, Any, List
from ..core.agent import Agent


class SummarizerAgent(Agent):
    """
    总结Agent: 负责汇总结果、生成最终答案
    """

    def __init__(self, agent_id: str = None, **kwargs):
        super().__init__(agent_id=agent_id or "summarizer_001", **kwargs)

        # 注册能力
        self.register_capability(
            name="summarize",
            func=self._summarize,
            input_schema={
                "type": "object",
                "properties": {"content": {"type": "string"}, "max_length": {"type": "integer"}},
                "required": ["content"],
            },
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )

        self.register_capability(
            name="generate_report",
            func=self._generate_report,
            input_schema={
                "type": "object",
                "properties": {"data": {"type": "object"}, "report_type": {"type": "string"}},
                "required": ["data"],
            },
            output_schema={"type": "object", "properties": {"report": {"type": "string"}}},
        )

    async def _summarize(self, content: str, max_length: int = 200) -> Dict[str, Any]:
        """
        总结内容

        Args:
            content: 要总结的内容
            max_length: 最大总结长度

        Returns:
            总结结果
        """
        self.logger.info(f"Summarizing content of length {len(content)}")

        # 简化示例：取前max_length个字符
        summary = content[:max_length]
        if len(content) > max_length:
            summary += "..."

        return {
            "original_length": len(content),
            "summary_length": len(summary),
            "summary": summary,
            "compression_ratio": len(summary) / len(content) if content else 0,
        }

    async def _generate_report(self, data: Dict, report_type: str = "standard") -> Dict[str, Any]:
        """
        生成报告

        Args:
            data: 数据字典
            report_type: 报告类型

        Returns:
            报告内容
        """
        self.logger.info(f"Generating {report_type} report")

        # 简化示例：生成基本报告
        report_content = f"""
Report Type: {report_type}
Generated: {self._get_timestamp()}
Data Summary:
- Total Keys: {len(data)}
- Keys: {', '.join(list(data.keys())[:5])}
"""

        return {
            "report_type": report_type,
            "report_length": len(report_content),
            "report": report_content,
            "status": "generated",
        }

    def _get_timestamp(self) -> str:
        """获取当前时间戳"""
        from datetime import datetime

        return datetime.now().isoformat()

    async def execute_task(self, task: Dict) -> Dict:
        """
        执行总结任务

        Args:
            task: 任务定义

        Returns:
            执行结果
        """
        action = task.get("action", "summarize")

        if action == "generate_report":
            data = task.get("data", {})
            report_type = task.get("report_type", "standard")
            return await self._generate_report(data, report_type)
        else:
            content = task.get("content", "")
            max_length = task.get("max_length", 200)
            return await self._summarize(content, max_length)
