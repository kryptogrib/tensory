# tensory — Final Implementation Plan
> Версия: v2, 27 марта 2026
> Context-aware architecture: raw → claims → graph → relevance

---

## Философия проекта

**"Context-aware memory for AI agents. One file. Built-in collision detection."**

Четыре принципа:

1. `pip install tensory` работает **без Docker, без Neo4j**
2. **Raw никогда не теряется** — оригинальный текст хранится всегда, claims переизвлекаемы
3. **Context-aware extraction** — claims извлекаются ОТНОСИТЕЛЬНО цели пользователя
4. **LLM on write** (extraction, relations) · **Algorithms on read** (search, collisions)

### Core insight
Мозг фильтрует информацию через текущую задачу. tensory делает то же: один текст → разные claims в зависимости от контекста ("зачем я это читаю").

### 4 слоя хранения
```
Layer 0: RAW       — episodes (raw text, source, url). Никогда не удаляется.
Layer 1: CLAIMS    — atomic claims + embeddings + salience. Ссылаются на raw episode.
Layer 2: GRAPH     — entities + LLM-extracted relations + waypoints.
Layer 3: CONTEXT   — goals (цели пользователя) + relevance scores (claim × goal).
```

### Memory lifecycle (inspired by cognitive science + OpenMemory HSG)
```
New claim → salience=1.0 → decay over time → reinforce on access
         → verified?  salience boost (+0.3)
         → contradicted? salience drop (×0.5)
         → never accessed? decay to cold storage
         → accessed often? stays "hot", slow decay
```

---

## Актуальность зависимостей (27.03.2026)

| Пакет | Статус | Последний релиз | Вердикт |
|---|---|---|---|
| sqlite-vec | ✅ активный | v0.1.8-alpha, 20 марта 2026 | использовать |
| aiosqlite | ✅ активный | стабильный | использовать |
| pydantic v2 | ✅ активный | стабильный | использовать |
| **kuzu** | ❌ **discontinued** | октябрь 2025, архив | **убрать из плана** |
| neo4j driver | ✅ активный | v5.x | optional extra (Phase 5+) |
| Hindsight | ✅ активный | v0.4.20, 24 марта 2026 | inspiration: TEMPR, CARA |
| Graphiti | ✅ активный | 20K+ stars | dedup код + driver pattern |

---

## Итоговая структура файлов

```
tensory/
├── tensory/
│   ├── __init__.py          # публичный API
│   ├── store.py             # Tensory — главный оркестратор
│   ├── schema.py            # SQLite схема (4 layers, WAL, FTS5, vec0)
│   ├── models.py            # Pydantic: Episode, Context, Claim, EntityRelation, Collision
│   ├── extract.py           # Context-aware LLM extraction + relation extraction
│   ├── dedup.py             # Entropy gate + MinHash/LSH
│   ├── embedder.py          # Pluggable embedding
│   ├── search.py            # Parallel hybrid search + RRF (context-weighted)
│   ├── collisions.py        # Collision detection (vector + entity + temporal)
│   ├── temporal.py          # Superseding, timeline, cleanup
│   ├── graph.py             # GraphBackend Protocol + SQLiteGraphBackend
│   └── py.typed
├── tests/
│   ├── test_store.py
│   ├── test_dedup.py
│   ├── test_search.py
│   ├── test_collisions.py
│   ├── test_temporal.py
│   ├── test_extract.py
│   ├── test_graph.py
│   └── conftest.py
├── pyproject.toml
├── README.md
└── LICENSE                  # MIT
```

---

## Public API (7 core methods)

```python
from tensory import Tensory, Claim, Context

store = Tensory("memory.db", llm=my_llm_fn, embed_fn=my_embed_fn)

# ====== CONTEXT (research goals) ======

# Create a research goal — the lens for extraction
ctx = await store.create_context(
    goal="Track DeFi team movements and protocol partnerships",
    domain="crypto",
    user_id="user_123",
)

# ====== WRITE ======

# Mode 1: raw text → auto-extract claims relative to context
result = await store.add(
    "Google announced partnership with EigenLayer for cloud restaking...",
    source="reddit:r/defi",
    context=ctx,              # claims extracted through this lens
)
# → result.episode_id        # raw stored (Layer 0)
# → result.claims            # extracted relative to context (Layer 1)
# → result.relations         # LLM-extracted entity relations (Layer 2)
# → result.collisions        # auto-detected (algorithmic)

# Mode 2: pre-extracted claims (no LLM needed)
await store.add_claims([
    Claim(text="...", entities=["..."], context_id=ctx.id)
])

# ====== READ ======

# Search — context-weighted ranking
results = await store.search("EigenLayer", context=ctx)

# Timeline — how facts about an entity evolved
history = await store.timeline("EigenLayer")

# ====== RE-EVALUATE ======

# New goal → re-extract claims from OLD episodes through new lens
tech_ctx = await store.create_context(goal="Track Big Tech AI strategy")
new_claims = await store.reevaluate(episode_id=result.episode_id, context=tech_ctx)
# → extracts NEW claims from same raw text, through different lens

# ====== MAINTAIN ======
stats = await store.stats()
await store.cleanup(max_age_days=90)
```

---

## Модели данных (`models.py`)

```python
from enum import Enum
from pydantic import BaseModel
from datetime import datetime

class ClaimType(str, Enum):
    FACT        = "fact"         # верифицируемое утверждение
    EXPERIENCE  = "experience"   # событие, что произошло
    OBSERVATION = "observation"  # вывод / inference из других claims
    OPINION     = "opinion"      # оценочное суждение

class Episode(BaseModel):
    """Layer 0: Raw text. Never deleted."""
    id: str
    raw_text: str
    source: str = ""             # "reddit:r/defi", "telegram:channel", "web:url"
    source_url: str | None = None
    fetched_at: datetime = ...

class Context(BaseModel):
    """Layer 3: User's research goal — the lens for extraction."""
    id: str
    goal: str                    # "Track DeFi team movements and protocol partnerships"
    description: str = ""        # extended description
    domain: str = "general"      # "crypto", "tech", "health"
    user_id: str | None = None
    active: bool = True
    created_at: datetime = ...

class Claim(BaseModel):
    """Layer 1: Atomic verifiable statement, extracted relative to a Context."""
    id: str
    text: str
    entities: list[str] = []
    temporal: str | None = None
    metadata: dict = {}
    type: ClaimType = ClaimType.FACT
    confidence: float = 1.0
    episode_id: str | None = None     # ← link to raw text (Layer 0)
    context_id: str | None = None     # ← in which context extracted (Layer 3)
    relevance: float = 1.0            # ← relevance to context (0.0-1.0)
    # Salience (from OpenMemory HSG pattern)
    salience: float = 1.0             # ← 0.0-1.0, decays over time, boosted on access/verification
    decay_rate: float | None = None   # ← per-type decay (None = use default for ClaimType)
    # Temporal validity (from OpenMemory temporal graph)
    valid_from: datetime | None = None  # ← when this fact became true in real world
    valid_to: datetime | None = None    # ← when it stopped being true (None = still valid)
    embedding: list[float] | None = None
    created_at: datetime = ...
    superseded_at: datetime | None = None
    superseded_by: str | None = None

class EntityRelation(BaseModel):
    """Layer 2: LLM-extracted semantic relationship between entities."""
    from_entity: str
    to_entity: str
    rel_type: str                # PARTNERED_WITH, INVESTED_IN, DEPARTED_FROM...
    fact: str                    # human-readable description
    episode_id: str | None = None
    confidence: float = 0.8
    created_at: datetime = ...
    expired_at: datetime | None = None

class Collision(BaseModel):
    claim_a: Claim
    claim_b: Claim
    score: float                         # 0.0–1.0
    shared_entities: list[str]
    temporal_distance: float | None
    type: str                            # "contradiction" | "supersedes" | "related"

class IngestResult(BaseModel):
    episode_id: str                      # raw text stored
    claims: list[Claim]
    relations: list[EntityRelation]      # LLM-extracted relations
    collisions: list[Collision]
    new_entities: list[str]

class SearchResult(BaseModel):
    claim: Claim
    score: float
    relevance: float                     # relevance to current context
    method: str                          # "vector" | "fts" | "graph" | "hybrid"
```

**Что смотреть:**
- `ClaimType`, `confidence` — Hindsight paper (CARA architecture): https://arxiv.org/abs/2512.12818
- `EntityRelation` pattern — Graphiti edges: https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py
- `Context` as extraction lens — novel, no direct reference (our innovation)

---

## SQLite схема (`schema.py`)

```python
def create_schema(db, indexed_fields):
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=5000")
    # ... создание таблиц ниже
```

```sql
-- =================== Layer 0: RAW ===================
-- Never deleted. Source of truth.
CREATE TABLE episodes (
    id             TEXT PRIMARY KEY,
    raw_text       TEXT NOT NULL,
    source         TEXT,                -- "reddit:r/defi", "telegram:channel"
    source_url     TEXT,                -- full URL
    fetched_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =================== Layer 3: CONTEXT ===================
-- User research goals. The lens for extraction.
CREATE TABLE contexts (
    id             TEXT PRIMARY KEY,
    goal           TEXT NOT NULL,       -- "Track DeFi team movements"
    description    TEXT DEFAULT '',
    domain         TEXT DEFAULT 'general',
    user_id        TEXT,
    active         BOOLEAN DEFAULT 1,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =================== Layer 1: CLAIMS ===================
-- Atomic statements extracted from episodes relative to a context.
CREATE TABLE claims (
    id             TEXT PRIMARY KEY,
    episode_id     TEXT REFERENCES episodes(id),   -- ← link to raw
    context_id     TEXT REFERENCES contexts(id),   -- ← extraction lens
    text           TEXT NOT NULL,
    type           TEXT NOT NULL DEFAULT 'fact',
    confidence     REAL NOT NULL DEFAULT 1.0,
    relevance      REAL NOT NULL DEFAULT 1.0,      -- relevance to context
    -- Salience (OpenMemory pattern: decay + reinforce)
    salience       REAL NOT NULL DEFAULT 1.0,      -- 0.0-1.0, decays over time
    decay_rate     REAL,                           -- per-claim override (NULL = use type default)
    last_accessed  TIMESTAMP,                      -- reinforce on access
    access_count   INTEGER DEFAULT 0,
    -- Temporal validity (OpenMemory pattern: valid_from/valid_to)
    valid_from     TIMESTAMP,                      -- when fact became true in real world
    valid_to       TIMESTAMP,                      -- when it stopped being true (NULL = still valid)
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    superseded_at  TIMESTAMP,
    superseded_by  TEXT,
    metadata       JSON
    -- + dynamic indexed_fields columns
);

CREATE TABLE claim_entities (
    claim_id       TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    PRIMARY KEY (claim_id, entity_id)
);

-- FTS5 for keyword search
CREATE VIRTUAL TABLE claims_fts
    USING fts5(text, content='claims', content_rowid='rowid');

-- Vector embeddings for semantic search
CREATE VIRTUAL TABLE claim_embeddings
    USING vec0(claim_id TEXT PRIMARY KEY, embedding FLOAT[1536]);

-- =================== Layer 2: GRAPH ===================
-- Entities + LLM-extracted relations.
CREATE TABLE entities (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    type           TEXT,                -- person, protocol, token, org
    mention_count  INTEGER DEFAULT 1,
    first_seen     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE entity_relations (
    id             TEXT PRIMARY KEY,
    from_entity    TEXT NOT NULL REFERENCES entities(id),
    to_entity      TEXT NOT NULL REFERENCES entities(id),
    rel_type       TEXT NOT NULL,       -- PARTNERED_WITH, INVESTED_IN, DEPARTED_FROM
    fact           TEXT,                -- "Google partnered with EigenLayer for restaking"
    episode_id     TEXT REFERENCES episodes(id),
    confidence     REAL DEFAULT 0.8,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expired_at     TIMESTAMP           -- temporal invalidation
);

-- Cross-context relevance (one claim can be relevant to multiple goals)
CREATE TABLE relevance_scores (
    claim_id       TEXT NOT NULL REFERENCES claims(id),
    context_id     TEXT NOT NULL REFERENCES contexts(id),
    score          REAL NOT NULL,       -- 0.0-1.0, LLM-assigned
    PRIMARY KEY (claim_id, context_id)
);

-- Waypoints: lightweight 1-hop associative links (OpenMemory pattern)
-- Each claim links to its most similar claim (auto-created on ingest)
CREATE TABLE waypoints (
    src_claim      TEXT PRIMARY KEY REFERENCES claims(id),
    dst_claim      TEXT NOT NULL REFERENCES claims(id),
    similarity     REAL NOT NULL,       -- cosine similarity at link time
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indices
CREATE INDEX idx_claims_episode ON claims(episode_id);
CREATE INDEX idx_claims_context ON claims(context_id);
CREATE INDEX idx_claims_type ON claims(type);
CREATE INDEX idx_claims_salience ON claims(salience);
CREATE INDEX idx_claims_superseded ON claims(superseded_at);
CREATE INDEX idx_entities_name ON entities(name);
CREATE INDEX idx_relations_from ON entity_relations(from_entity);
CREATE INDEX idx_relations_to ON entity_relations(to_entity);
CREATE INDEX idx_relevance_context ON relevance_scores(context_id);
CREATE INDEX idx_waypoints_dst ON waypoints(dst_claim);
```

**Schema version migration:**
```python
SCHEMA_VERSION = 1
MIGRATIONS = {
    # Future: 2: "ALTER TABLE claims ADD COLUMN disposition JSON",
}
```

**Что смотреть:**
- WAL + busy_timeout → https://dev.to/nathanhamlett/sqlite-is-the-best-database-for-ai-agents-and-youre-overcomplicating-it-1a5g
- sqlite-vec setup → https://github.com/asg017/sqlite-vec/blob/main/README.md
- FTS5 → https://www.sqlite.org/fts5.html

---

## GraphBackend (`graph.py`) — НОВЫЙ ФАЙЛ

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class GraphBackend(Protocol):
    async def add_entity(self, name: str, type: str | None = None) -> str: ...
    async def add_edge(
        self, from_id: str, to_id: str,
        rel_type: str, properties: dict | None = None
    ) -> None: ...
    async def traverse(
        self, entity_name: str,
        depth: int = 2,
        edge_types: list[str] | None = None
    ) -> list[str]: ...
    async def get_shared_entities(
        self, claim_id: str, limit: int = 50
    ) -> list[str]: ...         # активно используется в collision scoring
    async def find_path(
        self, from_entity: str, to_entity: str
    ) -> list[str]: ...
    async def close(self) -> None: ...
```

### SQLiteGraphBackend (default, zero-dep)

```python
class SQLiteGraphBackend:
    """Recursive CTEs. Достаточно для <100K claims. Нет зависимостей."""

    async def traverse(self, entity_name: str, depth: int = 2,
                       edge_types: list[str] | None = None) -> list[str]:
        # WITH RECURSIVE cte(entity_id, lvl) AS (
        #   SELECT id, 0 FROM entities WHERE name = :name
        #   UNION ALL
        #   SELECT ce2.entity_id, cte.lvl + 1
        #   FROM claim_entities ce1
        #   JOIN claim_entities ce2 ON ce1.claim_id = ce2.claim_id
        #   JOIN cte ON ce1.entity_id = cte.entity_id
        #   WHERE cte.lvl < :depth AND ce2.entity_id != cte.entity_id
        # ) SELECT DISTINCT entity_id FROM cte
        ...
```

### Neo4jBackend (optional, enterprise — Phase 5+)

```python
class Neo4jBackend:
    """pip install tensory[neo4j]. Docker / cloud. Для production scale."""

    def __init__(self, uri: str, user: str = "neo4j", password: str = ""):
        from neo4j import AsyncGraphDatabase
        self._driver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def traverse(self, entity_name: str, depth: int = 2,
                       edge_types: list[str] | None = None) -> list[str]:
        cypher = f"MATCH (e:Entity {{name: $name}})-[*1..{depth}]-(r) RETURN r.id"
        ...
```

### Автовыбор бэкенда

```python
def _auto_select_graph_backend(db_path: str) -> GraphBackend:
    # Kuzu discontinued (октябрь 2025, Kuzu Inc закрылась) — убран
    # SQLiteGraphBackend всегда default, пока не передан явно
    return SQLiteGraphBackend(db_path)
```

**Инициализация:**
```python
# Быстрый старт — SQLiteGraphBackend автоматически
store = Tensory("memory.db")

# Production / scale
store = Tensory("memory.db", graph_backend=Neo4jBackend("bolt://localhost:7687"))
```

**Что смотреть:**
- Структура GraphBackend abstraction →  
  https://github.com/getzep/graphiti/tree/main/graphiti_core/driver  
  Смотреть: `neo4j_driver.py`, `falkordb_driver.py` — как абстрагируют методы
- Recursive CTEs для graph traversal →  
  https://www.sqlite.org/lang_with.html  
  Раздел "Recursive Common Table Expressions" — примеры с depth limit
- Neo4j async Python driver →  
  https://neo4j.com/docs/python-manual/current/async/

---

## Dedup (`dedup.py`)

```python
# Deduplication logic adapted from Graphiti (Apache-2.0)
# https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/dedup_helpers.py

import math
from collections import Counter
from functools import lru_cache

def _shannon_entropy(text: str) -> float:
    """Низкий entropy → строка нестабильна для fuzzy matching."""
    text = text.lower().strip()
    if not text:
        return 0.0
    c = Counter(text)
    total = len(text)
    return -sum((f / total) * math.log2(f / total) for f in c.values())

@lru_cache(maxsize=1024)
def _shingle(text: str, n: int = 3) -> frozenset:
    norm = " ".join(text.lower().split())
    return frozenset(norm[i:i+n] for i in range(len(norm) - n + 1))

def _minhash(shingles: frozenset, num_perm: int = 32) -> list[int]:
    import hashlib
    return [
        min(int(hashlib.md5(f"{i}:{s}".encode()).hexdigest(), 16) for s in shingles)
        for i in range(num_perm)
    ]

def _lsh_bands(signature: list[int], band_size: int = 4) -> list[tuple]:
    return [tuple(signature[i:i+band_size]) for i in range(0, len(signature), band_size)]

def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)

class MinHashDedup:
    ENTROPY_THRESHOLD = 2.5   # ниже → exact match fallback (без fuzzy)
    JACCARD_THRESHOLD = 0.9

    def is_duplicate(self, new_text: str, existing_texts: list[str]) -> bool:
        entropy = _shannon_entropy(new_text)
        if entropy < self.ENTROPY_THRESHOLD:
            # Короткие/повторяющиеся строки → только exact match
            norm = " ".join(new_text.lower().split())
            return any(" ".join(t.lower().split()) == norm for t in existing_texts)

        # Высокий entropy → MinHash/LSH
        new_shingles = _shingle(new_text)
        for existing in existing_texts:
            if _jaccard(new_shingles, _shingle(existing)) >= self.JACCARD_THRESHOLD:
                return True
        return False
```

**Что смотреть:**
- Полный MinHash + LSH + Jaccard код →  
  https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/dedup_helpers.py  
  **Apache 2.0 — брать напрямую, атрибуция обязательна в начале файла**
- Entropy gate логика и объяснение →  
  https://blog.getzep.com/graphiti-hits-20k-stars-mcp-server-1-0/  
  Раздел "Entropy-gated fuzzy matching"

---

## Search (`search.py`)

```python
import asyncio

async def hybrid_search(
    query: str,
    embedding: list[float] | None,
    graph_backend: GraphBackend,
    db,
    filters: dict | None = None,
    limit: int = 10,
    weights: dict | None = None,
) -> list[SearchResult]:
    """Параллельный retrieval по трём каналам + weighted RRF merge."""

    w = weights or {"vector": 0.4, "fts": 0.3, "graph": 0.3}

    # Все три стратегии параллельно — как в Hindsight TEMPR
    fts_r, vec_r, graph_r = await asyncio.gather(
        fts_search(query, db, filters, limit=20),
        vector_search(embedding, db, filters, limit=20) if embedding else _empty(),
        graph_search(query, graph_backend, filters, limit=20),
        return_exceptions=True,
    )

    # Заменяем ошибки пустыми списками (graceful degradation)
    fts_r   = fts_r   if not isinstance(fts_r,   Exception) else []
    vec_r   = vec_r   if not isinstance(vec_r,   Exception) else []
    graph_r = graph_r if not isinstance(graph_r, Exception) else []

    return _rrf_merge(
        [fts_r, vec_r, graph_r],
        weights=[w["fts"], w["vector"], w["graph"]],
        limit=limit,
    )

def _rrf_merge(
    result_lists: list[list],
    weights: list[float],
    k: int = 60,
    limit: int = 10,
) -> list[SearchResult]:
    scores: dict[str, float] = {}
    items:  dict[str, SearchResult] = {}
    for results, weight in zip(result_lists, weights):
        for rank, item in enumerate(results):
            cid = item.claim.id
            scores[cid] = scores.get(cid, 0.0) + weight / (k + rank + 1)
            items.setdefault(cid, item)
    sorted_ids = sorted(scores, key=scores.__getitem__, reverse=True)
    return [items[i] for i in sorted_ids[:limit]]
```

**Что смотреть:**
- Parallel TEMPR + RRF семантика →  
  https://github.com/vectorize-io/hindsight  
  README → "How recall works" — описание 4 стратегий и merge
- RRF + sqlite-vec + FTS5 готовый Python пример →  
  https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/  
  Автор sqlite-vec, точный код для SQLite hybrid search
- Ещё один чистый пример RRF с FTS5 →  
  https://ceaksan.com/en/hybrid-search-fts5-vector-rrf/
- RRF оригинальная формула (2 страницы) →  
  https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf

---

## Collision detection (`collisions.py`)

```python
# LLM-free salience + confidence update rules (OpenMemory-inspired)
SALIENCE_RULES = {
    "contradiction": lambda s: s * 0.5,       # contradicted → salience drops
    "supersedes":    lambda s: s * 0.1,        # superseded → nearly dead
    "confirms":      lambda s: min(1.0, s + 0.2),  # confirmed → boost
    "related":       lambda s: min(1.0, s + 0.05), # related → small boost
}

# Default decay rates per ClaimType
DECAY_RATES = {
    ClaimType.FACT: 0.005,           # verified facts decay slowly
    ClaimType.EXPERIENCE: 0.010,     # events lose relevance
    ClaimType.OBSERVATION: 0.008,    # inferences are valuable
    ClaimType.OPINION: 0.020,        # opinions expire fast
}

async def find_collisions(
    claim: Claim,
    db,
    embedder,
    graph_backend: GraphBackend,
    top_k: int = 10,
    threshold: float = 0.5,
) -> list[Collision]:
    """
    Two-level collision detection — zero LLM calls:

    Level 1: STRUCTURAL (OpenMemory pattern)
      Same entity + similar predicate → automatic conflict
      e.g., "EigenLayer team=50" vs "EigenLayer team=45"

    Level 2: SEMANTIC (4 signals)
      vector_score   = cosine similarity (sqlite-vec)
      entity_score   = shared_entities / max_entities
      temporal_score = 1 - (days_apart / 30), clipped [0, 1]
      waypoint_score = 1.0 if connected via waypoint, else 0.0

    final = vector * 0.4 + entity * 0.25 + temporal * 0.2 + waypoint * 0.15
    """
    collisions = []

    # Level 1: Structural — same entities + overlapping validity
    structural = await _find_structural_conflicts(claim, db)
    collisions.extend(structural)

    # Level 2: Semantic — vector + entity + temporal + waypoint
    candidates = await _get_candidates(claim, db, embedder, top_k)
    for candidate in candidates:
        if any(c.claim_b.id == candidate.id for c in collisions):
            continue  # already found structurally

        shared = set(claim.entities) & set(candidate.entities)
        is_waypoint = await _is_waypoint_linked(claim.id, candidate.id, db)

        vector_score   = _cosine_sim(claim.embedding, candidate.embedding)
        entity_score   = len(shared) / max(len(claim.entities), len(candidate.entities), 1)
        temporal_score = _temporal_proximity(claim.created_at, candidate.created_at)
        waypoint_score = 1.0 if is_waypoint else 0.0

        final = vector_score*0.4 + entity_score*0.25 + temporal_score*0.2 + waypoint_score*0.15

        if final >= threshold:
            collisions.append(Collision(
                claim_a=claim, claim_b=candidate,
                score=final, shared_entities=list(shared),
                temporal_distance=temporal_score,
                type=_classify_collision(claim, candidate, final),
            ))

    return sorted(collisions, key=lambda c: c.score, reverse=True)

async def _find_structural_conflicts(claim: Claim, db) -> list[Collision]:
    """Find claims about same entities with overlapping validity windows.
    Pattern from OpenMemory find_conflicting_facts()."""
    # SELECT * FROM claims WHERE
    #   id != :claim_id AND superseded_at IS NULL
    #   AND EXISTS (SELECT 1 FROM claim_entities ce1
    #     JOIN claim_entities ce2 ON ce1.entity_id = ce2.entity_id
    #     WHERE ce1.claim_id = :claim_id AND ce2.claim_id = claims.id)
    #   AND (valid_to IS NULL OR valid_to > :now)  -- still valid
    ...

async def apply_salience_updates(collisions: list[Collision], db) -> None:
    """LLM-free salience updates based on collision type."""
    for c in collisions:
        rule = SALIENCE_RULES.get(c.type)
        if rule:
            new_salience = rule(c.claim_b.salience)
            await _update_salience(c.claim_b.id, new_salience, db)
```

**Что смотреть:**
- LLM-free confidence + valid_from/valid_until паттерн →  
  https://gerus-lab.hashnode.dev/why-your-ai-agents-memory-is-broken-and-how-to-fix-it-with-sqlite  
  Структура таблицы nodes + "LLM on write, algorithms on read" принцип
- Temporal invalidation (supersedes, expired_at) →  
  https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py  
  Поле `expired_at` и как оно проставляется при superseding

---

## Store (`store.py`) — метод `reflect()`

```python
class Tensory:
    def __init__(
        self,
        path: str,
        indexed_fields: dict | None = None,
        llm: LLMProtocol | None = None,
        embed_fn: EmbedProtocol | None = None,
        graph_backend: GraphBackend | None = None,   # ← НОВОЕ
    ):
        if graph_backend is None:
            graph_backend = _auto_select_graph_backend(path)
        self._graph = graph_backend
        # ... остальной init

    async def reflect(
        self,
        query: str,
        disposition: dict | None = None,
        auto_update: bool = True,
    ) -> ReflectResult:
        """
        Learning via reflection (LLM-free по умолчанию).

        1. Recall через hybrid_search
        2. Collision detection между recalled claims
        3. LLM-free confidence update по правилам
        4. Создать OBSERVATION claim если паттерн найден
        5. (Опционально) LLM-based CARA prompt — если self._llm задан
        """
        results = await self.search(query, limit=20)
        claims  = [r.claim for r in results]

        all_collisions = []
        for claim in claims:
            cols = await find_collisions(claim, self._db, self._embedder, self._graph)
            all_collisions.extend(cols)

        if auto_update:
            await apply_confidence_updates(all_collisions, self._db)

        new_observations = []
        if len(all_collisions) >= 2:
            obs = Claim(
                text=_synthesize_observation(claims, all_collisions),
                type=ClaimType.OBSERVATION,
                confidence=0.6,
                entities=_extract_entities_from_claims(claims),
            )
            await self.add_claims([obs])
            new_observations.append(obs)

        updated = [c for c in claims
                   if any(col.claim_b.id == c.id for col in all_collisions)]

        return ReflectResult(
            updated_claims=updated,
            new_observations=new_observations,
            collisions=all_collisions,
        )
```

**Что смотреть:**
- `reflect()` семантика и use-cases (Project Manager, Sales Agent) →  
  https://github.com/vectorize-io/hindsight  
  README → "The reflect operation"
- CARA: disposition parameters + opinion update →  
  https://arxiv.org/abs/2512.12818  
  Section 3.2 + Appendix A — промпты для LLM-based reflect (Phase 5++)
- AWS AgentCore — консолидация при противоречиях →  
  https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/  
  Раздел "Conflicting information" handling

---

## `pyproject.toml` (финальный)

```toml
[project]
name = "tensory"
version = "0.1.0"
description = "Embedded claim-native memory for AI agents. Collision detection built-in."
requires-python = ">=3.11"
dependencies = [
    "aiosqlite>=0.17",
    "sqlite-vec>=0.1",
    "pydantic>=2.0",
]

[project.optional-dependencies]
openai = ["openai>=1.0"]    # OpenAIEmbedder
neo4j  = ["neo4j>=5.0"]     # Neo4jBackend (enterprise, Phase 5+)
# kuzu — discontinued октябрь 2025. Будет добавлен в следующих версиях.

[build-system]
requires      = ["hatchling"]
build-backend = "hatchling.build"

[tool.pyright]
strict = true
```

**Что смотреть:**
- Структура `[project.optional-dependencies]` с несколькими extras →  
  https://github.com/getzep/graphiti/blob/main/pyproject.toml

---

## Фазы реализации

### Фаза 1 — Core storage + salience (День 1–2)

**Цель:** claims in, claims out. Один SQLite файл. Salience lifecycle.

**Файлы:** `models.py`, `schema.py`, `store.py` (partial), `graph.py`

**Задачи:**
- `models.py` — все модели: Episode, Context, Claim (с `salience`, `decay_rate`, `valid_from`/`valid_to`), EntityRelation, Collision, IngestResult, SearchResult
- `schema.py` — WAL pragma + все 4 layers + FTS5 + vec0 + waypoints + schema versioning
- `store.py` — `__init__` (с `graph_backend=`), `create_context()`, `add_claims()` (без embeddings), `search()` (FTS only), `stats()`
- `graph.py` — `GraphBackend` Protocol + `SQLiteGraphBackend` (recursive CTEs)
- **Sentiment tagging** (cognitive idea #4): keyword-based sentiment + intensity on ingest (~30 lines)
  ```python
  SENTIMENT_WORDS = {
      "positive": {"partnership", "growth", "launch", "confirmed", "milestone"},
      "negative": {"departed", "hack", "exploit", "bankrupt", "crash", "lawsuit"},
      "urgent": {"breaking", "just in", "alert", "emergency"},
  }
  # Auto-tag on ingest: claim.metadata["sentiment"], claim.metadata["intensity"]
  # Urgent claims get salience boost (+0.3)
  ```

**Что смотреть:**
| Что нужно | Куда смотреть |
|---|---|
| WAL + busy_timeout | https://dev.to/nathanhamlett/sqlite-is-the-best-database-for-ai-agents-and-youre-overcomplicating-it-1a5g → "Concurrent access" |
| sqlite-vec `CREATE VIRTUAL TABLE vec0` | https://github.com/asg017/sqlite-vec/blob/main/README.md → "Getting started with Python" |
| GraphBackend Protocol структура | https://github.com/getzep/graphiti/tree/main/graphiti_core/driver → любой `*_driver.py` |
| Recursive CTE для traversal | https://www.sqlite.org/lang_with.html → "Recursive CTEs" с примерами |
| Salience + decay model | OpenMemory HSG: `CaviraOSS/OpenMemory` → `packages/openmemory-js/src/memory/hsg.ts` |

**Тесты:** `test_add_claims_and_retrieve`, `test_fts_search`, `test_metadata_indexed_fields`, `test_graph_traverse_sqlite`, `test_salience_defaults_by_type`, `test_sentiment_tagging`

---

### Фаза 2 — Vector search + surprise + priming (День 2–3)

**Цель:** семантический поиск через sqlite-vec. Surprise score. Priming.

**Файлы:** `embedder.py`, `search.py`, update `schema.py`, `store.py`

**Задачи:**
- `embedder.py` — `Embedder` Protocol + `OpenAIEmbedder` + `NullEmbedder`
- `search.py` — `fts_search` + `vector_search` + `graph_search` + **параллельный** `hybrid_search` + weighted RRF (vector=0.4, fts=0.3, graph=0.3, конфигурируемые)
- `store.py` — embed on ingest, hybrid search
- **Surprise score** (cognitive idea #1): on ingest, compute how different new claim is from existing knowledge (~20 lines)
  ```python
  async def _compute_surprise(claim, db, embedder) -> float:
      neighbors = await vector_search(claim.embedding, db, limit=5)
      if not neighbors: return 1.0  # empty DB = max surprise
      return 1.0 - mean([n.score for n in neighbors])
  # High surprise → salience boost: claim.salience += surprise * 0.3
  # Stored in claim.metadata["surprise"]
  ```
- **Priming** (cognitive idea #2): recent search context boosts related entities (~15 lines, in-memory)
  ```python
  _recent_entities: Counter  # tracks entity frequency in recent searches
  # On search: claims with recently-queried entities get +0.02 per recent mention
  # On search: record entities from top-5 results into _recent_entities
  ```
- **Reinforce on access** (OpenMemory pattern): claims found via search get salience +0.05

**Что смотреть:**
| Что нужно | Куда смотреть |
|---|---|
| sqlite-vec cosine search Python API | https://github.com/asg017/sqlite-vec/blob/main/README.md → "Vector search" |
| Hybrid search SQLite + sqlite-vec + FTS5 (готовый код) | https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/ |
| Hybrid search пример #2 (FTS5 + RRF, чистый код) | https://ceaksan.com/en/hybrid-search-fts5-vector-rrf/ |
| Параллельный TEMPR retrieval (семантика) | https://github.com/vectorize-io/hindsight → README "How recall works" |
| RRF формула оригинал (2 стр.) | https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf |
| Reinforce on access pattern | OpenMemory HSG: auto-reinforce on query (+0.05 salience, update last_seen) |

**Тесты:** `test_vector_search_finds_similar`, `test_hybrid_rrf_merges_correctly`, `test_search_without_embedder_falls_back_to_fts`, `test_surprise_score_high_for_novel`, `test_surprise_score_low_for_similar`, `test_priming_boosts_recent_entities`, `test_reinforce_on_access`

---

### Фаза 3 — Collision detection + waypoints (День 3–4)

**Цель:** новый claim → автоматически найти связанные / противоречащие. Waypoint graph.

**Файлы:** `dedup.py`, `collisions.py`, update `store.py`, `graph.py`

**Задачи:**
- `dedup.py` — `_shannon_entropy` + MinHash + LSH bands + `MinHashDedup.is_duplicate()` + атрибуция Graphiti
- `collisions.py` — **two-level** collision detection:
  - Level 1: Structural (same entities + overlapping validity → auto-conflict, OpenMemory pattern)
  - Level 2: Semantic (vector + entity + temporal + waypoint → weighted score)
  - `apply_salience_updates()` — LLM-free rules (contradiction → drop, confirms → boost)
- `graph.py` — `get_shared_entities()` + waypoint creation + 1-hop expansion
- **Waypoint creation on ingest** (OpenMemory pattern): each new claim auto-links to its most similar existing claim (cosine ≥ 0.75)
  ```python
  # On ingest after embedding:
  best_match = await vector_search(claim.embedding, db, limit=1)
  if best_match and best_match[0].score >= 0.75:
      await _create_waypoint(claim.id, best_match[0].claim.id, best_match[0].score)
  ```
- `store.py` — dedup check + collision detection + waypoint creation in `add_claims()`

**Что смотреть:**
| Что нужно | Куда смотреть |
|---|---|
| MinHash + LSH + Jaccard (брать напрямую, Apache 2.0) | https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/dedup_helpers.py |
| Entropy gate объяснение + обоснование | https://blog.getzep.com/graphiti-hits-20k-stars-mcp-server-1-0/ → "Entropy-gated fuzzy matching" |
| Structural conflict detection | OpenMemory: `packages/openmemory-js/src/temporal_graph/` → `find_conflicting_facts()` |
| Waypoint graph pattern | OpenMemory: `packages/openmemory-js/src/memory/hsg.ts` → waypoint linking |
| Temporal invalidation (expired_at) | https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py |

**Тесты:** `test_structural_collision_same_entity`, `test_semantic_collision_vector_plus_entity`, `test_waypoint_created_on_ingest`, `test_waypoint_expansion_in_search`, `test_salience_drops_on_contradiction`, `test_salience_boosts_on_confirmation`, `test_dedup_blocks_exact_and_fuzzy`, EigenLayer→ZetaDA end-to-end

---

### Фаза 4 — Extraction + temporal + consolidation + source fingerprinting (День 4–5)

**Цель:** `store.add("raw text")` работает. Claims supersede. Consolidation. Source profiles.

**Файлы:** `extract.py`, `temporal.py`, update `store.py`

**Задачи:**
- `extract.py` — context-aware EXTRACT_PROMPT с `type` + `confidence` + `temporal` + `relevance` + `relations`
- `temporal.py`:
  - `supersede()`, `timeline()`, `cleanup()`, auto-supersede при collision score > 0.9
  - **Exponential decay** (OpenMemory pattern): `salience *= e^(-decay_rate * days_since_access)`
  - Decay rates per ClaimType: FACT=0.005, EXPERIENCE=0.010, OBSERVATION=0.008, OPINION=0.020
- `store.py` — `add()` (text → extract → dedup → embed → collisions → supersede → waypoint)
- `store.py` — `reevaluate()` (re-extract from old episode with new context)
- `store.py` — `timeline()`, `cleanup()`
- **Consolidation** (cognitive idea #3, template-based, no LLM): ~60 lines
  ```python
  async def consolidate(self, days=7, min_cluster=3) -> list[Claim]:
      # 1. SQL: find claim pairs with ≥2 shared entities in last N days
      # 2. Union-Find: group into connected components
      # 3. Filter: keep clusters with ≥ min_cluster claims
      # 4. Template: "Pattern: {count} claims about {entities} from {sources} over {days} days"
      # 5. Save as ClaimType.OBSERVATION with salience=0.8
  ```
- **Source fingerprinting** (cognitive idea #5): ~40 lines
  ```python
  async def source_stats(self, source: str) -> dict:
      # Returns: total_claims, avg_salience, confirmed_ratio, avg_surprise,
      #          sentiment_profile, top_entities, claim_frequency
      # Signal Hunter uses this to auto-calibrate salience on ingest:
      #   source_trust = (await store.source_stats(source))["confirmed_ratio"]
      #   claim.salience *= source_trust
  ```

**Context-aware extraction prompt (extract.py):**
```
You are extracting information for a specific research goal.

RESEARCH GOAL: {context.goal}
DOMAIN: {context.domain}

Extract claims from this text that are RELEVANT to the research goal above.
Skip information that is not relevant to the goal.

For each claim, also:
- Rate its relevance to the research goal (0.0-1.0)
- Identify entity relationships (who did what to whom)

Return ONLY valid JSON:
{
  "claims": [
    {
      "text": "atomic claim",
      "type": "fact|experience|observation|opinion",
      "entities": ["Entity1", "Entity2"],
      "temporal": "when this happened, or null",
      "confidence": 0.0-1.0,
      "relevance": 0.0-1.0
    }
  ],
  "relations": [
    {
      "from": "Entity1",
      "to": "Entity2",
      "type": "PARTNERED_WITH|INVESTED_IN|DEPARTED_FROM|...",
      "fact": "human readable description"
    }
  ]
}

If nothing is relevant to the research goal, return {"claims": [], "relations": []}
```

**Without context** (no goal specified):
Falls back to generic extraction — all claims extracted without relevance filtering.

**reevaluate()** — re-runs extraction on stored episode with new context:
```python
async def reevaluate(self, episode_id: str, context: Context) -> IngestResult:
    episode = await self._get_episode(episode_id)
    # Same raw text, different context → different claims
    return await self._extract_and_store(episode.raw_text, episode, context)
```

**Что смотреть:**
| Что нужно | Куда смотреть |
|---|---|
| `reflect()` семантика + use-cases | https://github.com/vectorize-io/hindsight → README "The reflect operation" |
| CARA: disposition + opinion update (LLM-based, Phase 5++) | https://arxiv.org/abs/2512.12818 → Section 3.2 + Appendix A |
| Консолидация при противоречиях | https://aws.amazon.com/blogs/machine-learning/building-smarter-ai-agents-agentcore-long-term-memory-deep-dive/ → "Conflicting information" |
| Superseding + expired_at паттерн Graphiti | https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py |

**Тесты:** `test_add_text_extracts_with_type`, `test_reflect_updates_confidence`, `test_reflect_creates_observation`, `test_timeline_shows_superseded`, `test_auto_supersede_on_high_score`

---

### Фаза 5 — Publish (День 5–6)

**Цель:** `pip install tensory` работает. Документация. CI.

**Задачи:**
- `pyproject.toml` — финальная конфигурация
- `README.md` — quick start (3 строки) + раздел "Learning via Reflection" + раздел "Graph backends"
- `__init__.py` — чистый публичный API
- GitHub Actions CI — lint + typecheck + test на Python 3.11–3.13
- pyright strict mode pass

**Что смотреть:**
| Что нужно | Куда смотреть |
|---|---|
| README структура + quick start пример | https://github.com/getzep/graphiti/blob/main/README.md |
| README с minimal API (3 строки) | https://github.com/mem0ai/mem0/blob/main/README.md |
| pyproject.toml с несколькими optional extras | https://github.com/getzep/graphiti/blob/main/pyproject.toml |

---

### Фаза 5+ — Neo4jBackend (отдельный PR, после стабилизации)

Не включать в первый релиз. Три реализации GraphBackend одновременно сложно тестировать.

**Задачи:** `Neo4jBackend` с полным Protocol, тесты с Docker testcontainer, документация "Scaling to Neo4j"

**Что смотреть:**
- Neo4j async Python driver → https://neo4j.com/docs/python-manual/current/async/
- Graphiti Neo4j driver (референс, не копировать напрямую) → https://github.com/getzep/graphiti/blob/main/graphiti_core/driver/neo4j_driver.py

---

### Фаза 5++ — LLM-based reflect + CARA (отдельный PR)

**Задачи:** полноценные CARA-промпты в `reflect()`, auto-fact-checking, `timeline(type="opinion")`

**Что смотреть:**
- CARA промпты → https://arxiv.org/abs/2512.12818 Appendix A (Hindsight paper)
- Auto-fact-checking через cross-source voting → https://yenra.com/ai20/disinformation-and-misinformation-detection/ → "Temporal and Event Correlation"

---

### Фаза 5+++ — MCP server (отдельный PR)

**Цель:** Claude Code / Cursor / Aider могут использовать tensory как persistent memory.

**Задачи:**
- `tensory-mcp/` — MCP server plugin
- Tools: `store_claim`, `search_claims`, `get_timeline`, `get_collisions`
- `pip install tensory[mcp]`

**Что смотреть:**
- OpenMemory MCP implementation → `CaviraOSS/OpenMemory`
- Memori MCP plugin pattern

---

### Фаза 6 — Signal Hunter migration (День 7–8)

**Цель:** Signal Hunter использует tensory, `pipeline.py` < 150 строк.

**Задачи:**
- Добавить `tensory` в Signal Hunter `pyproject.toml`
- Переписать `pipeline.py`
- Удалить: `storage/graph.py` (Graphiti wrapper), `storage/insight_store.py`
- Удалить `graphiti-core` из зависимостей
- Docker compose больше не требует Neo4j для basic режима

---

## ВАЖНО: Порядок работы для агента-разработчика

**Перед написанием каждого модуля — сначала изучи reference implementation.**
Не изобретай велосипед. Читай чужой код, бери паттерны, адаптируй.

### Обязательные reference implementations по модулям

| Модуль tensory | Сначала изучить | Что именно взять |
|---|---|---|
| `dedup.py` | **Graphiti** `utils/dedup_helpers.py` ([github](https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/dedup_helpers.py)) | MinHash + LSH + Jaccard + entropy gate. Копировать с атрибуцией (Apache 2.0) |
| `search.py` | **sqlite-memory** `hybrid search` ([github](https://github.com/sqliteai/sqlite-memory)) | vector_weight/text_weight паттерн для hybrid search на SQLite. Самый близкий по стеку! |
| `search.py` | **alexgarcia.xyz** hybrid search пример ([blog](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/)) | Готовый Python код: sqlite-vec + FTS5 + RRF в одном файле |
| `collisions.py` (surprise) | **mnemos** `SurprisalGate` ([github](https://github.com/anthony-maio/mnemos)) | Prediction error → salience boost. Reference для нашего `_compute_surprise()` |
| `search.py` (priming) | **mnemos** `SpreadingActivation` ([github](https://github.com/anthony-maio/mnemos)) | Energy decay 20%, associative retrieval. Reference для нашего priming + waypoints |
| `temporal.py` (consolidation) | **mnemos** `SleepDaemon` ([github](https://github.com/anthony-maio/mnemos)) | Episodic → semantic transfer. Reference для нашего `consolidate()` |
| `collisions.py` (structural) | **OpenMemory** `temporal_graph/` ([local](../../../OpenMemory/packages/openmemory-js/src/temporal_graph/)) | `find_conflicting_facts()` — same subject+predicate detection |
| `temporal.py` (decay) | **OpenMemory** `memory/hsg.ts` ([local](../../../OpenMemory/packages/openmemory-js/src/memory/hsg.ts)) | Exponential decay + tiered storage + reinforce on access |
| `graph.py` | **Graphiti** `driver/` ([github](https://github.com/getzep/graphiti/tree/main/graphiti_core/driver)) | GraphBackend Protocol abstraction pattern |
| `schema.py` | **sqlite-vec** README ([github](https://github.com/asg017/sqlite-vec)) | vec0 virtual table setup + Python integration |
| `extract.py` | **Graphiti** `prompts/extract_edges.py` ([github](https://github.com/getzep/graphiti/tree/main/graphiti_core/prompts)) | Fact extraction + temporal bounds. Адаптировать для claims |

**Порядок: READ reference → UNDERSTAND pattern → ADAPT for claims → WRITE code → TEST.**

---

## Сводная таблица: что откуда брать

| Компонент | Источник | Лицензия | Что делать |
|---|---|---|---|
| MinHash + LSH + Jaccard | `github.com/getzep/graphiti` → `utils/dedup_helpers.py` | **Apache 2.0** | Копировать с атрибуцией |
| Entropy gate | `blog.getzep.com/graphiti-hits-20k-stars-mcp-server-1-0/` | — | Реализовать самому |
| GraphBackend Protocol | `github.com/getzep/graphiti/tree/main/graphiti_core/driver` | Apache 2.0 | Взять структуру |
| Temporal invalidation | `github.com/getzep/graphiti` → `edges.py` | Apache 2.0 | Взять паттерн |
| Parallel RRF (идея) | Hindsight README | MIT | Реализовать самому |
| ClaimType + confidence | Hindsight paper, arxiv.org/abs/2512.12818 | — | Идея |
| CARA + disposition | Hindsight paper, Appendix A | — | Промпты для Phase 5++ |
| WAL pragma | dev.to/nathanhamlett article | — | 2 строки кода |
| LLM on write принцип | gerus-lab.hashnode.dev | — | Архитектурный принцип |
| sqlite-vec setup | `github.com/asg017/sqlite-vec` | MIT | Примеры кода |
| **Hybrid search (sqlite-memory)** | `github.com/sqliteai/sqlite-memory` | MIT | **Reference implementation для search.py** |
| Hybrid search (blog) | alexgarcia.xyz + ceaksan.com | — | Готовый Python код |
| reflect() use-cases | Hindsight README | MIT | Идея + примеры |
| **Salience + decay model** | OpenMemory HSG (`CaviraOSS/OpenMemory`) | MIT | Паттерн: exponential decay + reinforce on access |
| **Waypoint graph** | OpenMemory HSG | MIT | Паттерн: 1-hop associative links, auto-created on ingest |
| **Structural collision** | OpenMemory temporal graph → `find_conflicting_facts` | MIT | Паттерн: same entity + same predicate = conflict |
| **Reinforce on access** | OpenMemory HSG query flow | MIT | +0.05 salience on search hit |
| **SurprisalGate** | **mnemos** (`anthony-maio/mnemos`) | MIT | **Reference для surprise score — изучить перед Phase 2** |
| **SpreadingActivation** | **mnemos** | MIT | **Reference для priming + waypoints — изучить перед Phase 2-3** |
| **SleepDaemon** | **mnemos** | MIT | **Reference для consolidation — изучить перед Phase 4** |
| **Surprise score** | Cognitive science + mnemos | — | Adapt SurprisalGate pattern |
| **Priming** | Cognitive science + mnemos | — | Adapt SpreadingActivation pattern |
| **Consolidation** | Hindsight + OpenMemory + mnemos | MIT | Adapt SleepDaemon pattern |
| **Sentiment tagging** | Standard NLP pattern | — | Keyword-based, ~30 lines |
| **Source fingerprinting** | Our innovation | — | SQL aggregates over source's claim history |

---

## Что НЕ брать

| Что | Почему |
|---|---|
| Kuzu | Discontinued октябрь 2025, Kuzu Inc закрылась |
| FalkorDB | FalkorDBLite = fork subprocess + Unix socket, не "один файл" |
| Hindsight архитектура | Docker + PostgreSQL + HTTP API — антипаттерн для embedded lib |
| Neo4j в Phase 1–4 | Добавлять только после стабилизации базовой архитектуры |
| mnemos как зависимость | Брать паттерны, НЕ импортировать. Их код — reference, не dependency |
| LangChain/LlamaIndex adapters | Phase 5+ после стабилизации API. Каждый adapter = maintenance |
| Local embedder (sentence-transformers) | Тянет torch ~2GB. Убивает "pip install и поехали". Ollama adapter — Phase 5+ |

---

## Когнитивные механизмы (все zero-LLM, ~285 строк суммарно)

| Механизм | Фаза | Строк | Как в мозге | Что делает в tensory |
|---|---|---|---|---|
| **Salience + decay** | 1 | ~50 | Забываем неважное со временем | Claims затухают экспоненциально, разные rates per type |
| **Sentiment tagging** | 1 | ~30 | Эмоциональное запоминается ярче | "Breaking: hack" → urgent → salience boost |
| **Surprise score** | 2 | ~20 | Необычное привлекает внимание | Новый claim далёк от известного → salience boost |
| **Priming** | 2 | ~15 | Недавний контекст усиливает восприятие | Часто ищешь "EigenLayer" → claims про него ранжируются выше |
| **Reinforce on access** | 2 | ~10 | Обращение к памяти укрепляет её | Claim найден через search → salience +0.05 |
| **Waypoints** | 3 | ~40 | Ассоциативные связи | Каждый claim линкуется к ближайшему (cosine ≥ 0.75) |
| **Structural collision** | 3 | ~30 | "Подожди, это противоречит тому что я знал" | Same entity + different value → auto-conflict |
| **Consolidation** | 4 | ~60 | Во сне мозг обобщает дневной опыт | Кластеризация claims → OBSERVATION claims |
| **Source fingerprinting** | 4 | ~40 | Учимся кому доверять | Auto-профиль: confirmed_ratio, avg_surprise per source |

---

## Критерии готовности

### Фазы 1–4 (библиотека готова):
- [ ] `store.add("text")` extracts claims + computes surprise + creates waypoint
- [ ] EigenLayer + ZetaDA сценарий находит collision (structural + semantic)
- [ ] Salience decay работает: old claims.salience < new claims.salience
- [ ] `store.consolidate()` создаёт OBSERVATION claims из кластеров
- [ ] `store.source_stats(source)` возвращает профиль надёжности
- [ ] `store.reevaluate(episode, new_context)` извлекает новые claims из старого текста
- [ ] `pip install tensory` работает без Neo4j, Docker
- [ ] pyright strict mode pass

### Фаза 5 (опубликована):
- [ ] Quick start в README: 3 строки кода работают
- [ ] CI зелёный на Python 3.11–3.13
- [ ] `pip install tensory[neo4j]` работает

### Фаза 6 (Signal Hunter мигрирован):
- [ ] `pipeline.py` < 150 строк
- [ ] `graphiti-core` полностью удалён
- [ ] Docker compose не требует Neo4j для basic режима

---

## Future ideas (after v0.1.0 — НЕ делать до релиза)

Всё ниже — идеи для v0.2+. Не добавлять в Phase 1-4.

- [ ] **MutableRAG** (mnemos) — reconsolidation при противоречии (labile flag + async overwrite)
- [ ] **AffectiveRouter** (mnemos) — affective_score в relevance_scores
- [ ] **Local embedder** — `tensory[local]` с sentence-transformers или Ollama (тянет torch ~2GB)
- [ ] **LangChain adapter** — `Tensory.as_langchain_memory()`
- [ ] **LlamaIndex adapter** — `Tensory.as_llama_index_store()`
- [ ] **Letta self-editing mode** — `agent_managed=True` в Context, агент сам редактирует claims
- [ ] **Cognee-style cognify()** — multimodal ingest (PDF, images → claims)
- [ ] **Markdown-aware chunking** (sqlite-memory pattern) — max_tokens + overlay
- [ ] **process_id / session_id** в metadata (Memori pattern)
- [ ] **LoCoMo / LongMemEval benchmarks** — формальная оценка recall quality
- [ ] **Vector compression** (OpenMemory pattern) — cold claims → reduced embedding dims
- [ ] **Multi-agent sync** (sqlite-memory pattern) — offline-first sync между агентами