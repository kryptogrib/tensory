"""Pluggable embedding backends for tensory.

Defines the Embedder Protocol and provides:
- OpenAIEmbedder: uses OpenAI's embedding API (requires `pip install tensory[openai]`)
- NullEmbedder: returns zero vectors — for testing or FTS-only mode

Usage::

    from tensory.embedder import OpenAIEmbedder, NullEmbedder

    # Production: real embeddings
    embedder = OpenAIEmbedder(api_key="sk-...")

    # Testing: zero vectors (disables vector search, FTS still works)
    embedder = NullEmbedder(dim=1536)
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding text into vectors."""

    @property
    def dim(self) -> int:
        """Embedding dimension."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Embed a single text string."""
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single call (for efficiency)."""
        ...


class NullEmbedder:
    """Returns zero vectors. For testing or FTS-only mode.

    Vector search will return no results, but FTS and graph search
    still work — graceful degradation by design.
    """

    def __init__(self, *, dim: int = 1536) -> None:
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, text: str) -> list[float]:
        return [0.0] * self._dim

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dim for _ in texts]


class OpenAIEmbedder:
    """Embedding via OpenAI's API.

    Requires: ``pip install tensory[openai]``

    Uses text-embedding-3-small by default (1536 dimensions).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ) -> None:
        try:
            import openai  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            msg = "OpenAI package required: pip install tensory[openai]"
            raise ImportError(msg) from exc

        self._client: Any = openai.AsyncOpenAI(api_key=api_key)  # type: ignore[no-untyped-call]
        self._model = model
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, text: str) -> list[float]:
        result: Any = await self._client.embeddings.create(
            input=[text],
            model=self._model,
        )
        embedding: list[float] = list(result.data[0].embedding)
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result: Any = await self._client.embeddings.create(
            input=texts,
            model=self._model,
        )
        embeddings: list[list[float]] = [list(item.embedding) for item in result.data]
        return embeddings
