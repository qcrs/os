"""
检索Agent - 负责信息检索
"""

from typing import Dict, List, Any
from ..core.agent import Agent


class RetrieverAgent(Agent):
    """
    检索Agent: 负责从知识库/文档库检索相关信息
    """

    def __init__(self, agent_id: str = None, **kwargs):
        super().__init__(agent_id=agent_id or "retriever_001", **kwargs)

        # 模拟的知识库
        self.knowledge_base = [
            {
                "id": "doc_001",
                "title": "Machine Learning Optimization",
                "content": "Techniques for optimizing ML models...",
            },
            {
                "id": "doc_002",
                "title": "Distributed Systems",
                "content": "Design patterns for distributed systems...",
            },
            {
                "id": "doc_003",
                "title": "Neural Network Architectures",
                "content": "Overview of modern neural network designs...",
            },
        ]

        # 注册能力
        self.register_capability(
            name="retrieve_documents",
            func=self._retrieve_documents,
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 5}},
                "required": ["query"],
            },
            output_schema={"type": "object", "properties": {"documents": {"type": "array"}}},
        )

    async def _retrieve_documents(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """
        检索相关文档

        Args:
            query: 查询字符串
            top_k: 返回的最大文档数

        Returns:
            检索结果
        """
        self.logger.info(f"Retrieving documents for query: {query}")

        # 简单的匹配逻辑（实际应该用向量搜索）
        retrieved = []
        for doc in self.knowledge_base:
            if query.lower() in doc["title"].lower() or query.lower() in doc["content"].lower():
                retrieved.append(
                    {
                        "id": doc["id"],
                        "title": doc["title"],
                        "content": doc["content"][:200],  # 截断为200字符
                        "score": 0.95,
                    }
                )

        return {
            "query": query,
            "total_count": len(self.knowledge_base),
            "retrieved_count": len(retrieved),
            "documents": retrieved[:top_k],
            "token_cost": len(query.split()) * 2,  # 简化token计算
        }

    async def execute_task(self, task: Dict) -> Dict:
        """
        执行检索任务

        Args:
            task: 任务定义

        Returns:
            执行结果
        """
        query = task.get("query", "")
        top_k = task.get("top_k", 5)
        result = await self._retrieve_documents(query, top_k)
        return result
