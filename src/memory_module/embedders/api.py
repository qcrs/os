from __future__ import annotations

from typing import Any

from openai import OpenAI

from .base import DenseEmbedder


class OpenAICompatibleEmbedder(DenseEmbedder):
    """Dense embedder for OpenAI-compatible embedding APIs."""

    def __init__(
        self,
        *,
        model: str,
        dimension: int,
        api_key: str,
        base_url: str | None = None,
        client: Any | None = None,
        pass_dimensions: bool = False,
    ) -> None:
        if not model.strip():
            raise ValueError("model must not be empty")
        if dimension <= 0:
            raise ValueError("dimension must be greater than zero")
        if client is None and not api_key:
            raise ValueError("api_key is required when client is not provided")

        self.model = model
        self._dimension = dimension
        self.pass_dimensions = pass_dimensions
        self.client = client or OpenAI(api_key=api_key, base_url=base_url)

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        kwargs: dict[str, Any] = {"input": texts, "model": self.model}
        if self.pass_dimensions:
            kwargs["dimensions"] = self.dimension

        response = self.client.embeddings.create(**kwargs)
        vectors = [item.embedding for item in sorted(response.data, key=lambda item: item.index)]
        for vector in vectors:
            if len(vector) != self.dimension:
                raise ValueError(
                    f"Embedding API returned dimension {len(vector)}, expected {self.dimension}"
                )
        return vectors
