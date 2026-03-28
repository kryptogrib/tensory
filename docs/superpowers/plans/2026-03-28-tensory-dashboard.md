# Tensory Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a readonly dashboard (Home + Claims Browser + Graph Explorer) for debugging and demoing Tensory.

**Architecture:** Python service layer (`tensory/service.py`) → FastAPI REST API (`api/`) → Next.js 15+ SPA (`ui/`). Service layer queries `store._db` directly for reads. Graph backend gets new list/query methods. Frontend uses TanStack Query + React Flow + TanStack Table.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, aiosqlite | Next.js 15+, TypeScript, Tailwind CSS v4, shadcn/ui, React Flow, TanStack Table/Query

**Spec:** `docs/superpowers/specs/2026-03-28-tensory-dashboard-design.md`

---

## File Map

### Python (Backend)

| File | Responsibility | Action |
|------|---------------|--------|
| `tensory/graph.py` | GraphBackend protocol + SQLiteGraphBackend | Modify: add `list_entities()`, `list_edges()`, `subgraph()` |
| `tests/test_graph.py` | Graph backend tests | Modify: add tests for new methods |
| `tensory/service.py` | TensoryService read-only query layer | Create |
| `tests/test_service.py` | Service layer tests | Create |
| `api/__init__.py` | Package marker | Create (empty) |
| `api/main.py` | FastAPI app, CORS, lifespan | Create |
| `api/dependencies.py` | `get_service()` DI | Create |
| `api/routers/__init__.py` | Package marker | Create (empty) |
| `api/routers/stats.py` | GET /api/stats | Create |
| `api/routers/claims.py` | GET /api/claims, /claims/{id}, /search | Create |
| `api/routers/graph.py` | GET /api/graph/* | Create |
| `tests/test_api.py` | FastAPI endpoint tests (httpx) | Create |
| `pyproject.toml` | Add `[ui]` extras | Modify |

### TypeScript (Frontend)

| File | Responsibility | Action |
|------|---------------|--------|
| `ui/package.json` | Next.js deps | Create (via create-next-app) |
| `ui/tailwind.config.ts` | Ember theme colors | Create/Modify |
| `ui/app/globals.css` | Base styles, monospace font | Modify |
| `ui/app/layout.tsx` | Root layout | Modify |
| `ui/app/(dashboard)/layout.tsx` | Dashboard shell: sidebar | Create |
| `ui/app/(dashboard)/page.tsx` | Home (graph + HUD) | Create |
| `ui/app/(dashboard)/claims/page.tsx` | Claims Browser | Create |
| `ui/app/(dashboard)/graph/page.tsx` | Graph Explorer | Create |
| `ui/lib/api.ts` | Typed fetch client | Create |
| `ui/lib/types.ts` | TypeScript types matching Pydantic | Create |
| `ui/hooks/use-stats.ts` | TanStack Query: stats | Create |
| `ui/hooks/use-claims.ts` | TanStack Query: claims | Create |
| `ui/hooks/use-graph.ts` | TanStack Query: graph | Create |
| `ui/providers/query-provider.tsx` | TanStack Query provider | Create |
| `ui/components/dashboard/Sidebar.tsx` | Icon sidebar (44px) | Create |
| `ui/components/dashboard/StatsBar.tsx` | HUD stats bar | Create |
| `ui/components/dashboard/LiveFeed.tsx` | Recent claims window | Create |
| `ui/components/dashboard/EntityBadges.tsx` | Active entities window | Create |
| `ui/components/dashboard/GraphViewer.tsx` | React Flow canvas | Create |
| `ui/components/dashboard/PulseNode.tsx` | Custom React Flow node | Create |
| `ui/components/dashboard/SalienceEdge.tsx` | Custom React Flow edge | Create |
| `ui/components/dashboard/CursorGlow.tsx` | Background cursor trail | Create |
| `ui/components/dashboard/ClaimsTable.tsx` | TanStack Table | Create |
| `ui/components/dashboard/HudWindow.tsx` | Reusable HUD container | Create |

### Infrastructure

| File | Responsibility | Action |
|------|---------------|--------|
| `docker-compose.yml` | api + ui services | Create |
| `Dockerfile.api` | Python API container | Create |
| `ui/Dockerfile` | Next.js frontend container | Create |
| `.gitignore` | Unignore docs/superpowers | Modify |

---

## Task 0: Fix .gitignore for docs/superpowers

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Add exception for docs/superpowers**

In `.gitignore`, change the `/docs` rule to allow `docs/superpowers/`:

```
/docs
!/docs/superpowers/
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: unignore docs/superpowers in .gitignore"
```

---

## Task 1: GraphBackend — New Read Methods

**Files:**
- Modify: `tensory/graph.py`
- Modify: `tests/test_graph.py`

- [ ] **Step 1: Write failing tests for `list_entities()`**

In `tests/test_graph.py`, add:

```python
async def test_list_entities(store: Tensory) -> None:
    """list_entities returns entities ordered by mention_count DESC."""
    await store.add_claims([
        Claim(text="Google builds AI", entities=["Google"]),
        Claim(text="Google partners with Meta", entities=["Google", "Meta"]),
        Claim(text="Apple releases iPhone", entities=["Apple"]),
    ])
    entities = await store._graph.list_entities(limit=10, min_mentions=1)
    assert len(entities) >= 2
    # Google has 2 mentions, should be first
    assert entities[0]["name"] == "Google"
    assert entities[0]["mention_count"] >= 2
    # All entities have required fields
    for e in entities:
        assert "id" in e
        assert "name" in e
        assert "type" in e
        assert "mention_count" in e
        assert "first_seen" in e


async def test_list_entities_min_mentions_filter(store: Tensory) -> None:
    """list_entities respects min_mentions filter."""
    await store.add_claims([
        Claim(text="Google builds AI", entities=["Google"]),
        Claim(text="Google partners with Meta", entities=["Google", "Meta"]),
    ])
    entities = await store._graph.list_entities(limit=10, min_mentions=2)
    names = [e["name"] for e in entities]
    assert "Google" in names
    assert "Meta" not in names  # Meta only has 1 mention
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_graph.py::test_list_entities tests/test_graph.py::test_list_entities_min_mentions_filter -v`
Expected: FAIL — `AttributeError: 'SQLiteGraphBackend' object has no attribute 'list_entities'`

- [ ] **Step 3: Implement `list_entities()` on protocol and SQLiteGraphBackend**

In `tensory/graph.py`, add to `GraphBackend` protocol:

```python
async def list_entities(
    self, *, limit: int = 100, min_mentions: int = 1
) -> list[dict[str, object]]:
    """List entities ordered by mention_count DESC."""
    ...
```

In `SQLiteGraphBackend`, implement:

```python
async def list_entities(
    self, *, limit: int = 100, min_mentions: int = 1
) -> list[dict[str, object]]:
    """List entities ordered by mention_count DESC."""
    rows = await self._db.execute_fetchall(
        """SELECT id, name, type, mention_count, first_seen
           FROM entities
           WHERE mention_count >= ?
           ORDER BY mention_count DESC
           LIMIT ?""",
        (min_mentions, limit),
    )
    return [
        {
            "id": r[0],
            "name": r[1],
            "type": r[2],
            "mention_count": r[3],
            "first_seen": r[4],
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_graph.py::test_list_entities tests/test_graph.py::test_list_entities_min_mentions_filter -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for `list_edges()`**

```python
async def test_list_edges(store: Tensory) -> None:
    """list_edges returns non-expired entity relations."""
    result = await store.add_claims([
        Claim(text="Google partners with Meta", entities=["Google", "Meta"]),
    ])
    # add_claims creates entities but not relations directly;
    # we need to add an edge manually via the graph backend
    await store._graph.add_edge(
        "google-id", "meta-id", "PARTNERED_WITH",
        properties={"fact": "Google partners with Meta", "confidence": 0.9},
    )
    edges = await store._graph.list_edges()
    assert len(edges) >= 1
    edge = edges[0]
    assert "from_entity" in edge
    assert "to_entity" in edge
    assert "rel_type" in edge
    assert "confidence" in edge


async def test_list_edges_entity_filter(store: Tensory) -> None:
    """list_edges filters by entity when specified."""
    await store.add_claims([
        Claim(text="A works with B", entities=["A", "B"]),
        Claim(text="C works with D", entities=["C", "D"]),
    ])
    # Get entity IDs
    entities_a = await store._graph.list_entities(limit=100, min_mentions=1)
    id_map = {e["name"]: e["id"] for e in entities_a}

    await store._graph.add_edge(id_map["A"], id_map["B"], "WORKS_WITH")
    await store._graph.add_edge(id_map["C"], id_map["D"], "WORKS_WITH")

    edges = await store._graph.list_edges(entity_filter=id_map["A"])
    # Should only get edges involving entity A
    for edge in edges:
        assert edge["from_entity"] == id_map["A"] or edge["to_entity"] == id_map["A"]
```

- [ ] **Step 6: Implement `list_edges()`**

Protocol addition:

```python
async def list_edges(
    self, *, entity_filter: str | None = None
) -> list[dict[str, object]]:
    """List entity relations. Optionally filter by entity ID."""
    ...
```

SQLiteGraphBackend implementation:

```python
async def list_edges(
    self, *, entity_filter: str | None = None
) -> list[dict[str, object]]:
    """List entity relations, optionally filtered by entity ID."""
    if entity_filter:
        rows = await self._db.execute_fetchall(
            """SELECT id, from_entity, to_entity, rel_type, fact,
                      episode_id, confidence, created_at, expired_at
               FROM entity_relations
               WHERE expired_at IS NULL
                 AND (from_entity = ? OR to_entity = ?)
               ORDER BY created_at DESC""",
            (entity_filter, entity_filter),
        )
    else:
        rows = await self._db.execute_fetchall(
            """SELECT id, from_entity, to_entity, rel_type, fact,
                      episode_id, confidence, created_at, expired_at
               FROM entity_relations
               WHERE expired_at IS NULL
               ORDER BY created_at DESC""",
        )
    return [
        {
            "id": r[0],
            "from_entity": r[1],
            "to_entity": r[2],
            "rel_type": r[3],
            "fact": r[4],
            "episode_id": r[5],
            "confidence": r[6],
            "created_at": r[7],
            "expired_at": r[8],
        }
        for r in rows
    ]
```

- [ ] **Step 7: Run edge tests**

Run: `uv run pytest tests/test_graph.py::test_list_edges tests/test_graph.py::test_list_edges_entity_filter -v`
Expected: PASS

- [ ] **Step 8: Write failing test for `subgraph()`**

```python
async def test_subgraph(store: Tensory) -> None:
    """subgraph returns nodes and edges within depth from entity."""
    await store.add_claims([
        Claim(text="Google works with Meta", entities=["Google", "Meta"]),
        Claim(text="Meta partners with Apple", entities=["Meta", "Apple"]),
    ])
    entities = await store._graph.list_entities(limit=100, min_mentions=1)
    id_map = {e["name"]: e["id"] for e in entities}

    await store._graph.add_edge(id_map["Google"], id_map["Meta"], "WORKS_WITH")
    await store._graph.add_edge(id_map["Meta"], id_map["Apple"], "PARTNERED_WITH")

    result = await store._graph.subgraph("Google", depth=2)
    assert "nodes" in result
    assert "edges" in result
    node_names = {n["name"] for n in result["nodes"]}
    assert "Google" in node_names
    assert "Meta" in node_names  # 1 hop away
```

- [ ] **Step 9: Implement `subgraph()`**

Protocol:

```python
async def subgraph(
    self, entity_name: str, *, depth: int = 2
) -> dict[str, list[dict[str, object]]]:
    """Get subgraph around entity: nodes + edges within depth hops."""
    ...
```

SQLiteGraphBackend:

```python
async def subgraph(
    self, entity_name: str, *, depth: int = 2
) -> dict[str, list[dict[str, object]]]:
    """Get subgraph around entity within depth hops."""
    # 1. Get reachable entity IDs via traverse
    entity_ids = await self.traverse(entity_name, depth=depth)

    if not entity_ids:
        return {"nodes": [], "edges": []}

    # 2. Fetch entity rows
    placeholders = ",".join("?" for _ in entity_ids)
    node_rows = await self._db.execute_fetchall(
        f"""SELECT id, name, type, mention_count, first_seen
            FROM entities WHERE id IN ({placeholders})""",
        entity_ids,
    )
    nodes = [
        {"id": r[0], "name": r[1], "type": r[2],
         "mention_count": r[3], "first_seen": r[4]}
        for r in node_rows
    ]

    # 3. Fetch edges between these entities
    edge_rows = await self._db.execute_fetchall(
        f"""SELECT id, from_entity, to_entity, rel_type, fact,
                   confidence, created_at, expired_at
            FROM entity_relations
            WHERE expired_at IS NULL
              AND from_entity IN ({placeholders})
              AND to_entity IN ({placeholders})""",
        entity_ids + entity_ids,
    )
    edges = [
        {"id": r[0], "from_entity": r[1], "to_entity": r[2],
         "rel_type": r[3], "fact": r[4], "confidence": r[5],
         "created_at": r[6], "expired_at": r[7]}
        for r in edge_rows
    ]

    return {"nodes": nodes, "edges": edges}
```

- [ ] **Step 10: Run subgraph test + full graph test suite**

Run: `uv run pytest tests/test_graph.py -v`
Expected: ALL PASS

- [ ] **Step 11: Add stub implementations to Neo4jBackend**

`Neo4jBackend` also implements the `GraphBackend` protocol. Add stub methods to maintain protocol compliance:

```python
async def list_entities(self, *, limit: int = 100, min_mentions: int = 1) -> list[dict[str, object]]:
    """List entities ordered by mention_count DESC."""
    msg = "list_entities not yet implemented for Neo4j"
    raise NotImplementedError(msg)

async def list_edges(self, *, entity_filter: str | None = None) -> list[dict[str, object]]:
    """List entity relations."""
    msg = "list_edges not yet implemented for Neo4j"
    raise NotImplementedError(msg)

async def subgraph(self, entity_name: str, *, depth: int = 2) -> dict[str, list[dict[str, object]]]:
    """Get subgraph around entity."""
    msg = "subgraph not yet implemented for Neo4j"
    raise NotImplementedError(msg)
```

- [ ] **Step 12: Run pyright on graph.py + ruff**

Run: `uv run pyright tensory/graph.py && uv run ruff check tensory/graph.py`
Expected: 0 errors

- [ ] **Step 13: Commit**

```bash
git add tensory/graph.py tests/test_graph.py
git commit -m "feat(graph): add list_entities, list_edges, subgraph read methods"
```

---

## Task 2: Service Layer — TensoryService

**Files:**
- Create: `tensory/service.py`
- Create: `tests/test_service.py`
- Modify: `tensory/__init__.py` (export TensoryService)

- [ ] **Step 1: Write failing tests for response models + `get_stats()`**

Create `tests/test_service.py`:

```python
"""Tests for tensory/service.py — read-only dashboard query layer."""

import pytest
from tensory import Claim, ClaimType, Tensory
from tensory.service import (
    ClaimDetail,
    DashboardStats,
    EdgeData,
    EntityNode,
    PaginatedClaims,
    SubGraph,
    TensoryService,
)


@pytest.fixture
async def service() -> TensoryService:
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    # Seed test data
    await store.add_claims([
        Claim(text="Google builds AI chips", entities=["Google"], type=ClaimType.FACT),
        Claim(text="Meta launches Llama 4", entities=["Meta"], type=ClaimType.FACT),
        Claim(text="AI hype is overblown", entities=["AI"], type=ClaimType.OPINION),
    ])
    yield svc
    await store.close()


async def test_get_stats(service: TensoryService) -> None:
    stats = await service.get_stats()
    assert isinstance(stats, DashboardStats)
    assert stats.counts["claims"] == 3
    assert stats.claims_by_type["fact"] == 2
    assert stats.claims_by_type["opinion"] == 1
    assert 0.0 <= stats.avg_salience <= 1.0
    assert len(stats.recent_claims) <= 5
    assert len(stats.hot_entities) <= 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_service.py::test_get_stats -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tensory.service'`

- [ ] **Step 3: Implement service.py with models and `get_stats()`**

Create `tensory/service.py` with module docstring, all Pydantic response models, and `TensoryService.get_stats()`. The implementation queries `store._db` directly for counts, claims_by_type, avg_salience, recent_claims (5 most recent), and hot_entities (top 5 by mention_count).

Key implementation detail: Use `store._db.execute_fetchall()` for raw SQL reads. Parse claim rows into `Claim` models. Parse entity rows into `EntityNode` models.

Exclude `Claim.embedding` from serialization by creating a `ClaimResponse` model or using `model_config = ConfigDict(json_schema_extra=...)` to exclude the field.

- [ ] **Step 4: Run test and verify pass**

Run: `uv run pytest tests/test_service.py::test_get_stats -v`
Expected: PASS

- [ ] **Step 5: Write + implement `list_claims()` with tests**

Test should cover: basic pagination (offset/limit), type_filter, salience_min/max, sort_by/sort_order, total count accuracy.

```python
async def test_list_claims_pagination(service: TensoryService) -> None:
    result = await service.list_claims(offset=0, limit=2)
    assert isinstance(result, PaginatedClaims)
    assert len(result.items) == 2
    assert result.total == 3
    assert result.offset == 0
    assert result.limit == 2


async def test_list_claims_type_filter(service: TensoryService) -> None:
    result = await service.list_claims(offset=0, limit=10, type_filter="opinion")
    assert result.total == 1
    assert result.items[0].type == ClaimType.OPINION
```

Implement using dynamic SQL with parameterized WHERE clauses.

- [ ] **Step 6: Run list_claims tests**

Run: `uv run pytest tests/test_service.py -k list_claims -v`
Expected: PASS

- [ ] **Step 7: Write + implement `get_claim()` with test**

```python
async def test_get_claim(service: TensoryService) -> None:
    claims = await service.list_claims(offset=0, limit=1)
    claim_id = claims.items[0].id
    detail = await service.get_claim(claim_id)
    assert isinstance(detail, ClaimDetail)
    assert detail.claim.id == claim_id
    assert isinstance(detail.waypoints, list)
```

Implementation joins claims + episodes, queries waypoints table, and fetches related entity_relations. **Note:** `collisions` field returns empty list `[]` for MVP — collisions are computed on-the-fly at ingest time and not persisted. A collisions cache/table can be added later.

- [ ] **Step 8: Write + implement `search_claims()` with test**

```python
async def test_search_claims(service: TensoryService) -> None:
    results = await service.search_claims("Google", limit=5)
    assert len(results) >= 1
    # SearchResult has .claim (Claim model) and .score
    assert any("Google" in r.claim.text for r in results)
```

Delegates to `store.search()`. Note: the existing `SearchResult` model contains a `claim: Claim` field — verify this matches the actual model before implementing. If the model differs (e.g., uses `claim_id` instead), adapt the service method to reconstruct the full Claim.

- [ ] **Step 9: Write + implement graph methods with tests**

```python
async def test_get_graph_entities(service: TensoryService) -> None:
    entities = await service.get_graph_entities(limit=10, min_mentions=1)
    assert len(entities) >= 1
    assert all(isinstance(e, EntityNode) for e in entities)


async def test_get_graph_edges(service: TensoryService) -> None:
    edges = await service.get_graph_edges()
    assert isinstance(edges, list)
    # May be empty if no relations were added


async def test_get_entity_subgraph(service: TensoryService) -> None:
    result = await service.get_entity_subgraph("Google", depth=2)
    assert isinstance(result, SubGraph)
    assert isinstance(result.nodes, list)
    assert isinstance(result.edges, list)
```

Delegate to `store._graph.list_entities()`, `list_edges()`, `subgraph()`.

- [ ] **Step 9b: Write + implement `get_entity_claims()` with test**

```python
async def test_get_entity_claims(service: TensoryService) -> None:
    claims = await service.get_entity_claims("Google")
    assert len(claims) >= 1
    assert all("Google" in c.entities for c in claims)
```

Implementation: query `claim_entities` JOIN `claims` WHERE entity name matches. Uses the entities table to resolve name → entity_id first.

- [ ] **Step 10: Run full service test suite + pyright + ruff**

Run: `uv run pytest tests/test_service.py -v && uv run pyright tensory/service.py && uv run ruff check tensory/service.py`
Expected: ALL PASS, 0 pyright errors

- [ ] **Step 11: Export TensoryService from __init__.py**

Add `TensoryService` to `tensory/__init__.py` exports.

- [ ] **Step 12: Commit**

```bash
git add tensory/service.py tests/test_service.py tensory/__init__.py
git commit -m "feat: add TensoryService read-only dashboard query layer"
```

---

## Task 3: FastAPI Backend

**Files:**
- Create: `api/__init__.py`, `api/main.py`, `api/dependencies.py`
- Create: `api/routers/__init__.py`, `api/routers/stats.py`, `api/routers/claims.py`, `api/routers/graph.py`
- Create: `tests/test_api.py`
- Modify: `pyproject.toml` (add `[ui]` extras)

- [ ] **Step 1: Add FastAPI deps to pyproject.toml**

Add to `[project.optional-dependencies]`:

```toml
ui = ["fastapi>=0.115", "uvicorn[standard]>=0.34", "httpx>=0.28"]
```

Also update `pyproject.toml` to include `api/` in pyright include paths and ruff targets, so CI picks them up.

Run: `uv sync --all-extras`

- [ ] **Step 2: Write failing test for /api/stats endpoint**

Create `tests/test_api.py`:

```python
"""Tests for FastAPI API endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app
from tensory import Claim, ClaimType, Tensory
from tensory.service import TensoryService


@pytest.fixture
async def client() -> AsyncClient:
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    await store.add_claims([
        Claim(text="Google builds AI", entities=["Google"], type=ClaimType.FACT),
        Claim(text="AI hype is overblown", entities=["AI"], type=ClaimType.OPINION),
    ])
    app = create_app(service=svc)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await store.close()


async def test_stats_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "counts" in data
    assert "avg_salience" in data
    assert "recent_claims" in data
    assert "hot_entities" in data
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py::test_stats_endpoint -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'api'`

- [ ] **Step 4: Implement FastAPI app skeleton + stats router**

Create `api/__init__.py` (empty), `api/routers/__init__.py` (empty).

Create `api/dependencies.py`:
```python
"""FastAPI dependency injection for TensoryService."""
from tensory.service import TensoryService

_service: TensoryService | None = None

def set_service(svc: TensoryService) -> None:
    global _service
    _service = svc

def get_service() -> TensoryService:
    assert _service is not None, "Service not initialized"
    return _service
```

Create `api/main.py`:
```python
"""FastAPI application for Tensory Dashboard."""
import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tensory import Tensory
from tensory.service import TensoryService
from api.dependencies import set_service, get_service
from api.routers import stats, claims, graph


def create_app(*, service: TensoryService | None = None) -> FastAPI:
    """Create FastAPI app. Pass service for testing, or None for production."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service:
            set_service(service)
        else:
            db_path = os.getenv("TENSORY_DB_PATH", "data/tensory.db")
            store = await Tensory.create(db_path)
            set_service(TensoryService(store))
        yield
        svc = get_service()
        await svc.store.close()

    app = FastAPI(title="Tensory Dashboard API", lifespan=lifespan)

    origins = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    app.include_router(stats.router, prefix="/api")
    app.include_router(claims.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")

    return app

# Module-level app for uvicorn (guarded — not used in tests)
app = create_app()
```

**Important:** In the lifespan, skip `close()` when a service is injected (test mode), to avoid double-close with test fixtures:

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if service:
        set_service(service)
        yield  # test mode — caller manages lifecycle
    else:
        db_path = os.getenv("TENSORY_DB_PATH", "data/tensory.db")
        store = await Tensory.create(db_path)
        set_service(TensoryService(store))
        yield
        svc = get_service()
        await svc.store.close()
```

Create `api/routers/stats.py`:
```python
"""Stats endpoint."""
from fastapi import APIRouter, Depends
from tensory.service import DashboardStats, TensoryService
from api.dependencies import get_service

router = APIRouter(tags=["stats"])

@router.get("/stats", response_model=DashboardStats)
async def get_stats(svc: TensoryService = Depends(get_service)) -> DashboardStats:
    return await svc.get_stats()
```

- [ ] **Step 5: Run stats test**

Run: `uv run pytest tests/test_api.py::test_stats_endpoint -v`
Expected: PASS

- [ ] **Step 6: Implement claims router + tests**

Create `api/routers/claims.py` with endpoints:
- `GET /claims` → `list_claims()` with query params
- `GET /claims/{claim_id}` → `get_claim()`
- `GET /search` → `search_claims()`

Tests:
```python
async def test_list_claims_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/claims?offset=0&limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data

async def test_search_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/search?q=Google&limit=5")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 7: Implement graph router + tests**

Create `api/routers/graph.py` with endpoints:
- `GET /graph/entities` → `get_graph_entities()`
- `GET /graph/edges` → `get_graph_edges()`
- `GET /graph/subgraph/{entity}` → `get_entity_subgraph()`
- `GET /graph/entity/{name}/claims` → `get_entity_claims()`

Tests:
```python
async def test_graph_entities_endpoint(client: AsyncClient) -> None:
    resp = await client.get("/api/graph/entities?limit=10")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
```

- [ ] **Step 8: Run full API test suite + pyright**

Run: `uv run pytest tests/test_api.py -v && uv run pyright api/`
Expected: ALL PASS, 0 pyright errors

- [ ] **Step 9: Verify OpenAPI schema generation**

Run: `uv run python -c "from api.main import app; import json; print(json.dumps(app.openapi(), indent=2)[:500])"`
Expected: Valid OpenAPI JSON with all endpoints

- [ ] **Step 10: Commit**

```bash
git add api/ tests/test_api.py pyproject.toml
git commit -m "feat: add FastAPI REST API for dashboard"
```

---

## Task 4: Next.js Scaffolding + Ember Theme

**Files:**
- Create: `ui/` (via create-next-app)
- Modify: `ui/tailwind.config.ts`, `ui/app/globals.css`, `ui/app/layout.tsx`
- Create: `ui/providers/query-provider.tsx`
- Create: `ui/lib/types.ts`, `ui/lib/api.ts`

- [ ] **Step 1: Create Next.js project**

```bash
cd /Users/chelovek/Work/tensory
npx create-next-app@latest ui --typescript --tailwind --app --eslint --src-dir=false --import-alias="@/*" --no-git
```

- [ ] **Step 2: Install dependencies**

```bash
cd ui
npm install @tanstack/react-query @tanstack/react-table @xyflow/react lucide-react date-fns
npm install -D @types/node
```

- [ ] **Step 2b: Initialize shadcn/ui and install components**

```bash
cd ui
npx shadcn@latest init
npx shadcn@latest add table card badge button dialog separator
```

- [ ] **Step 3: Configure Ember theme in Tailwind CSS v4**

Tailwind v4 uses CSS-based configuration via `@theme` directive in `globals.css` instead of `tailwind.config.ts`. Add Ember color tokens using the `@theme` block:
- `bg-base: #0a0908`
- `accent-primary: #d97706`
- `accent-secondary: #ea580c`
- `text-primary: #f5e6d3`
- etc.

Set monospace font family: `'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace`

- [ ] **Step 4: Set up globals.css with Ember base styles**

Dark background, monospace default font, custom scrollbar styling, selection color.

```css
:root {
  --bg-base: #0a0908;
  --bg-surface: rgba(10, 9, 8, 0.82);
  --accent-primary: #d97706;
  --text-primary: #f5e6d3;
}

body {
  background: var(--bg-base);
  color: var(--text-primary);
  font-family: 'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace;
}
```

- [ ] **Step 5: Create TypeScript types**

Create `ui/lib/types.ts` matching the Pydantic response models from the spec: `DashboardStats`, `Claim`, `ClaimType`, `PaginatedClaims`, `ClaimDetail`, `EntityNode`, `EdgeData`, `SubGraph`, `SearchResult`.

- [ ] **Step 6: Create typed API client**

Create `ui/lib/api.ts` with typed fetch functions:

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchStats(): Promise<DashboardStats> { ... }
export async function fetchClaims(params: ClaimFilters): Promise<PaginatedClaims> { ... }
export async function fetchGraphEntities(params: ...): Promise<EntityNode[]> { ... }
// etc.
```

- [ ] **Step 7: Create TanStack Query provider**

Create `ui/providers/query-provider.tsx` wrapping `QueryClientProvider`. Wire into root `layout.tsx`.

- [ ] **Step 8: Create TanStack Query hooks**

Create `ui/hooks/use-stats.ts`, `ui/hooks/use-claims.ts`, `ui/hooks/use-graph.ts` with `useQuery` wrappers using the typed API client.

- [ ] **Step 9: Verify Next.js builds**

Run: `cd ui && npm run build`
Expected: Build succeeds

- [ ] **Step 10: Commit**

```bash
git add ui/
git commit -m "feat: scaffold Next.js frontend with Ember theme and API hooks"
```

---

## Task 5: Dashboard Shell — Sidebar + HUD Components

**Files:**
- Create: `ui/components/dashboard/HudWindow.tsx`
- Create: `ui/components/dashboard/Sidebar.tsx`
- Create: `ui/components/dashboard/StatsBar.tsx`
- Create: `ui/components/dashboard/LiveFeed.tsx`
- Create: `ui/components/dashboard/EntityBadges.tsx`
- Create: `ui/app/(dashboard)/layout.tsx`

- [ ] **Step 1: Create HudWindow reusable component**

Glass-morphism container: `bg-surface` background, `backdrop-filter: blur(12px)`, `border-subtle` border, rounded corners. Props: `title`, `className`, `children`, optional `action` (e.g., "all →").

- [ ] **Step 2: Create Sidebar component**

44px wide, icon-only navigation. Logo (gradient amber→orange square, "T"), 3 nav icons (Home, Claims, Graph), Settings at bottom. Active state: amber background. Uses `usePathname()` for active detection.

- [ ] **Step 3: Create StatsBar component**

Terminal-style stats display: `$ claims 1,247 +23 | salience 0.73 | entities 342 | collisions 18`. Uses `useStats()` hook. Search trigger (⌘K) placeholder at right. HudWindow styling.

- [ ] **Step 4: Create LiveFeed component**

Recent claims list inside HudWindow. Each item: left-border color by type, claim text, meta line (type · salience · relative time). Opacity fades with salience. Uses `useStats()` for `recent_claims`.

- [ ] **Step 5: Create EntityBadges component**

Active entities pills inside HudWindow. Badge color brightness correlates to mention_count. Uses `useStats()` for `hot_entities`.

- [ ] **Step 6: Create dashboard layout**

`ui/app/(dashboard)/layout.tsx`: Sidebar on left (fixed), children fill rest. This is the shell shared by all 3 screens.

- [ ] **Step 7: Verify visual with dev server**

Run: `cd ui && npm run dev`
Open: `http://localhost:3000` — should see sidebar + empty content area with Ember theme.

- [ ] **Step 8: Commit**

```bash
git add ui/components/ ui/app/
git commit -m "feat: dashboard shell — sidebar, stats bar, HUD components"
```

---

## Task 6: Graph Explorer — React Flow Canvas

**Files:**
- Create: `ui/components/dashboard/GraphViewer.tsx`
- Create: `ui/components/dashboard/PulseNode.tsx`
- Create: `ui/components/dashboard/SalienceEdge.tsx`
- Create: `ui/components/dashboard/CursorGlow.tsx`
- Create: `ui/app/(dashboard)/page.tsx` (Home)
- Create: `ui/app/(dashboard)/graph/page.tsx`

- [ ] **Step 1: Create PulseNode custom React Flow node**

SVG-based node with:
- Outer pulse rings (count based on `mention_count` bucket)
- Breathing boundary circle
- Core dot with glow (brightness = salience-like metric)
- Label + meta text
- CSS `transition: transform 0.2s ease` for hover scale(1.15)

Props: `EntityNode` data + computed metrics.

- [ ] **Step 2: Create SalienceEdge custom React Flow edge**

Renders SVG lines with style based on `confidence`:
- Strong (>0.7): solid, thicker, higher opacity, traveling dot animation
- Moderate (0.4-0.7): dashed, medium
- Weak (<0.4): sparse dash, thin, faint
- Decaying (<0.2): barely visible

Traveling impulse: small SVG circle with `animateMotion` along the edge path. Only on strong/moderate edges.

- [ ] **Step 3: Create CursorGlow background component**

Div behind graph canvas. On `pointermove`, updates CSS `radial-gradient` position with amber tint, ~100px radius, opacity 0.03-0.05. Single `requestAnimationFrame` for smooth updates.

- [ ] **Step 4: Create GraphViewer component**

Main React Flow canvas. Props: `mode: "entity" | "full"`.

- Fetches data via `useGraphEntities()` and `useGraphEdges()` hooks
- Transforms `EntityNode[]` → React Flow nodes with `PulseNode` type
- Transforms `EdgeData[]` → React Flow edges with `SalienceEdge` type
- Includes: zoom controls, fit view, minimap
- Click node → highlight connected, dim rest
- Double-click node → navigate to `/claims?entity=NAME`

Background: dot grid pattern + `CursorGlow`.

- [ ] **Step 5: Create Graph controls panel**

Scanline-style buttons: ENTITY / FULL GRAPH / DEPTH: 2 / SHOW WEAK. Positioned top-right as HudWindow. Controls graph mode toggle and edge visibility filter.

- [ ] **Step 6: Create edge strength legend**

Small HudWindow top-left (below stats): visual guide for solid/dashed/sparse edge meanings.

- [ ] **Step 7: Wire up Home page**

`ui/app/(dashboard)/page.tsx`: Full GraphViewer canvas + StatsBar (top) + LiveFeed (bottom-right) + EntityBadges (bottom-left) + Legend (top-left) + Controls (top-right) + Zoom (bottom-center).

All HUD windows use absolute positioning over the graph canvas.

- [ ] **Step 8: Wire up Graph Explorer page**

`ui/app/(dashboard)/graph/page.tsx`: Same as Home but with different HUD focus (more graph controls, less feed). Or simply reuse the Home layout — spec says they share the same canvas.

- [ ] **Step 9: Test with API running**

Terminal 1: `uv run uvicorn api.main:app --reload --port 8000`
Terminal 2: `cd ui && npm run dev`

Open `http://localhost:3000` — should see graph with nodes/edges (if DB has data) or empty state.

- [ ] **Step 10: Commit**

```bash
git add ui/components/dashboard/ ui/app/
git commit -m "feat: graph explorer with Pulse Rings nodes, salience edges, cursor glow"
```

---

## Task 7: Claims Browser — TanStack Table

**Files:**
- Create: `ui/components/dashboard/ClaimsTable.tsx`
- Create: `ui/app/(dashboard)/claims/page.tsx`

- [ ] **Step 1: Create ClaimsTable component**

TanStack Table v8 with columns from spec:
- Text (truncated, expand on click)
- Type (color-coded badge: fact=amber, opinion=deep-amber, observation=orange, experience=lime)
- Entities (pills, clickable → filter)
- Salience (gradient bar + number)
- Relevance (only shown when context filter active)
- Source
- Created (relative time via `date-fns formatDistanceToNow`)

Features:
- Server-side pagination (offset/limit via `useClaims()` hook)
- Column sorting (passes `sort_by`/`sort_order` to API)
- Row expand on click: full text + episode raw_text + collisions + waypoints

- [ ] **Step 2: Create filter controls**

Above table:
- Type multi-select (checkboxes or dropdown)
- Salience range (two inputs or slider)
- Entity searchable input
- Full-text search input → calls `/api/search`

All filters update URL query params and trigger `useClaims()` refetch.

- [ ] **Step 3: Create Claims page**

`ui/app/(dashboard)/claims/page.tsx`: StatsBar (top) + ClaimsTable (main content area). Same sidebar from layout. No graph canvas on this page.

- [ ] **Step 4: Test with API**

Navigate to `http://localhost:3000/claims` — should see table with data or empty state.

- [ ] **Step 5: Commit**

```bash
git add ui/components/dashboard/ClaimsTable.tsx ui/app/
git commit -m "feat: claims browser with TanStack Table, filters, pagination"
```

---

## Task 8: Docker Compose + Final Integration

**Files:**
- Create: `docker-compose.yml`
- Modify: `.gitignore` (unignore docs/superpowers)
- Run: full integration test

- [ ] **Step 1: Create Dockerfile.api and ui/Dockerfile**

`Dockerfile.api`:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --extra ui
COPY tensory/ tensory/
COPY api/ api/
CMD ["uv", "run", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`ui/Dockerfile`:
```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
CMD ["npm", "start"]
```

- [ ] **Step 2: Create docker-compose.yml**

```yaml
services:
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    ports:
      - "8000:8000"
    environment:
      - TENSORY_DB_PATH=/data/tensory.db
      - CORS_ORIGINS=http://localhost:3000,http://frontend:3000
    volumes:
      - ./data:/data

  frontend:
    build:
      context: ./ui
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - api
```

- [ ] **Step 3: Run full test suite**

```bash
uv run pytest tests/ -v
uv run pyright tensory/ api/
uv run ruff check tensory/ api/ tests/
```

Expected: ALL PASS

- [ ] **Step 4: Integration smoke test**

Terminal 1: `uv run uvicorn api.main:app --reload`
Terminal 2: `cd ui && npm run dev`

Verify:
- `http://localhost:8000/docs` → Swagger UI with all endpoints
- `http://localhost:3000` → Home with graph canvas
- `http://localhost:3000/claims` → Claims table
- Navigate between pages via sidebar

- [ ] **Step 5: Final commit**

```bash
git add docker-compose.yml Dockerfile.api ui/Dockerfile
git commit -m "feat: docker compose + Dockerfiles for deployment"
```
