"""Pydantic models for tensory's 4-layer memory architecture.

Layer 0: RAW       — Episode (raw text, source). Never deleted.
Layer 1: CLAIMS    — Claim (atomic statement + salience + embedding).
Layer 2: GRAPH     — EntityRelation (LLM-extracted relationships).
Layer 3: CONTEXT   — Context (user research goal as extraction lens).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    """UTC-aware datetime factory for default field values."""
    return datetime.now(UTC)


class ClaimType(StrEnum):
    """Claim taxonomy — each type has a different decay rate.

    Inspired by Hindsight CARA architecture (arxiv.org/abs/2512.12818).
    """

    FACT = "fact"  # verifiable statement
    EXPERIENCE = "experience"  # event that happened
    OBSERVATION = "observation"  # inference from other claims
    OPINION = "opinion"  # evaluative judgment


# ---------------------------------------------------------------------------
# Layer 0: RAW — episodes (raw text). Never deleted.
# ---------------------------------------------------------------------------


class Episode(BaseModel):
    """Raw text stored forever. Source of truth for re-extraction."""

    id: str
    raw_text: str
    source: str = ""  # e.g. "reddit:r/defi", "telegram:channel"
    source_url: str | None = None
    fetched_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Layer 3: CONTEXT — user research goals (extraction lens)
# ---------------------------------------------------------------------------


class Context(BaseModel):
    """A research goal that acts as a lens for claim extraction.

    Core innovation: same text → different claims depending on why
    the user is reading it.
    """

    id: str
    goal: str  # "Track DeFi team movements and protocol partnerships"
    description: str = ""
    domain: str = "general"  # "crypto", "tech", "health"
    user_id: str | None = None
    active: bool = True
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Layer 1: CLAIMS — atomic statements with salience lifecycle
# ---------------------------------------------------------------------------


class Claim(BaseModel):
    """Atomic verifiable statement, extracted relative to a Context.

    Salience lifecycle (OpenMemory HSG pattern):
      new → salience=1.0 → decay over time → reinforce on access
      → contradicted? salience × 0.5
      → confirmed?    salience + 0.2
      → never accessed? decay to cold storage
    """

    id: str = ""
    text: str
    entities: list[str] = Field(default_factory=list)
    temporal: str | None = None  # "Q1 2026", "March 2026"
    metadata: dict[str, object] = Field(default_factory=dict)
    type: ClaimType = ClaimType.FACT
    confidence: float = 1.0

    # Links to other layers
    episode_id: str | None = None  # → Layer 0 (raw text)
    context_id: str | None = None  # → Layer 3 (extraction lens)
    relevance: float = 1.0  # relevance to context (0.0–1.0)

    # Salience (OpenMemory pattern: decay + reinforce)
    salience: float = 1.0  # 0.0–1.0, decays over time
    decay_rate: float | None = None  # per-claim override (None = use type default)

    # Temporal validity (when the fact was true in the real world)
    valid_from: datetime | None = None
    valid_to: datetime | None = None  # None = still valid

    # Embedding (populated by embedder)
    embedding: list[float] | None = None

    # Lifecycle
    created_at: datetime = Field(default_factory=_utcnow)
    superseded_at: datetime | None = None
    superseded_by: str | None = None


# ---------------------------------------------------------------------------
# Layer 2: GRAPH — LLM-extracted entity relations
# ---------------------------------------------------------------------------


class EntityRelation(BaseModel):
    """Semantic relationship between entities, extracted by LLM."""

    from_entity: str
    to_entity: str
    rel_type: str  # PARTNERED_WITH, INVESTED_IN, DEPARTED_FROM...
    fact: str  # human-readable: "Google partnered with EigenLayer"
    episode_id: str | None = None
    confidence: float = 0.8
    created_at: datetime = Field(default_factory=_utcnow)
    expired_at: datetime | None = None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class Collision(BaseModel):
    """Detected conflict or relationship between two claims."""

    claim_a: Claim
    claim_b: Claim
    score: float  # 0.0–1.0 composite score
    shared_entities: list[str] = Field(default_factory=list)
    temporal_distance: float | None = None
    type: str  # "contradiction" | "supersedes" | "confirms" | "related"


class IngestResult(BaseModel):
    """Result of ingesting raw text or pre-extracted claims."""

    episode_id: str
    claims: list[Claim] = []
    relations: list[EntityRelation] = []
    collisions: list[Collision] = []
    new_entities: list[str] = []


class SearchResult(BaseModel):
    """Single result from hybrid search."""

    claim: Claim
    score: float
    relevance: float = 1.0  # relevance to current context
    method: str = "hybrid"  # "vector" | "fts" | "graph" | "hybrid"
