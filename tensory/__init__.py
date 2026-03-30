"""tensory — Context-aware memory for AI agents.

One file. Built-in collision detection.

Usage::

    from tensory import Tensory, Claim, Context

    store = await Tensory.create("memory.db")
    ctx = await store.create_context(goal="Track DeFi team movements")
    result = await store.add_claims([Claim(text="...", entities=["ETH"])])
    results = await store.search("ETH")
"""

from tensory.context import format_context
from tensory.embedder import Embedder, NullEmbedder, OpenAIEmbedder
from tensory.extract import LLMProtocol
from tensory.routing import classify_query
from tensory.graph import GraphBackend, Neo4jBackend, SQLiteGraphBackend
from tensory.models import (
    Claim,
    ClaimType,
    Collision,
    Context,
    EntityRelation,
    Episode,
    IngestResult,
    MemoryType,
    ProceduralResult,
    ReflectResult,
    SearchResult,
)
from tensory.service import TensoryService
from tensory.store import Tensory

__all__ = [
    # Core
    "Tensory",
    "TensoryService",
    # Models
    "Claim",
    "ClaimType",
    "Collision",
    "Context",
    "EntityRelation",
    "Episode",
    "IngestResult",
    "MemoryType",
    "ProceduralResult",
    "ReflectResult",
    "SearchResult",
    # Protocols
    "Embedder",
    "LLMProtocol",
    # Embedders
    "NullEmbedder",
    "OpenAIEmbedder",
    # Graph backends
    "GraphBackend",
    "SQLiteGraphBackend",
    "Neo4jBackend",
    # Context formatting
    "format_context",
    "classify_query",
]

try:
    from tensory._version import __version__
except ModuleNotFoundError:  # editable install / dev without build
    __version__ = "0.0.0.dev0"
