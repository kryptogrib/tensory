"use client";

import { useCallback, useMemo, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useRouter } from "next/navigation";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";

import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import type { EntityNode, EdgeData } from "@/lib/types";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { CursorGlow } from "./CursorGlow";
import { ZoomControls } from "./ZoomControls";

const nodeTypes = { pulse: PulseNode };
const edgeTypes = { salience: SalienceEdge };

/* ─── d3-force Synchronous Layout ────────────────────────────────────
 *
 * Runs the force simulation synchronously for N ticks to compute
 * optimal positions, then hands the result to React Flow as static
 * positions. React Flow handles drag/pan/zoom natively.
 *
 * This avoids the React state cycling problem: no continuous
 * setNodes() calls, no render loops, no infinite updates.
 *
 * Forces:
 *   - forceManyBody: electrostatic repulsion between all nodes
 *   - forceLink: spring attraction along edges
 *   - forceCollide: prevent node overlap
 *   - forceCenter + forceX/Y: gravity toward center
 * ──────────────────────────────────────────────────────────────────── */

interface SimNode extends SimulationNodeDatum {
  nodeId: string;
  label: string;
  mentionCount: number;
  entityType: string | null;
}

function computeLayout(
  entities: EntityNode[],
  edgeData: EdgeData[],
): { nodes: Node[]; edges: Edge[] } {
  if (entities.length === 0) return { nodes: [], edges: [] };

  const n = entities.length;
  const idByName = new Map<string, string>();
  for (const e of entities) idByName.set(e.name, e.id);

  // Create sim nodes — initialize on a circle for faster convergence
  const simNodes: SimNode[] = entities.map((entity, i) => {
    const angle = (i / n) * 2 * Math.PI;
    const r = 120 + Math.random() * 30;
    return {
      nodeId: entity.id,
      label: entity.name,
      mentionCount: entity.mention_count,
      entityType: entity.type,
      x: Math.cos(angle) * r,
      y: Math.sin(angle) * r,
    };
  });

  // Build links + React Flow edges
  const simNodeMap = new Map<string, SimNode>();
  for (const sn of simNodes) simNodeMap.set(sn.nodeId, sn);

  const simLinks: SimulationLinkDatum<SimNode>[] = [];
  const rfEdges: Edge[] = [];
  let idx = 0;

  for (const edge of edgeData) {
    const srcId = idByName.get(edge.from_entity);
    const tgtId = idByName.get(edge.to_entity);
    if (!srcId || !tgtId || srcId === tgtId) continue;

    const src = simNodeMap.get(srcId);
    const tgt = simNodeMap.get(tgtId);
    if (!src || !tgt) continue;

    simLinks.push({ source: src, target: tgt });
    rfEdges.push({
      id: `e-${idx++}-${srcId}-${tgtId}`,
      source: srcId,
      target: tgtId,
      type: "salience",
      data: {
        relType: edge.rel_type,
        confidence: edge.confidence,
        fact: edge.fact,
      },
    });
  }

  // --- Configure and run simulation synchronously ---
  const chargeStrength = Math.min(-400, -120 * Math.sqrt(n));
  const linkDist = Math.max(150, 80 + n * 5);
  const collideR = 50 + n * 0.5;

  const sim = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(simLinks)
        .id((d) => d.nodeId)
        .distance(linkDist)
        .strength(0.5),
    )
    .force("charge", forceManyBody<SimNode>().strength(chargeStrength).distanceMax(1000))
    .force("center", forceCenter(0, 0).strength(0.08))
    .force("collide", forceCollide<SimNode>(collideR).strength(0.8))
    .force("x", forceX<SimNode>(0).strength(0.04))
    .force("y", forceY<SimNode>(0).strength(0.04))
    .velocityDecay(0.35)
    .stop(); // Don't auto-start — we tick manually

  // Run 300 ticks synchronously (instant, <10ms for 100 nodes)
  const TICKS = 300;
  for (let i = 0; i < TICKS; i++) {
    sim.tick();
  }

  // Build React Flow nodes from final positions
  const rfNodes: Node[] = simNodes.map((sn) => ({
    id: sn.nodeId,
    type: "pulse",
    position: { x: sn.x ?? 0, y: sn.y ?? 0 },
    data: {
      label: sn.label,
      mentionCount: sn.mentionCount,
      claimCount: 0,
      entityType: sn.entityType,
    },
  }));

  return { nodes: rfNodes, edges: rfEdges };
}

// ─── Graph Canvas Component ─────────────────────────────────────────

interface GraphCanvasProps {
  mode: "entity" | "full";
}

function GraphCanvas({ mode }: GraphCanvasProps) {
  const router = useRouter();
  const { fitView } = useReactFlow();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const { data: entities } = useGraphEntities({
    limit: mode === "entity" ? 50 : 80,
    min_mentions: mode === "entity" ? 1 : 0,
  });

  const { data: edgesData } = useGraphEdges({});

  // Compute layout synchronously (pure function, no side effects)
  const layout = useMemo(
    () => computeLayout(entities ?? [], edgesData ?? []),
    [entities, edgesData],
  );

  // React Flow manages node/edge state internally for drag/interaction
  const [nodes, setNodes, onNodesChange] = useNodesState(layout.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout.edges);

  // Re-layout when data changes (new key = fresh state)
  const dataKey = `${entities?.length ?? 0}-${edgesData?.length ?? 0}`;
  useMemo(() => {
    if (layout.nodes.length > 0) {
      setNodes(layout.nodes);
      setEdges(layout.edges);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataKey]);

  // Apply selection highlighting
  const displayNodes = useMemo(() => {
    if (!selectedNode) return nodes;

    const connected = new Set<string>([selectedNode]);
    for (const e of edges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connected.add(e.source);
        connected.add(e.target);
      }
    }

    return nodes.map((n) => ({
      ...n,
      style: connected.has(n.id)
        ? { opacity: 1 }
        : { opacity: 0.15, transition: "opacity 0.3s ease" },
    }));
  }, [nodes, edges, selectedNode]);

  const displayEdges = useMemo(() => {
    if (!selectedNode) return edges;

    const connectedEdges = new Set<string>();
    for (const e of edges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connectedEdges.add(e.id);
      }
    }

    return edges.map((e) => ({
      ...e,
      style: connectedEdges.has(e.id)
        ? { opacity: 1 }
        : { opacity: 0.05, transition: "opacity 0.3s ease" },
    }));
  }, [edges, selectedNode]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode((prev) => (prev === node.id ? null : node.id));
    },
    [],
  );

  const onNodeDoubleClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      const label = (node.data as Record<string, unknown>).label as string;
      router.push(`/claims?entity=${encodeURIComponent(label)}`);
    },
    [router],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNode(null);
  }, []);

  return (
    <div className="relative h-full w-full" style={{ background: "#0a0908" }}>
      {/* Ambient center glow — makes graph area feel lit */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background: "radial-gradient(ellipse 60% 50% at 50% 45%, rgba(217,119,6,0.04) 0%, rgba(217,119,6,0.015) 40%, transparent 70%)",
          zIndex: 0,
        }}
      />
      <CursorGlow />
      <ReactFlow
        nodes={displayNodes}
        edges={displayEdges}
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

// ─── Export ──────────────────────────────────────────────────────────

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
