"""Pluggable embedding backends for tensory.

Defines the Embedder Protocol and provides:
- OpenAIEmbedder: uses OpenAI's embedding API (requires `pip install tensory[openai]`)
- NullEmbedder: returns zero vectors — for testing or FTS-only mode

Any class implementing the Embedder Protocol works. See TODO at bottom
for planned backends (sentence-transformers, Ollama, etc.)

Usage::

    from tensory.embedder import OpenAIEmbedder, NullEmbedder

    # OpenAI (recommended: cheap and high quality)
    embedder = OpenAIEmbedder(api_key="sk-...")

    # OpenAI с уменьшенным dimension (ещё дешевле, хранение меньше)
    embedder = OpenAIEmbedder(model="text-embedding-3-small", dim=512)

    # OpenAI через прокси (как в openHunter)
    embedder = OpenAIEmbedder(base_url="http://localhost:8317", api_key="local")

    # Testing / FTS-only (без API ключа)
    embedder = NullEmbedder()

Pricing (OpenAI, March 2026):
    text-embedding-3-small: $0.02 / 1M tokens (1536 dim, reducible to 512)
    text-embedding-3-large: $0.13 / 1M tokens (3072 dim, reducible to 256)
    text-embedding-ada-002: $0.10 / 1M tokens (1536 dim, legacy)

    → 100K claims ≈ 10M tokens ≈ $0.20 with text-embedding-3-small
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Embedder(Protocol):
    """Protocol for embedding text into vectors.

    Implement this to add custom embedding backends:
    - Must provide `dim` property (vector dimension)
    - Must implement `embed()` for single text
    - Must implement `embed_batch()` for efficiency
    """

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

    Models:
        text-embedding-3-small (default) — 1536 dims, $0.02/1M tokens
        text-embedding-3-large           — 3072 dims, $0.13/1M tokens

    Dimension reduction:
        OpenAI supports native dimension reduction via the `dimensions` param.
        Smaller dims = cheaper storage + faster search, slight quality loss.
        Recommended: dim=512 for cost-sensitive, dim=1536 for quality.

    Proxy support:
        Pass base_url for OpenAI-compatible proxy (CLIProxyAPI, LiteLLM, etc.)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
    ) -> None:
        try:
            import openai  # pyright: ignore[reportMissingImports]
        except ImportError as exc:
            msg = "OpenAI package required: pip install tensory[openai]"
            raise ImportError(msg) from exc

        self._client: Any = openai.AsyncOpenAI(  # type: ignore[no-untyped-call]
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, text: str) -> list[float]:
        result: Any = await self._client.embeddings.create(
            input=[text],
            model=self._model,
            dimensions=self._dim,
        )
        embedding: list[float] = list(result.data[0].embedding)
        return embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        result: Any = await self._client.embeddings.create(
            input=texts,
            model=self._model,
            dimensions=self._dim,
        )
        embeddings: list[list[float]] = [list(item.embedding) for item in result.data]
        return embeddings


# ══════════════════════════════════════════════════════════════════════════
# TODO: Additional embedding backends (planned)
# ══════════════════════════════════════════════════════════════════════════
#
# All backends implement the Embedder Protocol above.
# PR contributions welcome!
#
# ── FREE / Local ──────────────────────────────────────────────────────────
#
# class SentenceTransformerEmbedder:
#     """Local embeddings via sentence-transformers. Free, no API key.
#
#     pip install tensory[local]  → sentence-transformers
#
#     Models:
#       all-MiniLM-L6-v2       — 384 dims, fast, good quality
#       all-mpnet-base-v2      — 768 dims, best quality
#       multilingual-e5-small  — 384 dims, multilingual
#
#     Tradeoff: pulls torch (~2GB), slower first load, but free forever.
#     """
#     def __init__(self, model="all-MiniLM-L6-v2"):
#         from sentence_transformers import SentenceTransformer
#         self._model = SentenceTransformer(model)
#         self._dim = self._model.get_sentence_embedding_dimension()
#
#     async def embed(self, text: str) -> list[float]:
#         return self._model.encode(text).tolist()
#
#     async def embed_batch(self, texts: list[str]) -> list[list[float]]:
#         return self._model.encode(texts).tolist()
#
#
# class OllamaEmbedder:
#     """Local embeddings via Ollama. Free, no API key, GPU-accelerated.
#
#     Requires: ollama pull nomic-embed-text
#
#     Models:
#       nomic-embed-text   — 768 dims, good quality
#       mxbai-embed-large  — 1024 dims, best local quality
#       all-minilm          — 384 dims, fastest
#     """
#     def __init__(self, model="nomic-embed-text", base_url="http://localhost:11434"):
#         self._model = model
#         self._base_url = base_url
#
#     async def embed(self, text: str) -> list[float]:
#         async with httpx.AsyncClient() as client:
#             r = await client.post(f"{self._base_url}/api/embeddings",
#                                   json={"model": self._model, "prompt": text})
#             return r.json()["embedding"]
#
#
# class FastEmbedEmbedder:
#     """Local embeddings via Qdrant FastEmbed. Lightweight, ONNX-based.
#
#     pip install fastembed  (no torch dependency!)
#
#     Models:
#       BAAI/bge-small-en-v1.5  — 384 dims, <100MB
#       BAAI/bge-base-en-v1.5   — 768 dims, best quality/size ratio
#     """
#
#
# ── PAID / Cloud ──────────────────────────────────────────────────────────
#
# class VoyageEmbedder:
#     """Voyage AI embeddings. High quality, reasonable pricing.
#     Used by Graphiti as alternative to OpenAI.
#     """
#
# class GeminiEmbedder:
#     """Google Gemini embeddings. Free tier available.
#     text-embedding-004 — 768 dims.
#     """
#
# class CohereEmbedder:
#     """Cohere Embed v3. Good multilingual support.
#     embed-multilingual-v3.0 — 1024 dims.
#     """
#
# ══════════════════════════════════════════════════════════════════════════
