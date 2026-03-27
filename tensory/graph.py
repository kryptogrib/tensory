"""Graph backend abstraction for tensory.

Defines the GraphBackend Protocol and provides SQLiteGraphBackend as the
zero-dependency default. Uses recursive CTEs for graph traversal.

References:
- GraphBackend pattern: github.com/getzep/graphiti (driver/ directory)
- Recursive CTEs: sqlite.org/lang_with.html
"""

from __future__ import annotations

import uuid
from typing import Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite


@runtime_checkable
class GraphBackend(Protocol):
    """Abstract graph operations used by tensory.

    Default implementation: SQLiteGraphBackend (recursive CTEs).
    Enterprise option: Neo4jBackend (Phase 5+).
    """

    async def add_entity(self, name: str, entity_type: str | None = None) -> str:
        """Add or update an entity. Returns entity ID."""
        ...

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, object] | None = None,
    ) -> None:
        """Create a directed edge between two entities."""
        ...

    async def traverse(
        self,
        entity_name: str,
        depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find entity IDs reachable within `depth` hops."""
        ...

    async def get_shared_entities(
        self, claim_id: str, limit: int = 50
    ) -> list[str]:
        """Get entity IDs shared with other claims (for collision scoring)."""
        ...

    async def find_path(
        self, from_entity: str, to_entity: str
    ) -> list[str]:
        """Find shortest path between two entities. Returns entity IDs."""
        ...

    async def close(self) -> None:
        """Release resources."""
        ...


class SQLiteGraphBackend:
    """Graph backend using SQLite recursive CTEs.

    Sufficient for <100K claims. Zero external dependencies.
    All graph data lives in the same SQLite file as everything else.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add_entity(self, name: str, entity_type: str | None = None) -> str:
        """Insert entity or increment mention_count if it exists."""
        # Normalize entity name for consistent lookups
        normalized = name.strip()

        cursor = await self._db.execute(
            "SELECT id FROM entities WHERE name = ?", (normalized,)
        )
        row = await cursor.fetchone()

        if row is not None:
            entity_id: str = row[0]
            await self._db.execute(
                "UPDATE entities SET mention_count = mention_count + 1 WHERE id = ?",
                (entity_id,),
            )
            return entity_id

        entity_id = uuid.uuid4().hex
        await self._db.execute(
            "INSERT INTO entities (id, name, type) VALUES (?, ?, ?)",
            (entity_id, normalized, entity_type),
        )
        # Flush so FK references in entity_relations resolve immediately
        await self._db.commit()
        return entity_id

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, object] | None = None,
    ) -> None:
        """Create a relation between two entities."""
        edge_id = uuid.uuid4().hex
        fact = str(properties.get("fact", "")) if properties else ""
        raw_ep = properties.get("episode_id") if properties else None
        episode_id = str(raw_ep) if raw_ep else None
        raw_conf = properties.get("confidence", 0.8) if properties else 0.8
        confidence = float(str(raw_conf))

        await self._db.execute(
            """INSERT INTO entity_relations
               (id, from_entity, to_entity, rel_type, fact, episode_id, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (edge_id, from_id, to_id, rel_type, fact, episode_id, confidence),
        )

    async def traverse(
        self,
        entity_name: str,
        depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """BFS traversal via recursive CTE through claim co-occurrence.

        Finds entities connected within `depth` hops through shared claims.
        """
        edge_filter = ""
        params: list[object] = [entity_name, depth]

        if edge_types:
            placeholders = ", ".join("?" for _ in edge_types)
            edge_filter = f"AND er.rel_type IN ({placeholders})"
            # params order: entity_name (seed), depth, then edge_types (in WHERE)
            params = [entity_name, depth, *edge_types]

        # Traverse through entity_relations (explicit LLM-extracted relations)
        sql = f"""
        WITH RECURSIVE reachable(entity_id, lvl) AS (
            -- Seed: find the starting entity
            SELECT id, 0 FROM entities WHERE name = ?

            UNION ALL

            -- Expand via entity_relations
            SELECT
                CASE
                    WHEN er.from_entity = r.entity_id THEN er.to_entity
                    ELSE er.from_entity
                END,
                r.lvl + 1
            FROM entity_relations er
            JOIN reachable r ON (
                er.from_entity = r.entity_id OR er.to_entity = r.entity_id
            )
            WHERE r.lvl < ? {edge_filter}
              AND er.expired_at IS NULL
        )
        SELECT DISTINCT entity_id FROM reachable WHERE lvl > 0
        """

        cursor = await self._db.execute(sql, params)

        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def get_shared_entities(
        self, claim_id: str, limit: int = 50
    ) -> list[str]:
        """Find entities shared between this claim and other claims."""
        cursor = await self._db.execute(
            """
            SELECT DISTINCT ce2.entity_id
            FROM claim_entities ce1
            JOIN claim_entities ce2 ON ce1.entity_id = ce2.entity_id
            WHERE ce1.claim_id = ? AND ce2.claim_id != ?
            LIMIT ?
            """,
            (claim_id, claim_id, limit),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def find_path(
        self, from_entity: str, to_entity: str
    ) -> list[str]:
        """BFS shortest path between two entities via entity_relations."""
        cursor = await self._db.execute(
            """
            WITH RECURSIVE path(entity_id, route, lvl) AS (
                SELECT id, id, 0
                FROM entities WHERE name = ?

                UNION ALL

                SELECT
                    CASE
                        WHEN er.from_entity = p.entity_id THEN er.to_entity
                        ELSE er.from_entity
                    END,
                    p.route || ',' ||
                    CASE
                        WHEN er.from_entity = p.entity_id THEN er.to_entity
                        ELSE er.from_entity
                    END,
                    p.lvl + 1
                FROM entity_relations er
                JOIN path p ON (
                    er.from_entity = p.entity_id OR er.to_entity = p.entity_id
                )
                WHERE p.lvl < 6
                  AND er.expired_at IS NULL
                  AND p.route NOT LIKE '%' ||
                      CASE
                          WHEN er.from_entity = p.entity_id THEN er.to_entity
                          ELSE er.from_entity
                      END || '%'
            )
            SELECT route FROM path
            JOIN entities e ON path.entity_id = e.id
            WHERE e.name = ?
            ORDER BY lvl
            LIMIT 1
            """,
            (from_entity, to_entity),
        )
        row = await cursor.fetchone()
        if row is None:
            return []
        return str(row[0]).split(",")

    async def close(self) -> None:
        """No-op — connection lifecycle managed by Tensory."""
        pass
