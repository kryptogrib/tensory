"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type NodeChange,
  type EdgeChange,
  type NodeMouseHandler,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useRouter } from "next/navigation";

import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import type { EntityNode, EdgeData } from "@/lib/types";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { CursorGlow } from "./CursorGlow";
import { ZoomControls } from "./ZoomControls";

const nodeTypes = { pulse: PulseNode };
const edgeTypes = { salience: SalienceEdge };

/* ─── Fruchterman-Reingold Force-Directed Layout ─────────────────────
 *
 * Classic algorithm for aesthetically pleasing graphs.
 *
 * Forces:
 *   Repulsive (all pairs):  Fr(d) = -k² / d        (Coulomb-like)
 *   Attractive (edges):     Fa(d) =  d² / k         (spring / Hooke)
 *   Gravity (to center):    Fg    = -strength * pos  (keeps graph centered)
 *
 * k = C * sqrt(area / |V|)  — ideal spring length
 * Temperature cools each iteration to converge.
 * ──────────────────────────────────────────────────────────────────── */

interface Vec2 {
  x: number;
  y: number;
}

function forceDirectedLayout(
  entities: EntityNode[],
  edgeList: EdgeData[],
): { positions: Map<string, Vec2> } {
  const n = entities.length;
  if (n === 0) return { positions: new Map() };

  // Index entities by name for edge resolution
  const idByName = new Map<string, number>();
  entities.forEach((e, i) => idByName.set(e.name, i));

  // Resolve edges to index pairs
  const links: [number, number][] = [];
  for (const edge of edgeList) {
    const s = idByName.get(edge.from_entity);
    const t = idByName.get(edge.to_entity);
    if (s !== undefined && t !== undefined && s !== t) {
      links.push([s, t]);
    }
  }

  // Build adjacency set for degree calculation
  const degree = new Array<number>(n).fill(0);
  for (const [s, t] of links) {
    degree[s]++;
    degree[t]++;
  }

  // --- Parameters ---
  const AREA = 800 * 800;
  const k = 1.2 * Math.sqrt(AREA / Math.max(n, 1)); // ideal edge length
  const ITERATIONS = 120;
  const GRAVITY = 0.08;
  const INITIAL_TEMP = k * 2;
  const MIN_DIST = 1; // avoid division by zero

  // --- Initialize positions in a circle (better starting point than random) ---
  const pos: Vec2[] = entities.map((_, i) => {
    const angle = (i / n) * 2 * Math.PI;
    const r = k * 1.5;
    return { x: Math.cos(angle) * r, y: Math.sin(angle) * r };
  });

  // --- Simulate ---
  let temp = INITIAL_TEMP;

  for (let iter = 0; iter < ITERATIONS; iter++) {
    const disp: Vec2[] = pos.map(() => ({ x: 0, y: 0 }));

    // Repulsive forces (all pairs) — O(n²), fine for <200 nodes
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const dx = pos[i].x - pos[j].x;
        const dy = pos[i].y - pos[j].y;
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), MIN_DIST);
        const force = (k * k) / dist; // Fr = k² / d
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        disp[i].x += fx;
        disp[i].y += fy;
        disp[j].x -= fx;
        disp[j].y -= fy;
      }
    }

    // Attractive forces (edges only) — spring pulls connected nodes together
    for (const [s, t] of links) {
      const dx = pos[s].x - pos[t].x;
      const dy = pos[s].y - pos[t].y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), MIN_DIST);
      const force = (dist * dist) / k; // Fa = d² / k
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      disp[s].x -= fx;
      disp[s].y -= fy;
      disp[t].x += fx;
      disp[t].y += fy;
    }

    // Gravity — pull toward center to prevent drift
    for (let i = 0; i < n; i++) {
      disp[i].x -= pos[i].x * GRAVITY;
      disp[i].y -= pos[i].y * GRAVITY;
    }

    // Apply displacement with temperature limiting
    for (let i = 0; i < n; i++) {
      const dx = disp[i].x;
      const dy = disp[i].y;
      const len = Math.max(Math.sqrt(dx * dx + dy * dy), MIN_DIST);
      const capped = Math.min(len, temp);
      pos[i].x += (dx / len) * capped;
      pos[i].y += (dy / len) * capped;
    }

    // Cool down
    temp *= 1 - iter / ITERATIONS; // linear cooling
  }

  // --- Scale positions to reasonable viewport coordinates ---
  // Find bounding box
  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
  for (const p of pos) {
    minX = Math.min(minX, p.x);
    maxX = Math.max(maxX, p.x);
    minY = Math.min(minY, p.y);
    maxY = Math.max(maxY, p.y);
  }
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;
  const TARGET = Math.max(400, n * 60); // scale with node count

  const positions = new Map<string, Vec2>();
  entities.forEach((entity, i) => {
    positions.set(entity.id, {
      x: ((pos[i].x - minX) / rangeX - 0.5) * TARGET,
      y: ((pos[i].y - minY) / rangeY - 0.5) * TARGET,
    });
  });

  return { positions };
}

function layoutNodes(entities: EntityNode[], edges: EdgeData[]): Node[] {
  if (entities.length === 0) return [];

  const { positions } = forceDirectedLayout(entities, edges);

  return entities.map((entity) => {
    const pos = positions.get(entity.id) ?? { x: 0, y: 0 };
    return {
      id: entity.id,
      type: "pulse",
      position: { x: pos.x, y: pos.y },
      data: {
        label: entity.name,
        mentionCount: entity.mention_count,
        claimCount: 0,
        entityType: entity.type,
      },
    };
  });
}

function buildEdges(edges: EdgeData[], entities: EntityNode[]): Edge[] {
  const entityIdByName = new Map<string, string>();
  for (const e of entities) {
    entityIdByName.set(e.name, e.id);
  }

  return edges
    .map((edge, i) => {
      const sourceId = entityIdByName.get(edge.from_entity);
      const targetId = entityIdByName.get(edge.to_entity);
      if (!sourceId || !targetId) return null;
      return {
        id: `e-${i}-${sourceId}-${targetId}`,
        source: sourceId,
        target: targetId,
        type: "salience",
        data: {
          relType: edge.rel_type,
          confidence: edge.confidence,
          fact: edge.fact,
        },
      };
    })
    .filter(Boolean) as Edge[];
}

interface GraphCanvasProps {
  mode: "entity" | "full";
}

function GraphCanvas({ mode }: GraphCanvasProps) {
  const router = useRouter();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const { data: entities } = useGraphEntities({
    limit: mode === "entity" ? 30 : 60,
    min_mentions: mode === "entity" ? 1 : 0,
  });

  const { data: edgesData } = useGraphEdges({});

  // Compute base layout from API data (force-directed)
  const baseNodes = useMemo(
    () => layoutNodes(entities ?? [], edgesData ?? []),
    [entities, edgesData]
  );

  const baseEdges = useMemo(
    () => buildEdges(edgesData ?? [], entities ?? []),
    [edgesData, entities]
  );

  // Apply selection highlighting via useMemo — no effects, no cycles
  const nodes = useMemo(() => {
    if (!selectedNode) return baseNodes;

    const connectedNodeIds = new Set<string>([selectedNode]);
    for (const e of baseEdges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connectedNodeIds.add(e.source);
        connectedNodeIds.add(e.target);
      }
    }

    return baseNodes.map((n) => ({
      ...n,
      style: connectedNodeIds.has(n.id)
        ? { opacity: 1 }
        : { opacity: 0.2, transition: "opacity 0.3s ease" },
    }));
  }, [baseNodes, baseEdges, selectedNode]);

  const edges = useMemo(() => {
    if (!selectedNode) return baseEdges;

    const connectedEdgeIds = new Set<string>();
    for (const e of baseEdges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connectedEdgeIds.add(e.id);
      }
    }

    return baseEdges.map((e) => ({
      ...e,
      style: connectedEdgeIds.has(e.id)
        ? { opacity: 1 }
        : { opacity: 0.1, transition: "opacity 0.3s ease" },
    }));
  }, [baseEdges, selectedNode]);

  // Handle React Flow's internal changes (drag, etc.) by merging into base
  const [nodeChanges, setNodeChanges] = useState<Node[]>([]);
  const displayNodes = nodeChanges.length > 0 ? nodeChanges : nodes;

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setNodeChanges((prev) => {
        const current = prev.length > 0 ? prev : nodes;
        return applyNodeChanges(changes, current);
      });
    },
    [nodes]
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      // Edge changes (selection etc.) — apply to current edges
      void changes; // Read-only graph, no edge mutations needed
    },
    []
  );

  // Reset drag state when API data changes
  const dataKey = entities?.length ?? 0;
  useMemo(() => setNodeChanges([]), [dataKey]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode((prev) => (prev === node.id ? null : node.id));
      setNodeChanges([]); // Reset to recalculate from selection
    },
    []
  );

  const onNodeDoubleClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const label = (node.data as Record<string, unknown>).label as string;
      router.push(`/claims?entity=${encodeURIComponent(label)}`);
    },
    [router]
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
    setNodeChanges([]);
  }, []);

  return (
    <div className="relative h-full w-full" style={{ background: "#0a0908" }}>
      <CursorGlow />
      <ReactFlow
        nodes={displayNodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeDoubleClick}
        onPaneClick={onPaneClick}
        fitView
        fitViewOptions={{ padding: 0.3, duration: 500 }}
        minZoom={0.1}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
        style={{ background: "transparent" }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={24}
          size={1}
          color="rgba(217, 119, 6, 0.06)"
        />
      </ReactFlow>

      {/* Zoom controls — bottom center */}
      <div className="absolute bottom-4 left-1/2 z-10 -translate-x-1/2">
        <ZoomControls />
      </div>
    </div>
  );
}

interface GraphViewerProps {
  mode?: "entity" | "full";
}

export function GraphViewer({ mode = "entity" }: GraphViewerProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvas mode={mode} />
    </ReactFlowProvider>
  );
}
