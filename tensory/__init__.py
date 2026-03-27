"""tensory — Context-aware memory for AI agents.

One file. Built-in collision detection.

Usage::

    from tensory import Tensory, Claim, Context

    store = await Tensory.create("memory.db")
    ctx = await store.create_context(goal="Track DeFi team movements")
    result = await store.add_claims([Claim(text="...", entities=["ETH"])])
    results = await store.search("ETH")
"""

from tensory.embedder import Embedder, NullEmbedder, OpenAIEmbedder
from tensory.extract import LLMProtocol
from tensory.models import (
    Claim,
    ClaimType,
    Collision,
    Context,
    EntityRelation,
    Episode,
    IngestResult,
    SearchResult,
)
from tensory.store import Tensory

__all__ = [
    # Core
    "Tensory",
    # Models
    "Claim",
    "ClaimType",
    "Collision",
    "Context",
    "EntityRelation",
    "Episode",
    "IngestResult",
    "SearchResult",
    # Protocols
    "Embedder",
    "LLMProtocol",
    # Embedders
    "NullEmbedder",
    "OpenAIEmbedder",
]

__version__ = "0.1.0"
