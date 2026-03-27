"""Tensory — main orchestrator for claim-native memory.

Phase 1 provides: create_context, add_claims, search (FTS only), stats.
Sentiment tagging is applied automatically on ingest.

Later phases add: add (text → extract), reevaluate, hybrid search,
collision detection, temporal operations.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from tensory.graph import GraphBackend, SQLiteGraphBackend
from tensory.models import (
    Claim,
    ClaimType,
    Context,
    IngestResult,
    SearchResult,
)
from tensory.schema import create_schema, migrate

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


def _tag_sentiment(text: str) -> dict[str, object]:
    """Keyword-based sentiment tagging with intensity scoring.

    Returns metadata dict with 'sentiment' and 'intensity' keys.
    Urgent claims get flagged for salience boost.
    """
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

        store = await Tensory.create("memory.db")
        ctx = await store.create_context(goal="Track DeFi movements")
        result = await store.add_claims([Claim(text="...", entities=["ETH"])])
        results = await store.search("ETH")
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        *,
        graph_backend: GraphBackend | None = None,
    ) -> None:
        self._db = db
        self._graph: GraphBackend = graph_backend or SQLiteGraphBackend(db)

    @classmethod
    async def create(
        cls,
        path: str | Path = ":memory:",
        *,
        graph_backend: GraphBackend | None = None,
        embedding_dim: int = 1536,
    ) -> Tensory:
        """Create and initialize a Tensory instance.

        Args:
            path: SQLite database path. Use \":memory:\" for testing.
            graph_backend: Optional custom graph backend (default: SQLiteGraphBackend).
            embedding_dim: Vector embedding dimension (default 1536 for OpenAI).
        """
        db = await aiosqlite.connect(str(path))
        db.row_factory = aiosqlite.Row
        await create_schema(db, embedding_dim=embedding_dim)
        await migrate(db)

        backend = graph_backend or SQLiteGraphBackend(db)
        return cls(db, graph_backend=backend)

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
        """Create a research goal — the lens for claim extraction.

        Args:
            goal: What the user is investigating ("Track DeFi team movements").
            domain: Knowledge domain ("crypto", "tech", "health").
            description: Extended description of the research goal.
            user_id: Optional user identifier.
        """
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
        """Ingest pre-extracted claims (no LLM needed).

        Applies sentiment tagging and default salience per ClaimType.
        Phase 2+ will add: embedding, dedup, collision detection, waypoints.

        Args:
            claims: List of Claim objects to store.
            episode_id: Optional episode ID to link claims to raw text.
            context_id: Optional context ID for the extraction lens.
        """
        stored_claims: list[Claim] = []
        new_entities: list[str] = []

        for claim in claims:
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

            # Sentiment tagging (cognitive mechanism)
            sentiment_meta = _tag_sentiment(claim.text)
            claim.metadata = {**claim.metadata, **sentiment_meta}

            # Urgency → salience boost
            if sentiment_meta.get("urgent"):
                claim.salience = min(1.0, claim.salience + URGENCY_SALIENCE_BOOST)

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

    # ── Search (Phase 1: FTS only) ────────────────────────────────────────

    async def search(
        self,
        query: str,
        *,
        context: Context | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Search claims using FTS5 full-text search.

        Phase 2 will upgrade this to hybrid search (vector + FTS + graph + RRF).

        Args:
            query: Search query string.
            context: Optional context to weight relevance.
            limit: Maximum results to return.
        """
        # FTS5 search
        cursor = await self._db.execute(
            """
            SELECT c.*, rank
            FROM claims_fts fts
            JOIN claims c ON c.rowid = fts.rowid
            WHERE claims_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        rows = await cursor.fetchall()

        results: list[SearchResult] = []
        for row in rows:
            claim = _row_to_claim(row)

            # Reinforce on access (cognitive mechanism — Phase 2 will formalize)
            await self._db.execute(
                """UPDATE claims
                   SET access_count = access_count + 1,
                       last_accessed = ?,
                       salience = MIN(1.0, salience + 0.05)
                   WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(), claim.id),
            )

            relevance = 1.0
            if context:
                # Check for cross-context relevance score
                rel_cursor = await self._db.execute(
                    "SELECT score FROM relevance_scores WHERE claim_id = ? AND context_id = ?",
                    (claim.id, context.id),
                )
                rel_row = await rel_cursor.fetchone()
                if rel_row is not None:
                    relevance = float(rel_row[0])

            fts_rank = float(row["rank"]) if "rank" in row.keys() else 0.0
            # FTS5 rank is negative (more negative = better match)
            score = -fts_rank if fts_rank < 0 else fts_rank

            results.append(SearchResult(
                claim=claim,
                score=score,
                relevance=relevance,
                method="fts",
            ))

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


# ── Helpers ───────────────────────────────────────────────────────────────


def _row_to_claim(row: aiosqlite.Row) -> Claim:
    """Convert a database row to a Claim model."""
    metadata_raw = row["metadata"]
    metadata: dict[str, object] = {}
    if metadata_raw:
        parsed: dict[str, object] = json.loads(str(metadata_raw))
        metadata = parsed

    return Claim(
        id=row["id"],
        text=row["text"],
        type=ClaimType(row["type"]),
        confidence=float(row["confidence"]),
        relevance=float(row["relevance"]),
        salience=float(row["salience"]),
        decay_rate=float(row["decay_rate"]) if row["decay_rate"] is not None else None,
        episode_id=row["episode_id"],
        context_id=row["context_id"],
        valid_from=datetime.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
        valid_to=datetime.fromisoformat(row["valid_to"]) if row["valid_to"] else None,
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(timezone.utc),
        superseded_at=datetime.fromisoformat(row["superseded_at"]) if row["superseded_at"] else None,
        superseded_by=row["superseded_by"],
        metadata=metadata,
    )
