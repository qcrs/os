"""
Embedding 管理器：封装 sentence-transformers 的编码接口，提供回退实现以便在无模型环境下仍可运行。
"""

from typing import List, Optional
import logging


class EmbeddingManager:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        self.logger = logging.getLogger("EmbeddingManager")
        self.model_name = model_name
        self.dimension = dimension
        self.model = None

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(model_name)
            self.logger.info(f"Loaded embedding model: {model_name}")
        except Exception as e:
            # 回退：无模型环境下使用伪随机向量
            self.logger.warning(
                f"Failed to load SentenceTransformer('{model_name}'): {e}. Using random fallback."
            )
            self.model = None

    def encode(self, text: str) -> List[float]:
        """将单个文本编码为embedding（列表浮点数）"""
        if self.model is not None:
            vec = self.model.encode(text)
            return vec.tolist()

        # fallback
        import numpy as np

        vec = np.random.RandomState(abs(hash(text)) % (2 ** 32)).randn(self.dimension)
        # 归一化
        norm = (vec ** 2).sum() ** 0.5
        if norm > 0:
            vec = vec / norm
        return vec.tolist()

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """批量编码文本为embedding列表"""
        if self.model is not None:
            vecs = self.model.encode(texts)
            return [v.tolist() for v in vecs]

        # fallback
        return [self.encode(t) for t in texts]

    def get_dimension(self) -> int:
        return self.dimension
