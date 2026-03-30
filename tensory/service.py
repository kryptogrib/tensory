"""Read-only dashboard query layer for tensory.

Wraps the Tensory store to provide structured, paginated, and filtered
read access for dashboard UIs. All methods are read-only — no mutations.

Key patterns:
- Direct SQL queries on store._db for reads (avoiding unnecessary abstractions)
- Delegates to store._graph for graph operations
- Delegates to store.search() for hybrid search
- Returns Pydantic v2 models for type safety and serialization
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel

from tensory.models import (
    Claim,
    ClaimType,
    Collision,
    Context,
    EntityRelation,
    Episode,
    SearchResult,
)
from tensory.store import Tensory

logger = logging.getLogger(__name__)

# ── Allowed sort columns (whitelist to prevent SQL injection) ────────────

_ALLOWED_SORT_COLUMNS = {"created_at", "salience", "relevance", "type"}

# ── Response models ──────────────────────────────────────────────────────


class EntityNode(BaseModel):
    """An entity node with aggregated metadata."""

    id: str
    name: str
    type: str | None
    mention_count: int
    first_seen: datetime


class EdgeData(BaseModel):
    """A directed edge between two entities."""

    from_entity: str
    to_entity: str
    rel_type: str
    fact: str
    confidence: float
    created_at: datetime
    expired_at: datetime | None = None


class SubGraph(BaseModel):
    """A subgraph of nodes and edges reachable from a seed entity."""

    nodes: list[EntityNode]
    edges: list[EdgeData]


class DashboardStats(BaseModel):
    """Aggregated statistics for the dashboard HUD."""

    counts: dict[str, int]
    claims_by_type: dict[str, int]
    avg_salience: float
    recent_claims: list[Claim]
    hot_entities: list[EntityNode]


class PaginatedClaims(BaseModel):
    """Paginated list of claims with total count."""

    items: list[Claim]
    total: int
    offset: int
    limit: int


class ClaimDetail(BaseModel):
    """Full detail view of a single claim."""

    claim: Claim
    episode: Episode | None
    collisions: list[Collision]
    waypoints: list[str]
    related_entities: list[EntityRelation]


class TimelineEntry(BaseModel):
    """A claim in an entity's timeline, enriched with supersede chain info."""

    claim: Claim
    supersedes: str | None = None  # ID of claim THIS claim replaced


class HistogramBucket(BaseModel):
    """One bar in the event histogram."""

    date: str  # ISO date YYYY-MM-DD
    count: int


class GraphSnapshot(BaseModel):
    """State of the knowledge graph at a point in time."""

    active_nodes: list[EntityNode]
    ghost_nodes: list[EntityNode]
    edges: list[EdgeData]
    stats: dict[str, int]


class TimelineRange(BaseModel):
    """Min/max dates and event histogram for the timeline slider."""

    min_date: str  # ISO datetime
    max_date: str  # ISO datetime
    event_histogram: list[HistogramBucket]


# ── Helpers ──────────────────────────────────────────────────────────────


def _parse_datetime(value: object) -> datetime | None:
    """Parse a datetime from a SQLite string or return None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value)
    # Try ISO format first, then common SQLite format
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    # Fallback: try fromisoformat (handles various formats)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _parse_json_dict(value: object) -> dict[str, object]:
    """Parse a JSON string into a dict, returning empty dict if invalid."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, dict):
            return cast(dict[str, object], parsed)
    except (json.JSONDecodeError, TypeError):
        pass
    return {}


def _parse_json_list(value: object) -> list[str]:
    """Parse a JSON string into a list of strings, returning empty list if invalid."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in cast(list[object], value)]
    try:
        parsed: object = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(item) for item in cast(list[object], parsed)]
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _parse_json_list_optional(value: object) -> list[str] | None:
    """Parse a JSON string into a list of strings, returning None if null/invalid."""
    if value is None:
        return None
    if isinstance(value, list):
        return [str(item) for item in cast(list[object], value)]
    try:
        parsed: object = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(item) for item in cast(list[object], parsed)]
    except (json.JSONDecodeError, TypeError):
        pass
    return None


async def _row_to_claim(
    row: dict[str, Any],
    entity_names: list[str] | None = None,
) -> Claim:
    """Convert a SQLite row dict to a Claim model."""
    return Claim(
        id=str(row.get("id", "")),
        text=str(row.get("text", "")),
        type=ClaimType(str(row.get("type", "fact"))),
        confidence=float(row.get("confidence", 1.0)),
        relevance=float(row.get("relevance", 1.0)),
        salience=float(row.get("salience", 1.0)),
        decay_rate=float(row["decay_rate"]) if row.get("decay_rate") is not None else None,
        episode_id=str(row["episode_id"]) if row.get("episode_id") else None,
        context_id=str(row["context_id"]) if row.get("context_id") else None,
        valid_from=_parse_datetime(row.get("valid_from")),
        valid_to=_parse_datetime(row.get("valid_to")),
        created_at=_parse_datetime(row.get("created_at")) or datetime.now(UTC),
        superseded_at=_parse_datetime(row.get("superseded_at")),
        superseded_by=str(row["superseded_by"]) if row.get("superseded_by") else None,
        metadata=_parse_json_dict(row.get("metadata")),
        memory_type=row.get("memory_type", "semantic"),
        trigger=str(row["trigger"]) if row.get("trigger") else None,
        steps=_parse_json_list_optional(row.get("steps")),
        termination_condition=(
            str(row["termination_condition"]) if row.get("termination_condition") else None
        ),
        success_rate=float(row.get("success_rate", 0.5)),
        usage_count=int(row.get("usage_count", 0)),
        last_used=_parse_datetime(row.get("last_used")),
        source_episode_ids=_parse_json_list(row.get("source_episode_ids")),
        entities=entity_names or [],
        embedding=None,
    )


async def _fetch_claim_entities(
    db: Any,
    claim_id: str,
) -> list[str]:
    """Fetch entity names for a claim from claim_entities + entities tables."""
    cursor = await db.execute(
        """SELECT e.name FROM claim_entities ce
           JOIN entities e ON ce.entity_id = e.id
           WHERE ce.claim_id = ?""",
        (claim_id,),
    )
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


def _parse_entity_node(raw: dict[str, object]) -> EntityNode:
    """Convert a graph backend entity dict to an EntityNode model."""
    first_seen = _parse_datetime(raw.get("first_seen")) or datetime.now(UTC)
    return EntityNode(
        id=str(raw.get("id", "")),
        name=str(raw.get("name", "")),
        type=str(raw["type"]) if raw.get("type") is not None else None,
        mention_count=int(str(raw.get("mention_count", 1))),
        first_seen=first_seen,
    )


def _parse_edge_data(raw: dict[str, object]) -> EdgeData:
    """Convert a graph backend edge dict to an EdgeData model."""
    created_at = _parse_datetime(raw.get("created_at")) or datetime.now(UTC)
    expired_at = _parse_datetime(raw.get("expired_at"))
    return EdgeData(
        from_entity=str(raw.get("from_entity", "")),
        to_entity=str(raw.get("to_entity", "")),
        rel_type=str(raw.get("rel_type", "")),
        fact=str(raw.get("fact", "")),
        confidence=float(str(raw.get("confidence", 0.8))),
        created_at=created_at,
        expired_at=expired_at,
    )


# ── Service class ────────────────────────────────────────────────────────


class TensoryService:
    """Read-only query layer for the tensory dashboard.

    Wraps a Tensory store instance and provides structured queries
    with pagination, filtering, and Pydantic response models.
    All methods are read-only — no data mutations.
    """

    def __init__(self, store: Tensory) -> None:
        self.store = store

    async def get_stats(self) -> DashboardStats:
        """Aggregate dashboard statistics."""
        raw_stats = await self.store.stats()
        counts: dict[str, int] = raw_stats["counts"]
        claims_by_type: dict[str, int] = raw_stats["claims_by_type"]
        avg_salience: float = raw_stats["avg_salience"]

        db = self.store.db

        # Recent claims (newest 5)
        cursor = await db.execute("SELECT * FROM claims ORDER BY created_at DESC LIMIT 5")
        claim_rows = await cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []

        recent_claims: list[Claim] = []
        for row in claim_rows:
            row_dict = dict(zip(col_names, row, strict=False))
            entities = await _fetch_claim_entities(db, str(row_dict["id"]))
            claim = await _row_to_claim(row_dict, entities)
            recent_claims.append(claim)

        # Hot entities (top 5 by mention count)
        entity_dicts = await self.store.graph.list_entities(limit=5, min_mentions=1)
        hot_entities = [_parse_entity_node(d) for d in entity_dicts]

        return DashboardStats(
            counts=counts,
            claims_by_type=claims_by_type,
            avg_salience=avg_salience,
            recent_claims=recent_claims,
            hot_entities=hot_entities,
        )

    async def list_claims(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        type_filter: str | None = None,
        salience_min: float | None = None,
        salience_max: float | None = None,
        entity_filter: str | None = None,
        context_id: str | None = None,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> PaginatedClaims:
        """List claims with pagination and optional filters."""
        if sort_by not in _ALLOWED_SORT_COLUMNS:
            msg = f"sort_by must be one of {_ALLOWED_SORT_COLUMNS}, got {sort_by!r}"
            raise ValueError(msg)

        sort_direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        db = self.store.db

        # Build WHERE clauses
        conditions: list[str] = []
        params: list[object] = []

        if type_filter is not None:
            conditions.append("c.type = ?")
            params.append(type_filter)

        if salience_min is not None:
            conditions.append("c.salience >= ?")
            params.append(salience_min)

        if salience_max is not None:
            conditions.append("c.salience <= ?")
            params.append(salience_max)

        if context_id is not None:
            conditions.append("c.context_id = ?")
            params.append(context_id)

        # Entity filter requires a JOIN
        join_clause = ""
        if entity_filter is not None:
            join_clause = (
                " JOIN claim_entities ce ON c.id = ce.claim_id"
                " JOIN entities e ON ce.entity_id = e.id"
            )
            conditions.append("e.name = ?")
            params.append(entity_filter)

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        # Count total
        count_sql = f"SELECT COUNT(DISTINCT c.id) FROM claims c{join_clause}{where_clause}"
        cursor = await db.execute(count_sql, params)
        count_row = await cursor.fetchone()
        total = count_row[0] if count_row else 0

        # Fetch page
        # sort_by is validated against whitelist above, safe for interpolation
        select_sql = (
            f"SELECT DISTINCT c.* FROM claims c{join_clause}{where_clause}"
            f" ORDER BY c.{sort_by} {sort_direction}"
            f" LIMIT ? OFFSET ?"
        )
        cursor = await db.execute(select_sql, [*params, limit, offset])
        rows = await cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []

        items: list[Claim] = []
        for row in rows:
            row_dict = dict(zip(col_names, row, strict=False))
            entities = await _fetch_claim_entities(db, str(row_dict["id"]))
            claim = await _row_to_claim(row_dict, entities)
            items.append(claim)

        return PaginatedClaims(items=items, total=total, offset=offset, limit=limit)

    async def get_claim(self, claim_id: str) -> ClaimDetail:
        """Fetch full detail for a single claim."""
        db = self.store.db

        # Fetch claim
        cursor = await db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,))
        row = await cursor.fetchone()
        if row is None:
            msg = f"Claim {claim_id!r} not found"
            raise ValueError(msg)

        col_names = [desc[0] for desc in cursor.description] if cursor.description else []
        row_dict = dict(zip(col_names, row, strict=False))
        entities = await _fetch_claim_entities(db, claim_id)
        claim = await _row_to_claim(row_dict, entities)

        # Fetch episode
        episode: Episode | None = None
        if claim.episode_id:
            ep_cursor = await db.execute("SELECT * FROM episodes WHERE id = ?", (claim.episode_id,))
            ep_row = await ep_cursor.fetchone()
            if ep_row is not None:
                ep_cols = [d[0] for d in ep_cursor.description] if ep_cursor.description else []
                ep_dict = dict(zip(ep_cols, ep_row, strict=False))
                episode = Episode(
                    id=str(ep_dict["id"]),
                    raw_text=str(ep_dict["raw_text"]),
                    source=str(ep_dict.get("source", "")),
                    source_url=str(ep_dict["source_url"]) if ep_dict.get("source_url") else None,
                    fetched_at=_parse_datetime(ep_dict.get("fetched_at")) or datetime.now(UTC),
                )

        # Fetch waypoints
        wp_cursor = await db.execute(
            "SELECT dst_claim FROM waypoints WHERE src_claim = ?", (claim_id,)
        )
        wp_rows = await wp_cursor.fetchall()
        waypoints = [str(r[0]) for r in wp_rows]

        # Fetch related entity relations via claim's entities
        related_entities: list[EntityRelation] = []
        if entities:
            # Get entity IDs for this claim
            eid_cursor = await db.execute(
                "SELECT entity_id FROM claim_entities WHERE claim_id = ?", (claim_id,)
            )
            eid_rows = await eid_cursor.fetchall()
            entity_ids = [str(r[0]) for r in eid_rows]

            if entity_ids:
                placeholders = ", ".join("?" for _ in entity_ids)
                # DISTINCT to avoid duplicates when both from/to are in entity_ids
                # JOIN entities to resolve UUIDs → human-readable names
                rel_cursor = await db.execute(
                    f"""SELECT DISTINCT er.id, e_from.name AS from_name,
                               e_to.name AS to_name, er.rel_type, er.fact,
                               er.episode_id, er.confidence, er.created_at, er.expired_at
                        FROM entity_relations er
                        JOIN entities e_from ON er.from_entity = e_from.id
                        JOIN entities e_to ON er.to_entity = e_to.id
                        WHERE er.from_entity IN ({placeholders})
                           OR er.to_entity IN ({placeholders})""",
                    [*entity_ids, *entity_ids],
                )
                rel_rows = await rel_cursor.fetchall()
                rel_cols = [d[0] for d in rel_cursor.description] if rel_cursor.description else []
                # Deduplicate by content (from+to+rel_type), not by row ID.
                # Multiple ingests can create duplicate relations with different IDs.
                seen_keys: set[str] = set()
                for rr in rel_rows:
                    rd = dict(zip(rel_cols, rr, strict=False))
                    dedup_key = f"{rd['from_name']}|{rd['to_name']}|{rd['rel_type']}"
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    related_entities.append(
                        EntityRelation(
                            from_entity=str(rd["from_name"]),
                            to_entity=str(rd["to_name"]),
                            rel_type=str(rd["rel_type"]),
                            fact=str(rd.get("fact", "")),
                            episode_id=str(rd["episode_id"]) if rd.get("episode_id") else None,
                            confidence=float(rd.get("confidence", 0.8)),
                            created_at=_parse_datetime(rd.get("created_at")) or datetime.now(UTC),
                            expired_at=_parse_datetime(rd.get("expired_at")),
                        )
                    )

        # Collisions are not persisted — computed on-the-fly at ingest time
        collisions: list[Collision] = []

        return ClaimDetail(
            claim=claim,
            episode=episode,
            collisions=collisions,
            waypoints=waypoints,
            related_entities=related_entities,
        )

    async def search_claims(
        self,
        query: str,
        *,
        context_id: str | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Search claims via hybrid search (FTS + vector + graph)."""
        context: Context | None = None
        if context_id is not None:
            db = self.store.db
            cursor = await db.execute("SELECT * FROM contexts WHERE id = ?", (context_id,))
            row = await cursor.fetchone()
            if row is not None:
                col_names = [d[0] for d in cursor.description] if cursor.description else []
                ctx_dict = dict(zip(col_names, row, strict=False))
                context = Context(
                    id=str(ctx_dict["id"]),
                    goal=str(ctx_dict["goal"]),
                    description=str(ctx_dict.get("description", "")),
                    domain=str(ctx_dict.get("domain", "general")),
                    user_id=str(ctx_dict["user_id"]) if ctx_dict.get("user_id") else None,
                    active=bool(ctx_dict.get("active", True)),
                    created_at=_parse_datetime(ctx_dict.get("created_at")) or datetime.now(UTC),
                )

        return await self.store.search(query, context=context, limit=limit)

    async def get_graph_entities(
        self,
        *,
        limit: int = 100,
        min_mentions: int = 1,
    ) -> list[EntityNode]:
        """List graph entities ordered by mention count."""
        raw = await self.store.graph.list_entities(limit=limit, min_mentions=min_mentions)
        return [_parse_entity_node(d) for d in raw]

    async def get_graph_edges(
        self,
        *,
        entity_filter: str | None = None,
    ) -> list[EdgeData]:
        """List active graph edges, optionally filtered by entity."""
        raw = await self.store.graph.list_edges(entity_filter=entity_filter)
        return [_parse_edge_data(d) for d in raw]

    async def get_entity_subgraph(
        self,
        entity_name: str,
        *,
        depth: int = 2,
    ) -> SubGraph:
        """Get a subgraph of nodes and edges reachable from an entity."""
        raw = await self.store.graph.subgraph(entity_name, depth=depth)
        nodes_raw: list[dict[str, object]] = raw.get("nodes", [])
        edges_raw: list[dict[str, object]] = raw.get("edges", [])
        return SubGraph(
            nodes=[_parse_entity_node(n) for n in nodes_raw],
            edges=[_parse_edge_data(e) for e in edges_raw],
        )

    async def get_entity_claims(self, entity_name: str) -> list[Claim]:
        """Get all claims associated with a specific entity."""
        db = self.store.db
        cursor = await db.execute(
            """SELECT c.* FROM claims c
               JOIN claim_entities ce ON c.id = ce.claim_id
               JOIN entities e ON ce.entity_id = e.id
               WHERE e.name = ?""",
            (entity_name,),
        )
        rows = await cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description] if cursor.description else []

        claims: list[Claim] = []
        for row in rows:
            row_dict = dict(zip(col_names, row, strict=False))
            entities = await _fetch_claim_entities(db, str(row_dict["id"]))
            claim = await _row_to_claim(row_dict, entities)
            claims.append(claim)
        return claims
