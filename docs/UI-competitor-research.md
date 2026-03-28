# Competitor Dashboard & UI Research

Research conducted March 2026 for Tensory Dashboard UI design decisions.

## Competitor Overview

| Product | Screens | Strongest UX Pattern | Weakest Point |
|---------|---------|---------------------|---------------|
| Mem0 / OpenMemory | Memory list, Apps, Settings | ACL audit trail (who read/wrote each memory) | No graph, no timeline, flat text blobs |
| Cognee | Notebooks, Graph, Datasets | Reasoning subgraph (show WHY a result was returned) | Graph as static HTML, perf issues on large graphs |
| Zep | Graph, Playground, Analytics | Playground: mutate data → observe graph change → see downstream effect | Has temporal data but zero temporal UI |
| Letta (ex-MemGPT) | 3-panel IDE (config/chat/state) | Live context window viewer, core memory block editor | No graph at all, flat memory blocks |
| Graphiti | D3.js force graph | Incremental graph building animation | Despite being a temporal graph engine, no timeline UI |
| Neo4j Bloom | Graph explorer | NL-search → graph, progressive expand via right-click | Performance on very large graphs |

## Detailed Analysis

### Mem0 / OpenMemory

**Tech:** Next.js + Redux + Tailwind + pnpm

**Screens:**
- Dashboard home with stats and install instructions
- `/memories` — memory list with CRUD
- `/memory/[id]` — detail view with access logs
- `/apps` — connected applications
- `/settings` — configuration

**Data shown:** Flat list of memories (text strings) with metadata: timestamp, source app, category, state (active/paused/archived). Per-app statistics. Access logs showing which app read/wrote and when.

**Adopt:** Memory access audit trail; per-app ACL toggle; memory state lifecycle (active/pause/archive); bulk actions.

**Avoid:** Flat text-only display with no relationships.

### Cognee

**Tech:** Next.js frontend, knowledge graph backend

**Screens:**
- Dashboard with Datasets/Instances/Notebooks accordions
- Graph visualization with GraphView, GraphControls, GraphLegend, ActivityLog
- `/visualize` — dedicated graph page
- Auth, Plan, Account pages

**Data shown:** Interactive notebooks (code cells for `cognee.add()`, `cognee.cognify()`, `cognee.search()`). Knowledge graph with color-coded nodes by type, weighted edges with labels. Reasoning subgraph — only the subgraph used to answer a specific query.

**Adopt:** Reasoning subgraph visualization (show WHY a result was returned); button vs code duality; local-first with cloud sync.

**Avoid:** Static HTML graph rendering; notebook paradigm that intimidates non-technical users.

### Zep (Cloud)

**Screens:**
- Dashboard with analytics (API usage, latency)
- User/Group pages with per-user knowledge graphs
- Graph Explorer — force-directed D3.js
- Playground — interactive testing with preloaded demo data
- API logs and debug logs

**Data shown:** Entity nodes with evolving summaries. Fact edges (entity-relationship-entity triplets) with temporal validity windows (valid_from, invalid_at). Episode nodes. Per-user/group knowledge graphs. Analytics.

**Adopt:** Playground with live graph mutation feedback; temporal validity windows on facts; per-user knowledge graph isolation.

**Avoid:** Basic graph visualization despite rich temporal data model; analytics focused on API ops rather than memory quality.

### Letta (ex-MemGPT)

**Layout:** Three-panel layout (left: config, center: chat, right: state)

**Screens:**
- Left: Agent Configuration — model, system instructions, tools, data sources
- Center: Agent Simulator — chat interface, real-time tool usage monitoring
- Right: Agent State — Core Memory Blocks (labeled, editable, with char limits), Archival Memory (searchable), Context Window Viewer

**Adopt:** Three-panel layout for agent debugging; core memory editor with character limits; live context window viewer; system message injection for testing; agent checkpointing.

**Avoid:** No graph visualization; no relationships between memories; can feel overwhelming.

### Graphiti (by Zep)

**Visualization:** Single-page D3.js force-directed graph with custom node colors by entity type, clickable nodes/edges, zoom/pan, dark/light mode.

**Adopt:** Incremental graph building animation; embeddable lightweight viewer; entity-type color coding.

**Avoid:** Zero temporal features despite being a temporal graph engine.

### Neo4j Bloom

**Screens:** Scene (main workspace), Search bar (NL queries), Perspective drawer, Legend panel, Card list, Context menu

**Adopt:** Search-to-visualization paradigm; Perspective-based views; progressive expansion via right-click ("show neighbors of type X"); scene saving/sharing; rule-based visual styling.

**Avoid:** Learning curve of Perspective concept; limited NL search.

### Vestige (notable newcomer)

3D force-directed neural graph (Three.js, SvelteKit) at 60fps. FSRS retention curves showing predicted memory decay at 1d/7d/30d. Endangered memory alerts. "Dream mode" visualization during consolidation. Nodes pulse on access, fade as retention decays. Command palette (Cmd+K).

## Cross-Cutting Patterns

### Timeline Views
**Massive gap across all competitors.** Zep/Graphiti have temporal data (valid_from/invalid_at) but no timeline UI. Nobody has a timeline slider showing how knowledge evolves over time. Tensory's temporal features (superseding, exponential decay, timeline) could have a standout UI here.

### Memory Editing
- Letta: best-in-class (inline editing of core memory blocks with character limits)
- Mem0: basic CRUD
- Cognee: via notebook code cells
- Zep: API only

### Search UX
Best search combines a simple search bar with faceted filters (by type, date, source) and shows WHY results matched (Cognee's reasoning subgraph).

### Confidence / Salience / Strength
**Nobody shows this well.** Zep has temporal validity. Vestige has FSRS decay curves. No competitor shows salience scores, collision confidence, or decay rates in a dashboard. Tensory has a unique opportunity here.

### Relationship Visualization
- Cognee: full knowledge graph with typed nodes/edges
- Zep/Graphiti: temporal knowledge graph (entity-fact-entity triplets)
- Neo4j Bloom: full graph exploration
- Letta: none (flat memory blocks)
- Mem0: none (flat memory list)

## Opportunities for Tensory

Features no competitor has that we can build:

1. **Timeline View** — slider showing knowledge evolution over time, superseding events, decay curves. Nobody has this.
2. **Collision Detection UI** — show when two claims collide, resolution (supersede/confirm/contradict), confidence scores.
3. **Salience Decay Dashboard** — exponential decay curves, "endangered memories" alerts, visual health indicators.
4. **Procedural Memory View** — skill cards with trigger/steps/termination, success rate bars, feedback history.
5. **Reasoning Provenance** — when searching, show the subgraph that contributed to results (like Cognee but integrated).
6. **Temporal Graph Playback** — animate how the graph evolved over time.

## Sources

- [Mem0 Platform](https://mem0.ai/)
- [Mem0 OpenMemory GitHub](https://github.com/mem0ai/mem0/tree/main/openmemory)
- [Cognee UI Announcement](https://www.cognee.ai/blog/cognee-news/product-announcement-cognee-ui)
- [Cognee Graph Visualization Docs](https://docs.cognee.ai/guides/graph-visualization)
- [Zep Q1 2025 Product Roundup](https://blog.getzep.com/zep-q1-2025-product-round-up/)
- [Zep Graph Overview Docs](https://help.getzep.com/graph-overview)
- [Letta ADE Overview](https://docs.letta.com/guides/ade/overview)
- [Graphiti GitHub](https://github.com/getzep/graphiti)
- [Neo4j Bloom Overview](https://neo4j.com/docs/bloom-user-guide/current/bloom-visual-tour/bloom-overview/)
- [Vestige GitHub](https://github.com/samvallad33/vestige)
