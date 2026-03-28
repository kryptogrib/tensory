"""Hybrid search with parallel retrieval and Reciprocal Rank Fusion.

Three search channels run in parallel (inspired by Hindsight TEMPR):
1. **FTS5** — keyword/full-text search
2. **sqlite-vec** — vector cosine similarity
3. **Graph** — entity co-occurrence traversal

Results are merged via weighted RRF (Reciprocal Rank Fusion).
Any channel that fails returns empty results (graceful degradation).

References:
- RRF formula: plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- Hybrid search with sqlite-vec + FTS5: alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/
- Parallel TEMPR retrieval: github.com/vectorize-io/hindsight
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tensory.models import Claim, ClaimType, MemoryType, SearchResult

if TYPE_CHECKING:
    import aiosqlite

    from tensory.graph import GraphBackend

logger = logging.getLogger(__name__)

# Default weights for RRF merge
DEFAULT_WEIGHTS: dict[str, float] = {
    "vector": 0.4,
    "fts": 0.3,
    "graph": 0.3,
}


# ── Public API ────────────────────────────────────────────────────────────


async def hybrid_search(
    query: str,
    *,
    embedding: list[float] | None,
    graph_backend: GraphBackend,
    db: aiosqlite.Connection,
    context_id: str | None = None,
    limit: int = 10,
    weights: dict[str, float] | None = None,
    memory_type: str | None = None,
) -> list[SearchResult]:
    """Parallel retrieval across 3 channels + weighted RRF merge.

    Args:
        query: Search query text.
        embedding: Query vector (None → skip vector search).
        graph_backend: Graph backend for entity traversal.
        db: Database connection.
        context_id: Optional context for relevance filtering.
        limit: Maximum results to return.
        weights: Channel weights for RRF (default: vector=0.4, fts=0.3, graph=0.3).
        memory_type: Optional memory type filter (e.g. "semantic", "procedural").
    """
    w = weights or DEFAULT_WEIGHTS
    internal_limit = max(limit * 3, 20)  # fetch more for better RRF merge

    # All three channels in parallel — graceful degradation on failure
    fts_task = fts_search(
        query, db, context_id=context_id, limit=internal_limit, memory_type=memory_type
    )
    vec_task = (
        vector_search(
            embedding, db, context_id=context_id, limit=internal_limit, memory_type=memory_type
        )
        if embedding
        else _empty_results()
    )
    graph_task = graph_search(
        query,
        graph_backend,
        db,
        context_id=context_id,
        limit=internal_limit,
        memory_type=memory_type,
    )

    results = await asyncio.gather(fts_task, vec_task, graph_task, return_exceptions=True)

    fts_r: list[SearchResult] = results[0] if not isinstance(results[0], BaseException) else []
    vec_r: list[SearchResult] = results[1] if not isinstance(results[1], BaseException) else []
    graph_r: list[SearchResult] = results[2] if not isinstance(results[2], BaseException) else []

    # Log any errors for debugging
    for name, res in [("fts", results[0]), ("vector", results[1]), ("graph", results[2])]:
        if isinstance(res, BaseException):
            logger.warning("Search channel %s failed: %s", name, res)

    return _rrf_merge(
        [fts_r, vec_r, graph_r],
        weights=[w.get("fts", 0.3), w.get("vector", 0.4), w.get("graph", 0.3)],
        limit=limit,
    )


# ── Individual search channels ────────────────────────────────────────────


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5 MATCH.

    FTS5 treats characters like ?, ', *, (, ), ", -, + as operators.
    We strip them and join remaining tokens with implicit AND.
    """
    # Remove FTS5 special characters
    cleaned = re.sub(r"[?\'\"*()^\-+~:{}[\]|!@#$%&]", " ", query)
    # Collapse whitespace, strip
    tokens = cleaned.split()
    if not tokens:
        return ""
    # Quote each token to prevent FTS5 interpretation
    return " ".join(f'"{t}"' for t in tokens if t)


async def fts_search(
    query: str,
    db: aiosqlite.Connection,
    *,
    context_id: str | None = None,
    limit: int = 20,
    memory_type: str | None = None,
) -> list[SearchResult]:
    """Full-text search via FTS5."""
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []

    memory_type_filter = "AND c.memory_type = ?" if memory_type is not None else ""
    params: list[object] = [safe_query]
    if memory_type is not None:
        params.append(memory_type)
    params.append(limit)

    cursor = await db.execute(
        f"""
        SELECT c.*, fts.rank
        FROM claims_fts fts
        JOIN claims c ON c.rowid = fts.rowid
        WHERE claims_fts MATCH ?
          AND c.superseded_at IS NULL
          {memory_type_filter}
        ORDER BY fts.rank
        LIMIT ?
        """,
        params,
    )
    rows = await cursor.fetchall()

    results: list[SearchResult] = []
    for row in rows:
        claim = row_to_claim(row)
        fts_rank = float(row["rank"]) if "rank" in row else 0.0
        score = -fts_rank if fts_rank < 0 else fts_rank

        results.append(
            SearchResult(
                claim=claim,
                score=score,
                method="fts",
            )
        )

    return results


async def vector_search(
    embedding: list[float],
    db: aiosqlite.Connection,
    *,
    context_id: str | None = None,
    limit: int = 20,
    memory_type: str | None = None,
) -> list[SearchResult]:
    """Vector similarity search via sqlite-vec.

    Uses cosine distance — lower distance = more similar.
    """
    memory_type_filter = "AND c.memory_type = ?" if memory_type is not None else ""
    vec_params: list[object] = [json.dumps(embedding), limit]
    if memory_type is not None:
        vec_params.append(memory_type)

    cursor = await db.execute(
        f"""
        SELECT ce.claim_id, ce.distance, c.*
        FROM claim_embeddings ce
        JOIN claims c ON c.id = ce.claim_id
        WHERE ce.embedding MATCH ?
          AND k = ?
          AND c.superseded_at IS NULL
          {memory_type_filter}
        ORDER BY ce.distance
        """,
        vec_params,
    )
    rows = await cursor.fetchall()

    results: list[SearchResult] = []
    for row in rows:
        claim = row_to_claim(row)
        distance = float(row["distance"])
        # Convert cosine distance to similarity score (1 - distance)
        score = max(0.0, 1.0 - distance)

        results.append(
            SearchResult(
                claim=claim,
                score=score,
                method="vector",
            )
        )

    return results


async def graph_search(
    query: str,
    graph_backend: GraphBackend,
    db: aiosqlite.Connection,
    *,
    context_id: str | None = None,
    limit: int = 20,
    memory_type: str | None = None,
) -> list[SearchResult]:
    """Graph-based search via entity traversal.

    Extracts entity names from the query, traverses the graph,
    and returns claims linked to reachable entities.
    """
    # Simple entity extraction: look up query terms as entity names
    words = query.strip().split()
    entity_ids: list[str] = []

    for word in words:
        cursor = await db.execute(
            "SELECT id FROM entities WHERE name = ? COLLATE NOCASE",
            (word.strip(),),
        )
        row = await cursor.fetchone()
        if row:
            entity_ids.append(str(row[0]))

    if not entity_ids:
        # Try multi-word match
        cursor = await db.execute(
            "SELECT id FROM entities WHERE name LIKE ? COLLATE NOCASE",
            (f"%{query}%",),
        )
        rows = await cursor.fetchall()
        entity_ids = [str(r[0]) for r in rows]

    if not entity_ids:
        return []

    # Expand through graph (1-hop neighbors)
    all_entity_ids = set(entity_ids)
    for eid in entity_ids:
        # Get entity name for traversal
        cursor = await db.execute("SELECT name FROM entities WHERE id = ?", (eid,))
        row = await cursor.fetchone()
        if row:
            neighbors = await graph_backend.traverse(str(row[0]), depth=1)
            all_entity_ids.update(neighbors)

    if not all_entity_ids:
        return []

    # Find claims linked to these entities
    placeholders = ", ".join("?" for _ in all_entity_ids)
    memory_type_filter = "AND c.memory_type = ?" if memory_type is not None else ""
    graph_params: list[object] = [*all_entity_ids]
    if memory_type is not None:
        graph_params.append(memory_type)
    graph_params.append(limit)

    cursor = await db.execute(
        f"""
        SELECT DISTINCT c.*
        FROM claims c
        JOIN claim_entities ce ON c.id = ce.claim_id
        WHERE ce.entity_id IN ({placeholders})
          AND c.superseded_at IS NULL
          {memory_type_filter}
        LIMIT ?
        """,
        graph_params,
    )
    rows = await cursor.fetchall()

    results: list[SearchResult] = []
    for i, row in enumerate(rows):
        claim = row_to_claim(row)
        # Score by position (graph doesn't have a natural similarity score)
        score = 1.0 / (1 + i)
        results.append(
            SearchResult(
                claim=claim,
                score=score,
                method="graph",
            )
        )

    return results


# ── RRF merge ─────────────────────────────────────────────────────────────


def _rrf_merge(
    result_lists: list[list[SearchResult]],
    weights: list[float],
    k: int = 60,
    limit: int = 10,
) -> list[SearchResult]:
    """Weighted Reciprocal Rank Fusion.

    RRF formula: score(d) = Σ weight_i / (k + rank_i + 1)

    The constant k=60 is from the original RRF paper (Cormack et al., 2009).
    It dampens the effect of high-ranked documents in any single list.
    """
    scores: dict[str, float] = {}
    items: dict[str, SearchResult] = {}

    for results, weight in zip(result_lists, weights, strict=False):
        for rank, item in enumerate(results):
            cid = item.claim.id
            scores[cid] = scores.get(cid, 0.0) + weight / (k + rank + 1)
            if cid not in items:
                items[cid] = item

    sorted_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

    merged: list[SearchResult] = []
    for cid in sorted_ids[:limit]:
        result = items[cid]
        merged.append(
            SearchResult(
                claim=result.claim,
                score=scores[cid],
                relevance=result.relevance,
                method="hybrid",
            )
        )

    return merged


# ── Helpers ───────────────────────────────────────────────────────────────


async def _empty_results() -> list[SearchResult]:
    """Return empty results (for disabled channels)."""
    return []


async def load_claim_entities(claim_id: str, db: aiosqlite.Connection) -> list[str]:
    """Load entity names for a claim from claim_entities + entities tables."""
    cursor = await db.execute(
        """SELECT e.name FROM claim_entities ce
           JOIN entities e ON ce.entity_id = e.id
           WHERE ce.claim_id = ?""",
        (claim_id,),
    )
    rows = await cursor.fetchall()
    return [str(row[0]) for row in rows]


def row_to_claim(row: aiosqlite.Row) -> Claim:
    """Convert a database row to a Claim model."""
    metadata_raw = row["metadata"]
    metadata: dict[str, object] = {}
    if metadata_raw:
        metadata = json.loads(str(metadata_raw))

    # sqlite3.Row: `in` checks values not keys — must use row.keys() for column existence
    keys = row.keys()  # noqa: SIM118
    steps_raw = row["steps"] if "steps" in keys else None  # noqa: SIM401
    steps: list[str] | None = json.loads(str(steps_raw)) if steps_raw else None

    source_ep_raw = row["source_episode_ids"] if "source_episode_ids" in keys else None  # noqa: SIM401
    source_episode_ids: list[str] = json.loads(str(source_ep_raw)) if source_ep_raw else []

    last_used_raw = row["last_used"] if "last_used" in keys else None  # noqa: SIM401

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
        created_at=datetime.fromisoformat(row["created_at"])
        if row["created_at"]
        else datetime.now(UTC),
        superseded_at=datetime.fromisoformat(row["superseded_at"])
        if row["superseded_at"]
        else None,
        superseded_by=row["superseded_by"],
        metadata=metadata,
        memory_type=MemoryType(row["memory_type"])
        if "memory_type" in keys and row["memory_type"]
        else MemoryType.SEMANTIC,  # noqa: SIM401
        trigger=row["trigger"] if "trigger" in keys else None,  # noqa: SIM401
        steps=steps,
        termination_condition=row["termination_condition"]  # noqa: SIM401
        if "termination_condition" in keys
        else None,
        success_rate=float(row["success_rate"])
        if "success_rate" in keys and row["success_rate"] is not None
        else 0.5,
        usage_count=int(row["usage_count"])
        if "usage_count" in keys and row["usage_count"] is not None
        else 0,
        last_used=datetime.fromisoformat(str(last_used_raw)) if last_used_raw else None,
        source_episode_ids=source_episode_ids,
    )
