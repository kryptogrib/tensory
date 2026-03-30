"""Hybrid search with parallel retrieval and Reciprocal Rank Fusion.

Three search channels run in parallel (inspired by Hindsight TEMPR):
1. **FTS5** — keyword/full-text search
2. **sqlite-vec** — vector cosine similarity
3. **Graph** — entity co-occurrence traversal

Results are merged via weighted RRF (Reciprocal Rank Fusion), then
diversified via MMR (Maximal Marginal Relevance) reranking to prevent
entity crowding. Falls back to entity-cap filtering when embeddings
are unavailable.

Optional Fisher-Rao reranking (inspired by SuperLocalMemory V3, arXiv:2603.14588)
re-scores top candidates using information-geometric similarity when cosine
scores are too close to discriminate.

Any channel that fails returns empty results (graceful degradation).

References:
- RRF formula: plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf
- Hybrid search with sqlite-vec + FTS5: alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/
- Parallel TEMPR retrieval: github.com/vectorize-io/hindsight
- Fisher-Rao metric: SuperLocalMemory V3 (arXiv:2603.14588)
- MMR: Carbonell & Goldstein, 1998 (SIGIR)
- MMR in Graphiti/Zep: graphiti_core/search/search_utils.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import struct
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

    # Over-fetch 3x for MMR/diversity filtering headroom
    merged = _rrf_merge(
        [fts_r, vec_r, graph_r],
        weights=[w.get("fts", 0.3), w.get("vector", 0.4), w.get("graph", 0.3)],
        limit=limit * 3,
    )

    # MMR reranking for diversity (falls back to entity cap if no embeddings)
    return await _mmr_rerank(
        merged, query_embedding=embedding, db=db, limit=limit,
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


# ── MMR reranking ────────────────────────────────────────────────────────


def _cosine_sim(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors (pure Python, no numpy).

    OpenAI embeddings are pre-normalized so dot product ≈ cosine.
    We add norm division for safety with non-normalized vectors.
    """
    dot = sum(ai * bi for ai, bi in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(ai * ai for ai in a))
    norm_b = math.sqrt(sum(bi * bi for bi in b))
    if norm_a < 1e-10 or norm_b < 1e-10:
        return 0.0
    return dot / (norm_a * norm_b)


async def _load_candidate_embeddings(
    claim_ids: list[str],
    db: aiosqlite.Connection,
) -> dict[str, list[float]]:
    """Batch-load embeddings for candidate claims from sqlite-vec.

    Returns dict mapping claim_id → embedding vector.
    Claims without stored embeddings are omitted.
    """
    if not claim_ids:
        return {}

    result: dict[str, list[float]] = {}
    for cid in claim_ids:
        try:
            cursor = await db.execute(
                "SELECT embedding FROM claim_embeddings WHERE claim_id = ?",
                (cid,),
            )
            row = await cursor.fetchone()
            if row and row[0] is not None:
                raw = row[0]
                if isinstance(raw, bytes):
                    # sqlite-vec stores as binary float32
                    n = len(raw) // 4
                    result[cid] = list(struct.unpack(f"<{n}f", raw))
                elif isinstance(raw, str):
                    result[cid] = json.loads(raw)
        except Exception:
            continue  # graceful degradation

    return result


async def _mmr_rerank(
    results: list[SearchResult],
    *,
    query_embedding: list[float] | None,
    db: aiosqlite.Connection,
    limit: int = 10,
    mmr_lambda: float = 0.7,
) -> list[SearchResult]:
    """Maximal Marginal Relevance reranking (Carbonell & Goldstein, 1998).

    Balances relevance to query with diversity among selected results.
    Falls back to entity-cap filter when embeddings are unavailable.

    Formula: MMR(d) = λ·sim(d, query) - (1-λ)·max(sim(d, selected))

    Args:
        results: Ranked candidates from RRF merge (over-fetched).
        query_embedding: Query vector (None → fallback to entity cap).
        db: Database connection for loading claim embeddings.
        limit: Final number of results to return.
        mmr_lambda: Balance parameter. 1.0=pure relevance, 0.0=pure diversity.
    """
    if len(results) <= limit:
        return results

    # No query embedding → fall back to entity-cap diversity
    if not query_embedding:
        return await _entity_diverse_filter(results, db, limit=limit)

    # Load embeddings for all candidates
    candidate_ids = [r.claim.id for r in results]
    embeddings = await _load_candidate_embeddings(candidate_ids, db)

    # Not enough embeddings → fall back to entity cap
    if len(embeddings) < 2:
        return await _entity_diverse_filter(results, db, limit=limit)

    # Separate candidates with/without embeddings
    with_emb: list[tuple[SearchResult, list[float]]] = []
    without_emb: list[SearchResult] = []
    for r in results:
        emb = embeddings.get(r.claim.id)
        if emb is not None:
            with_emb.append((r, emb))
        else:
            without_emb.append(r)

    # Greedy MMR selection
    selected: list[SearchResult] = []
    selected_embs: list[list[float]] = []
    remaining = list(with_emb)

    while len(selected) < limit and remaining:
        best_score = -float("inf")
        best_idx = -1

        for i, (_result, emb) in enumerate(remaining):
            # Relevance: cosine similarity to query
            relevance = _cosine_sim(query_embedding, emb)

            # Redundancy: max similarity to any already-selected
            redundancy = 0.0
            if selected_embs:
                redundancy = max(
                    _cosine_sim(emb, s_emb) for s_emb in selected_embs
                )

            # MMR score
            score = mmr_lambda * relevance - (1 - mmr_lambda) * redundancy

            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx < 0:
            break

        chosen_result, chosen_emb = remaining.pop(best_idx)
        selected.append(chosen_result)
        selected_embs.append(chosen_emb)

    # Fill remaining slots with non-embedded candidates (if any)
    if len(selected) < limit and without_emb:
        selected.extend(without_emb[: limit - len(selected)])

    return selected


async def _entity_diverse_filter(
    results: list[SearchResult],
    db: aiosqlite.Connection,
    *,
    limit: int = 10,
    max_per_entity: int = 3,
) -> list[SearchResult]:
    """Fallback: entity-cap diversity filter (Google-style).

    Used when embeddings are unavailable for MMR reranking.
    Limits claims per entity to prevent entity crowding.
    """
    if len(results) <= limit:
        return results

    claim_entities: dict[str, list[str]] = {}
    for r in results:
        entities = await load_claim_entities(r.claim.id, db)
        claim_entities[r.claim.id] = [e.lower() for e in entities]

    entity_counts: dict[str, int] = {}
    diverse: list[SearchResult] = []

    for r in results:
        if len(diverse) >= limit:
            break

        entities = claim_entities.get(r.claim.id, [])

        if entities and all(
            entity_counts.get(e, 0) >= max_per_entity for e in entities
        ):
            continue

        diverse.append(r)
        for e in entities:
            entity_counts[e] = entity_counts.get(e, 0) + 1

    return diverse


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


# ── Fisher-Rao reranking (SuperLocalMemory V3) ─────────────────────────────

# Variance heuristic constants (from SLM V3, Section 4.2)
VARIANCE_FLOOR: float = 0.05  # high-confidence dimensions
VARIANCE_CEIL: float = 2.0  # low-confidence dimensions


def _estimate_variance(embedding: list[float]) -> list[float]:
    """Estimate per-dimension variance using SLM V3 signal-magnitude heuristic.

    Dimensions with large absolute values in the L2-normalized embedding
    get low variance (model is "confident"), dimensions near zero get
    high variance (model is "uncertain").  This lets the Fisher metric
    down-weight noisy dimensions automatically.

    Reference: SuperLocalMemory V3 (arXiv:2603.14588), Section 4.2.

    TODO(contributor): This is the core design decision for Fisher quality.
    The FLOOR/CEIL constants and the linear interpolation below come from
    SLM V3 defaults.  Alternative approaches:
      - Corpus-level variance (compute σ² across all stored embeddings)
      - Exponential mapping instead of linear
      - Per-context variance (different topics → different noise profiles)
    """
    norm = math.sqrt(sum(x * x for x in embedding)) or 1e-12
    normalized = [x / norm for x in embedding]
    max_abs = max(abs(x) for x in normalized) or 1e-12

    return [VARIANCE_CEIL - (VARIANCE_CEIL - VARIANCE_FLOOR) * abs(x) / max_abs for x in normalized]


def _fisher_distance(a: list[float], b: list[float]) -> float:
    """Compute approximate Fisher-Rao distance between two embeddings.

    Maps each embedding to a diagonal Gaussian N(μ, diag(σ²)) using
    the signal-magnitude heuristic, then computes the closed-form
    Fisher-Rao distance for diagonal Gaussians.

    For numerical stability, uses Taylor expansion of arccosh for
    small delta values.
    """
    var_a = _estimate_variance(a)
    var_b = _estimate_variance(b)

    total = 0.0
    for mu_a, mu_b, s_a, s_b in zip(a, b, var_a, var_b, strict=False):
        denom = 4.0 * s_a * s_b
        if denom < 1e-15:
            continue
        delta = ((mu_a - mu_b) ** 2 + 2.0 * (s_a - s_b) ** 2) / denom

        # arccosh(1 + delta) — Taylor expansion for small delta
        if delta < 1e-6:
            arc = math.sqrt(2.0 * delta) * (1.0 - delta / 12.0)
        else:
            arc = math.log1p(delta + math.sqrt(delta * (delta + 2.0)))
        total += arc * arc

    return math.sqrt(total)


def _fisher_similarity(a: list[float], b: list[float], temperature: float = 15.0) -> float:
    """Convert Fisher-Rao distance to a similarity score in [0, 1].

    Uses exponential kernel: sim = exp(-distance / temperature).
    Temperature=15.0 is the SLM V3 default.
    """
    dist = _fisher_distance(a, b)
    return math.exp(-dist / temperature)


def should_rerank(
    results: list[SearchResult],
    min_candidates: int = 3,
    threshold: float = 0.05,
) -> bool:
    """Decide whether Fisher reranking would help.

    Returns True when the top cosine scores are too close together —
    meaning cosine similarity cannot discriminate between candidates.
    Fisher's variance-weighted metric may separate them better.

    Args:
        results: Search results sorted by score (descending).
        min_candidates: Minimum results needed for reranking to make sense.
        threshold: Maximum score spread that triggers reranking.
    """
    if len(results) < min_candidates:
        return False
    spread = results[0].score - results[min_candidates - 1].score
    return spread < threshold


async def fisher_rerank(
    query_embedding: list[float],
    results: list[SearchResult],
    db: aiosqlite.Connection,
    *,
    top_k: int = 20,
) -> list[SearchResult]:
    """Re-rank search results using Fisher-Rao similarity.

    Loads stored embeddings for the top-k candidates, computes Fisher
    similarity against the query embedding, and re-sorts.

    Results beyond top_k keep their original order (appended at the end).

    Args:
        query_embedding: The query vector.
        results: RRF-merged results from hybrid_search.
        db: Database connection (to load claim embeddings).
        top_k: How many top results to rerank.
    """
    if not results or not query_embedding:
        return results

    to_rerank = results[:top_k]
    tail = results[top_k:]

    # Load embeddings for candidates
    reranked: list[SearchResult] = []
    for result in to_rerank:
        cursor = await db.execute(
            "SELECT embedding FROM claim_embeddings WHERE claim_id = ?",
            (result.claim.id,),
        )
        row = await cursor.fetchone()
        if row is None:
            # No embedding stored — keep original score
            reranked.append(result)
            continue

        raw = row[0]
        if isinstance(raw, bytes):
            # sqlite-vec stores embeddings as raw float32 bytes
            n_floats = len(raw) // 4
            claim_embedding: list[float] = list(struct.unpack(f"<{n_floats}f", raw))
        else:
            claim_embedding = json.loads(str(raw))
        fisher_score = _fisher_similarity(query_embedding, claim_embedding)

        reranked.append(
            SearchResult(
                claim=result.claim,
                score=fisher_score,
                relevance=result.relevance,
                method="fisher",
            )
        )

    # Sort by Fisher score (descending)
    reranked.sort(key=lambda r: r.score, reverse=True)
    return reranked + tail
