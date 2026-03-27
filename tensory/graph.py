"""Graph backend abstraction for tensory.

Defines the GraphBackend Protocol and provides two implementations:
- SQLiteGraphBackend: zero-dependency default (recursive CTEs, <100K claims)
- Neo4jBackend: enterprise option (Cypher, pip install tensory[neo4j])

References:
- GraphBackend pattern: github.com/getzep/graphiti (driver/ directory)
- Recursive CTEs: sqlite.org/lang_with.html
- Neo4j async driver: neo4j.com/docs/python-manual/current/async/
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)


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

    async def get_shared_entities(self, claim_id: str, limit: int = 50) -> list[str]:
        """Get entity IDs shared with other claims (for collision scoring)."""
        ...

    async def find_path(self, from_entity: str, to_entity: str) -> list[str]:
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

        cursor = await self._db.execute("SELECT id FROM entities WHERE name = ?", (normalized,))
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

    async def get_shared_entities(self, claim_id: str, limit: int = 50) -> list[str]:
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

    async def find_path(self, from_entity: str, to_entity: str) -> list[str]:
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


class Neo4jBackend:
    """Graph backend using Neo4j for production scale.

    Requires: ``pip install tensory[neo4j]``

    Uses Cypher queries for traversal — handles millions of entities
    with proper indexing. Docker or Neo4j Aura (cloud) required.

    Usage::

        from tensory.graph import Neo4jBackend

        backend = Neo4jBackend("bolt://localhost:7687", password="secret")
        store = await Tensory.create("memory.db", graph_backend=backend)
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
    ) -> None:
        try:
            from neo4j import AsyncGraphDatabase  # pyright: ignore[reportMissingTypeStubs]
        except ImportError as exc:
            msg = "Neo4j driver required: pip install tensory[neo4j]"
            raise ImportError(msg) from exc

        self._driver: Any = AsyncGraphDatabase.driver(uri, auth=(user, password))  # pyright: ignore[reportUnknownMemberType]
        self._database = database

    async def _ensure_indexes(self) -> None:
        """Create indexes on first use for fast lookups."""
        async with self._driver.session(database=self._database) as session:
            await session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.name)")
            await session.run("CREATE INDEX IF NOT EXISTS FOR (e:Entity) ON (e.entity_id)")

    async def add_entity(self, name: str, entity_type: str | None = None) -> str:
        """Add or update an entity node. Returns entity ID."""
        normalized = name.strip()
        entity_id = uuid.uuid4().hex

        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                """
                MERGE (e:Entity {name: $name})
                ON CREATE SET e.entity_id = $entity_id,
                              e.type = $entity_type,
                              e.mention_count = 1
                ON MATCH SET e.mention_count = e.mention_count + 1
                RETURN e.entity_id AS id
                """,
                name=normalized,
                entity_id=entity_id,
                entity_type=entity_type,
            )
            record = await result.single()
            return str(record["id"]) if record else entity_id

    async def add_edge(
        self,
        from_id: str,
        to_id: str,
        rel_type: str,
        properties: dict[str, object] | None = None,
    ) -> None:
        """Create a directed relationship between two entities."""
        props = properties or {}
        fact = str(props.get("fact", ""))
        raw_ep = props.get("episode_id")
        episode_id = str(raw_ep) if raw_ep else None
        raw_conf = props.get("confidence", 0.8)
        confidence = float(str(raw_conf))

        # Sanitize rel_type for Cypher (must be alphanumeric + underscore)
        safe_rel_type = "".join(c if c.isalnum() or c == "_" else "_" for c in rel_type)

        async with self._driver.session(database=self._database) as session:
            await session.run(
                f"""
                MATCH (a:Entity {{entity_id: $from_id}})
                MATCH (b:Entity {{entity_id: $to_id}})
                CREATE (a)-[r:{safe_rel_type} {{
                    fact: $fact,
                    episode_id: $episode_id,
                    confidence: $confidence
                }}]->(b)
                """,
                from_id=from_id,
                to_id=to_id,
                fact=fact,
                episode_id=episode_id,
                confidence=confidence,
            )

    async def traverse(
        self,
        entity_name: str,
        depth: int = 2,
        edge_types: list[str] | None = None,
    ) -> list[str]:
        """Find entity IDs reachable within `depth` hops via Cypher."""
        if edge_types:
            # Filter by relationship types
            rel_filter = "|".join(edge_types)
            cypher = f"""
                MATCH (start:Entity {{name: $name}})-[:{rel_filter}*1..{depth}]-(reached:Entity)
                WHERE reached <> start
                RETURN DISTINCT reached.entity_id AS id
            """
        else:
            cypher = f"""
                MATCH (start:Entity {{name: $name}})-[*1..{depth}]-(reached:Entity)
                WHERE reached <> start
                RETURN DISTINCT reached.entity_id AS id
            """

        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, name=entity_name)
            records = [record async for record in result]
            return [str(r["id"]) for r in records]

    async def get_shared_entities(self, claim_id: str, limit: int = 50) -> list[str]:
        """Get entity IDs shared with other claims.

        Note: claim_entities mapping is still in SQLite.
        This method queries Neo4j for entities connected via relationships.
        For full claim-entity integration, the caller should supplement
        with SQLite claim_entities queries.
        """
        # Neo4j doesn't store claim_entities — this is a SQLite concept.
        # Return entities connected to any entity that this claim references.
        # The store.py layer handles the claim_entities join.
        logger.debug(
            "get_shared_entities called on Neo4jBackend — "
            "claim_entities are in SQLite, returning empty. "
            "Store handles this via SQL."
        )
        return []

    async def find_path(self, from_entity: str, to_entity: str) -> list[str]:
        """Find shortest path between two entities via Cypher."""
        async with self._driver.session(database=self._database) as session:
            result = await session.run(
                """
                MATCH path = shortestPath(
                    (a:Entity {name: $from_name})-[*..6]-(b:Entity {name: $to_name})
                )
                RETURN [n IN nodes(path) | n.entity_id] AS entity_ids
                """,
                from_name=from_entity,
                to_name=to_entity,
            )
            record = await result.single()
            if record is None:
                return []
            return [str(eid) for eid in record["entity_ids"]]

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        await self._driver.close()
