---
description: UI/Frontend conventions for Tensory Dashboard
globs: "ui/**/*.{ts,tsx,css}"
---

- Next.js 16+ with App Router, React 19, TypeScript strict
- All dashboard components MUST be `"use client"` (they use hooks/interactivity)
- One component per file, PascalCase filename (e.g., `PulseNode.tsx`)
- Colors: use CSS variables from `globals.css` (`--accent-primary`, etc.), NOT hardcoded hex
- Monospace font inherited from body — do NOT set font-family on individual components unless overriding
- Data fetching: ALWAYS via TanStack Query hooks in `hooks/`, NEVER raw `fetch()` in components
- Types: ALL types in `lib/types.ts`, MUST match Python Pydantic models from `tensory/service.py`
- React Flow: import from `@xyflow/react` (NOT `reactflow`), use `OnNodeDrag` type (NOT `NodeDragHandler`)
- NEVER use `useEffect` + `setNodes/setEdges` in a loop — causes infinite React update loops
- NEVER animate via `left`/`top` CSS properties — use `transform: translate()` (GPU compositor, no layout thrashing)
- d3-force layout MUST run synchronously in `useMemo`, NOT in useEffect/rAF
- shadcn/ui components live in `components/ui/`, add new ones via `npx shadcn@latest add <name>`
