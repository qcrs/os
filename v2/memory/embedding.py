from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Protocol

from v2.memory.models import StructuredEmbedding
from v2.utils import sha256_digest


DEFAULT_EMBED_DEVICE = "auto"
_MODEL_CACHE: dict[tuple[str, str], object] = {}


class EmbeddingEncoder(Protocol):
    def encode(self, *, embedding_id: str, text: str) -> StructuredEmbedding: ...


def default_embedding_model_path() -> Path:
    statebus_home = Path(os.getenv("STATEBUS_HOME", Path.home() / "statebus"))
    return Path(os.getenv("STATEBUS_EMBED_MODEL_PATH", statebus_home / "models" / "Qwen3-Embedding-0.6B"))


def torch_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_embed_device(device: str | None = None) -> str:
    candidate = (device or os.getenv("STATEBUS_EMBED_DEVICE") or DEFAULT_EMBED_DEVICE).strip()
    if not candidate or candidate.lower() == DEFAULT_EMBED_DEVICE:
        return "cuda:0" if torch_cuda_available() else "cpu"
    return candidate


@dataclass(frozen=True)
class DeterministicEmbeddingEncoder:
    dims: int = 16

    def encode(self, *, embedding_id: str, text: str) -> StructuredEmbedding:
        counts = [0.0] * self.dims
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        if not tokens:
            return StructuredEmbedding(
                embedding_id=embedding_id,
                vector=tuple(counts),
                dims=self.dims,
                source_text_hash=sha256_digest(text),
            )
        for token in tokens:
            slot = int(sha256_digest(token), 16) % self.dims
            counts[slot] += float(len(token))
        norm = sum(value * value for value in counts) ** 0.5 or 1.0
        vector = tuple(round(value / norm, 6) for value in counts)
        return StructuredEmbedding(
            embedding_id=embedding_id,
            vector=vector,
            dims=self.dims,
            source_text_hash=sha256_digest(text),
        )


class SentenceTransformerEmbeddingEncoder:
    def __init__(
        self,
        *,
        model_path: str | Path | None = None,
        device: str | None = None,
    ) -> None:
        self.model_path = Path(model_path or default_embedding_model_path())
        self.device = resolve_embed_device(device)
        self._model = None
        self._dims: int | None = None

    def _ensure_model(self) -> object:
        if self._model is not None:
            return self._model
        if not self.model_path.exists():
            raise FileNotFoundError(f"embedding model not found: {self.model_path}")
        cache_key = (str(self.model_path.resolve()), self.device)
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            self._model = cached
            return cached
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(str(self.model_path), device=self.device)
        _MODEL_CACHE[cache_key] = self._model
        return self._model

    @property
    def dims(self) -> int:
        if self._dims is None:
            self._dims = self.encode(embedding_id="warmup-embedding", text="statebus warmup").dims
        return self._dims

    def encode(self, *, embedding_id: str, text: str) -> StructuredEmbedding:
        model = self._ensure_model()
        vector = model.encode(  # type: ignore[attr-defined]
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        values = tuple(round(float(item), 6) for item in vector.tolist())
        dims = len(values)
        self._dims = dims
        return StructuredEmbedding(
            embedding_id=embedding_id,
            vector=values,
            dims=dims,
            source_text_hash=sha256_digest(text),
            encoding=f"sentence-transformers:{self.model_path.name}",
        )


def build_embedding_encoder(
    mode: str = "deterministic",
    *,
    dims: int = 16,
    model_path: str | Path | None = None,
    device: str | None = None,
) -> EmbeddingEncoder:
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "deterministic":
        return DeterministicEmbeddingEncoder(dims=dims)
    if normalized_mode in {"local", "sentence-transformers", "sentence_transformer"}:
        return SentenceTransformerEmbeddingEncoder(model_path=model_path, device=device)
    raise ValueError(f"unsupported embedding mode: {mode}")


def cosine_similarity(left: StructuredEmbedding, right: StructuredEmbedding) -> float:
    if left.dims != right.dims:
        raise ValueError("embedding dims mismatch")
    return round(sum(lv * rv for lv, rv in zip(left.vector, right.vector)), 6)
