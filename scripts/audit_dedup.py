"""One-shot dedup audit: how polluted is the claim store?

Loads all claims, computes pairwise Jaccard via MinHashDedup,
reports duplicate clusters and overall uniqueness %.

Usage:
    uv run python scripts/audit_dedup.py [--db PATH] [--threshold 0.9]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import defaultdict

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tensory.dedup import MinHashDedup, _jaccard, _shingle, _word_jaccard


async def load_claims(db_path: str) -> list[tuple[str, str, str]]:
    """Load all claims as (id, text, type) tuples."""
    import aiosqlite

    db_path = os.path.expanduser(db_path)
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT id, text, type FROM claims ORDER BY created_at")
        return [(row[0], row[1], row[2]) for row in await cursor.fetchall()]


def find_clusters(
    claims: list[tuple[str, str, str]], threshold: float
) -> list[list[int]]:
    """Find clusters of near-duplicate claims using Jaccard similarity."""
    n = len(claims)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Pairwise comparison with char + word Jaccard
    shingles = [_shingle(c[1]) for c in claims]
    for i in range(n):
        for j in range(i + 1, n):
            char_j = _jaccard(shingles[i], shingles[j])
            if char_j >= threshold:
                union(i, j)
            elif char_j >= 0.7 and _word_jaccard(claims[i][1], claims[j][1]) >= 0.8:
                union(i, j)

    # Group by root
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    # Return only clusters with >1 member
    return [indices for indices in groups.values() if len(indices) > 1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Tensory claim dedup audit")
    parser.add_argument(
        "--db",
        default="~/.local/share/tensory/memory.db",
        help="Database path",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.9,
        help="Jaccard threshold (default: 0.9 = strict)",
    )
    args = parser.parse_args()

    claims = asyncio.run(load_claims(args.db))
    print(f"\n{'='*60}")
    print(f"  TENSORY DEDUP AUDIT")
    print(f"  Claims: {len(claims)} | Threshold: {args.threshold}")
    print(f"{'='*60}\n")

    if not claims:
        print("No claims found.")
        return

    clusters = find_clusters(claims, args.threshold)

    duplicated_count = sum(len(c) for c in clusters)
    unique_count = len(claims) - duplicated_count + len(clusters)
    pollution_pct = (1 - unique_count / len(claims)) * 100

    # Summary
    print(f"  Unique claims:     {unique_count}/{len(claims)} ({100 - pollution_pct:.1f}%)")
    print(f"  Duplicate claims:  {duplicated_count - len(clusters)} (could be removed)")
    print(f"  Clusters found:    {len(clusters)}")
    print(f"  Pollution rate:    {pollution_pct:.1f}%")
    print()

    # Type distribution
    type_counts: dict[str, int] = defaultdict(int)
    for _, _, t in claims:
        type_counts[t] += 1
    print("  Claims by type:")
    for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"    {t:15s} {count:4d}")
    print()

    # Show clusters
    if clusters:
        # Sort by size (largest first)
        clusters.sort(key=len, reverse=True)
        print(f"  {'─'*56}")
        print(f"  TOP DUPLICATE CLUSTERS (showing max 15)")
        print(f"  {'─'*56}")
        for i, cluster in enumerate(clusters[:15]):
            print(f"\n  Cluster {i+1} ({len(cluster)} claims):")
            for idx in cluster:
                cid, text, ctype = claims[idx]
                short = text[:90] + "..." if len(text) > 90 else text
                print(f"    [{ctype:11s}] {short}")
    else:
        print("  ✅ No duplicate clusters found! Store is clean.")

    print(f"\n{'='*60}\n")


if __name__ == "__main__":
    main()
