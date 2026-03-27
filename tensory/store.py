"""Tensory — main orchestrator for claim-native memory.

Phase 1: create_context, add_claims, search (FTS only), stats.
Phase 2: embed on ingest, hybrid search (vector + FTS + graph + RRF),
         surprise score, priming, reinforce-on-access.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from tensory.embedder import Embedder, NullEmbedder
from tensory.graph import GraphBackend, SQLiteGraphBackend
from tensory.models import (
    Claim,
    ClaimType,
    Context,
    IngestResult,
    SearchResult,
)
from tensory.schema import create_schema, migrate
from tensory.search import hybrid_search, load_claim_entities, vector_search

logger = logging.getLogger(__name__)

# ── Salience defaults per ClaimType ───────────────────────────────────────

DECAY_RATES: dict[ClaimType, float] = {
    ClaimType.FACT: 0.005,
    ClaimType.EXPERIENCE: 0.010,
    ClaimType.OBSERVATION: 0.008,
    ClaimType.OPINION: 0.020,
}

# ── Sentiment tagging (cognitive mechanism #4) ────────────────────────────

SENTIMENT_WORDS: dict[str, set[str]] = {
    "positive": {"partnership", "growth", "launch", "confirmed", "milestone",
                 "approved", "success", "breakthrough", "upgrade", "adoption"},
    "negative": {"departed", "hack", "exploit", "bankrupt", "crash", "lawsuit",
                 "scam", "vulnerability", "downgrade", "shutdown", "breach"},
    "urgent": {"breaking", "just in", "alert", "emergency", "critical",
               "urgent", "immediately", "warning"},
}

URGENCY_SALIENCE_BOOST = 0.3
SURPRISE_SALIENCE_FACTOR = 0.3  # surprise * factor = salience boost
REINFORCE_BOOST = 0.05  # salience boost on search access
PRIMING_BOOST = 0.02  # per recent mention of entity


def _tag_sentiment(text: str) -> dict[str, object]:
    """Keyword-based sentiment tagging with intensity scoring."""
    text_lower = text.lower()
    scores: dict[str, int] = {"positive": 0, "negative": 0, "urgent": 0}

    for category, words in SENTIMENT_WORDS.items():
        for word in words:
            if word in text_lower:
                scores[category] += 1

    total = scores["positive"] + scores["negative"]
    if total == 0:
        sentiment = "neutral"
        intensity = 0.0
    elif scores["positive"] > scores["negative"]:
        sentiment = "positive"
        intensity = min(1.0, scores["positive"] / max(total, 1))
    else:
        sentiment = "negative"
        intensity = min(1.0, scores["negative"] / max(total, 1))

    result: dict[str, object] = {
        "sentiment": sentiment,
        "intensity": intensity,
    }
    if scores["urgent"] > 0:
        result["urgent"] = True

    return result


# ── Main class ────────────────────────────────────────────────────────────


class Tensory:
    """Embedded claim-native memory store.

    Usage::

        from tensory.embedder import NullEmbedder

        store = await Tensory.create("memory.db", embedder=NullEmbedder())
        ctx = await store.create_context(goal="Track DeFi movements")
        result = await store.add_claims([Claim(text="...", entities=["ETH"])])
        results = await store.search("ETH")
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        *,
        embedder: Embedder | None = None,
        graph_backend: GraphBackend | None = None,
    ) -> None:
        self._db = db
        self._embedder: Embedder = embedder or NullEmbedder()
        self._graph: GraphBackend = graph_backend or SQLiteGraphBackend(db)
        # Priming: in-memory counter of recently-searched entities
        self._recent_entities: Counter[str] = Counter()
        self._vec_available: bool = True  # set False if sqlite-vec not loaded

    @classmethod
    async def create(
        cls,
        path: str | Path = ":memory:",
        *,
        embedder: Embedder | None = None,
        graph_backend: GraphBackend | None = None,
        embedding_dim: int | None = None,
    ) -> Tensory:
        """Create and initialize a Tensory instance.

        Args:
            path: SQLite database path. Use \":memory:\" for testing.
            embedder: Embedding backend (default: NullEmbedder).
            graph_backend: Optional custom graph backend (default: SQLiteGraphBackend).
            embedding_dim: Vector dimension. Auto-detected from embedder if not set.
        """
        resolved_embedder = embedder or NullEmbedder()
        dim = embedding_dim or resolved_embedder.dim

        db = await aiosqlite.connect(str(path))
        db.row_factory = aiosqlite.Row
        await create_schema(db, embedding_dim=dim)
        await migrate(db)

        backend = graph_backend or SQLiteGraphBackend(db)
        instance = cls(db, embedder=resolved_embedder, graph_backend=backend)

        # Check if sqlite-vec is available
        try:
            await db.execute("SELECT * FROM claim_embeddings LIMIT 0")
        except Exception:
            instance._vec_available = False
            logger.info("sqlite-vec not available, vector search disabled")

        return instance

    async def close(self) -> None:
        """Close database connection and graph backend."""
        await self._graph.close()
        await self._db.close()

    # ── Context management (Layer 3) ──────────────────────────────────────

    async def create_context(
        self,
        goal: str,
        *,
        domain: str = "general",
        description: str = "",
        user_id: str | None = None,
    ) -> Context:
        """Create a research goal — the lens for claim extraction."""
        ctx = Context(
            id=uuid.uuid4().hex,
            goal=goal,
            domain=domain,
            description=description,
            user_id=user_id,
        )
        await self._db.execute(
            """INSERT INTO contexts (id, goal, description, domain, user_id, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ctx.id, ctx.goal, ctx.description, ctx.domain, ctx.user_id,
             1, ctx.created_at.isoformat()),
        )
        await self._db.commit()
        return ctx

    # ── Claim ingestion (Layer 1) ─────────────────────────────────────────

    async def add_claims(
        self,
        claims: list[Claim],
        *,
        episode_id: str | None = None,
        context_id: str | None = None,
    ) -> IngestResult:
        """Ingest pre-extracted claims.

        Pipeline: assign IDs → sentiment tag → embed → compute surprise
        → store claim → store embedding → register entities.

        Args:
            claims: List of Claim objects to store.
            episode_id: Optional episode ID to link claims to raw text.
            context_id: Optional context ID for the extraction lens.
        """
        stored_claims: list[Claim] = []
        new_entities: list[str] = []

        # ── Batch embed all claims ────────────────────────────────────────
        texts = [c.text for c in claims]
        embeddings: list[list[float]] = []
        if texts and not isinstance(self._embedder, NullEmbedder):
            try:
                embeddings = await self._embedder.embed_batch(texts)
            except Exception:
                logger.warning("Embedding failed, proceeding without vectors")
                embeddings = []

        for i, claim in enumerate(claims):
            # Assign ID if missing
            if not claim.id:
                claim.id = uuid.uuid4().hex

            # Override episode/context if provided at batch level
            if episode_id:
                claim.episode_id = episode_id
            if context_id:
                claim.context_id = context_id

            # Apply default decay rate based on claim type
            if claim.decay_rate is None:
                claim.decay_rate = DECAY_RATES.get(claim.type, 0.010)

            # Sentiment tagging
            sentiment_meta = _tag_sentiment(claim.text)
            claim.metadata = {**claim.metadata, **sentiment_meta}

            # Urgency → salience boost
            if sentiment_meta.get("urgent"):
                claim.salience = min(1.0, claim.salience + URGENCY_SALIENCE_BOOST)

            # Assign embedding
            if i < len(embeddings):
                claim.embedding = embeddings[i]

            # ── Surprise score (cognitive mechanism #1) ───────────────────
            surprise = await self._compute_surprise(claim)
            claim.metadata["surprise"] = surprise
            claim.salience = min(1.0, claim.salience + surprise * SURPRISE_SALIENCE_FACTOR)

            # Insert claim
            await self._db.execute(
                """INSERT INTO claims
                   (id, episode_id, context_id, text, type, confidence, relevance,
                    salience, decay_rate, valid_from, valid_to, created_at, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    claim.id,
                    claim.episode_id,
                    claim.context_id,
                    claim.text,
                    claim.type.value,
                    claim.confidence,
                    claim.relevance,
                    claim.salience,
                    claim.decay_rate,
                    claim.valid_from.isoformat() if claim.valid_from else None,
                    claim.valid_to.isoformat() if claim.valid_to else None,
                    claim.created_at.isoformat(),
                    json.dumps(claim.metadata, default=str),
                ),
            )

            # Store embedding in sqlite-vec
            if claim.embedding and self._vec_available:
                try:
                    await self._db.execute(
                        "INSERT INTO claim_embeddings (claim_id, embedding) VALUES (?, ?)",
                        (claim.id, json.dumps(claim.embedding)),
                    )
                except Exception:
                    logger.debug("Failed to store embedding for claim %s", claim.id)

            # Register entities (Layer 2)
            for entity_name in claim.entities:
                entity_id = await self._graph.add_entity(entity_name)
                await self._db.execute(
                    "INSERT OR IGNORE INTO claim_entities (claim_id, entity_id) VALUES (?, ?)",
                    (claim.id, entity_id),
                )
                new_entities.append(entity_name)

            stored_claims.append(claim)

        await self._db.commit()

        return IngestResult(
            episode_id=episode_id or "",
            claims=stored_claims,
            new_entities=list(set(new_entities)),
        )

    # ── Surprise score (cognitive mechanism #1) ───────────────────────────

    async def _compute_surprise(self, claim: Claim) -> float:
        """How different is this claim from existing knowledge?

        Inspired by mnemos SurprisalGate: high surprise → salience boost.
        Returns 0.0 (very similar to existing) to 1.0 (completely novel).
        """
        if not claim.embedding or not self._vec_available:
            return 0.0  # can't compute without vectors

        try:
            neighbors = await vector_search(
                claim.embedding, self._db, limit=5
            )
        except Exception:
            return 1.0  # empty DB or vec error = max surprise

        if not neighbors:
            return 1.0  # empty DB = everything is novel

        # Mean similarity of 5 nearest neighbors
        mean_sim = sum(r.score for r in neighbors) / len(neighbors)
        # Surprise = 1 - similarity (novel = far from existing)
        return round(max(0.0, 1.0 - mean_sim), 4)

    # ── Search (Phase 2: hybrid) ──────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        context: Context | None = None,
        limit: int = 10,
        weights: dict[str, float] | None = None,
    ) -> list[SearchResult]:
        """Hybrid search across vector, FTS, and graph channels.

        Pipeline: embed query → parallel search → RRF merge → priming
        boost → reinforce on access.

        Args:
            query: Search query string.
            context: Optional context to weight relevance.
            limit: Maximum results to return.
            weights: Channel weights for RRF (default: vector=0.4, fts=0.3, graph=0.3).
        """
        # Embed the query
        query_embedding: list[float] | None = None
        if not isinstance(self._embedder, NullEmbedder):
            try:
                query_embedding = await self._embedder.embed(query)
            except Exception:
                logger.warning("Query embedding failed, falling back to FTS+graph")

        # Hybrid search with parallel channels + RRF
        results = await hybrid_search(
            query,
            embedding=query_embedding,
            graph_backend=self._graph,
            db=self._db,
            context_id=context.id if context else None,
            limit=limit,
            weights=weights,
        )

        # ── Load entities for results (needed for priming) ────────────────
        for result in results:
            result.claim.entities = await load_claim_entities(result.claim.id, self._db)

        # ── Priming boost (cognitive mechanism #2) ────────────────────────
        for result in results:
            priming_boost = 0.0
            for entity in result.claim.entities:
                mentions = self._recent_entities.get(entity, 0)
                priming_boost += mentions * PRIMING_BOOST
            if priming_boost > 0:
                result.score += priming_boost

        # Re-sort after priming boost
        results.sort(key=lambda r: r.score, reverse=True)

        # ── Record entities for future priming ────────────────────────────
        for result in results[:5]:
            for entity in result.claim.entities:
                self._recent_entities[entity] += 1

        # Cap priming memory (keep top 100 entities)
        if len(self._recent_entities) > 200:
            self._recent_entities = Counter(
                dict(self._recent_entities.most_common(100))
            )

        # ── Reinforce on access (OpenMemory pattern) ─────────────────────
        for result in results:
            await self._db.execute(
                """UPDATE claims
                   SET access_count = access_count + 1,
                       last_accessed = ?,
                       salience = MIN(1.0, salience + ?)
                   WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), REINFORCE_BOOST, result.claim.id),
            )

        # ── Context relevance ────────────────────────────────────────────
        if context:
            for result in results:
                rel_cursor = await self._db.execute(
                    "SELECT score FROM relevance_scores WHERE claim_id = ? AND context_id = ?",
                    (result.claim.id, context.id),
                )
                rel_row = await rel_cursor.fetchone()
                if rel_row is not None:
                    result.relevance = float(rel_row[0])

        await self._db.commit()
        return results

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """Return summary statistics about the memory store."""
        counts: dict[str, int] = {}
        for table in ("episodes", "contexts", "claims", "entities", "entity_relations", "waypoints"):
            cursor = await self._db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = await cursor.fetchone()
            counts[table] = row[0] if row else 0

        # Claims by type
        cursor = await self._db.execute(
            "SELECT type, COUNT(*) FROM claims GROUP BY type"
        )
        type_rows = await cursor.fetchall()
        claims_by_type = {row[0]: row[1] for row in type_rows}

        # Average salience
        cursor = await self._db.execute("SELECT AVG(salience) FROM claims")
        row = await cursor.fetchone()
        avg_salience = float(row[0]) if row and row[0] is not None else 0.0

        return {
            "counts": counts,
            "claims_by_type": claims_by_type,
            "avg_salience": round(avg_salience, 4),
        }


