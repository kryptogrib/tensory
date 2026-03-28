"""Tensory — main orchestrator for claim-native memory.

Phase 1: create_context, add_claims, search (FTS only), stats.
Phase 2: embed on ingest, hybrid search (vector + FTS + graph + RRF),
         surprise score, priming, reinforce-on-access.
Phase 3: dedup, collision detection + salience updates, waypoint creation.
Phase 4: add (text → extract), reevaluate, timeline, consolidate,
         source_stats, cleanup.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import aiosqlite

from tensory.collisions import apply_salience_updates, find_collisions
from tensory.dedup import MinHashDedup
from tensory.embedder import Embedder, NullEmbedder
from tensory.extract import LLMProtocol, extract_claims
from tensory.graph import GraphBackend, SQLiteGraphBackend
from tensory.models import (
    Claim,
    ClaimType,
    Collision,
    Context,
    Episode,
    IngestResult,
    MemoryType,
    ProceduralResult,
    ReflectResult,
    SearchResult,
)
from tensory.prompts import CARA_OPINION_FORMATION, OBSERVATION_SYNTHESIS
from tensory.schema import create_schema, migrate
from tensory.search import hybrid_search, load_claim_entities, vector_search
from tensory.temporal import (
    apply_decay as _apply_decay,
)
from tensory.temporal import (
    auto_supersede_on_collision,
)
from tensory.temporal import (
    cleanup as _cleanup,
)
from tensory.temporal import (
    timeline as _timeline,
)

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
    "positive": {
        "partnership",
        "growth",
        "launch",
        "confirmed",
        "milestone",
        "approved",
        "success",
        "breakthrough",
        "upgrade",
        "adoption",
    },
    "negative": {
        "departed",
        "hack",
        "exploit",
        "bankrupt",
        "crash",
        "lawsuit",
        "scam",
        "vulnerability",
        "downgrade",
        "shutdown",
        "breach",
    },
    "urgent": {
        "breaking",
        "just in",
        "alert",
        "emergency",
        "critical",
        "urgent",
        "immediately",
        "warning",
    },
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
        llm: LLMProtocol | None = None,
        embedder: Embedder | None = None,
        graph_backend: GraphBackend | None = None,
    ) -> None:
        self._db = db
        self._llm = llm
        self._embedder: Embedder = embedder or NullEmbedder()
        self._graph: GraphBackend = graph_backend or SQLiteGraphBackend(db)
        self._dedup = MinHashDedup()
        # Priming: in-memory counter of recently-searched entities
        self._recent_entities: Counter[str] = Counter()
        self._vec_available: bool = True  # set False if sqlite-vec not loaded

    @classmethod
    async def create(
        cls,
        path: str | Path = ":memory:",
        *,
        llm: LLMProtocol | None = None,
        embedder: Embedder | None = None,
        graph_backend: GraphBackend | None = None,
        embedding_dim: int | None = None,
    ) -> Tensory:
        """Create and initialize a Tensory instance.

        Args:
            path: SQLite database path. Use \":memory:\" for testing.
            llm: LLM callable for claim extraction (prompt → response).
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
        instance = cls(db, llm=llm, embedder=resolved_embedder, graph_backend=backend)

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
            (
                ctx.id,
                ctx.goal,
                ctx.description,
                ctx.domain,
                ctx.user_id,
                1,
                ctx.created_at.isoformat(),
            ),
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

        Pipeline: assign IDs → dedup check → sentiment tag → embed →
        compute surprise → store claim → store embedding → register
        entities → create waypoint → detect collisions → update salience.

        Args:
            claims: List of Claim objects to store.
            episode_id: Optional episode ID to link claims to raw text.
            context_id: Optional context ID for the extraction lens.
        """
        stored_claims: list[Claim] = []
        new_entities: list[str] = []
        all_collisions: list[Collision] = []

        # ── Load existing claim texts for dedup ───────────────────────────
        existing_texts = await self._get_existing_claim_texts(limit=200)

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

            # ── Dedup check ───────────────────────────────────────────────
            if self._dedup.is_duplicate(claim.text, existing_texts):
                logger.debug("Duplicate claim skipped: %s", claim.text[:60])
                claim.metadata["dedup_skipped"] = True
                continue

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
                    salience, decay_rate, valid_from, valid_to, created_at, metadata,
                    memory_type, trigger, steps, termination_condition, success_rate,
                    usage_count, source_episode_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    claim.memory_type.value,
                    claim.trigger,
                    json.dumps(claim.steps) if claim.steps is not None else None,
                    claim.termination_condition,
                    claim.success_rate,
                    claim.usage_count,
                    json.dumps(claim.source_episode_ids),
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

            await self._db.commit()

            # ── Waypoint creation (OpenMemory pattern) ────────────────────
            await self._create_waypoint(claim)

            # ── Collision detection ───────────────────────────────────────
            collisions = await find_collisions(claim, self._db, graph_backend=self._graph)
            if collisions:
                await apply_salience_updates(collisions, self._db)
                all_collisions.extend(collisions)

                # Auto-supersede on very high collision scores
                for col in collisions:
                    if col.type == "supersedes":
                        await auto_supersede_on_collision(
                            claim.id, col.claim_b.id, col.score, self._db
                        )

            # Add to existing texts for intra-batch dedup
            existing_texts.append(claim.text)
            stored_claims.append(claim)

        await self._db.commit()

        return IngestResult(
            episode_id=episode_id or "",
            claims=stored_claims,
            collisions=all_collisions,
            new_entities=list(set(new_entities)),
        )

    # ── Surprise score (cognitive mechanism #1) ───────────────────────────

    # ── Waypoint creation (OpenMemory pattern) ──────────────────────────

    async def _create_waypoint(self, claim: Claim) -> None:
        """Link new claim to its most similar existing claim (cosine ≥ 0.75).

        Creates a 1-hop associative link in the waypoints table.
        This enables waypoint-expanded search and collision detection.
        """
        if not claim.embedding or not self._vec_available:
            return

        try:
            neighbors = await vector_search(claim.embedding, self._db, limit=5)
        except Exception:
            return

        if not neighbors:
            return

        # Find best match that isn't self
        best = None
        for neighbor in neighbors:
            if neighbor.claim.id != claim.id:
                best = neighbor
                break

        if best is None:
            return

        # cosine similarity threshold
        if best.score >= 0.75:
            try:
                await self._db.execute(
                    """INSERT OR REPLACE INTO waypoints
                       (src_claim, dst_claim, similarity)
                       VALUES (?, ?, ?)""",
                    (claim.id, best.claim.id, best.score),
                )
                await self._db.commit()
            except Exception:
                logger.debug("Waypoint creation failed for claim %s", claim.id)

    # ── Dedup helpers ─────────────────────────────────────────────────────

    async def _get_existing_claim_texts(self, limit: int = 200) -> list[str]:
        """Load recent claim texts for dedup comparison."""
        cursor = await self._db.execute(
            "SELECT text FROM claims ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]

    # ── Surprise score (cognitive mechanism #1) ───────────────────────────

    async def _compute_surprise(self, claim: Claim) -> float:
        """How different is this claim from existing knowledge?

        Inspired by mnemos SurprisalGate: high surprise → salience boost.
        Returns 0.0 (very similar to existing) to 1.0 (completely novel).
        """
        if not claim.embedding or not self._vec_available:
            return 0.0  # can't compute without vectors

        try:
            neighbors = await vector_search(claim.embedding, self._db, limit=5)
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
        memory_type: MemoryType | None = None,
    ) -> list[SearchResult]:
        """Hybrid search across vector, FTS, and graph channels.

        Pipeline: embed query → parallel search → RRF merge → priming
        boost → reinforce on access.

        Args:
            query: Search query string.
            context: Optional context to weight relevance.
            limit: Maximum results to return.
            weights: Channel weights for RRF (default: vector=0.4, fts=0.3, graph=0.3).
            memory_type: Optional filter by memory type (semantic, procedural, episodic).
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
            memory_type=memory_type.value if memory_type else None,
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
            self._recent_entities = Counter(dict(self._recent_entities.most_common(100)))

        # ── Reinforce on access (OpenMemory pattern) ─────────────────────
        for result in results:
            await self._db.execute(
                """UPDATE claims
                   SET access_count = access_count + 1,
                       last_accessed = ?,
                       salience = MIN(1.0, salience + ?)
                   WHERE id = ?""",
                (datetime.now(UTC).isoformat(), REINFORCE_BOOST, result.claim.id),
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

    # ── reflect() — learning via reflection (CARA) ─────────────────────

    async def reflect(
        self,
        query: str,
        *,
        disposition: dict[str, str] | None = None,
        auto_update: bool = True,
        limit: int = 20,
    ) -> ReflectResult:
        """Learning via reflection — recall, detect collisions, form opinions.

        Two modes:
        1. LLM-free (default): recall → collision detection → salience update
           → template observation if patterns found
        2. LLM-based (CARA): if self._llm is set, also runs:
           → CARA Opinion Formation (first-person opinions from facts)
           → Observation Synthesis (entity-level summaries)

        Inspired by Hindsight reflect() (arxiv.org/abs/2512.12818).

        Args:
            query: What to reflect on ("What do I know about EigenLayer?").
            disposition: CARA personality params (e.g. {"risk_tolerance": "conservative"}).
            auto_update: Apply salience updates from collisions.
            limit: How many claims to recall for reflection.
        """
        # ── Step 1: Recall ────────────────────────────────────────────
        results = await self.search(query, limit=limit)
        claims = [r.claim for r in results]

        if not claims:
            return ReflectResult()

        # ── Step 2: Cross-collision detection ─────────────────────────
        all_collisions: list[Collision] = []
        for claim in claims:
            cols = await find_collisions(claim, self._db, graph_backend=self._graph)
            # Only keep collisions between recalled claims (not all DB)
            for col in cols:
                if not any(c.claim_b.id == col.claim_b.id for c in all_collisions):
                    all_collisions.append(col)

        # ── Step 3: Salience updates ──────────────────────────────────
        if auto_update and all_collisions:
            await apply_salience_updates(all_collisions, self._db)

        updated_claims = [
            c for c in claims if any(col.claim_b.id == c.id for col in all_collisions)
        ]

        # ── Step 4: Observations (template-based, no LLM) ────────────
        new_observations: list[Claim] = []
        if len(all_collisions) >= 2:
            obs = Claim(
                text=_synthesize_observation_template(claims, all_collisions),
                type=ClaimType.OBSERVATION,
                confidence=0.6,
                entities=_collect_entities(claims),
            )
            obs_result = await self.add_claims([obs])
            new_observations.extend(obs_result.claims)

        # ── Step 5: CARA (LLM-based, optional) ───────────────────────
        new_opinions: list[Claim] = []
        if self._llm and claims:
            opinions, llm_observations = await self._cara_reflect(
                query, claims, all_collisions, disposition
            )
            new_opinions.extend(opinions)
            new_observations.extend(llm_observations)

        return ReflectResult(
            updated_claims=updated_claims,
            new_observations=new_observations,
            new_opinions=new_opinions,
            collisions=all_collisions,
        )

    async def _cara_reflect(
        self,
        query: str,
        claims: list[Claim],
        collisions: list[Collision],
        disposition: dict[str, str] | None,
    ) -> tuple[list[Claim], list[Claim]]:
        """Run CARA prompts for opinion formation + observation synthesis.

        Returns (opinions, observations).
        """
        assert self._llm is not None
        opinions: list[Claim] = []
        observations: list[Claim] = []

        facts_text = "\n".join(f"- {c.text} (salience={c.salience:.2f})" for c in claims)
        collisions_text = (
            "\n".join(
                f"- {col.type}: '{col.claim_a.text[:60]}' vs '{col.claim_b.text[:60]}' (score={col.score})"
                for col in collisions
            )
            or "None detected"
        )
        disposition_text = (
            json.dumps(disposition) if disposition else "neutral — no specific disposition"
        )

        # ── CARA Opinion Formation ────────────────────────────────────
        try:
            opinion_prompt = CARA_OPINION_FORMATION.format(
                query=query,
                disposition=disposition_text,
                facts_text=facts_text,
                collisions_text=collisions_text,
            )
            response = await self._llm(opinion_prompt)
            parsed = _parse_json_response(response)

            for raw_item in cast(list[dict[str, Any]], parsed.get("opinions", [])):
                if raw_item.get("text"):
                    opinion = Claim(
                        text=str(raw_item["text"]),
                        type=ClaimType.OPINION,
                        confidence=float(str(raw_item.get("confidence", 0.7))),
                        entities=[str(e) for e in cast(list[Any], raw_item.get("entities") or [])],
                    )
                    result = await self.add_claims([opinion])
                    opinions.extend(result.claims)
        except Exception:
            logger.warning("CARA opinion formation failed")

        # ── Observation Synthesis (per top entity) ────────────────────
        entity_counts: Counter[str] = Counter()
        for c in claims:
            for e in c.entities:
                entity_counts[e] += 1

        top_entities = [e for e, _ in entity_counts.most_common(3)]

        for entity_name in top_entities:
            entity_facts = [c for c in claims if entity_name in c.entities]
            if len(entity_facts) < 2:
                continue

            try:
                entity_facts_text = "\n".join(f"- {c.text}" for c in entity_facts)
                obs_prompt = OBSERVATION_SYNTHESIS.format(
                    entity_name=entity_name,
                    ENTITY_NAME=entity_name.upper(),
                    facts_text=entity_facts_text,
                )
                response = await self._llm(obs_prompt)
                parsed = _parse_json_response(response)

                for raw_obs in parsed.get("observations", []):
                    obs_text: str
                    obs_entities: list[str]
                    if isinstance(raw_obs, dict):
                        obs_dict = cast(dict[str, Any], raw_obs)
                        obs_text = str(obs_dict.get("text", ""))
                        obs_entities = [
                            str(e)
                            for e in cast(list[Any], obs_dict.get("entities") or [entity_name])
                        ]
                    elif isinstance(raw_obs, str):
                        obs_text = raw_obs
                        obs_entities = [entity_name]
                    else:
                        continue

                    if obs_text:
                        obs = Claim(
                            text=obs_text,
                            type=ClaimType.OBSERVATION,
                            confidence=0.7,
                            entities=obs_entities,
                            salience=0.8,
                        )
                        result = await self.add_claims([obs])
                        observations.extend(result.claims)
            except Exception:
                logger.warning("Observation synthesis failed for %s", entity_name)

        return opinions, observations

    # ── Stats ─────────────────────────────────────────────────────────────

    async def stats(self) -> dict[str, Any]:
        """Return summary statistics about the memory store."""
        counts: dict[str, int] = {}
        for table in (
            "episodes",
            "contexts",
            "claims",
            "entities",
            "entity_relations",
            "waypoints",
        ):
            cursor = await self._db.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
            row = await cursor.fetchone()
            counts[table] = row[0] if row else 0

        # Claims by type
        cursor = await self._db.execute("SELECT type, COUNT(*) FROM claims GROUP BY type")
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

    # ── add() — raw text → extract → ingest (Phase 4) ────────────────────

    async def add(
        self,
        text: str,
        *,
        source: str = "",
        source_url: str | None = None,
        context: Context | None = None,
    ) -> IngestResult:
        """Ingest raw text: store episode → LLM extract → add_claims.

        This is the primary high-level API. Requires an LLM to be configured.

        Args:
            text: Raw text to extract claims from.
            source: Source identifier (e.g. "reddit:r/defi").
            source_url: Full URL of the source.
            context: Research goal for context-aware extraction.
        """
        if not self._llm:
            msg = "LLM required for add(). Use add_claims() for pre-extracted claims."
            raise ValueError(msg)

        # Store episode (Layer 0 — raw never dies)
        episode = Episode(
            id=uuid.uuid4().hex,
            raw_text=text,
            source=source,
            source_url=source_url,
        )
        await self._db.execute(
            """INSERT INTO episodes (id, raw_text, source, source_url, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                episode.id,
                episode.raw_text,
                episode.source,
                episode.source_url,
                episode.fetched_at.isoformat(),
            ),
        )
        await self._db.commit()

        # Extract claims via LLM
        claims, relations = await extract_claims(text, self._llm, context=context)

        # Store relations in graph
        for rel in relations:
            from_id = await self._graph.add_entity(rel.from_entity)
            to_id = await self._graph.add_entity(rel.to_entity)
            await self._graph.add_edge(
                from_id,
                to_id,
                rel.rel_type,
                {
                    "fact": rel.fact,
                    "episode_id": episode.id,
                    "confidence": rel.confidence,
                },
            )

        # Ingest claims through the standard pipeline
        result = await self.add_claims(
            claims,
            episode_id=episode.id,
            context_id=context.id if context else None,
        )

        result.relations = relations
        return result

    # ── add_procedural() — LLM skill extraction + storage ────────────────

    async def add_procedural(
        self,
        text: str,
        *,
        source: str = "",
        source_url: str | None = None,
        context: Context | None = None,
    ) -> ProceduralResult:
        """Extract procedural skills from raw experience text.

        Pipeline: store episode → LLM extract skills → add_claims
        with memory_type=PROCEDURAL → collision detection.

        Uses Skill-MDP framework (ProcMEM arXiv:2602.01869):
        trigger + steps + termination_condition.

        Args:
            text: Raw experience text describing a procedure.
            source: Source identifier.
            source_url: Full URL of the source.
            context: Optional research goal context.
        """
        if not self._llm:
            msg = "LLM required for add_procedural(). Configure llm= on Tensory.create()."
            raise ValueError(msg)

        from tensory.extract import extract_procedural

        # Store episode (Layer 0)
        episode = Episode(
            id=uuid.uuid4().hex,
            raw_text=text,
            source=source,
            source_url=source_url,
        )
        await self._db.execute(
            """INSERT INTO episodes (id, raw_text, source, source_url, fetched_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                episode.id,
                episode.raw_text,
                episode.source,
                episode.source_url,
                episode.fetched_at.isoformat(),
            ),
        )
        await self._db.commit()

        # Extract procedural skills via LLM
        skills = await extract_procedural(text, self._llm)

        # Set provenance on each skill
        for skill in skills:
            skill.source_episode_ids = [episode.id]

        # Store through standard pipeline (dedup + embed + collisions)
        stored_skills: list[Claim] = []
        if skills:
            result = await self.add_claims(
                skills,
                episode_id=episode.id,
                context_id=context.id if context else None,
            )
            stored_skills = result.claims

        return ProceduralResult(
            episode_id=episode.id,
            skills=stored_skills,
        )

    # ── reevaluate() — re-extract from old episode with new context ───────

    async def reevaluate(
        self,
        episode_id: str,
        context: Context,
    ) -> IngestResult:
        """Re-extract claims from a stored episode through a new context lens.

        Same raw text → different claims depending on research goal.

        Args:
            episode_id: ID of the stored episode to re-extract from.
            context: New research goal to extract through.
        """
        if not self._llm:
            msg = "LLM required for reevaluate()."
            raise ValueError(msg)

        # Fetch episode
        cursor = await self._db.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,))
        row = await cursor.fetchone()
        if row is None:
            msg = f"Episode {episode_id} not found"
            raise ValueError(msg)

        raw_text = str(row["raw_text"])

        # Extract with new context
        claims, relations = await extract_claims(raw_text, self._llm, context=context)

        # Store relations
        for rel in relations:
            from_id = await self._graph.add_entity(rel.from_entity)
            to_id = await self._graph.add_entity(rel.to_entity)
            await self._graph.add_edge(
                from_id,
                to_id,
                rel.rel_type,
                {
                    "fact": rel.fact,
                    "episode_id": episode_id,
                    "confidence": rel.confidence,
                },
            )

        result = await self.add_claims(
            claims,
            episode_id=episode_id,
            context_id=context.id,
        )

        result.relations = relations
        return result

    # ── timeline() — entity history ───────────────────────────────────────

    async def timeline(
        self,
        entity_name: str,
        *,
        include_superseded: bool = True,
        limit: int = 50,
    ) -> list[Claim]:
        """Show how facts about an entity evolved over time.

        Args:
            entity_name: Entity to trace.
            include_superseded: Include superseded claims in timeline.
            limit: Maximum claims to return.
        """
        return await _timeline(
            entity_name,
            self._db,
            include_superseded=include_superseded,
            limit=limit,
        )

    # ── cleanup() — remove old low-salience claims ────────────────────────

    async def cleanup(self, *, max_age_days: int = 90) -> int:
        """Remove low-salience superseded claims past max age.

        Does NOT delete episodes (raw text preserved forever).
        """
        await _apply_decay(self._db)
        return await _cleanup(self._db, max_age_days=max_age_days)

    # ── consolidate() — cluster claims into observations ──────────────────

    async def consolidate(
        self,
        *,
        days: int = 7,
        min_cluster: int = 3,
    ) -> list[Claim]:
        """Cluster recent claims into OBSERVATION summaries (no LLM).

        Uses Union-Find to group claims sharing ≥2 entities.
        Generates template-based observation claims.

        Args:
            days: Look back window in days.
            min_cluster: Minimum claims per cluster.
        """
        from datetime import timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()

        # Find claim pairs sharing ≥2 entities in the last N days
        cursor = await self._db.execute(
            """
            SELECT ce1.claim_id AS c1, ce2.claim_id AS c2, COUNT(*) AS shared
            FROM claim_entities ce1
            JOIN claim_entities ce2 ON ce1.entity_id = ce2.entity_id
            JOIN claims cl1 ON ce1.claim_id = cl1.id
            JOIN claims cl2 ON ce2.claim_id = cl2.id
            WHERE ce1.claim_id < ce2.claim_id
              AND cl1.created_at > ? AND cl2.created_at > ?
              AND cl1.superseded_at IS NULL AND cl2.superseded_at IS NULL
            GROUP BY ce1.claim_id, ce2.claim_id
            HAVING shared >= 2
            """,
            (cutoff, cutoff),
        )
        pairs = await cursor.fetchall()

        if not pairs:
            return []

        # Union-Find clustering
        parent: dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for row in pairs:
            union(str(row[0]), str(row[1]))

        # Group into clusters
        clusters: dict[str, list[str]] = {}
        all_claim_ids: set[str] = set()
        for row in pairs:
            all_claim_ids.add(str(row[0]))
            all_claim_ids.add(str(row[1]))

        for cid in all_claim_ids:
            root = find(cid)
            clusters.setdefault(root, []).append(cid)

        # Filter by min_cluster and generate observations
        observations: list[Claim] = []
        for cluster_ids in clusters.values():
            if len(cluster_ids) < min_cluster:
                continue

            # Collect entities from cluster
            placeholders = ", ".join("?" for _ in cluster_ids)
            ent_cursor = await self._db.execute(
                f"""SELECT DISTINCT e.name
                    FROM claim_entities ce
                    JOIN entities e ON ce.entity_id = e.id
                    WHERE ce.claim_id IN ({placeholders})""",
                cluster_ids,
            )
            ent_rows = await ent_cursor.fetchall()
            entities = [str(r[0]) for r in ent_rows]

            # Collect sources
            src_cursor = await self._db.execute(
                f"""SELECT DISTINCT e.source
                    FROM claims c
                    JOIN episodes e ON c.episode_id = e.id
                    WHERE c.id IN ({placeholders}) AND e.source != ''""",
                cluster_ids,
            )
            src_rows = await src_cursor.fetchall()
            sources = [str(r[0]) for r in src_rows] or ["unknown"]

            # Template-based observation (no LLM)
            obs_text = (
                f"Pattern: {len(cluster_ids)} claims about "
                f"{', '.join(entities[:5])} from {', '.join(sources[:3])} "
                f"over {days} days"
            )

            obs = Claim(
                text=obs_text,
                type=ClaimType.OBSERVATION,
                entities=entities[:10],
                confidence=0.6,
                salience=0.8,
            )
            result = await self.add_claims([obs])
            if result.claims:
                observations.extend(result.claims)

        return observations

    # ── source_stats() — per-source reliability profile ───────────────────

    async def source_stats(self, source: str) -> dict[str, Any]:
        """Get reliability profile for a source.

        Returns aggregated stats useful for calibrating trust:
        total_claims, avg_salience, confirmed_ratio, avg_surprise,
        sentiment_profile, top_entities, claim_frequency.
        """
        # Total claims from this source
        cursor = await self._db.execute(
            """SELECT COUNT(*), AVG(c.salience)
               FROM claims c
               JOIN episodes e ON c.episode_id = e.id
               WHERE e.source = ?""",
            (source,),
        )
        row = await cursor.fetchone()
        total = int(row[0]) if row and row[0] else 0
        avg_salience = float(row[1]) if row and row[1] else 0.0

        if total == 0:
            return {
                "source": source,
                "total_claims": 0,
                "avg_salience": 0.0,
                "confirmed_ratio": 0.0,
                "avg_surprise": 0.0,
                "sentiment_profile": {},
                "top_entities": [],
                "claim_frequency": 0.0,
            }

        # Confirmed ratio (claims with salience > 0.8 / total)
        cursor = await self._db.execute(
            """SELECT COUNT(*)
               FROM claims c
               JOIN episodes e ON c.episode_id = e.id
               WHERE e.source = ? AND c.salience > 0.8""",
            (source,),
        )
        row = await cursor.fetchone()
        confirmed = int(row[0]) if row and row[0] else 0

        # Average surprise
        cursor = await self._db.execute(
            """SELECT AVG(json_extract(c.metadata, '$.surprise'))
               FROM claims c
               JOIN episodes e ON c.episode_id = e.id
               WHERE e.source = ?""",
            (source,),
        )
        row = await cursor.fetchone()
        avg_surprise = float(row[0]) if row and row[0] else 0.0

        # Sentiment profile
        cursor = await self._db.execute(
            """SELECT json_extract(c.metadata, '$.sentiment') AS sent, COUNT(*)
               FROM claims c
               JOIN episodes e ON c.episode_id = e.id
               WHERE e.source = ?
               GROUP BY sent""",
            (source,),
        )
        sent_rows = await cursor.fetchall()
        sentiment_profile = {str(r[0]): int(r[1]) for r in sent_rows if r[0]}

        # Top entities
        cursor = await self._db.execute(
            """SELECT en.name, COUNT(*) as cnt
               FROM claims c
               JOIN episodes e ON c.episode_id = e.id
               JOIN claim_entities ce ON c.id = ce.claim_id
               JOIN entities en ON ce.entity_id = en.id
               WHERE e.source = ?
               GROUP BY en.name
               ORDER BY cnt DESC
               LIMIT 10""",
            (source,),
        )
        ent_rows = await cursor.fetchall()
        top_entities = [str(r[0]) for r in ent_rows]

        # Claim frequency (claims per day)
        cursor = await self._db.execute(
            """SELECT MIN(e.fetched_at), MAX(e.fetched_at)
               FROM episodes e WHERE e.source = ?""",
            (source,),
        )
        row = await cursor.fetchone()
        frequency = 0.0
        if row and row[0] and row[1]:
            try:
                first = datetime.fromisoformat(str(row[0]))
                last = datetime.fromisoformat(str(row[1]))
                days_span = max(1, (last - first).days)
                frequency = round(total / days_span, 2)
            except (ValueError, TypeError):
                pass

        return {
            "source": source,
            "total_claims": total,
            "avg_salience": round(avg_salience, 4),
            "confirmed_ratio": round(confirmed / max(total, 1), 4),
            "avg_surprise": round(avg_surprise, 4),
            "sentiment_profile": sentiment_profile,
            "top_entities": top_entities,
            "claim_frequency": frequency,
        }


# ── Helpers ───────────────────────────────────────────────────────────────


def _synthesize_observation_template(claims: list[Claim], collisions: list[Collision]) -> str:
    """Template-based observation from claims and collisions (no LLM)."""
    entities = _collect_entities(claims)
    collision_types = [c.type for c in collisions]
    n_contradictions = collision_types.count("contradiction")
    n_confirms = collision_types.count("confirms")

    parts = [f"Reflection on {len(claims)} claims"]
    if entities:
        parts.append(f"about {', '.join(entities[:5])}")
    if n_contradictions:
        parts.append(f"({n_contradictions} contradictions detected)")
    if n_confirms:
        parts.append(f"({n_confirms} confirmations)")

    return ". ".join(parts)


def _collect_entities(claims: list[Claim]) -> list[str]:
    """Collect unique entities from claims, ordered by frequency."""
    counts: Counter[str] = Counter()
    for c in claims:
        for e in c.entities:
            counts[e] += 1
    return [e for e, _ in counts.most_common(10)]


def _parse_json_response(response: str) -> dict[str, Any]:
    """Parse LLM JSON response, stripping markdown if needed."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        result: dict[str, Any] = json.loads(text)
        return result
    except json.JSONDecodeError:
        return {}
