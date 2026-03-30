# Timeline UI — Design Spec

## Overview

Timeline UI for the Tensory dashboard — a dedicated `/timeline` page combining entity history (branching timeline) with graph playback (time-travel slider). No competitor has temporal visualization despite having temporal data. Tensory has all the data: `valid_from/valid_to`, `superseded_at`, `created_at`, exponential decay.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Entity History + Graph Playback | Combination of deep per-entity view and bird's-eye graph evolution |
| Placement | Separate `/timeline` page | Simpler to build first; shared GraphViewer component enables later migration to toggle mode |
| Entity history style | Branching timeline | Shows superseding chains visually (old → new), not just strikethrough |
| Slider visualization | Histogram + decay curves (progressive) | Histogram by default; select entity → decay curves appear below |
| Graph time-travel | Active nodes + ghost nodes | Strict filtering (only show what existed at `at`) + dashed ghost nodes for "not yet known" |
| Architecture | Shared `useGraphLayout` hook + separate `TimelineGraphViewer` | Keeps GraphViewer clean (~300 lines), shared physics via hook, same PulseNode/SalienceEdge |

## MVP Scope (v1)

**Included:**
1. `/timeline` page in Sidebar navigation
2. Entity History — branching timeline (left panel)
3. Graph Playback — slider + graph with ghost/active nodes (right panel)
4. Event histogram above slider

**Deferred to v2:**
- Decay curves (appear on entity select)
- Supersede indicators on graph nodes ($2,400→$2,800)
- "New entity" green glow + ✦ marker
- Decaying node visualization
- ◀ ▶ step buttons for event-by-event navigation
- Color-coded event dots on slider (orange/red/green)

## Backend

### New API Endpoints

New router: `api/routers/timeline.py`

```
GET /api/timeline/{entity_name}?include_superseded=true&limit=50
→ TimelineEntry[]

GET /api/timeline/snapshot?at=2026-03-18T14:00:00Z
→ GraphSnapshot {
    active_nodes: EntityNode[],
    ghost_nodes: EntityNode[],
    edges: EdgeData[],
    stats: { claims: int, superseded: int }
  }

GET /api/timeline/range
→ TimelineRange {
    min_date: string,
    max_date: string,
    event_histogram: { date: string, count: int }[]
  }
```

### Service Layer

Three new methods in `TensoryService`:

- `get_entity_timeline(entity_name, include_superseded, limit)` — wraps `temporal.timeline()`
- `get_graph_snapshot(at: datetime)` — SQL: claims WHERE `created_at <= at` AND (`superseded_at IS NULL OR superseded_at > at`); entities with at least one active claim = active; rest = ghost
- `get_timeline_range()` — min/max `created_at` + histogram via `GROUP BY date(created_at)`

### New Models

```python
class TimelineEntry(BaseModel):
    claim: Claim
    supersedes: str | None
    superseded_by: str | None

class GraphSnapshot(BaseModel):
    active_nodes: list[EntityNode]
    ghost_nodes: list[EntityNode]
    edges: list[EdgeData]
    stats: dict[str, int]

class TimelineRange(BaseModel):
    min_date: datetime
    max_date: datetime
    event_histogram: list[dict[str, Any]]
```

## Frontend

### New Files

```
ui/app/(dashboard)/timeline/page.tsx      — route /timeline
ui/components/dashboard/TimelinePage.tsx   — layout orchestrator
ui/components/dashboard/EntityTimeline.tsx — branching timeline (left panel)
ui/components/dashboard/TimelineSlider.tsx — slider + histogram
ui/components/dashboard/GhostNode.tsx     — React Flow custom node
ui/hooks/use-timeline.ts                  — TanStack Query hooks
```

### Refactored Files

```
ui/hooks/use-graph-layout.ts              — NEW: shared d3-force hook
ui/components/dashboard/GraphViewer.tsx    — refactor to use useGraphLayout()
```

### Page Layout

```
┌─────────────────────────────────────────────────┐
│ Sidebar │  Entity Timeline  │   Graph (React Flow)  │
│  44px   │     ~300px        │       flex-1          │
│         │                   │                       │
│  [home] │  Entity picker    │   [active + ghost     │
│  [claim]│  ─── Mar 5 ───   │    nodes, edges       │
│ >[time] │  ● ETH at $2400  │    filtered by        │
│         │     ╰─superseded─╮│    slider date]       │
│         │  ─── Mar 18 ──── ││                       │
│         │  ● ETH at $2800 ←╯│                       │
│         │  ● Staking 4.2%  │                       │
│         │                   │                       │
│         ├───────────────────┴───────────────────────┤
│         │  [▐▐▐ ▐▐ ▐▐▐▐▐ ▐▐▐] histogram           │
│         │  Mar 1 ━━━━━━━●━━━━━━━━━━━━━ Mar 30      │
│         │              ↑ slider                     │
└─────────────────────────────────────────────────┘
```

### New Types (`lib/types.ts`)

```typescript
interface TimelineEntry {
  claim: Claim
  supersedes: string | null
  superseded_by: string | null
}

interface GraphSnapshot {
  active_nodes: EntityNode[]
  ghost_nodes: EntityNode[]
  edges: EdgeData[]
  stats: { claims: number; superseded: number }
}

interface TimelineRange {
  min_date: string
  max_date: string
  event_histogram: { date: string; count: number }[]
}
```

### Components

| Component | Purpose | Key Props |
|-----------|---------|-----------|
| `TimelinePage` | Layout orchestrator, state management | — |
| `EntityTimeline` | Branching timeline list with supersede chains | `entity: string, entries: TimelineEntry[], currentDate: Date` |
| `TimelineSlider` | Slider + histogram bars | `range: TimelineRange, value: Date, onChange: (date: Date) => void` |
| `GhostNode` | Dashed, dim React Flow node for future entities | `data: { name: string, type: string \| null, first_seen: string }` |
| `useGraphLayout` | Shared d3-force simulation hook | `nodes, edges, physicsParams` → positioned nodes + simulation ref |

### Shared (no changes)

`PulseNode`, `SalienceEdge`, `HudWindow`, `ZoomControls`

### Data Flow

```
1. Page load
   → useTimelineRange() → GET /api/timeline/range
   → slider renders histogram, playhead at max_date

2. Slider drag → debounce 150ms
   → useGraphSnapshot(date) → GET /api/timeline/snapshot?at=date
   → graph re-renders: active → PulseNode, ghost → GhostNode

3. Click entity (graph or entity picker)
   → useEntityTimeline(name) → GET /api/timeline/{name}
   → left panel shows branching timeline

4. Click claim in entity timeline
   → slider jumps to that claim's created_at
   → graph updates to that moment
```

### Interaction Details

- **Debounce:** slider drag → 150ms debounce + TanStack Query `keepPreviousData: true` to prevent graph flicker
- **Bi-directional sync:** click in timeline → slider jumps; drag slider → timeline highlights current moment
- **Entity selection:** click node in graph or use picker in entity panel

### Visual Encoding

| Element | Appearance | Meaning |
|---------|------------|---------|
| Active node | Solid PulseNode (existing component) | Entity exists at this point in time |
| Ghost node | Dashed border, ~0.2 opacity, dim label | Entity not yet known at this time |
| Active edge | SalienceEdge (existing component) | Relationship exists at this time |
| Supersede in timeline | Branch line: old ╰──superseded──╮ new | Fact was replaced by newer fact |

## Testing

### Backend Tests — `tests/test_timeline_api.py`

- `test_entity_timeline_returns_chronological_order`
- `test_entity_timeline_includes_superseded`
- `test_graph_snapshot_filters_by_date`
- `test_graph_snapshot_ghost_nodes`
- `test_graph_snapshot_superseded_excluded`
- `test_timeline_range_histogram`
- `test_timeline_range_empty_db`

### Service Tests — `tests/test_service.py` (additions)

- `test_get_entity_timeline`
- `test_get_graph_snapshot`
- `test_get_timeline_range`

**Approach:** all on `:memory:` SQLite, `NullEmbedder`, no mocks.

## Key Risks

- **Snapshot query performance** — filtering by date across claims + entities + edges could be slow on large DBs. Mitigation: `created_at` and `superseded_at` are already indexed.
- **Debounce tuning** — 150ms may feel laggy or still cause too many requests. Tune during implementation.
- **Ghost node positioning** — d3-force positions depend on all nodes being present. Ghost nodes need to participate in simulation but with reduced forces to avoid layout jumps when scrubbing.
