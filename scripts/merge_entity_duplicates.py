"""Merge case-insensitive entity duplicates in production DB.

Fixes the historical issue where "Tensory" and "tensory" were stored
as separate entities, preventing structural collision detection.

Usage:
    uv run python scripts/merge_entity_duplicates.py [--db PATH] [--dry-run]

Default DB: ~/.local/share/tensory/memory.db
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from collections import defaultdict


def find_duplicates(db: sqlite3.Connection) -> dict[str, list[tuple[str, str, int]]]:
    """Find entities that differ only by case.

    Returns: {lower_name: [(id, name, mention_count), ...]}
    """
    rows = db.execute(
        """
        SELECT e.id, e.name, e.mention_count,
               (SELECT COUNT(*) FROM claim_entities WHERE entity_id = e.id) as link_count
        FROM entities e
        ORDER BY e.name
        """
    ).fetchall()

    groups: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    for row in rows:
        key = row[1].lower()
        groups[key].append((row[0], row[1], row[2], row[3]))

    # Only keep groups with >1 variant
    return {k: v for k, v in groups.items() if len(v) > 1}


def merge_group(
    db: sqlite3.Connection,
    variants: list[tuple[str, str, int, int]],
    *,
    dry_run: bool = False,
) -> tuple[str, int]:
    """Merge entity variants into the one with most links.

    Returns: (canonical_name, num_links_updated)
    """
    # Pick canonical: most claim links, ties broken by mention_count
    variants.sort(key=lambda v: (v[3], v[2]), reverse=True)
    canonical_id, canonical_name, _, _ = variants[0]
    others = variants[1:]

    total_updated = 0
    for other_id, other_name, _, link_count in others:
        if dry_run:
            print(f"  Would merge '{other_name}' ({link_count} links) → '{canonical_name}'")
            total_updated += link_count
            continue

        # Repoint claim_entities links from old → canonical
        # Use INSERT OR IGNORE to handle cases where claim already linked to canonical
        db.execute(
            """
            INSERT OR IGNORE INTO claim_entities (claim_id, entity_id)
            SELECT claim_id, ? FROM claim_entities WHERE entity_id = ?
            """,
            (canonical_id, other_id),
        )
        # Delete old links
        db.execute("DELETE FROM claim_entities WHERE entity_id = ?", (other_id,))

        # Repoint entity_relations
        db.execute(
            "UPDATE entity_relations SET from_entity = ? WHERE from_entity = ?",
            (canonical_id, other_id),
        )
        db.execute(
            "UPDATE entity_relations SET to_entity = ? WHERE to_entity = ?",
            (canonical_id, other_id),
        )

        # Sum mention counts
        db.execute(
            "UPDATE entities SET mention_count = mention_count + ? WHERE id = ?",
            (link_count, canonical_id),
        )

        # Delete old entity
        db.execute("DELETE FROM entities WHERE id = ?", (other_id,))
        total_updated += link_count

    return canonical_name, total_updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge case-insensitive entity duplicates.")
    parser.add_argument(
        "--db",
        default=os.path.expanduser("~/.local/share/tensory/memory.db"),
        help="Path to tensory database",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be merged")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print(f"Database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    db = sqlite3.connect(args.db)
    duplicates = find_duplicates(db)

    if not duplicates:
        print("No case-insensitive duplicates found.")
        return

    print(f"Found {len(duplicates)} entity groups with case duplicates:\n")

    total_merged = 0
    for lower_name, variants in sorted(duplicates.items(), key=lambda x: -len(x[1])):
        names = [f"'{v[1]}' ({v[3]} links)" for v in variants]
        print(f"  {lower_name}: {', '.join(names)}")
        canonical, updated = merge_group(db, variants, dry_run=args.dry_run)
        if not args.dry_run:
            print(f"    → merged into '{canonical}' ({updated} links repointed)")
        total_merged += updated

    if not args.dry_run:
        # Backfill canonical column for all entities (schema v4 migration)
        try:
            db.execute("SELECT canonical FROM entities LIMIT 1")
            # Column exists — backfill any NULLs
            from tensory.graph import normalize_entity_name

            rows = db.execute("SELECT id, name FROM entities WHERE canonical IS NULL").fetchall()
            for row in rows:
                db.execute(
                    "UPDATE entities SET canonical = ? WHERE id = ?",
                    (normalize_entity_name(row[1]), row[0]),
                )
            if rows:
                print(f"\nBackfilled canonical for {len(rows)} entities.")
        except Exception:
            pass  # canonical column may not exist yet (pre-v4)

        db.commit()
        print(f"\nDone. Merged {total_merged} entity links across {len(duplicates)} groups.")
    else:
        print(f"\nDry run complete. Would merge {total_merged} links in {len(duplicates)} groups.")

    db.close()


if __name__ == "__main__":
    main()
