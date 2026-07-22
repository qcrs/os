from __future__ import annotations

from abc import ABC, abstractmethod


class DenseEmbedder(ABC):
    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the configured dense vector dimension."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate one dense embedding."""

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
