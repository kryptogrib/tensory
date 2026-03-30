# Timeline UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/timeline` page to the Tensory dashboard that combines entity history (branching timeline) with graph playback (time-travel slider with ghost nodes).

**Architecture:** Three new backend service methods + one API router expose temporal data. Frontend adds a `/timeline` page using a shared `useGraphLayout` hook (extracted from existing `GraphViewer`) plus new components: `EntityTimeline`, `TimelineSlider`, `GhostNode`. Same `PulseNode`/`SalienceEdge` as main graph.

**Tech Stack:** Python 3.11+ / FastAPI / aiosqlite (backend), Next.js 16 / React 19 / React Flow / d3-force / TanStack Query (frontend)

**Spec:** `docs/superpowers/specs/2026-03-30-timeline-ui-design.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `tensory/service.py` (modify) | Add `TimelineEntry`, `HistogramBucket`, `GraphSnapshot`, `TimelineRange` models + 3 service methods |
| `api/routers/timeline.py` (create) | Three GET endpoints: entity timeline, snapshot, range |
| `api/main.py` (modify) | Register timeline router |
| `tests/test_timeline_api.py` (create) | Backend integration tests (7 tests) |
| `ui/lib/types.ts` (modify) | Add `TimelineEntry`, `GraphSnapshot`, `HistogramBucket`, `TimelineRange` |
| `ui/lib/api.ts` (modify) | Add 3 fetch functions |
| `ui/hooks/use-timeline.ts` (create) | 3 TanStack Query hooks |
| `ui/hooks/use-graph-layout.ts` (create) | Shared d3-force hook extracted from GraphViewer |
| `ui/components/dashboard/GraphViewer.tsx` (modify) | Refactor to use `useGraphLayout` |
| `ui/components/dashboard/GhostNode.tsx` (create) | Dashed/dim React Flow custom node |
| `ui/components/dashboard/TimelineSlider.tsx` (create) | Range slider + histogram bars |
| `ui/components/dashboard/EntityTimeline.tsx` (create) | Branching timeline list |
| `ui/components/dashboard/TimelinePage.tsx` (create) | Layout orchestrator |
| `ui/app/(dashboard)/timeline/page.tsx` (create) | Route page |
| `ui/components/dashboard/Sidebar.tsx` (modify) | Add Timeline nav item |

---

## Task 1: Backend Models

**Files:**
- Modify: `tensory/service.py` (add models after line ~98, before `TensoryService` class)

- [ ] **Step 1: Add Pydantic models to service.py**

Add after the existing `ClaimDetail` model (around line 98):

```python
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
```

- [ ] **Step 2: Run type check**

Run: `uv run pyright tensory/service.py`
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add tensory/service.py
git commit -m "feat(timeline): add Pydantic models for timeline API"
```

---

## Task 2: Service Methods — `get_entity_timeline`

**Files:**
- Modify: `tensory/service.py` (add method to `TensoryService` class, after `get_entity_claims` ~line 555)
- Test: `tests/test_timeline_api.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_timeline_api.py`:

```python
"""Tests for timeline service methods and API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tensory.models import Claim, ClaimType
from tensory.service import TensoryService, TimelineEntry
from tensory.store import Tensory


@pytest.fixture
async def service_with_timeline() -> TensoryService:
    """Service with claims that form a supersede chain."""
    store = await Tensory.create(":memory:")
    now = datetime.now(timezone.utc)

    old_claim = Claim(
        id="claim-old",
        text="ETH price is $2400",
        claim_type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.9,
        created_at=now - timedelta(days=10),
    )
    new_claim = Claim(
        id="claim-new",
        text="ETH price is $2800",
        claim_type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.95,
        created_at=now - timedelta(days=5),
        superseded_by=None,
    )
    other_claim = Claim(
        id="claim-other",
        text="ETH uses proof of stake",
        claim_type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.99,
        created_at=now - timedelta(days=3),
    )

    await store.add_claims([old_claim, new_claim, other_claim])

    # Supersede old → new
    db = store._db
    assert db is not None
    await db.execute(
        "UPDATE claims SET superseded_at = ?, superseded_by = ? WHERE id = ?",
        (now - timedelta(days=5), "claim-new", "claim-old"),
    )
    await db.commit()

    svc = TensoryService(store)
    yield svc  # type: ignore[misc]
    await store.close()


async def test_entity_timeline_returns_chronological_order(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline("Ethereum")
    assert len(entries) >= 2
    dates = [e.claim.created_at for e in entries]
    assert dates == sorted(dates), "Timeline must be chronologically ordered"


async def test_entity_timeline_includes_superseded(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline(
        "Ethereum", include_superseded=True
    )
    ids = [e.claim.id for e in entries]
    assert "claim-old" in ids, "Superseded claims must be included"


async def test_entity_timeline_supersedes_reverse_lookup(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline("Ethereum")
    entry_map = {e.claim.id: e for e in entries}
    new_entry = entry_map.get("claim-new")
    assert new_entry is not None
    assert new_entry.supersedes == "claim-old", (
        "supersedes must point to the claim THIS claim replaced"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: FAIL — `TensoryService` has no `get_entity_timeline` method

- [ ] **Step 3: Implement `get_entity_timeline`**

Add to `TensoryService` class in `tensory/service.py`:

```python
async def get_entity_timeline(
    self,
    entity_name: str,
    *,
    include_superseded: bool = True,
    limit: int = 50,
) -> list[TimelineEntry]:
    """Get chronological timeline of claims for an entity."""
    from tensory.temporal import timeline as _timeline

    db = self._store._db
    assert db is not None

    claims = await _timeline(
        entity_name, db, include_superseded=include_superseded, limit=limit
    )

    entries: list[TimelineEntry] = []
    for claim in claims:
        # Reverse lookup: find the claim that THIS claim superseded
        supersedes: str | None = None
        cursor = await db.execute(
            "SELECT id FROM claims WHERE superseded_by = ?", (claim.id,)
        )
        row = await cursor.fetchone()
        if row:
            supersedes = str(row[0])

        entries.append(TimelineEntry(claim=claim, supersedes=supersedes))

    return entries
```

Note: `self._store` references the `Tensory` instance. Check the constructor — it stores as `self._store` (line 261: `self._store = store`). The `_db` attribute is the aiosqlite connection.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add tensory/service.py tests/test_timeline_api.py
git commit -m "feat(timeline): add get_entity_timeline service method with tests"
```

---

## Task 3: Service Methods — `get_graph_snapshot`

**Files:**
- Modify: `tensory/service.py`
- Modify: `tests/test_timeline_api.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_timeline_api.py`:

```python
async def test_graph_snapshot_filters_by_date(
    service_with_timeline: TensoryService,
) -> None:
    """Snapshot at a date should only show entities with first_seen <= at."""
    now = datetime.now(timezone.utc)
    # Snapshot at a time before any claims → should have 0 active
    early = now - timedelta(days=30)
    snapshot = await service_with_timeline.get_graph_snapshot(early)
    assert len(snapshot.active_nodes) == 0
    assert len(snapshot.ghost_nodes) >= 1, "Future entities should be ghosts"


async def test_graph_snapshot_ghost_nodes(
    service_with_timeline: TensoryService,
) -> None:
    """Ghost nodes are entities that don't exist yet at the given time."""
    now = datetime.now(timezone.utc)
    # Snapshot at current time → all entities active, no ghosts
    snapshot = await service_with_timeline.get_graph_snapshot(now)
    assert len(snapshot.active_nodes) >= 1
    ghost_names = [n.name for n in snapshot.ghost_nodes]
    active_names = [n.name for n in snapshot.active_nodes]
    # No overlap
    assert not set(ghost_names) & set(active_names)


async def test_graph_snapshot_superseded_excluded(
    service_with_timeline: TensoryService,
) -> None:
    """Claims superseded before `at` should not count toward active stats."""
    now = datetime.now(timezone.utc)
    snapshot = await service_with_timeline.get_graph_snapshot(now)
    assert snapshot.stats["superseded"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeline_api.py::test_graph_snapshot_filters_by_date -v`
Expected: FAIL — `get_graph_snapshot` not found

- [ ] **Step 3: Implement `get_graph_snapshot`**

Add to `TensoryService` class:

```python
async def get_graph_snapshot(self, at: datetime) -> GraphSnapshot:
    """Get the state of the knowledge graph at a point in time."""
    db = self._store._db
    assert db is not None
    at_str = at.isoformat()

    # Active entities: first_seen <= at
    cursor = await db.execute(
        """SELECT id, name, type, mention_count, first_seen
           FROM entities WHERE first_seen <= ?
           ORDER BY mention_count DESC""",
        (at_str,),
    )
    active_rows = await cursor.fetchall()
    active_nodes = [
        EntityNode(
            id=str(r[0]),
            name=str(r[1]),
            type=str(r[2]) if r[2] else None,
            mention_count=int(r[3]),
            first_seen=_parse_datetime(str(r[4])),
        )
        for r in active_rows
    ]

    # Ghost entities: first_seen > at
    cursor = await db.execute(
        """SELECT id, name, type, mention_count, first_seen
           FROM entities WHERE first_seen > ?
           ORDER BY first_seen ASC""",
        (at_str,),
    )
    ghost_rows = await cursor.fetchall()
    ghost_nodes = [
        EntityNode(
            id=str(r[0]),
            name=str(r[1]),
            type=str(r[2]) if r[2] else None,
            mention_count=int(r[3]),
            first_seen=_parse_datetime(str(r[4])),
        )
        for r in ghost_rows
    ]

    # Active edges: created_at <= at AND (expired_at IS NULL OR expired_at > at)
    active_entity_ids = [n.id for n in active_nodes]
    edges: list[EdgeData] = []
    if active_entity_ids:
        placeholders = ",".join("?" * len(active_entity_ids))
        cursor = await db.execute(
            f"""SELECT e1.name, e2.name, er.rel_type, er.fact,
                       er.confidence, er.created_at, er.expired_at
                FROM entity_relations er
                JOIN entities e1 ON er.from_entity = e1.id
                JOIN entities e2 ON er.to_entity = e2.id
                WHERE er.created_at <= ?
                  AND (er.expired_at IS NULL OR er.expired_at > ?)
                  AND er.from_entity IN ({placeholders})
                  AND er.to_entity IN ({placeholders})""",
            (at_str, at_str, *active_entity_ids, *active_entity_ids),
        )
        edge_rows = await cursor.fetchall()
        edges = [
            EdgeData(
                from_entity=str(r[0]),
                to_entity=str(r[1]),
                rel_type=str(r[2]) if r[2] else "",
                fact=str(r[3]) if r[3] else "",
                confidence=float(r[4]) if r[4] else 0.0,
                created_at=str(r[5]),
                expired_at=str(r[6]) if r[6] else None,
            )
            for r in edge_rows
        ]

    # Stats
    cursor = await db.execute(
        "SELECT COUNT(*) FROM claims WHERE created_at <= ?",
        (at_str,),
    )
    total_row = await cursor.fetchone()
    total_claims = int(total_row[0]) if total_row else 0

    cursor = await db.execute(
        "SELECT COUNT(*) FROM claims WHERE created_at <= ? AND superseded_at IS NOT NULL AND superseded_at <= ?",
        (at_str, at_str),
    )
    sup_row = await cursor.fetchone()
    superseded = int(sup_row[0]) if sup_row else 0

    return GraphSnapshot(
        active_nodes=active_nodes,
        ghost_nodes=ghost_nodes,
        edges=edges,
        stats={"claims": total_claims, "superseded": superseded},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add tensory/service.py tests/test_timeline_api.py
git commit -m "feat(timeline): add get_graph_snapshot service method with tests"
```

---

## Task 4: Service Methods — `get_timeline_range`

**Files:**
- Modify: `tensory/service.py`
- Modify: `tests/test_timeline_api.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_timeline_api.py`:

```python
async def test_timeline_range_histogram(
    service_with_timeline: TensoryService,
) -> None:
    result = await service_with_timeline.get_timeline_range()
    assert result.min_date is not None
    assert result.max_date is not None
    assert result.min_date <= result.max_date
    assert len(result.event_histogram) >= 1
    total_events = sum(b.count for b in result.event_histogram)
    assert total_events >= 3, "Should count all claims in histogram"


async def test_timeline_range_empty_db() -> None:
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    result = await svc.get_timeline_range()
    assert result.min_date == result.max_date
    assert len(result.event_histogram) == 0
    await store.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_timeline_api.py::test_timeline_range_histogram -v`
Expected: FAIL

- [ ] **Step 3: Implement `get_timeline_range`**

Add to `TensoryService` class:

```python
async def get_timeline_range(self) -> TimelineRange:
    """Get the date range and event histogram for the timeline slider."""
    db = self._store._db
    assert db is not None

    cursor = await db.execute(
        "SELECT MIN(created_at), MAX(created_at) FROM claims"
    )
    row = await cursor.fetchone()
    if not row or row[0] is None:
        now = datetime.now(timezone.utc).isoformat()
        return TimelineRange(
            min_date=now, max_date=now, event_histogram=[]
        )

    min_date = str(row[0])
    max_date = str(row[1])

    cursor = await db.execute(
        """SELECT date(created_at) as day, COUNT(*) as cnt
           FROM claims
           GROUP BY date(created_at)
           ORDER BY day ASC"""
    )
    histogram_rows = await cursor.fetchall()
    histogram = [
        HistogramBucket(date=str(r[0]), count=int(r[1]))
        for r in histogram_rows
    ]

    return TimelineRange(
        min_date=min_date,
        max_date=max_date,
        event_histogram=histogram,
    )
```

Add the `datetime` and `timezone` imports at the top of service.py if not already present.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: 8 PASS

- [ ] **Step 5: Run type check**

Run: `uv run pyright tensory/service.py`
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add tensory/service.py tests/test_timeline_api.py
git commit -m "feat(timeline): add get_timeline_range service method with tests"
```

---

## Task 5: API Router

**Files:**
- Create: `api/routers/timeline.py`
- Modify: `api/main.py` (line 27 import, line 76 include_router)
- Modify: `tests/test_timeline_api.py` (add API-level tests)

- [ ] **Step 1: Create the timeline router**

Create `api/routers/timeline.py`:

```python
"""Timeline API endpoints for temporal knowledge visualization."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_service
from tensory.service import TensoryService

router = APIRouter(prefix="/timeline", tags=["timeline"])
ServiceDep = Annotated[TensoryService, Depends(get_service)]


@router.get("/{entity_name}")
async def get_entity_timeline(
    entity_name: str,
    service: ServiceDep,
    include_superseded: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    """Get chronological timeline of claims for an entity."""
    entries = await service.get_entity_timeline(
        entity_name, include_superseded=include_superseded, limit=limit
    )
    return [
        {
            "claim": e.claim.model_dump(exclude={"embedding"}),
            "supersedes": e.supersedes,
        }
        for e in entries
    ]


@router.get("/snapshot/at")
async def get_graph_snapshot(
    service: ServiceDep,
    at: str = Query(..., description="ISO datetime for snapshot"),
) -> dict[str, Any]:
    """Get knowledge graph state at a point in time."""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {at}") from exc

    snapshot = await service.get_graph_snapshot(dt)
    return snapshot.model_dump()


@router.get("/range/bounds")
async def get_timeline_range(service: ServiceDep) -> dict[str, Any]:
    """Get date range and event histogram for timeline slider."""
    result = await service.get_timeline_range()
    return result.model_dump()
```

Note the endpoint paths: `/snapshot/at` and `/range/bounds` avoid collision with `/{entity_name}` dynamic route. FastAPI matches static routes before dynamic ones when defined first, but explicit distinct paths are safer.

- [ ] **Step 2: Register router in main.py**

In `api/main.py`, add to imports (line ~27):
```python
from api.routers import claims, graph, stats, timeline
```

Add after the graph router registration (line ~76):
```python
application.include_router(timeline.router, prefix="/api")
```

- [ ] **Step 3: Write API-level tests**

Append to `tests/test_timeline_api.py`:

```python
from httpx import ASGITransport, AsyncClient
from api.main import create_app


@pytest.fixture
async def client(service_with_timeline: TensoryService):
    app = create_app(service=service_with_timeline)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_api_entity_timeline(client: AsyncClient) -> None:
    resp = await client.get("/api/timeline/Ethereum")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 2
    assert "claim" in data[0]
    assert "supersedes" in data[0]


async def test_api_snapshot(client: AsyncClient) -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    resp = await client.get(f"/api/timeline/snapshot/at?at={now}")
    assert resp.status_code == 200
    data = resp.json()
    assert "active_nodes" in data
    assert "ghost_nodes" in data
    assert "edges" in data
    assert "stats" in data


async def test_api_range(client: AsyncClient) -> None:
    resp = await client.get("/api/timeline/range/bounds")
    assert resp.status_code == 200
    data = resp.json()
    assert "min_date" in data
    assert "max_date" in data
    assert "event_histogram" in data
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: 11 PASS

- [ ] **Step 5: Run lint + type check**

Run: `uv run pyright tensory/ api/` and `uv run ruff check tensory/ api/ tests/`
Expected: 0 errors

- [ ] **Step 6: Commit**

```bash
git add api/routers/timeline.py api/main.py tests/test_timeline_api.py
git commit -m "feat(timeline): add timeline API router with 3 endpoints"
```

---

## Task 6: Frontend Types + API Client + Hooks

**Files:**
- Modify: `ui/lib/types.ts` (append new types after line ~100)
- Modify: `ui/lib/api.ts` (append new fetch functions)
- Create: `ui/hooks/use-timeline.ts`

- [ ] **Step 1: Add TypeScript types**

Append to `ui/lib/types.ts`:

```typescript
// ── Timeline ──────────────────────────────────────

export interface TimelineEntry {
  claim: Claim;
  supersedes: string | null;
}

export interface GraphSnapshot {
  active_nodes: EntityNode[];
  ghost_nodes: EntityNode[];
  edges: EdgeData[];
  stats: { claims: number; superseded: number };
}

export interface HistogramBucket {
  date: string;
  count: number;
}

export interface TimelineRange {
  min_date: string;
  max_date: string;
  event_histogram: HistogramBucket[];
}
```

- [ ] **Step 2: Add API fetch functions**

Append to `ui/lib/api.ts`:

```typescript
export async function fetchEntityTimeline(
  entity: string,
  params?: { include_superseded?: boolean; limit?: number }
): Promise<TimelineEntry[]> {
  return apiFetch<TimelineEntry[]>(
    `/api/timeline/${encodeURIComponent(entity)}${qs(params ?? {})}`
  );
}

export async function fetchGraphSnapshot(at: string): Promise<GraphSnapshot> {
  return apiFetch<GraphSnapshot>(
    `/api/timeline/snapshot/at${qs({ at })}`
  );
}

export async function fetchTimelineRange(): Promise<TimelineRange> {
  return apiFetch<TimelineRange>("/api/timeline/range/bounds");
}
```

Add the new types to the import at the top of `api.ts`.

- [ ] **Step 3: Create TanStack Query hooks**

Create `ui/hooks/use-timeline.ts`:

```typescript
"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  fetchEntityTimeline,
  fetchGraphSnapshot,
  fetchTimelineRange,
} from "@/lib/api";

export function useTimelineRange() {
  return useQuery({
    queryKey: ["timeline-range"],
    queryFn: fetchTimelineRange,
  });
}

export function useGraphSnapshot(at: string | null) {
  return useQuery({
    queryKey: ["graph-snapshot", at],
    queryFn: () => fetchGraphSnapshot(at!),
    enabled: !!at,
    placeholderData: keepPreviousData,
  });
}

export function useEntityTimeline(entity: string | null) {
  return useQuery({
    queryKey: ["entity-timeline", entity],
    queryFn: () => fetchEntityTimeline(entity!),
    enabled: !!entity,
  });
}
```

- [ ] **Step 4: Verify no TypeScript errors**

Run: `cd ui && npx tsc --noEmit`
Expected: 0 errors (or only pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add ui/lib/types.ts ui/lib/api.ts ui/hooks/use-timeline.ts
git commit -m "feat(timeline): add frontend types, API client, and TanStack Query hooks"
```

---

## Task 7: Extract `useGraphLayout` Hook

This is the key refactoring step. Extract the d3-force layout logic from `GraphViewer.tsx` into a shared hook so both the main graph and timeline graph can reuse it.

**Files:**
- Create: `ui/hooks/use-graph-layout.ts`
- Modify: `ui/components/dashboard/GraphViewer.tsx`

- [ ] **Step 1: Create `useGraphLayout` hook**

Create `ui/hooks/use-graph-layout.ts`:

Extract the `computeLayout()` function (currently in GraphViewer.tsx lines ~47-213) and the simulation ref management into a reusable hook. The hook should:

1. Accept `entities: EntityNode[]`, `edges: EdgeData[]`, and optional physics params
2. Run `computeLayout()` internally (the pure function that does the 300-tick d3-force simulation)
3. Return positioned React Flow nodes, React Flow edges, simulation ref, adjacency maps, and confidence map
4. Expose `getSimRef()` for drag interaction

The existing `computeLayout()` function is ~165 lines of pure logic (no React). Move it as-is into the hook file and wrap it in a `useMemo`.

Read `GraphViewer.tsx` carefully before implementing — the exact shape of `SimNode`, adjacency maps, and confidence maps must match.

- [ ] **Step 2: Refactor GraphViewer to use the hook**

In `GraphViewer.tsx`:
1. Remove the `computeLayout()` function
2. Import `useGraphLayout` from the new hook
3. Replace the inline `useMemo` that calls `computeLayout()` with a call to `useGraphLayout(entities, edges, physicsParams)`
4. Keep all drag handlers, selection logic, and React Flow rendering in GraphViewer

- [ ] **Step 3: Verify the main graph page still works**

Run: `cd ui && npm run build`
Expected: Build succeeds. Then manually verify `/` page renders the graph correctly.

- [ ] **Step 4: Commit**

```bash
git add ui/hooks/use-graph-layout.ts ui/components/dashboard/GraphViewer.tsx
git commit -m "refactor: extract useGraphLayout hook from GraphViewer"
```

---

## Task 8: GhostNode Component

**Files:**
- Create: `ui/components/dashboard/GhostNode.tsx`

- [ ] **Step 1: Create GhostNode**

Create `ui/components/dashboard/GhostNode.tsx`:

```tsx
"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

interface GhostNodeData {
  name: string;
  type: string | null;
  first_seen: string;
  [key: string]: unknown;
}

function GhostNodeComponent({ data }: NodeProps) {
  const d = data as GhostNodeData;
  const size = 32;

  return (
    <div
      style={{
        width: size,
        height: size,
        position: "relative",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* Invisible handles for edges */}
      <Handle
        type="target"
        position={Position.Top}
        style={{ opacity: 0, top: "50%", left: "50%" }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{ opacity: 0, top: "50%", left: "50%" }}
      />

      {/* Dashed circle */}
      <div
        style={{
          width: size,
          height: size,
          borderRadius: "50%",
          border: "1.5px dashed rgb(var(--text-muted))",
          opacity: 0.2,
          position: "absolute",
          top: 0,
          left: 0,
        }}
      />

      {/* Label */}
      <div
        style={{
          position: "absolute",
          top: size + 4,
          left: "50%",
          transform: "translateX(-50%)",
          whiteSpace: "nowrap",
          fontSize: 8,
          color: "rgb(var(--text-muted))",
          opacity: 0.3,
          pointerEvents: "none",
        }}
      >
        {d.name}
      </div>
    </div>
  );
}

export const GhostNode = memo(GhostNodeComponent);
```

- [ ] **Step 2: Verify build**

Run: `cd ui && npx tsc --noEmit`
Expected: 0 errors

- [ ] **Step 3: Commit**

```bash
git add ui/components/dashboard/GhostNode.tsx
git commit -m "feat(timeline): add GhostNode component for future entities"
```

---

## Task 9: TimelineSlider Component

**Files:**
- Create: `ui/components/dashboard/TimelineSlider.tsx`

- [ ] **Step 1: Create TimelineSlider**

Create `ui/components/dashboard/TimelineSlider.tsx`:

```tsx
"use client";

import { memo, useCallback, useMemo } from "react";
import type { TimelineRange } from "@/lib/types";

interface TimelineSliderProps {
  range: TimelineRange;
  value: Date;
  onChange: (date: Date) => void;
}

function TimelineSliderComponent({ range, value, onChange }: TimelineSliderProps) {
  const minMs = new Date(range.min_date).getTime();
  const maxMs = new Date(range.max_date).getTime();
  const spanMs = maxMs - minMs || 1;
  const currentMs = value.getTime();

  // Histogram bar heights (normalized)
  const maxCount = useMemo(
    () => Math.max(1, ...range.event_histogram.map((b) => b.count)),
    [range.event_histogram]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const ms = Number(e.target.value);
      onChange(new Date(ms));
    },
    [onChange]
  );

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  return (
    <div
      style={{
        background: "rgba(var(--bg-surface), 0.82)",
        backdropFilter: "blur(12px)",
        borderTop: "1px solid rgba(var(--accent-primary), 0.06)",
        padding: "8px 16px 12px",
      }}
    >
      {/* Histogram */}
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 1,
          height: 32,
          marginBottom: 4,
          padding: "0 2px",
        }}
      >
        {range.event_histogram.map((bucket) => {
          const height = (bucket.count / maxCount) * 100;
          const bucketMs = new Date(bucket.date).getTime();
          const isAtPlayhead =
            Math.abs(bucketMs - currentMs) < 86400000; // within 1 day
          return (
            <div
              key={bucket.date}
              style={{
                flex: 1,
                height: `${height}%`,
                minHeight: 2,
                background: isAtPlayhead
                  ? "rgb(var(--accent-primary))"
                  : "rgba(var(--accent-primary), 0.3)",
                borderRadius: "1px 1px 0 0",
                transition: "background 150ms",
              }}
            />
          );
        })}
      </div>

      {/* Slider */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          style={{
            fontSize: 9,
            color: "rgb(var(--text-muted))",
            whiteSpace: "nowrap",
          }}
        >
          {formatDate(range.min_date)}
        </span>
        <input
          type="range"
          min={minMs}
          max={maxMs}
          value={currentMs}
          onChange={handleChange}
          style={{ flex: 1 }}
        />
        <span
          style={{
            fontSize: 9,
            color: "rgb(var(--text-muted))",
            whiteSpace: "nowrap",
          }}
        >
          {formatDate(range.max_date)}
        </span>
      </div>
    </div>
  );
}

export const TimelineSlider = memo(TimelineSliderComponent);
```

- [ ] **Step 2: Commit**

```bash
git add ui/components/dashboard/TimelineSlider.tsx
git commit -m "feat(timeline): add TimelineSlider component with histogram"
```

---

## Task 10: EntityTimeline Component (Branching)

**Files:**
- Create: `ui/components/dashboard/EntityTimeline.tsx`

- [ ] **Step 1: Create EntityTimeline**

Create `ui/components/dashboard/EntityTimeline.tsx`:

This component renders a vertical branching timeline for a selected entity. Key visual rules:
- Claims ordered chronologically (oldest first)
- Each claim = a dot on a vertical line with text + date
- Superseded claims: branch line connects old → new (`╰──superseded──╮`)
- Active claim at `currentDate`: highlighted
- Superseded claims: dimmer text, muted color

```tsx
"use client";

import { memo, useMemo } from "react";
import { format } from "date-fns";
import type { TimelineEntry } from "@/lib/types";

interface EntityTimelineProps {
  entity: string;
  entries: TimelineEntry[];
  currentDate: Date;
  onClaimClick?: (claimDate: Date) => void;
}

function EntityTimelineComponent({
  entity,
  entries,
  currentDate,
  onClaimClick,
}: EntityTimelineProps) {
  // Build supersede chain map: superseded_by → supersedes
  const supersedeMap = useMemo(() => {
    const map = new Map<string, string>(); // new_id → old_id
    for (const entry of entries) {
      if (entry.supersedes) {
        map.set(entry.claim.id, entry.supersedes);
      }
    }
    return map;
  }, [entries]);

  if (entries.length === 0) {
    return (
      <div style={{ padding: 16, color: "rgb(var(--text-secondary))", fontSize: 12 }}>
        No claims found for {entity}.
      </div>
    );
  }

  return (
    <div style={{ padding: "12px 16px", overflowY: "auto", height: "100%" }}>
      <div
        style={{
          fontSize: 10,
          color: "rgb(var(--accent-primary))",
          marginBottom: 12,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}
      >
        {entity} History
      </div>

      <div style={{ position: "relative", paddingLeft: 16 }}>
        {/* Vertical line */}
        <div
          style={{
            position: "absolute",
            left: 4,
            top: 0,
            bottom: 0,
            width: 2,
            background: "rgba(var(--accent-primary), 0.2)",
          }}
        />

        {entries.map((entry, i) => {
          const isSuperseded = entry.claim.superseded_at != null;
          const hasSupersededAnother = supersedeMap.has(entry.claim.id);
          const claimDate = new Date(entry.claim.created_at);
          const isAtPlayhead =
            Math.abs(claimDate.getTime() - currentDate.getTime()) < 86400000;

          return (
            <div
              key={entry.claim.id}
              style={{
                position: "relative",
                marginBottom: 16,
                cursor: onClaimClick ? "pointer" : "default",
              }}
              onClick={() => onClaimClick?.(claimDate)}
            >
              {/* Dot */}
              <div
                style={{
                  position: "absolute",
                  left: -14,
                  top: 2,
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: isSuperseded
                    ? "rgb(var(--decaying))"
                    : isAtPlayhead
                      ? "rgb(var(--accent-primary))"
                      : "rgb(var(--accent-secondary))",
                  boxShadow: isAtPlayhead
                    ? "0 0 6px rgb(var(--accent-primary))"
                    : "none",
                }}
              />

              {/* Branch indicator: this claim superseded another */}
              {hasSupersededAnother && (
                <div
                  style={{
                    position: "absolute",
                    left: -20,
                    top: -10,
                    fontSize: 8,
                    color: "rgb(var(--accent-primary))",
                    opacity: 0.5,
                  }}
                >
                  ╭←
                </div>
              )}

              {/* Branch indicator: this claim was superseded */}
              {isSuperseded && (
                <div
                  style={{
                    position: "absolute",
                    left: -20,
                    bottom: -6,
                    fontSize: 8,
                    color: "rgb(var(--decaying))",
                    opacity: 0.5,
                  }}
                >
                  ╰→
                </div>
              )}

              {/* Date */}
              <div
                style={{
                  fontSize: 8,
                  color: "rgb(var(--text-muted))",
                  marginBottom: 2,
                }}
              >
                {format(claimDate, "MMM d, yyyy")}
              </div>

              {/* Claim text */}
              <div
                style={{
                  fontSize: 11,
                  color: isSuperseded
                    ? "rgb(var(--decaying))"
                    : "rgb(var(--text-primary))",
                  textDecoration: isSuperseded ? "line-through" : "none",
                  lineHeight: 1.4,
                }}
              >
                {entry.claim.text}
              </div>

              {/* Type badge */}
              <div
                style={{
                  fontSize: 8,
                  color: "rgb(var(--text-tertiary))",
                  marginTop: 2,
                }}
              >
                {entry.claim.type} · {(entry.claim.confidence * 100).toFixed(0)}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const EntityTimeline = memo(EntityTimelineComponent);
```

- [ ] **Step 2: Commit**

```bash
git add ui/components/dashboard/EntityTimeline.tsx
git commit -m "feat(timeline): add EntityTimeline branching component"
```

---

## Task 11: TimelinePage + Route

**Files:**
- Create: `ui/components/dashboard/TimelinePage.tsx`
- Create: `ui/app/(dashboard)/timeline/page.tsx`
- Modify: `ui/components/dashboard/Sidebar.tsx`

- [ ] **Step 1: Create TimelinePage orchestrator**

Create `ui/components/dashboard/TimelinePage.tsx`:

This is the layout orchestrator. It manages:
- `selectedDate` state (slider position)
- `selectedEntity` state (which entity is shown in left panel)
- Debounced snapshot fetching
- Bi-directional sync between slider and entity timeline

```tsx
"use client";

import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTimelineRange, useGraphSnapshot, useEntityTimeline } from "@/hooks/use-timeline";
import { useGraphLayout } from "@/hooks/use-graph-layout";
import { TimelineSlider } from "./TimelineSlider";
import { EntityTimeline } from "./EntityTimeline";
import { PulseNode } from "./PulseNode";
import { GhostNode } from "./GhostNode";
import { SalienceEdge } from "./SalienceEdge";
import { ZoomControls } from "./ZoomControls";
import { HudWindow } from "./HudWindow";

const nodeTypes = { pulse: PulseNode, ghost: GhostNode };
const edgeTypes = { salience: SalienceEdge };

export function TimelinePage() {
  const { data: range } = useTimelineRange();
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);

  // Initialize slider to max_date when range loads
  useEffect(() => {
    if (range && !selectedDate) {
      setSelectedDate(new Date(range.max_date));
    }
  }, [range, selectedDate]);

  // Debounced date for snapshot fetching
  const [debouncedDate, setDebouncedDate] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!selectedDate) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      setDebouncedDate(selectedDate.toISOString());
    }, 150);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [selectedDate]);

  const { data: snapshot } = useGraphSnapshot(debouncedDate);
  const { data: entityEntries } = useEntityTimeline(selectedEntity);

  // Combine active + ghost entities for layout input
  const allEntities = useMemo(() => {
    if (!snapshot) return [];
    return [
      ...snapshot.active_nodes,
      ...snapshot.ghost_nodes.map((n) => ({ ...n, id: `ghost-${n.id}` })),
    ];
  }, [snapshot]);

  // Use shared d3-force layout (same physics as main graph)
  const { nodes: layoutNodes, edges: layoutEdges } = useGraphLayout(
    allEntities,
    snapshot?.edges ?? [],
  );

  // Assign correct node types (pulse vs ghost) after layout
  const nodes: Node[] = useMemo(() => {
    if (!snapshot) return [];
    const ghostIdSet = new Set(snapshot.ghost_nodes.map((n) => `ghost-${n.id}`));
    return layoutNodes.map((node) => ({
      ...node,
      type: ghostIdSet.has(node.id) ? "ghost" : "pulse",
    }));
  }, [layoutNodes, snapshot]);

  const edges = layoutEdges;

  const handleNodeClick = useCallback((_: unknown, node: Node) => {
    if (node.type === "ghost") return;
    const name = (node.data as { name: string }).name;
    setSelectedEntity(name);
  }, []);

  const handleClaimClick = useCallback((claimDate: Date) => {
    setSelectedDate(claimDate);
  }, []);

  if (!range) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%" }}>
        <span style={{ color: "rgb(var(--text-secondary))", fontSize: 12 }}>Loading timeline...</span>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100%", width: "100%" }}>
      {/* Left panel: Entity Timeline */}
      <div
        style={{
          width: 300,
          minWidth: 300,
          borderRight: "1px solid rgba(var(--accent-primary), 0.06)",
          display: "flex",
          flexDirection: "column",
          background: "rgba(var(--bg-surface), 0.82)",
        }}
      >
        {/* Entity picker */}
        <div
          style={{
            padding: "8px 12px",
            borderBottom: "1px solid rgba(var(--accent-primary), 0.06)",
            fontSize: 10,
            color: "rgb(var(--text-secondary))",
          }}
        >
          {selectedEntity ? (
            <span>
              Entity:{" "}
              <span style={{ color: "rgb(var(--text-primary))" }}>{selectedEntity}</span>
              <button
                onClick={() => setSelectedEntity(null)}
                style={{
                  marginLeft: 8,
                  background: "none",
                  border: "none",
                  color: "rgb(var(--text-muted))",
                  cursor: "pointer",
                  fontSize: 10,
                }}
              >
                ✕
              </button>
            </span>
          ) : (
            "Click a node to see its history"
          )}
        </div>

        {/* Timeline entries */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          {selectedEntity && entityEntries ? (
            <EntityTimeline
              entity={selectedEntity}
              entries={entityEntries}
              currentDate={selectedDate ?? new Date()}
              onClaimClick={handleClaimClick}
            />
          ) : (
            <div
              style={{
                padding: 16,
                color: "rgb(var(--text-muted))",
                fontSize: 11,
              }}
            >
              Select an entity from the graph to view its timeline.
            </div>
          )}
        </div>

        {/* Stats */}
        {snapshot && (
          <div
            style={{
              padding: "6px 12px",
              borderTop: "1px solid rgba(var(--accent-primary), 0.06)",
              fontSize: 9,
              color: "rgb(var(--text-tertiary))",
              display: "flex",
              gap: 12,
            }}
          >
            <span>{snapshot.stats.claims} claims</span>
            <span>{snapshot.stats.superseded} superseded</span>
            <span>{snapshot.active_nodes.length} entities</span>
          </div>
        )}
      </div>

      {/* Right panel: Graph + Slider */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Graph */}
        <div style={{ flex: 1, position: "relative" }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodeClick={handleNodeClick}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="rgba(var(--accent-primary), 0.03)" gap={20} size={1} />
          </ReactFlow>
          <ZoomControls />
        </div>

        {/* Slider */}
        {selectedDate && (
          <TimelineSlider
            range={range}
            value={selectedDate}
            onChange={setSelectedDate}
          />
        )}
      </div>
    </div>
  );
}
```

Note: Uses `useGraphLayout` hook (from Task 7) for d3-force positioning. Ghost nodes participate in the simulation alongside active nodes, ensuring consistent layout as the slider moves.

- [ ] **Step 2: Create route page**

Create `ui/app/(dashboard)/timeline/page.tsx`:

```tsx
import { TimelinePage } from "@/components/dashboard/TimelinePage";

export default function TimelineRoute() {
  return <TimelinePage />;
}
```

- [ ] **Step 3: Add Timeline to Sidebar**

In `ui/components/dashboard/Sidebar.tsx`, add to imports:
```typescript
import { LayoutDashboard, List, Clock } from "lucide-react";
```

Update `NAV_ITEMS` (around line 8-11):
```typescript
const NAV_ITEMS = [
  { href: "/", icon: LayoutDashboard, label: "Home" },
  { href: "/claims", icon: List, label: "Claims" },
  { href: "/timeline", icon: Clock, label: "Timeline" },
] as const;
```

- [ ] **Step 4: Verify build**

Run: `cd ui && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Commit**

```bash
git add ui/components/dashboard/TimelinePage.tsx ui/app/\(dashboard\)/timeline/page.tsx ui/components/dashboard/Sidebar.tsx
git commit -m "feat(timeline): add TimelinePage, route, and sidebar navigation"
```

---

## Task 12: Integration Verification

**Files:** None (verification only)

- [ ] **Step 1: Run all backend tests**

Run: `uv run pytest tests/test_timeline_api.py -v`
Expected: 11 PASS

- [ ] **Step 2: Run full backend test suite**

Run: `uv run pytest tests/ -v`
Expected: All existing tests still pass + 11 new timeline tests

- [ ] **Step 3: Run type check and lint**

Run: `uv run pyright tensory/ api/` and `uv run ruff check tensory/ api/ tests/`
Expected: 0 errors

- [ ] **Step 4: Run frontend build**

Run: `cd ui && npm run build`
Expected: Build succeeds

- [ ] **Step 5: Manual integration test**

Start the API server and frontend dev server. Navigate to `/timeline`:
1. Slider should show at the bottom with histogram bars
2. Graph should show entities as nodes
3. Dragging slider should update the graph (nodes appear/disappear)
4. Clicking a node should populate the left panel with entity history
5. Clicking a claim in the history should jump the slider to that date

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(timeline): integration fixes from manual testing"
```
