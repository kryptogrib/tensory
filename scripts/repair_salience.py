"""One-time repair script: fix salience damaged by structural false positives.

The old _find_structural_conflicts() marked ALL claims sharing an entity as
"contradiction" (salience × 0.5), even when claims described different
attributes. This caused cascading salience destruction — claims about
"tensory" and "claude-agent-sdk" dropped to near-zero (0.000002).

This script:
1. Migrates schema to v3 (adds collision_log table)
2. Resets salience for non-superseded claims to a reasonable baseline
3. Reports the repair results

Usage:
    uv run python scripts/repair_salience.py [--db PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import aiosqlite

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DB = Path.home() / ".local/share/tensory/memory.db"


async def repair(db_path: str, *, dry_run: bool = False) -> dict[str, int]:
    """Repair salience and migrate schema."""
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row

    results: dict[str, int] = {}

    try:
        # ── Step 1: Schema migration to v3 ───────────────────────────────
        cursor = await db.execute("SELECT version FROM schema_version LIMIT 1")
        row = await cursor.fetchone()
        current_version = row[0] if row else 0
        logger.info("Current schema version: %d", current_version)

        if current_version < 3:
            if not dry_run:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS collision_log (
                        id             TEXT PRIMARY KEY,
                        claim_a_id     TEXT NOT NULL,
                        claim_b_id     TEXT NOT NULL,
                        collision_type TEXT NOT NULL,
                        score          REAL NOT NULL,
                        shared_entities JSON DEFAULT '[]',
                        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_collision_log_a "
                    "ON collision_log(claim_a_id)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_collision_log_b "
                    "ON collision_log(claim_b_id)"
                )
                await db.execute(
                    "CREATE INDEX IF NOT EXISTS idx_collision_log_type "
                    "ON collision_log(collision_type)"
                )
                await db.execute(
                    "UPDATE schema_version SET version = 3"
                )
                logger.info("Migrated schema to v3 (collision_log table)")
            else:
                logger.info("[DRY RUN] Would migrate schema to v3")
            results["schema_migrated"] = 1
        else:
            logger.info("Schema already at v%d, no migration needed", current_version)
            results["schema_migrated"] = 0

        # ── Step 2: Count damaged claims ─────────────────────────────────
        cursor = await db.execute("""
            SELECT COUNT(*) FROM claims
            WHERE salience < 0.5 AND superseded_at IS NULL
        """)
        row = await cursor.fetchone()
        damaged_count = row[0] if row else 0
        results["damaged_claims"] = damaged_count
        logger.info("Found %d claims with salience < 0.5 (not superseded)", damaged_count)

        # ── Step 3: Repair salience ──────────────────────────────────────
        # Strategy: reset to 0.8 (slightly below fresh = 1.0, acknowledging
        # some natural decay may have occurred). Claims that were legitimately
        # low will naturally decay again.
        if damaged_count > 0:
            if not dry_run:
                await db.execute("""
                    UPDATE claims
                    SET salience = 0.8
                    WHERE salience < 0.5
                      AND superseded_at IS NULL
                """)
                logger.info("Reset %d claims to salience=0.8", damaged_count)
            else:
                logger.info("[DRY RUN] Would reset %d claims to salience=0.8", damaged_count)
            results["repaired_claims"] = damaged_count

        # ── Step 4: Report ───────────────────────────────────────────────
        cursor = await db.execute("""
            SELECT ROUND(AVG(salience), 4) as avg_sal,
                   ROUND(MIN(salience), 4) as min_sal,
                   COUNT(*) as total
            FROM claims WHERE superseded_at IS NULL
        """)
        row = await cursor.fetchone()
        if row:
            logger.info(
                "After repair: avg_salience=%.4f, min_salience=%.4f, total=%d",
                float(row[0] or 0), float(row[1] or 0), row[2],
            )

        if not dry_run:
            await db.commit()
        results["success"] = 1

    finally:
        await db.close()

    return results


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Repair salience damaged by false contradictions")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Path to tensory DB")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    if not Path(args.db).exists():
        logger.error("Database not found: %s", args.db)
        sys.exit(1)

    results = asyncio.run(repair(args.db, dry_run=args.dry_run))
    logger.info("Results: %s", results)


if __name__ == "__main__":
    main()
