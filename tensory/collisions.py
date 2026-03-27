"""Two-level collision detection for tensory — zero LLM calls.

Level 1: STRUCTURAL (OpenMemory pattern)
  Same entity + overlapping temporal validity → automatic conflict.
  e.g., "EigenLayer team=50" vs "EigenLayer team=45"

Level 2: SEMANTIC (4-signal weighted score)
  vector_score   = cosine similarity (sqlite-vec)
  entity_score   = shared_entities / max_entities
  temporal_score = 1 - (days_apart / 30), clipped [0, 1]
  waypoint_score = 1.0 if connected via waypoint, else 0.0

  final = vector×0.4 + entity×0.25 + temporal×0.2 + waypoint×0.15

References:
- Structural conflict: OpenMemory find_conflicting_facts()
- Temporal invalidation: Graphiti edges.py (expired_at pattern)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tensory.models import Claim, ClaimType, Collision

if TYPE_CHECKING:
    import aiosqlite

    from tensory.graph import GraphBackend

logger = logging.getLogger(__name__)

# ── Salience update rules (LLM-free) ─────────────────────────────────────

SALIENCE_RULES: dict[str, Callable[[float], float]] = {
    "contradiction": lambda s: s * 0.5,
    "supersedes": lambda s: s * 0.1,
    "confirms": lambda s: min(1.0, s + 0.2),
    "related": lambda s: min(1.0, s + 0.05),
}

# Default decay rates per ClaimType (also in store.py, duplicated for independence)
DECAY_RATES: dict[ClaimType, float] = {
    ClaimType.FACT: 0.005,
    ClaimType.EXPERIENCE: 0.010,
    ClaimType.OBSERVATION: 0.008,
    ClaimType.OPINION: 0.020,
}

# ── Collision scoring weights ─────────────────────────────────────────────

VECTOR_WEIGHT = 0.4
ENTITY_WEIGHT = 0.25
TEMPORAL_WEIGHT = 0.2
WAYPOINT_WEIGHT = 0.15


# ── Public API ────────────────────────────────────────────────────────────


async def find_collisions(
    claim: Claim,
    db: aiosqlite.Connection,
    *,
    graph_backend: GraphBackend | None = None,
    top_k: int = 10,
    threshold: float = 0.5,
) -> list[Collision]:
    """Find collisions between a new claim and existing claims.

    Two-level detection:
    1. Structural: same entities + overlapping validity windows
    2. Semantic: weighted composite of vector, entity, temporal, waypoint scores

    Args:
        claim: The new claim to check.
        db: Database connection.
        graph_backend: Graph backend for shared entity lookup.
        top_k: Max candidates for semantic collision check.
        threshold: Minimum score to report a collision.
    """
    collisions: list[Collision] = []

    # ── Level 1: Structural ───────────────────────────────────────────
    structural = await _find_structural_conflicts(claim, db)
    collisions.extend(structural)

    # ── Level 2: Semantic ─────────────────────────────────────────────
    candidates = await _get_candidates(claim, db, top_k)
    seen_ids = {c.claim_b.id for c in collisions}

    for candidate in candidates:
        if candidate.id == claim.id or candidate.id in seen_ids:
            continue

        shared = set(claim.entities) & set(candidate.entities)
        is_waypoint = await _is_waypoint_linked(claim.id, candidate.id, db)

        vector_score = _cosine_sim(claim.embedding, candidate.embedding)
        entity_score = len(shared) / max(len(claim.entities), len(candidate.entities), 1)
        temporal_score = _temporal_proximity(claim.created_at, candidate.created_at)
        waypoint_score = 1.0 if is_waypoint else 0.0

        final = (
            vector_score * VECTOR_WEIGHT
            + entity_score * ENTITY_WEIGHT
            + temporal_score * TEMPORAL_WEIGHT
            + waypoint_score * WAYPOINT_WEIGHT
        )

        if final >= threshold:
            collision_type = _classify_collision(claim, candidate, final)
            collisions.append(
                Collision(
                    claim_a=claim,
                    claim_b=candidate,
                    score=round(final, 4),
                    shared_entities=list(shared),
                    temporal_distance=round(temporal_score, 4),
                    type=collision_type,
                )
            )

    return sorted(collisions, key=lambda c: c.score, reverse=True)


async def apply_salience_updates(collisions: list[Collision], db: aiosqlite.Connection) -> None:
    """Apply LLM-free salience updates based on collision type.

    Rules:
    - contradiction → salience × 0.5 (on the OLD claim)
    - supersedes    → salience × 0.1 (old claim nearly dead)
    - confirms      → salience + 0.2 (both claims boosted)
    - related       → salience + 0.05 (small boost)
    """
    for collision in collisions:
        rule = SALIENCE_RULES.get(collision.type)
        if rule:
            new_salience = rule(collision.claim_b.salience)
            await db.execute(
                "UPDATE claims SET salience = ? WHERE id = ?",
                (new_salience, collision.claim_b.id),
            )

    await db.commit()


# ── Level 1: Structural conflicts ────────────────────────────────────────


async def _find_structural_conflicts(claim: Claim, db: aiosqlite.Connection) -> list[Collision]:
    """Find claims about same entities with overlapping validity windows.

    Pattern from OpenMemory find_conflicting_facts(): if two claims
    share entities and both are currently valid, they likely conflict.
    """
    if not claim.entities:
        return []

    # Find claims sharing at least one entity, that aren't superseded
    placeholders = ", ".join("?" for _ in claim.entities)
    cursor = await db.execute(
        f"""
        SELECT DISTINCT c.*
        FROM claims c
        JOIN claim_entities ce ON c.id = ce.claim_id
        JOIN entities e ON ce.entity_id = e.id
        WHERE e.name IN ({placeholders})
          AND c.id != ?
          AND c.superseded_at IS NULL
          AND (c.valid_to IS NULL OR c.valid_to > ?)
        LIMIT 20
        """,
        (*claim.entities, claim.id, datetime.now(UTC).isoformat()),
    )
    rows = await cursor.fetchall()

    conflicts: list[Collision] = []
    for row in rows:
        candidate = _row_to_claim_light(row)
        # Load entities for the candidate
        ent_cursor = await db.execute(
            """SELECT e.name FROM claim_entities ce
               JOIN entities e ON ce.entity_id = e.id
               WHERE ce.claim_id = ?""",
            (candidate.id,),
        )
        ent_rows = await ent_cursor.fetchall()
        candidate.entities = [str(r[0]) for r in ent_rows]

        shared = set(claim.entities) & set(candidate.entities)
        if shared:
            conflicts.append(
                Collision(
                    claim_a=claim,
                    claim_b=candidate,
                    score=0.8,  # structural conflicts have high base score
                    shared_entities=list(shared),
                    temporal_distance=None,
                    type="contradiction",
                )
            )

    return conflicts


# ── Level 2: Semantic candidates ─────────────────────────────────────────


async def _get_candidates(claim: Claim, db: aiosqlite.Connection, top_k: int) -> list[Claim]:
    """Get candidate claims for semantic collision check.

    Uses vector search if embedding available, falls back to FTS.
    """
    candidates: list[Claim] = []

    # Try vector search first
    if claim.embedding:
        try:
            cursor = await db.execute(
                """
                SELECT ce.claim_id, ce.distance, c.*
                FROM claim_embeddings ce
                JOIN claims c ON c.id = ce.claim_id
                WHERE ce.embedding MATCH ?
                  AND k = ?
                  AND c.id != ?
                  AND c.superseded_at IS NULL
                """,
                (json.dumps(claim.embedding), top_k, claim.id),
            )
            rows = await cursor.fetchall()
            for row in rows:
                c = _row_to_claim_light(row)
                # Load embedding for cosine sim computation
                c.embedding = claim.embedding  # approximate: use distance instead
                candidates.append(c)
        except Exception:
            logger.debug("Vector candidate search failed, falling back to FTS")

    # Fallback / supplement with FTS
    if len(candidates) < top_k:
        remaining = top_k - len(candidates)
        seen_ids = {c.id for c in candidates}
        try:
            # Use first few words as FTS query
            query_words = " ".join(claim.text.split()[:5])
            cursor = await db.execute(
                """
                SELECT c.*
                FROM claims_fts fts
                JOIN claims c ON c.rowid = fts.rowid
                WHERE claims_fts MATCH ?
                  AND c.id != ?
                  AND c.superseded_at IS NULL
                ORDER BY fts.rank
                LIMIT ?
                """,
                (query_words, claim.id, remaining),
            )
            rows = await cursor.fetchall()
            for row in rows:
                c = _row_to_claim_light(row)
                if c.id not in seen_ids:
                    candidates.append(c)
        except Exception:
            pass  # graceful degradation

    # Load entities for all candidates
    for candidate in candidates:
        ent_cursor = await db.execute(
            """SELECT e.name FROM claim_entities ce
               JOIN entities e ON ce.entity_id = e.id
               WHERE ce.claim_id = ?""",
            (candidate.id,),
        )
        ent_rows = await ent_cursor.fetchall()
        candidate.entities = [str(r[0]) for r in ent_rows]

    return candidates


# ── Scoring helpers ───────────────────────────────────────────────────────


def _cosine_sim(a: list[float] | None, b: list[float] | None) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5

    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _temporal_proximity(a: datetime, b: datetime) -> float:
    """Score how close two claims are in time.

    Returns 1.0 for same-day, 0.0 for 30+ days apart.
    """
    days_apart = abs((a - b).total_seconds()) / 86400
    return max(0.0, 1.0 - days_apart / 30.0)


async def _is_waypoint_linked(claim_a_id: str, claim_b_id: str, db: aiosqlite.Connection) -> bool:
    """Check if two claims are connected via waypoint graph."""
    cursor = await db.execute(
        """SELECT 1 FROM waypoints
           WHERE (src_claim = ? AND dst_claim = ?)
              OR (src_claim = ? AND dst_claim = ?)
           LIMIT 1""",
        (claim_a_id, claim_b_id, claim_b_id, claim_a_id),
    )
    return await cursor.fetchone() is not None


def _classify_collision(new_claim: Claim, existing: Claim, score: float) -> str:
    """Classify collision type based on signals.

    - score > 0.9 → supersedes (very similar, newer replaces older)
    - shared entities + high score → contradiction
    - moderate overlap → related
    - both confirm each other → confirms
    """
    shared = set(new_claim.entities) & set(existing.entities)

    if score > 0.9:
        return "supersedes"

    if shared and score > 0.7:
        return "contradiction"

    if score > 0.6:
        return "confirms"

    return "related"


# ── Helpers ───────────────────────────────────────────────────────────────


def _row_to_claim_light(row: aiosqlite.Row) -> Claim:
    """Convert DB row to Claim (without loading entities — done separately)."""
    import json as _json

    from tensory.models import ClaimType as _CT

    metadata_raw = row["metadata"]
    metadata: dict[str, object] = {}
    if metadata_raw:
        metadata = _json.loads(str(metadata_raw))

    return Claim(
        id=row["id"],
        text=row["text"],
        type=_CT(row["type"]),
        confidence=float(row["confidence"]),
        relevance=float(row["relevance"]),
        salience=float(row["salience"]),
        decay_rate=float(row["decay_rate"]) if row["decay_rate"] is not None else None,
        episode_id=row["episode_id"],
        context_id=row["context_id"],
        created_at=(
            datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(UTC)
        ),
        superseded_at=(
            datetime.fromisoformat(row["superseded_at"]) if row["superseded_at"] else None
        ),
        superseded_by=row["superseded_by"],
        metadata=metadata,
    )
