"""Temporal operations for tensory — superseding, timeline, decay, cleanup.

Manages the lifecycle of claims over time:
- Supersede: mark old claim as replaced by new claim
- Timeline: show how facts about an entity evolved
- Decay: exponential salience decay based on time since last access
- Cleanup: remove low-salience claims past max age

References:
- Superseding + expired_at: Graphiti edges.py
- Exponential decay: OpenMemory HSG salience model
"""

from __future__ import annotations

import contextlib
import logging
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tensory.models import Claim, ClaimType, MemoryType

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

# Default decay rates per ClaimType
DECAY_RATES: dict[ClaimType, float] = {
    ClaimType.FACT: 0.005,
    ClaimType.EXPERIENCE: 0.010,
    ClaimType.OBSERVATION: 0.008,
    ClaimType.OPINION: 0.020,
}


async def supersede(
    old_claim_id: str,
    new_claim_id: str,
    db: aiosqlite.Connection,
) -> None:
    """Mark old claim as superseded by new claim.

    Sets superseded_at timestamp and superseded_by reference.
    Superseded claims are excluded from search results.
    """
    now = datetime.now(UTC).isoformat()
    await db.execute(
        """UPDATE claims
           SET superseded_at = ?, superseded_by = ?, salience = salience * 0.1
           WHERE id = ? AND superseded_at IS NULL""",
        (now, new_claim_id, old_claim_id),
    )
    await db.commit()


async def auto_supersede_on_collision(
    new_claim_id: str,
    old_claim_id: str,
    collision_score: float,
    db: aiosqlite.Connection,
    *,
    threshold: float = 0.9,
) -> bool:
    """Auto-supersede old claim if collision score > threshold.

    Returns True if superseding occurred.
    """
    if collision_score > threshold:
        await supersede(old_claim_id, new_claim_id, db)
        logger.info(
            "Auto-superseded claim %s by %s (score=%.2f)",
            old_claim_id[:8],
            new_claim_id[:8],
            collision_score,
        )
        return True
    return False


async def timeline(
    entity_name: str,
    db: aiosqlite.Connection,
    *,
    include_superseded: bool = True,
    limit: int = 50,
) -> list[Claim]:
    """Show how facts about an entity evolved over time.

    Returns claims mentioning the entity, ordered by creation time.
    Optionally includes superseded claims to show the full history.
    """
    superseded_filter = "" if include_superseded else "AND c.superseded_at IS NULL"

    cursor = await db.execute(
        f"""
        SELECT c.*
        FROM claims c
        JOIN claim_entities ce ON c.id = ce.claim_id
        JOIN entities e ON ce.entity_id = e.id
        WHERE e.name = ? COLLATE NOCASE
        {superseded_filter}
        ORDER BY c.created_at ASC
        LIMIT ?
        """,
        (entity_name, limit),
    )
    rows = await cursor.fetchall()
    return [_row_to_claim(row) for row in rows]


async def apply_decay(db: aiosqlite.Connection) -> int:
    """Apply exponential decay to all claims based on time since last access.

    Formula: salience *= e^(-decay_rate * days_since_access)

    Returns number of claims updated.
    """
    now = datetime.now(UTC)
    cursor = await db.execute(
        """SELECT id, salience, decay_rate, type, last_accessed, created_at
           FROM claims
           WHERE superseded_at IS NULL AND salience > 0.01"""
    )
    rows = await cursor.fetchall()

    updated = 0
    for row in rows:
        claim_id = row[0]
        current_salience = float(row[1])
        decay_rate = (
            float(row[2]) if row[2] is not None else DECAY_RATES.get(ClaimType(row[3]), 0.010)
        )

        # Use last_accessed if available, otherwise created_at
        reference_time = row[4] or row[5]
        if reference_time:
            ref_dt = datetime.fromisoformat(str(reference_time))
            # Make timezone-aware if needed
            if ref_dt.tzinfo is None:
                ref_dt = ref_dt.replace(tzinfo=UTC)
            days_elapsed = (now - ref_dt).total_seconds() / 86400
        else:
            days_elapsed = 0

        if days_elapsed <= 0:
            continue

        new_salience = current_salience * math.exp(-decay_rate * days_elapsed)
        new_salience = max(0.0, round(new_salience, 6))

        if abs(new_salience - current_salience) > 0.001:
            await db.execute(
                "UPDATE claims SET salience = ? WHERE id = ?",
                (new_salience, claim_id),
            )
            updated += 1

    await db.commit()
    return updated


async def cleanup(
    db: aiosqlite.Connection,
    *,
    max_age_days: int = 90,
    min_salience: float = 0.01,
) -> int:
    """Remove low-salience claims that are past max age.

    Does NOT delete episodes (raw text is preserved forever).
    Only removes claims, their entities links, and embeddings.

    Returns number of claims removed.
    """
    cutoff = datetime.now(UTC)
    from datetime import timedelta

    cutoff_str = (cutoff - timedelta(days=max_age_days)).isoformat()

    # Find claims to remove
    cursor = await db.execute(
        """SELECT id FROM claims
           WHERE salience < ?
             AND created_at < ?
             AND superseded_at IS NOT NULL""",
        (min_salience, cutoff_str),
    )
    rows = await cursor.fetchall()
    claim_ids = [row[0] for row in rows]

    if not claim_ids:
        return 0

    placeholders = ", ".join("?" for _ in claim_ids)

    # Remove related data
    await db.execute(
        f"DELETE FROM claim_entities WHERE claim_id IN ({placeholders})",
        claim_ids,
    )
    await db.execute(
        f"DELETE FROM waypoints WHERE src_claim IN ({placeholders}) OR dst_claim IN ({placeholders})",
        [*claim_ids, *claim_ids],
    )
    await db.execute(
        f"DELETE FROM relevance_scores WHERE claim_id IN ({placeholders})",
        claim_ids,
    )

    # Try to remove embeddings (may not exist if sqlite-vec unavailable)
    with contextlib.suppress(Exception):
        await db.execute(
            f"DELETE FROM claim_embeddings WHERE claim_id IN ({placeholders})",
            claim_ids,
        )

    # Remove claims themselves
    await db.execute(
        f"DELETE FROM claims WHERE id IN ({placeholders})",
        claim_ids,
    )

    await db.commit()
    logger.info("Cleaned up %d low-salience claims", len(claim_ids))
    return len(claim_ids)


# ── Helpers ───────────────────────────────────────────────────────────────


def _row_to_claim(row: aiosqlite.Row) -> Claim:
    """Convert DB row to Claim."""
    import json

    metadata_raw = row["metadata"]
    metadata: dict[str, object] = {}
    if metadata_raw:
        metadata = json.loads(str(metadata_raw))

    # Parse procedural JSON columns
    steps_raw = row["steps"] if "steps" in row.keys() else None
    steps: list[str] | None = json.loads(str(steps_raw)) if steps_raw else None

    source_ep_raw = row["source_episode_ids"] if "source_episode_ids" in row.keys() else None
    source_episode_ids: list[str] = json.loads(str(source_ep_raw)) if source_ep_raw else []

    last_used_raw = row["last_used"] if "last_used" in row.keys() else None

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
        created_at=(
            datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(UTC)
        ),
        superseded_at=(
            datetime.fromisoformat(row["superseded_at"]) if row["superseded_at"] else None
        ),
        superseded_by=row["superseded_by"],
        metadata=metadata,
        memory_type=MemoryType(row["memory_type"]) if "memory_type" in row.keys() and row["memory_type"] else MemoryType.SEMANTIC,
        trigger=row["trigger"] if "trigger" in row.keys() else None,
        steps=steps,
        termination_condition=row["termination_condition"] if "termination_condition" in row.keys() else None,
        success_rate=float(row["success_rate"]) if "success_rate" in row.keys() and row["success_rate"] is not None else 0.5,
        usage_count=int(row["usage_count"]) if "usage_count" in row.keys() and row["usage_count"] is not None else 0,
        last_used=datetime.fromisoformat(str(last_used_raw)) if last_used_raw else None,
        source_episode_ids=source_episode_ids,
    )
