"""SQLite schema for tensory's 4-layer memory architecture.

Sets up WAL mode, FTS5 for keyword search, sqlite-vec for vector
embeddings, and all tables across all four layers. Includes schema
versioning with forward-compatible migrations.

References:
- WAL + busy_timeout: dev.to/nathanhamlett (SQLite for AI agents)
- sqlite-vec: github.com/asg017/sqlite-vec
- FTS5: sqlite.org/fts5.html
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 4

# Future migrations: version -> list of SQL statements
MIGRATIONS: dict[int, list[str]] = {
    2: [
        "ALTER TABLE claims ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'semantic'",
        "ALTER TABLE claims ADD COLUMN trigger TEXT",
        "ALTER TABLE claims ADD COLUMN steps JSON",
        "ALTER TABLE claims ADD COLUMN termination_condition TEXT",
        "ALTER TABLE claims ADD COLUMN success_rate REAL DEFAULT 0.5",
        "ALTER TABLE claims ADD COLUMN usage_count INTEGER DEFAULT 0",
        "ALTER TABLE claims ADD COLUMN last_used TIMESTAMP",
        "ALTER TABLE claims ADD COLUMN source_episode_ids JSON DEFAULT '[]'",
    ],
    3: [
        # Collision log — persist all detected collisions for audit trail
        """CREATE TABLE IF NOT EXISTS collision_log (
            id             TEXT PRIMARY KEY,
            claim_a_id     TEXT NOT NULL,
            claim_b_id     TEXT NOT NULL,
            collision_type TEXT NOT NULL,
            score          REAL NOT NULL,
            shared_entities JSON DEFAULT '[]',
            created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )""",
        "CREATE INDEX IF NOT EXISTS idx_collision_log_a ON collision_log(claim_a_id)",
        "CREATE INDEX IF NOT EXISTS idx_collision_log_b ON collision_log(claim_b_id)",
        "CREATE INDEX IF NOT EXISTS idx_collision_log_type ON collision_log(collision_type)",
    ],
    4: [
        # Canonical entity name for case-insensitive dedup + indexed lookups.
        # `name` stays as display name; `canonical` is the normalized lookup key.
        "ALTER TABLE entities ADD COLUMN canonical TEXT",
        # Backfill canonical from existing names (lowercase + strip)
        "UPDATE entities SET canonical = LOWER(TRIM(name))",
        # After backfill, make it NOT NULL via index (SQLite can't ALTER to NOT NULL)
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical)",
    ],
}

# ── Pragma configuration ──────────────────────────────────────────────────

_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA foreign_keys=ON",
    "PRAGMA synchronous=NORMAL",  # safe with WAL
]

# ── Table definitions (ordered by layer) ──────────────────────────────────

_TABLES = [
    # ─── Layer 0: RAW — episodes. Never deleted. ───
    """
    CREATE TABLE IF NOT EXISTS episodes (
        id             TEXT PRIMARY KEY,
        raw_text       TEXT NOT NULL,
        source         TEXT DEFAULT '',
        source_url     TEXT,
        fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ─── Layer 3: CONTEXT — user research goals ───
    """
    CREATE TABLE IF NOT EXISTS contexts (
        id             TEXT PRIMARY KEY,
        goal           TEXT NOT NULL,
        description    TEXT DEFAULT '',
        domain         TEXT DEFAULT 'general',
        user_id        TEXT,
        active         INTEGER DEFAULT 1,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ─── Layer 1: CLAIMS — atomic statements ───
    """
    CREATE TABLE IF NOT EXISTS claims (
        id             TEXT PRIMARY KEY,
        episode_id     TEXT,
        context_id     TEXT,
        text           TEXT NOT NULL,
        type           TEXT NOT NULL DEFAULT 'fact',
        confidence     REAL NOT NULL DEFAULT 1.0,
        relevance      REAL NOT NULL DEFAULT 1.0,
        salience       REAL NOT NULL DEFAULT 1.0,
        decay_rate     REAL,
        last_accessed  TIMESTAMP,
        access_count   INTEGER DEFAULT 0,
        valid_from     TIMESTAMP,
        valid_to       TIMESTAMP,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        superseded_at  TIMESTAMP,
        superseded_by  TEXT,
        metadata       JSON,
        -- Procedural memory (Skill-MDP)
        memory_type        TEXT NOT NULL DEFAULT 'semantic',
        trigger            TEXT,
        steps              JSON,
        termination_condition TEXT,
        success_rate       REAL DEFAULT 0.5,
        usage_count        INTEGER DEFAULT 0,
        last_used          TIMESTAMP,
        source_episode_ids JSON DEFAULT '[]'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS claim_entities (
        claim_id       TEXT NOT NULL REFERENCES claims(id),
        entity_id      TEXT NOT NULL,
        PRIMARY KEY (claim_id, entity_id)
    )
    """,
    # ─── Layer 2: GRAPH — entities + relations ───
    """
    CREATE TABLE IF NOT EXISTS entities (
        id             TEXT PRIMARY KEY,
        name           TEXT NOT NULL,
        canonical      TEXT,
        type           TEXT,
        mention_count  INTEGER DEFAULT 1,
        first_seen     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS entity_relations (
        id             TEXT PRIMARY KEY,
        from_entity    TEXT NOT NULL REFERENCES entities(id),
        to_entity      TEXT NOT NULL REFERENCES entities(id),
        rel_type       TEXT NOT NULL,
        fact           TEXT,
        episode_id     TEXT,
        confidence     REAL DEFAULT 0.8,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expired_at     TIMESTAMP
    )
    """,
    # ─── Cross-context relevance scores ───
    """
    CREATE TABLE IF NOT EXISTS relevance_scores (
        claim_id       TEXT NOT NULL REFERENCES claims(id),
        context_id     TEXT NOT NULL REFERENCES contexts(id),
        score          REAL NOT NULL,
        PRIMARY KEY (claim_id, context_id)
    )
    """,
    # ─── Waypoints: 1-hop associative links (OpenMemory pattern) ───
    """
    CREATE TABLE IF NOT EXISTS waypoints (
        src_claim      TEXT PRIMARY KEY REFERENCES claims(id),
        dst_claim      TEXT NOT NULL REFERENCES claims(id),
        similarity     REAL NOT NULL,
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ─── Collision log: persist all detected collisions ───
    """
    CREATE TABLE IF NOT EXISTS collision_log (
        id             TEXT PRIMARY KEY,
        claim_a_id     TEXT NOT NULL,
        claim_b_id     TEXT NOT NULL,
        collision_type TEXT NOT NULL,
        score          REAL NOT NULL,
        shared_entities JSON DEFAULT '[]',
        created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # ─── Schema version tracking ───
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version        INTEGER NOT NULL
    )
    """,
]

# ── FTS5 virtual table ────────────────────────────────────────────────────

_FTS_TABLE = """
    CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts
    USING fts5(text, content='claims', content_rowid='rowid')
"""

# FTS5 triggers to keep the index in sync with the claims table
_FTS_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
        INSERT INTO claims_fts(rowid, text) VALUES (new.rowid, new.text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
        INSERT INTO claims_fts(claims_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS claims_au AFTER UPDATE ON claims BEGIN
        INSERT INTO claims_fts(claims_fts, rowid, text)
        VALUES ('delete', old.rowid, old.text);
        INSERT INTO claims_fts(rowid, text) VALUES (new.rowid, new.text);
    END
    """,
]

# ── Indices ───────────────────────────────────────────────────────────────

_INDICES = [
    "CREATE INDEX IF NOT EXISTS idx_claims_episode ON claims(episode_id)",
    "CREATE INDEX IF NOT EXISTS idx_claims_context ON claims(context_id)",
    "CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(type)",
    "CREATE INDEX IF NOT EXISTS idx_claims_salience ON claims(salience)",
    "CREATE INDEX IF NOT EXISTS idx_claims_superseded ON claims(superseded_at)",
    "CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name)",
    "CREATE INDEX IF NOT EXISTS idx_relations_from ON entity_relations(from_entity)",
    "CREATE INDEX IF NOT EXISTS idx_relations_to ON entity_relations(to_entity)",
    "CREATE INDEX IF NOT EXISTS idx_relevance_context ON relevance_scores(context_id)",
    "CREATE INDEX IF NOT EXISTS idx_waypoints_dst ON waypoints(dst_claim)",
    "CREATE INDEX IF NOT EXISTS idx_claims_memory_type ON claims(memory_type)",
    "CREATE INDEX IF NOT EXISTS idx_collision_log_a ON collision_log(claim_a_id)",
    "CREATE INDEX IF NOT EXISTS idx_collision_log_b ON collision_log(claim_b_id)",
    "CREATE INDEX IF NOT EXISTS idx_collision_log_type ON collision_log(collision_type)",
]


# ── Public API ────────────────────────────────────────────────────────────


async def create_schema(db: aiosqlite.Connection, *, embedding_dim: int = 1536) -> None:
    """Initialize the full tensory schema.

    Args:
        db: An open aiosqlite connection.
        embedding_dim: Dimension for vector embeddings (default 1536 for OpenAI).
    """
    # Pragmas
    for pragma in _PRAGMAS:
        await db.execute(pragma)

    # Core tables
    for ddl in _TABLES:
        await db.execute(ddl)

    # FTS5
    await db.execute(_FTS_TABLE)
    for trigger in _FTS_TRIGGERS:
        await db.execute(trigger)

    # Vector embeddings via sqlite-vec
    # Must load extension before creating vec0 virtual table
    try:
        import sqlite_vec  # pyright: ignore[reportMissingTypeStubs]

        await db.enable_load_extension(True)
        await db.load_extension(sqlite_vec.loadable_path())

        await db.execute(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS claim_embeddings "
            f"USING vec0(claim_id TEXT PRIMARY KEY, embedding FLOAT[{embedding_dim}] distance_metric=cosine)"
        )
    except Exception:
        logger.warning(
            "sqlite-vec not available — vector search will be disabled. "
            "Install with: pip install sqlite-vec"
        )

    # Indices
    for idx in _INDICES:
        await db.execute(idx)

    # Schema version
    cursor = await db.execute("SELECT COUNT(*) FROM schema_version")
    row = await cursor.fetchone()
    if row is not None and row[0] == 0:
        await db.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))

    await db.commit()


async def migrate(db: aiosqlite.Connection) -> int:
    """Run pending migrations. Returns the final schema version."""
    cursor = await db.execute("SELECT version FROM schema_version LIMIT 1")
    row = await cursor.fetchone()
    current = row[0] if row else 0

    for version in sorted(MIGRATIONS.keys()):
        if version > current:
            logger.info("Applying migration v%d", version)
            for sql in MIGRATIONS[version]:
                await db.execute(sql)
            await db.execute("UPDATE schema_version SET version = ?", (version,))
            current = version

    await db.commit()
    return current
