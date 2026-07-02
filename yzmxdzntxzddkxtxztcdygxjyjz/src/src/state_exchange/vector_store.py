"""
简单向量存储：优先使用FAISS（若已安装），否则使用内存线性扫描。
提供 add_vector 和 search 接口。
"""

from typing import List, Dict, Optional, Tuple
import logging


class VectorStore:
    def __init__(self, dimension: int = 384, backend: str = "auto"):
        self.logger = logging.getLogger("VectorStore")
        self.dimension = dimension
        self.backend = backend
        self._use_faiss = False
        self._id_to_index: Dict[str, int] = {}
        self._vectors: List[List[float]] = []
        self._metadatas: List[Dict] = []

        if backend in ("faiss", "auto"):
            try:
                import faiss  # type: ignore

                # 使用内积检索（需保证向量归一化）
                self._faiss = faiss.IndexFlatIP(self.dimension)
                self._use_faiss = True
                self.logger.info("FAISS backend initialized")
            except Exception as e:
                self._use_faiss = False
                self.logger.warning(f"FAISS not available, fallback to in-memory store: {e}")
        else:
            self.logger.info("Using in-memory vector store (no FAISS)")

    def add_vector(self, vector_id: str, vector: List[float], metadata: Optional[Dict] = None) -> None:
        """添加向量到存储中（如果存在则覆盖）"""
        if vector_id in self._id_to_index:
            idx = self._id_to_index[vector_id]
            self._vectors[idx] = vector
            self._metadatas[idx] = metadata or {}
            if self._use_faiss:
                # FAISS不支持直接替换指定索引的向量，重建索引
                self._rebuild_faiss()
            return

        idx = len(self._vectors)
        self._id_to_index[vector_id] = idx
        self._vectors.append(vector)
        self._metadatas.append(metadata or {})

        if self._use_faiss:
            import numpy as np

            vec = np.array(vector, dtype="float32")[None, :]
            self._faiss.add(vec)

    def search(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float, Dict]]:
        """
        搜索最相似的向量，返回 (vector_id, score, metadata)
        score 越大越相似（使用内积或余弦，假定向量已归一化）
        """
        if not self._vectors:
            return []

        if self._use_faiss:
            try:
                import numpy as np

                q = np.array(query_vector, dtype="float32")[None, :]
                distances, indices = self._faiss.search(q, top_k)
                results = []
                for score, idx in zip(distances[0], indices[0]):
                    if idx < 0 or idx >= len(self._metadatas):
                        continue
                    # FAISS返回的是相似度（内积）
                    vid = list(self._id_to_index.keys())[list(self._id_to_index.values()).index(idx)]
                    results.append((vid, float(score), self._metadatas[idx]))
                return results
            except Exception as e:
                self.logger.warning(f"FAISS search failed, fallback to in-memory: {e}")

        # in-memory brute-force (余弦相似度)
        return self._search_bruteforce(query_vector, top_k)

    def _search_bruteforce(self, query_vector: List[float], top_k: int = 5) -> List[Tuple[str, float, Dict]]:
        import math

        q = query_vector
        results = []
        for vid, idx in self._id_to_index.items():
            v = self._vectors[idx]
            # 余弦相似度
            dot = sum(a * b for a, b in zip(q, v))
            mag_q = math.sqrt(sum(a * a for a in q))
            mag_v = math.sqrt(sum(b * b for b in v))
            score = 0.0
            if mag_q > 0 and mag_v > 0:
                score = dot / (mag_q * mag_v)
            results.append((vid, score, self._metadatas[idx]))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _rebuild_faiss(self):
        try:
            import numpy as np
            import faiss  # type: ignore

            self._faiss = faiss.IndexFlatIP(self.dimension)
            if self._vectors:
                arr = np.array(self._vectors, dtype="float32")
                self._faiss.add(arr)
        except Exception as e:
            self.logger.warning(f"Failed to rebuild FAISS index: {e}")
            self._use_faiss = False
