# Tensory Dashboard UI

Readonly dashboard for debugging Tensory internals and demoing capabilities.
Three screens: Home (graph canvas + HUD), Claims Browser, Graph Explorer.

## Tech Stack

Next.js 16+, React 19, TypeScript, Tailwind CSS v4
React Flow (@xyflow/react), TanStack Table, TanStack Query, d3-force
shadcn/ui, lucide-react, date-fns
Package manager: **npm**

## Commands

```bash
cd ui
npm install                          # Install deps
npm run dev                          # Dev server (localhost:3000)
npm run build                        # Production build (type checks included)
npm run lint                         # ESLint
```

From project root:
```bash
make dashboard                       # Start API + UI together
make ui                              # UI only (assumes API on :8000)
```

## Architecture

```
ui/
  app/
    layout.tsx                       # Root layout (dark theme, QueryProvider)
    (dashboard)/
      layout.tsx                     # Dashboard shell: Sidebar + main area
      page.tsx                       # Home — full-screen graph canvas + HUD overlays
      claims/page.tsx                # Claims Browser — TanStack Table + filters
      graph/page.tsx                 # Graph Explorer — same as Home, different route
  components/
    ui/                              # shadcn/ui primitives (table, card, badge, button, dialog, separator)
    dashboard/
      Sidebar.tsx                    # Compact icon sidebar (44px), navigation
      StatsBar.tsx                   # Terminal-style stats bar + search (⌘K)
      HudWindow.tsx                  # Reusable glass-morphism container
      GraphViewer.tsx                # React Flow canvas + d3-force layout
      PulseNode.tsx                  # Custom React Flow node (pulse rings, glow)
      SalienceEdge.tsx               # Custom React Flow edge (dissolve gradient, confidence styling)
      CursorGlow.tsx                 # Ambient cursor light (GPU-accelerated transform)
      LiveFeed.tsx                   # Recent claims HUD window
      EntityBadges.tsx               # Active entities HUD window
      GraphControls.tsx              # Entity/Full mode toggle, depth, show weak
      EdgeLegend.tsx                 # Edge strength visual guide
      ZoomControls.tsx               # Zoom in/out/fit-view bar
      ClaimsTable.tsx                # TanStack Table with expandable rows
      ClaimsFilters.tsx              # Type, entity, salience, search filters
      AmbientPlayer.tsx              # Background ambient audio (optional)
  hooks/
    use-stats.ts                     # TanStack Query: GET /api/stats
    use-claims.ts                    # TanStack Query: GET /api/claims, /search, /claims/{id}
    use-graph.ts                     # TanStack Query: GET /api/graph/*
  lib/
    api.ts                           # Typed fetch client (all API endpoints)
    types.ts                         # TypeScript types matching Python Pydantic models
    utils.ts                         # shadcn/ui utility (cn)
  providers/
    query-provider.tsx               # TanStack Query provider (30s stale time)
```

## API Backend

FastAPI at `api/` in the project root. Consumed via `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`).

Key endpoints:
- `GET /api/stats` → DashboardStats (counts, claims_by_type, avg_salience, recent_claims, hot_entities)
- `GET /api/claims` → PaginatedClaims (offset, limit, type, entity, salience filters, sort)
- `GET /api/claims/{id}` → ClaimDetail (claim + episode + relations + waypoints)
- `GET /api/search?q=` → SearchResult[] (hybrid search)
- `GET /api/graph/entities` → EntityNode[] (for React Flow nodes)
- `GET /api/graph/edges` → EdgeData[] (for React Flow edges)
- `GET /api/graph/subgraph/{entity}` → SubGraph (nodes + edges around entity)

## Visual Design: Ember Terminal

Dark sci-fi theme with amber/orange accents, monospace typography.

### Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| bg-base | `#0a0908` | Page background, graph canvas |
| bg-surface | `rgba(10,9,8,0.82)` | HUD windows (+ backdrop-filter: blur(12px)) |
| border-subtle | `rgba(217,119,6,0.06)` | Window borders, dividers |
| accent-primary | `#d97706` | Nodes, strong edges, active states |
| accent-secondary | `#ea580c` | Secondary nodes, relation badges |
| accent-deep | `#b45309` | Weak elements, opinion type |
| text-primary | `#f5e6d3` | Primary text, entity names (warm white) |
| text-secondary | `#8a7e72` | Labels, meta text |
| text-tertiary | `#6b6560` | Timestamps, facts |
| text-muted | `#4a4540` | Decorative, prompt symbol |
| status-positive | `#a3e635` | Lime — positive changes, experience type |
| status-negative | `#fca5a5` | Soft red — collisions count |
| decaying | `#78716c` | Weak/decaying edges and nodes |

### Typography

Monospace everywhere: `'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace`
Set in `globals.css` on body. All components inherit.

### Layout: Graph Canvas + Corners HUD

Graph fills entire viewport. UI elements are semi-transparent floating windows (HudWindow) with `backdrop-filter: blur(12px)` positioned at corners:
- Top: StatsBar (full width)
- Top-left: EdgeLegend
- Top-right: GraphControls
- Bottom-left: EntityBadges
- Bottom-right: LiveFeed
- Bottom-center: ZoomControls

## Conventions

- All dashboard components are `"use client"` (hooks, interactivity)
- Component files: one component per file, PascalCase filename
- Hooks: `use-<name>.ts` in `hooks/`
- Types: all in `lib/types.ts`, must match Python Pydantic models from `tensory/service.py`
- Colors: use CSS variables from `globals.css`, NOT hardcoded hex in new code
- shadcn/ui: use existing primitives from `components/ui/`, add new via `npx shadcn@latest add <name>`
- TanStack Query: all data fetching via hooks in `hooks/`, never raw fetch in components

## Gotchas

- React Flow requires `<ReactFlowProvider>` wrapper — see GraphViewer.tsx
- Import from `@xyflow/react` (NOT `reactflow` — that's the old package)
- React Flow edge type is `OnNodeDrag` (NOT `NodeDragHandler` — doesn't exist in v12)
- Custom edges: use `useInternalNode(source)` to get true node center coordinates, bypassing Handle offset issues
- SalienceEdge uses SVG `linearGradient` per-edge with `gradientUnits="userSpaceOnUse"` — gradient direction follows edge
- PulseNode uses fixed-size square container (`width = height = size * 2`) so Handle at 50%/50% is the true visual center
- d3-force layout runs **synchronously** in `useMemo` (300 ticks, ~5ms) — NOT in useEffect/rAF (causes infinite React update loops)
- NEVER use `useEffect` + `setNodes()` in a loop with React Flow — causes "Maximum update depth exceeded"
- CursorGlow uses `transform: translate()` (GPU compositor) — NEVER `left/top` (causes layout thrashing + visible stepping)
- CSS transition on `transform` = smooth, on `left/top` = laggy
- `will-change: transform` promotes element to GPU layer — use sparingly (memory cost)
- ClaimDetail.collisions returns `[]` (not persisted, computed at ingest time)
- Service layer JOINs entities table to resolve UUID → entity names for relations

## Graph Explorer

### Node: PulseNode
- Pulse rings count = mention_count bucket (0-2: 0 rings, 3-7: 1, 8-15: 2, 16+: 3)
- Core dot brightness = salience
- Box-shadow glow: 3 layers (near/mid/far)
- Hover: CSS `scale(1.15)` transition
- Halo: radial gradient on all nodes (brighter for high-mention)

### Edge: SalienceEdge
- Confidence tiers: >0.7 solid, >=0.4 dashed, >=0.2 sparse, <0.2 very sparse
- SVG linearGradient dissolves at both ends (0-20% fade-in, 80-100% fade-out)
- Hover: glow blur(4px) + tooltip with rel_type
- Traveling impulse dot on strong edges (CSS offset-path animation)

### Layout: d3-force (synchronous)
- `forceSimulation` with: forceManyBody, forceLink, forceCenter, forceCollide, forceX, forceY
- Runs 300 ticks synchronously in `useMemo` — instant, deterministic
- React Flow handles drag/pan/zoom natively after layout

## Current Status

MVP complete: Home + Claims Browser + Graph Explorer.
- Graph Canvas + Corners HUD layout
- d3-force synchronous layout
- Pulse Ring nodes + Salience-encoded dissolving edges
- GPU-accelerated cursor glow
- TanStack Table with filters, pagination, expandable rows
- ⌘K search hotkey
- Docker Compose deployment ready
