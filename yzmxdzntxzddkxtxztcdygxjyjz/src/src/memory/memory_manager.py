"""
共享记忆模块 - 存储和检索任务中的中间结果
"""

import uuid
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
import json


class MemoryUnit:
    """
    记忆单元 - 表示一个可存储、可检索的记忆
    """

    def __init__(
        self,
        source_agent: str,
        task_id: str,
        task_topic: str,
        summary: str,
        content: Any = None,
        tags: List[str] = None,
        embedding: List[float] = None,
    ):
        """
        初始化记忆单元

        Args:
            source_agent: 来源Agent
            task_id: 任务ID
            task_topic: 任务主题
            summary: 摘要
            content: 完整内容
            tags: 标签列表
            embedding: 向量表示
        """
        self.memory_id = f"mem_{uuid.uuid4().hex[:12]}"
        self.source_agent = source_agent
        self.created_at = datetime.now()
        self.task_id = task_id
        self.task_topic = task_topic
        self.summary = summary
        self.content = content or {}
        self.tags = tags or []
        self.embedding = embedding or []
        self.confidence = 0.9
        self.hit_count = 0

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "memory_id": self.memory_id,
            "source_agent": self.source_agent,
            "created_at": self.created_at.isoformat(),
            "task_id": self.task_id,
            "task_topic": self.task_topic,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
            "embedding": self.embedding,
            "confidence": self.confidence,
            "hit_count": self.hit_count,
        }


class MemoryStore:
    """
    记忆存储 - 管理所有记忆单元的存储和检索
    """

    def __init__(self, backend: str = "memory"):
        """
        初始化记忆存储

        Args:
            backend: 存储后端 (memory|sqlite|chroma)
        """
        self.backend = backend
        self.memories: Dict[str, MemoryUnit] = {}  # 在内存中存储
        self.logger = logging.getLogger("MemoryStore")

    def save_memory(self, memory: MemoryUnit) -> str:
        """
        保存记忆单元

        Args:
            memory: 记忆单元

        Returns:
            记忆ID
        """
        self.memories[memory.memory_id] = memory
        self.logger.info(f"Saved memory: {memory.memory_id}")
        return memory.memory_id

    def retrieve_by_id(self, memory_id: str) -> Optional[MemoryUnit]:
        """按ID检索记忆"""
        return self.memories.get(memory_id)

    def retrieve_by_keyword(self, keywords: List[str], top_k: int = 5) -> List[MemoryUnit]:
        """
        按关键词检索记忆

        Args:
            keywords: 关键词列表
            top_k: 返回最多记忆数

        Returns:
            匹配的记忆列表
        """
        results = []

        for memory in self.memories.values():
            # 检查标签是否匹配
            if any(kw in memory.tags for kw in keywords):
                results.append(memory)
            # 检查摘要是否包含关键词
            elif any(kw.lower() in memory.summary.lower() for kw in keywords):
                results.append(memory)

        # 按命中数排序
        results.sort(key=lambda m: m.hit_count, reverse=True)
        return results[:top_k]

    def retrieve_by_task(self, task_id: str) -> List[MemoryUnit]:
        """按任务ID检索相关记忆"""
        return [m for m in self.memories.values() if m.task_id == task_id]

    def retrieve_by_topic(self, topic: str, top_k: int = 5) -> List[MemoryUnit]:
        """按主题检索记忆"""
        results = [m for m in self.memories.values() if m.task_topic == topic]
        results.sort(key=lambda m: m.hit_count, reverse=True)
        return results[:top_k]

    def list_all_memories(self) -> List[MemoryUnit]:
        """列出所有记忆"""
        return list(self.memories.values())

    def get_memory_stats(self) -> Dict:
        """获取记忆统计信息"""
        total_memories = len(self.memories)
        total_hits = sum(m.hit_count for m in self.memories.values())
        avg_confidence = (
            sum(m.confidence for m in self.memories.values()) / total_memories if total_memories > 0 else 0
        )

        return {
            "total_memories": total_memories,
            "total_hits": total_hits,
            "avg_confidence": avg_confidence,
            "avg_hits_per_memory": total_hits / total_memories if total_memories > 0 else 0,
        }


class SemanticMemorySearcher:
    """
    语义记忆搜索器 - 基于向量相似度搜索记忆
    """

    def __init__(self):
        self.logger = logging.getLogger("SemanticMemorySearcher")

    def search_by_similarity(
        self, query_embedding: List[float], memories: List[MemoryUnit], top_k: int = 5
    ) -> List[tuple]:
        """
        按向量相似度搜索记忆

        Args:
            query_embedding: 查询的向量表示
            memories: 记忆列表
            top_k: 返回最多结果数

        Returns:
            (记忆, 相似度分数) 的列表，按相似度降序排列
        """
        results = []

        for memory in memories:
            if memory.embedding:
                # 计算余弦相似度
                similarity = self._cosine_similarity(query_embedding, memory.embedding)
                results.append((memory, similarity))

        # 按相似度降序排列
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)


class MemoryManager:
    """
    记忆管理器 - 整合记忆存储和检索功能
    """

    def __init__(self, backend: str = "memory", embedding_model: str = "all-MiniLM-L6-v2"):
        self.store = MemoryStore(backend=backend)
        self.searcher = SemanticMemorySearcher()
        self.logger = logging.getLogger("MemoryManager")

        # 状态交换组件：Embedding 生成与向量存储
        try:
            from src.state_exchange.embedding_manager import EmbeddingManager
            from src.state_exchange.vector_store import VectorStore

            self.embedding_manager = EmbeddingManager(model_name=embedding_model)
            self.vector_store = VectorStore(dimension=self.embedding_manager.get_dimension())
            self.logger.info("EmbeddingManager and VectorStore initialized")
        except Exception as e:
            # 安全降级：若导入失败，保留属性为None，但系统仍可运行
            self.embedding_manager = None
            self.vector_store = None
            self.logger.warning(f"Failed to initialize embedding/vector store: {e}")

    def save_result(
        self,
        source_agent: str,
        task_id: str,
        task_topic: str,
        result: Any,
        tags: List[str] = None,
        embedding: List[float] = None,
    ) -> str:
        """
        保存任务结果到记忆

        Args:
            source_agent: 来源Agent
            task_id: 任务ID
            task_topic: 任务主题
            result: 结果
            tags: 标签
            embedding: 向量表示

        Returns:
            记忆ID
        """
        # 生成摘要
        summary = self._generate_summary(result)

        # 如果没有提供 embedding，则尝试生成
        emb = embedding
        if (emb is None or len(emb) == 0) and self.embedding_manager is not None:
            try:
                emb = self.embedding_manager.encode(summary or str(result))
            except Exception as e:
                self.logger.warning(f"Embedding generation failed: {e}")
                emb = []

        # 创建记忆单元
        memory = MemoryUnit(
            source_agent=source_agent,
            task_id=task_id,
            task_topic=task_topic,
            summary=summary,
            content=result,
            tags=tags or [],
            embedding=emb or [],
        )

        mem_id = self.store.save_memory(memory)

        # 将embedding索引到向量存储
        if self.vector_store is not None and memory.embedding:
            try:
                self.vector_store.add_vector(mem_id, memory.embedding, metadata={
                    "task_topic": task_topic,
                    "source_agent": source_agent,
                })
            except Exception as e:
                self.logger.warning(f"Failed to add vector to store for memory {mem_id}: {e}")

        return mem_id

    def retrieve_relevant(
        self, query: str, query_embedding: List[float] = None, top_k: int = 5
    ) -> List[MemoryUnit]:
        """
        检索相关记忆

        Args:
            query: 查询文本
            query_embedding: 查询向量
            top_k: 返回最多结果数

        Returns:
            相关记忆列表
        """
        # 优先使用向量检索（若可用）
        if query_embedding is None and self.embedding_manager is not None:
            try:
                query_embedding = self.embedding_manager.encode(query)
            except Exception as e:
                self.logger.warning(f"Failed to encode query to embedding: {e}")
                query_embedding = None

        if query_embedding is not None and self.vector_store is not None:
            try:
                vec_results = self.vector_store.search(query_embedding, top_k=top_k)
                memories = []
                for mem_id, score, metadata in vec_results:
                    mem = self.store.retrieve_by_id(mem_id)
                    if mem:
                        # 记录命中并附加相似度分数
                        mem.hit_count += 1
                        setattr(mem, "similarity_score", score)
                        memories.append(mem)
                return memories
            except Exception as e:
                self.logger.warning(f"Vector search failed: {e}")

        # 回退到关键词检索
        keywords = query.split()
        keyword_results = self.store.retrieve_by_keyword(keywords, top_k=top_k * 2)
        for mem in keyword_results:
            mem.hit_count += 1
        return keyword_results[:top_k]

    def _generate_summary(self, result: Any) -> str:
        """生成结果摘要"""
        if isinstance(result, dict):
            # 提取关键字段
            if "summary" in result:
                return result["summary"][:200]
            elif "result" in result:
                text = str(result["result"])
                return text[:200]

        text = str(result)
        return text[:200] + ("..." if len(text) > 200 else "")

    def get_hit_stats(self) -> Dict:
        """获取记忆命中统计"""
        return self.store.get_memory_stats()
