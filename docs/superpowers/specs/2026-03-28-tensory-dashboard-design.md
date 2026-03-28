# Tensory Dashboard — Design Spec

## Purpose

Readonly dashboard for **debugging** Tensory internals and **demoing** capabilities to potential users. Three screens: Home, Claims Browser, Graph Explorer.

## Architecture

### Layers

```
tensory/service.py    →  Shared service layer (read-only queries)
                      ↓
api/main.py (FastAPI) →  REST /api/* endpoints, OpenAPI schema
                      ↓
ui/ (Next.js 16)      →  SPA, App Router, typed API client from OpenAPI
                      ↑
tensory_mcp.py        →  Also consumes service.py (migration path)
```

### Project Structure

```
tensory/                          # Existing library (untouched)
tensory/service.py                # NEW: shared service layer

api/                              # NEW: FastAPI backend
  main.py                         # FastAPI app, CORS, lifespan
  routers/
    claims.py                     # GET /api/claims, /api/claims/{id}, /api/search
    graph.py                      # GET /api/graph/entities, /edges, /subgraph/{entity}
    stats.py                      # GET /api/stats
  dependencies.py                 # get_service() dependency injection

ui/                               # NEW: Next.js 16 (App Router)
  app/
    (dashboard)/
      layout.tsx                  # Sidebar + graph canvas base
      page.tsx                    # Home
      claims/page.tsx             # Claims Browser
      graph/page.tsx              # Graph Explorer
  components/
    ui/                           # shadcn/ui primitives
    dashboard/
      Sidebar.tsx                 # Compact icon sidebar (44px)
      StatsBar.tsx                # HUD stats bar
      ClaimsTable.tsx             # TanStack Table
      GraphViewer.tsx             # React Flow + custom nodes
      LiveFeed.tsx                # Recent claims HUD window
      EntityBadges.tsx            # Active entities HUD window
  lib/
    api.ts                        # Typed REST client (generated from OpenAPI)
    types.ts                      # TypeScript types from OpenAPI codegen
  hooks/
    use-claims.ts                 # TanStack Query hooks
    use-graph.ts
    use-stats.ts
  providers/
    query-provider.tsx            # TanStack Query provider

docker-compose.yml                # api + ui services
```

### Key Principle

`tensory/` library is untouched. Only `tensory/service.py` is added — a thin read-only wrapper that both FastAPI and MCP server consume. No business logic duplication.

## Service Layer

`tensory/service.py` — wraps `Tensory` class with read-only query methods.

```python
class TensoryService:
    def __init__(self, store: Tensory): ...

    # Home
    async def get_stats(self) -> DashboardStats
    # → counts, claims_by_type, avg_salience, recent_claims(5), hot_entities(5)

    # Claims Browser
    async def list_claims(self, *, offset, limit, type_filter,
                          salience_min, salience_max, entity_filter,
                          context_id, sort_by, sort_order) -> PaginatedClaims
    async def get_claim(self, claim_id: str) -> ClaimDetail
    async def search_claims(self, query: str, *, context_id, limit) -> list[SearchResult]

    # Graph Explorer
    async def get_graph_entities(self, *, limit, min_mentions) -> list[EntityNode]
    async def get_graph_edges(self, *, entity_filter) -> list[EdgeData]
    async def get_entity_subgraph(self, entity_name: str, *, depth) -> SubGraph
    async def get_entity_claims(self, entity_name: str) -> list[Claim]
```

Response models: `DashboardStats`, `PaginatedClaims`, `ClaimDetail`, `EntityNode`, `EdgeData`, `SubGraph` — new Pydantic models in service.py.

## API Endpoints

```
GET /api/stats                         → DashboardStats
GET /api/claims?offset&limit&type&...  → PaginatedClaims
GET /api/claims/{id}                   → ClaimDetail
GET /api/search?q=&limit=10            → list[SearchResult]
GET /api/graph/entities?limit&min_mentions → list[EntityNode]
GET /api/graph/edges?entity=           → list[EdgeData]
GET /api/graph/subgraph/{entity}?depth → SubGraph
GET /api/graph/entity/{name}/claims    → list[Claim]
```

Technical decisions:
- CORS: allow `localhost:3000` + configurable
- Lifespan: `Tensory.create()` on startup, `store.close()` on shutdown
- DB path: `TENSORY_DB_PATH` env var (default: `data/tensory.db`)
- Single `TensoryService` instance via FastAPI `Depends()`
- OpenAPI auto-generated at `/docs` and `/openapi.json`
- All responses typed with Pydantic v2 models

Not in MVP: POST/PUT/DELETE, WebSocket, Auth.

## Visual Design

### Style: Ember Terminal

Deep dark background with warm amber/orange accents. Monospace typography. Terminal aesthetic with sci-fi elements.

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `bg-base` | `#0a0908` | Page background, graph canvas |
| `bg-surface` | `rgba(10,9,8,0.82)` | HUD windows (+ backdrop-filter: blur(12px)) |
| `border-subtle` | `rgba(217,119,6,0.06)` | Window borders, dividers |
| `accent-primary` | `#d97706` | Primary amber — nodes, strong edges, active states |
| `accent-secondary` | `#ea580c` | Secondary orange — secondary nodes, some edges |
| `accent-deep` | `#b45309` | Muted amber — weak elements |
| `text-primary` | `#f5e6d3` | Primary text, active labels (warm white) |
| `text-secondary` | `#8a7e72` | Secondary text, labels, meta |
| `text-tertiary` | `#6b6560` | Tertiary text, timestamps |
| `text-muted` | `#4a4540` | Barely visible, decorative |
| `status-positive` | `#a3e635` | Lime — positive changes (+23) |
| `status-negative` | `#fca5a5` | Soft red — collisions count |
| `status-warning` | `#b45309` | Muted orange — opinion type |
| `decaying` | `#78716c` | Gray — weak/decaying edges and nodes |

### Typography

Monospace throughout: `'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace`

- Stats values: 9px, font-weight 700
- Labels: 8-9px, uppercase, letter-spacing 1.2px
- Node names: 8-11px (scaled by importance), font-weight 600-700
- Node meta: 6-7px
- HUD headers: 8px, uppercase, letter-spacing 1.2px

### Layout: Graph Canvas + Corners HUD

The graph occupies the entire viewport behind the UI. Interface elements are semi-transparent floating windows with backdrop blur, positioned at screen corners.

```
┌─────────────────────────────────────────────┐
│ [sidebar] ┌─[stats bar]──────────────────┐  │
│  44px     │ $ claims 1,247  salience 0.73│  │
│  icons    └──────────────────────────────┘  │
│           ┌─[legend]─┐        ┌─[controls]─┐│
│           │ edge     │        │ ENTITY     ││
│           │ strength │        │ FULL GRAPH ││
│           └──────────┘        │ DEPTH: 2   ││
│                               └────────────┘│
│           ╔══════════════════════╗           │
│           ║   GRAPH CANVAS      ║           │
│           ║   (full viewport)   ║           │
│           ║   nodes + edges     ║           │
│           ╚══════════════════════╝           │
│  ┌─[entities]──┐   ┌──┐  ┌─[live feed]────┐│
│  │ EigenLayer  │   │-+│  │ claim 1        ││
│  │ Google      │   │% │  │ claim 2        ││
│  │ a16z        │   │⊡ │  │ claim 3        ││
│  └─────────────┘   └──┘  └────────────────┘│
└─────────────────────────────────────────────┘
         zoom controls (center-bottom)
```

### Components

**Sidebar** (44px, left edge):
- Logo: 24x24 gradient square (amber→orange), "T"
- Navigation: icon-only buttons, 28x28, active has amber background
- Settings at bottom

**Stats Bar** (top, full width):
- Terminal-style: `$ claims 1,247 +23 | salience 0.73 | entities 342 | collisions 18`
- Search trigger (⌘K) at right

**Controls** (top-right):
- Scanline-style buttons: amber left-border = active, dim border = inactive
- Buttons: ENTITY, FULL GRAPH, separator, DEPTH: 2, SHOW WEAK
- Uppercase, letter-spacing 0.5px

**Live Feed** (bottom-right):
- Window with header (dot + "LIVE FEED" + "all →")
- Claim items: left-border color = type, text + meta (type · salience · time)
- Items fade opacity based on salience

**Active Entities** (bottom-left):
- Compact pill badges with subtle amber borders
- Brightness correlates to entity activity

**Legend** (top-left, below stats):
- Edge strength visual guide: solid/dashed/sparse + labels

**Zoom Controls** (bottom-center):
- −/100%/+/fit grouped buttons

## Graph Explorer

### Node Design: Pulse Rings

Each entity node consists of:
1. **Outer pulse rings** (0-3): animated expanding/fading circles. Count = `mention_count` bucket (0-2: 0 rings, 3-7: 1 ring, 8-15: 2 rings, 16+: 3 rings). Speed correlates to recent activity.
2. **Boundary circle**: static ring with subtle border. Gently breathes (r ±1-2px).
3. **Core dot**: filled circle, brightness = salience. Soft glow filter.
4. **Label**: entity name below node. Font size scales with importance.
5. **Meta text**: "N claims · sal X.XX" below label.

Node size (boundary radius) scales with mention_count: 6px (1-2 mentions) → 20px (16+ mentions).

### Edge Design: Salience-Encoded

Edges visually encode relationship strength (mapped from salience + confidence + recency):

| Strength | Line Style | Width | Opacity | Impulse |
|----------|-----------|-------|---------|---------|
| Strong (>0.7) | Solid | 1.0-1.5px | 0.2-0.3 | Yes — traveling dots |
| Moderate (0.4-0.7) | Dashed (6 3) | 0.5-0.8px | 0.1-0.15 | Slow, occasional |
| Weak (<0.4) | Sparse dash (3 5) | 0.3-0.4px | 0.04-0.06 | None |
| Decaying (<0.2) | Very sparse (2 6-8) | 0.2-0.3px | 0.02-0.04 | None |

**Traveling impulses**: small dots (r=1.5-2.5) animate along strong edges using SVG `animateMotion`. Speed ∝ confidence. Only on strong/moderate edges. Staggered start times for organic feel.

### Animations (all lightweight)

| Animation | Technique | Performance |
|-----------|-----------|-------------|
| Pulse rings | SVG `animate` on r + opacity | Zero JS, native SVG |
| Core glow | SVG `animate` on opacity | Zero JS |
| Boundary breath | SVG `animate` on r (±2px) | Zero JS |
| Traveling impulses | SVG `animateMotion` along path | Zero JS |
| Node hover: scale up | CSS `transform: scale(1.15)`, `transition: 0.2s ease` | GPU-accelerated |
| Cursor trail | CSS `radial-gradient` following `pointermove` | Single div, no canvas |
| Drag nodes | React Flow built-in | Optimized by library |
| Pan/zoom | React Flow built-in | Optimized by library |

Background effect: subtle radial gradient glow follows cursor position via `pointermove` event on a div behind the graph. Single `requestAnimationFrame` update, no particle system. CSS `radial-gradient` with amber tint, ~100px radius, low opacity (0.03-0.05).

### Dual Mode

- **Entity Mode** (default): Only entity nodes + EntityRelation edges. Clean overview.
- **Full Graph Mode**: Entities + claim nodes (smaller, colored by type) + waypoint edges (dashed). Richer but denser — for debugging.

Toggle via scanline buttons in controls panel.

### Interactions

- **Click node**: highlights node + connected edges, dims rest. Shows detail tooltip.
- **Double-click node**: navigates to Claims Browser filtered by that entity.
- **Hover edge**: shows relation type label in floating tooltip.
- **Right-click node**: context menu (timeline, related claims, hide).
- **Search** (⌘K): highlights matching nodes, smooth pan to result.

## Screen: Home Dashboard

Same Graph Canvas layout as default view. Stats bar shows aggregate metrics. Live feed shows recent claims. Active entities show primed entities. This IS the graph view — Home and Graph Explorer share the same canvas, just with different HUD focus.

Home-specific additions:
- Stats bar is always visible
- Live feed auto-updates (TanStack Query refetch interval: 30s)
- Hot entities pulled from priming data

## Screen: Claims Browser

Replaces graph canvas with a full TanStack Table. Same sidebar + stats bar.

### Table Columns

| Column | Content | Features |
|--------|---------|----------|
| Text | Claim text | Truncated, expand on click |
| Type | ClaimType badge | Color-coded: fact=amber, opinion=deep-amber, observation=orange, experience=lime |
| Entities | Entity pills | Clickable → filter |
| Salience | Bar + number | Gradient bar (deep→bright amber) |
| Relevance | Number | 0.0-1.0 |
| Source | Source string | |
| Created | Relative time | date-fns `formatDistanceToNow` |

### Filters

- Type: multi-select (fact, opinion, observation, experience)
- Salience range: slider 0.0-1.0
- Entity: searchable dropdown
- Context: dropdown (if multiple contexts)
- Full-text search: input field → calls /api/search

### Interactions

- Click row → expand: full claim text + episode raw_text + collisions + waypoints
- Sort by any column
- Pagination: offset/limit with page controls

## Tech Stack

### Frontend (ui/)
- Next.js 16 (App Router, TypeScript)
- Tailwind CSS v4
- shadcn/ui (Table, Card, Badge, Button, Dialog, Separator)
- TanStack Table v8 (claims table)
- TanStack Query v5 (data fetching, caching, background refetch)
- React Flow (graph visualization, custom nodes/edges)
- lucide-react (icons)
- date-fns (relative timestamps)
- next-themes (dark mode — though we're dark-only for now)
- openapi-typescript (type generation from FastAPI OpenAPI schema)

### Backend (api/)
- FastAPI
- uvicorn
- Pydantic v2 (response models)

### Infrastructure
- Docker Compose (api + ui services)
- `pyproject.toml` extras: `[ui]` → fastapi, uvicorn

## Launch Methods

1. **Dev**: Terminal 1: `uv run uvicorn api.main:app --reload` / Terminal 2: `cd ui && npm run dev`
2. **Docker**: `docker compose up`
3. **Future**: `tensory serve` CLI command (Typer)

## Not in MVP

- Write operations (POST/PUT/DELETE)
- WebSocket real-time updates
- Authentication
- Timeline screen
- Collisions screen
- Analytics screen
- Light theme
- Mobile responsive
- Draggable/resizable HUD windows (fixed positions for now)
