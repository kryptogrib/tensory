"""Consolidation (dream) — periodic maintenance of the claim store.

Lightweight consolidation without LLM calls:
1. Apply salience decay (exponential, per ClaimType)
2. Retrospective dedup — find near-duplicate claims across sessions
3. Cleanup — remove dead claims (low salience + old + superseded)

Adapted from Claude Code's AutoDream pattern, but LLM-free for
automatic scheduling. Full reflect() with LLM is available
separately via store.reflect().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from tensory.dedup import jaccard, shingle
from tensory.temporal import apply_decay, auto_supersede_on_collision, cleanup

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


@dataclass
class ConsolidationResult:
    """Summary of what consolidation did."""

    decayed_count: int = 0
    dedup_pairs_found: int = 0
    dedup_superseded: int = 0
    cleaned_up: int = 0
    errors: list[str] = field(default_factory=list[str])


async def consolidate(
    db: aiosqlite.Connection,
    *,
    max_age_days: int = 90,
    min_salience: float = 0.01,
    dedup_threshold: float = 0.9,
    dedup_batch_size: int = 500,
) -> ConsolidationResult:
    """Run lightweight consolidation on the claim store.

    Steps (cheapest first):
    1. Decay — reduce salience of stale claims
    2. Retrospective dedup — find and supersede near-duplicates
    3. Cleanup — remove dead claims

    Args:
        db: Database connection.
        max_age_days: Max age for cleanup (default 90 days).
        min_salience: Salience floor for cleanup (default 0.01).
        dedup_threshold: Jaccard threshold for dedup (default 0.9).
        dedup_batch_size: How many claims to scan for dedup (default 500).

    Returns:
        ConsolidationResult with counts of what was done.
    """
    result = ConsolidationResult()

    # Step 1: Decay
    try:
        result.decayed_count = await apply_decay(db)
        logger.info("Decay: updated %d claims", result.decayed_count)
    except Exception as e:
        msg = f"Decay failed: {e}"
        logger.warning(msg)
        result.errors.append(msg)

    # Step 2: Retrospective dedup
    try:
        dedup_result = await _retrospective_dedup(
            db,
            threshold=dedup_threshold,
            batch_size=dedup_batch_size,
        )
        result.dedup_pairs_found = dedup_result[0]
        result.dedup_superseded = dedup_result[1]
        logger.info(
            "Dedup: found %d pairs, superseded %d claims",
            result.dedup_pairs_found,
            result.dedup_superseded,
        )
    except Exception as e:
        msg = f"Dedup failed: {e}"
        logger.warning(msg)
        result.errors.append(msg)

    # Step 3: Cleanup
    try:
        result.cleaned_up = await cleanup(
            db,
            max_age_days=max_age_days,
            min_salience=min_salience,
        )
        logger.info("Cleanup: removed %d claims", result.cleaned_up)
    except Exception as e:
        msg = f"Cleanup failed: {e}"
        logger.warning(msg)
        result.errors.append(msg)

    return result


async def _retrospective_dedup(
    db: aiosqlite.Connection,
    *,
    threshold: float = 0.9,
    batch_size: int = 500,
) -> tuple[int, int]:
    """Find and supersede near-duplicate claims across sessions.

    Scans active claims ordered by creation time (newest first).
    For each claim, checks Jaccard similarity against older claims
    with shared entities. If overlap > threshold, supersede the older one.

    Returns (pairs_found, claims_superseded).
    """
    # Load recent active claims
    cursor = await db.execute(
        """SELECT c.id, c.text, c.created_at
           FROM claims c
           WHERE c.superseded_at IS NULL
           ORDER BY c.created_at DESC
           LIMIT ?""",
        (batch_size,),
    )
    rows = list(await cursor.fetchall())

    if len(rows) < 2:
        return (0, 0)

    # Build shingle index for all claims
    claims_data: list[tuple[str, str, frozenset[str]]] = []
    for row in rows:
        claim_id: str = row[0]
        text: str = row[1]
        shingles = shingle(text)
        claims_data.append((claim_id, text, shingles))

    pairs_found = 0
    superseded = 0
    already_superseded: set[str] = set()

    # Compare each claim against all older claims (later in list = older)
    for i, (new_id, _new_text, new_shingles) in enumerate(claims_data):
        if new_id in already_superseded:
            continue

        for old_id, _old_text, old_shingles in claims_data[i + 1 :]:
            if old_id in already_superseded:
                continue

            sim = jaccard(new_shingles, old_shingles)
            if sim >= threshold:
                pairs_found += 1
                # Supersede the older claim (newer wins)
                did_supersede = await auto_supersede_on_collision(
                    new_id,
                    old_id,
                    sim,
                    db,
                    threshold=threshold,
                )
                if did_supersede:
                    superseded += 1
                    already_superseded.add(old_id)

    if superseded > 0:
        await db.commit()

    return (pairs_found, superseded)
