from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any, Callable


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


class BM25Encoder:
    """Qdrant BM25 encoder with optional Chinese word segmentation."""

    def __init__(
        self,
        model_name: str = "Qdrant/bm25",
        *,
        model_path: str | Path | None = None,
        language: str = "english",
        chinese_tokenizer: Callable[[str], list[str]] | None = None,
        encoder: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.model_path = Path(model_path).expanduser().resolve() if model_path else None
        self.language = language
        self._chinese_tokenizer = chinese_tokenizer
        self._encoder = encoder

    def _get_chinese_tokenizer(self) -> Callable[[str], list[str]]:
        if self._chinese_tokenizer is None:
            try:
                import jieba
            except ImportError as exc:
                raise RuntimeError(
                    "Chinese BM25 tokenization requires jieba. "
                    "Install memory_module requirements first."
                ) from exc
            tokenizer = jieba.Tokenizer()
            tokenizer.cache_file = str(
                Path(tempfile.gettempdir()) / "memory_module_jieba.cache"
            )
            self._chinese_tokenizer = lambda text: list(
                tokenizer.cut(text, cut_all=False)
            )
        return self._chinese_tokenizer

    def preprocess(self, text: str) -> str:
        text = text.strip()
        if not text or not _CJK_RE.search(text):
            return text

        tokens = self._get_chinese_tokenizer()(text)
        return " ".join(token.strip() for token in tokens if token.strip())

    def _get_encoder(self) -> Any:
        if self._encoder is None:
            if self.model_path is not None and not self.model_path.is_dir():
                raise RuntimeError(
                    f"BM25 model path does not exist or is not a directory: {self.model_path}"
                )
            try:
                from fastembed import SparseTextEmbedding
            except ImportError as exc:
                raise RuntimeError(
                    "BM25 search requires fastembed. Install memory_module requirements first."
                ) from exc
            try:
                self._encoder = SparseTextEmbedding(
                    model_name=self.model_name,
                    specific_model_path=(
                        str(self.model_path) if self.model_path is not None else None
                    ),
                    language=self.language,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to initialize BM25 model '{self.model_name}'. "
                    "The first run may need to download model files; check network, "
                    "proxy, and Hugging Face cache configuration."
                ) from exc
        return self._encoder

    def encode(self, text: str) -> tuple[list[int], list[float]]:
        prepared_text = self.preprocess(text)
        results = list(self._get_encoder().embed([prepared_text]))
        if not results:
            return [], []
        vector = results[0]
        return vector.indices.tolist(), vector.values.tolist()
