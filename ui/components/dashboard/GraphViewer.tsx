"use client";

import { useCallback, useMemo, useRef, useState, useEffect } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  type OnNodeDrag,
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
  type Simulation,
} from "d3-force";

import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import type { EntityNode, EdgeData } from "@/lib/types";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { CursorGlow } from "./CursorGlow";
import { ZoomControls } from "./ZoomControls";
import {
  PhysicsTuner,
  DEFAULT_PHYSICS,
  type PhysicsParams,
} from "./PhysicsTuner";

const nodeTypes = { pulse: PulseNode };
const edgeTypes = { salience: SalienceEdge };

/* ─── d3-force Layout + Live Simulation ────────────────────────────────
 *
 * The simulation runs synchronously at mount for initial layout (300 ticks),
 * then stays ALIVE in a useRef (alpha≈0, sleeping). On drag:
 *   - onNodeDrag:  pin fx/fy, sync-tick 2-3 times, update neighbor positions
 *   - onNodeDragStop: unpin, short RAF settle (8 ticks over ~150ms)
 *
 * This avoids continuous render loops while giving floaty, meditative physics.
 * ──────────────────────────────────────────────────────────────────── */

interface SimNode extends SimulationNodeDatum {
  nodeId: string;
  label: string;
  mentionCount: number;
  entityType: string | null;
}

/** Return value from layout computation — includes the live simulation. */
interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
  sim: Simulation<SimNode, SimulationLinkDatum<SimNode>>;
  simNodes: SimNode[];
  simNodeMap: Map<string, SimNode>;
  /** Adjacency: nodeId → Set of 1-hop neighbor nodeIds */
  adjacency: Map<string, Set<string>>;
  /** 2-hop adjacency: nodeId → Set of 2-hop neighbor nodeIds (excluding 1-hop) */
  adjacency2: Map<string, Set<string>>;
  /** Edge confidence map: "srcId-tgtId" → confidence */
  confidenceMap: Map<string, number>;
}

function computeLayout(
  entities: EntityNode[],
  edgeData: EdgeData[],
): LayoutResult | null {
  if (entities.length === 0) return null;

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

  // Build links, edges, adjacency, confidence
  const simNodeMap = new Map<string, SimNode>();
  for (const sn of simNodes) simNodeMap.set(sn.nodeId, sn);

  const simLinks: SimulationLinkDatum<SimNode>[] = [];
  const rfEdges: Edge[] = [];
  const adjacency = new Map<string, Set<string>>();
  const confidenceMap = new Map<string, number>();
  let idx = 0;

  // Init adjacency for all nodes
  for (const sn of simNodes) adjacency.set(sn.nodeId, new Set());

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

    // Build adjacency
    adjacency.get(srcId)!.add(tgtId);
    adjacency.get(tgtId)!.add(srcId);

    // Confidence map (bidirectional)
    const conf = edge.confidence ?? 0.5;
    confidenceMap.set(`${srcId}-${tgtId}`, conf);
    confidenceMap.set(`${tgtId}-${srcId}`, conf);
  }

  // Build 2-hop adjacency
  const adjacency2 = new Map<string, Set<string>>();
  for (const [nodeId, neighbors] of adjacency) {
    const hop2 = new Set<string>();
    for (const n1 of neighbors) {
      const n1Neighbors = adjacency.get(n1);
      if (!n1Neighbors) continue;
      for (const n2 of n1Neighbors) {
        if (n2 !== nodeId && !neighbors.has(n2)) hop2.add(n2);
      }
    }
    adjacency2.set(nodeId, hop2);
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
    .stop();

  // Run 300 ticks synchronously (instant, <10ms for 100 nodes)
  const TICKS = 300;
  for (let i = 0; i < TICKS; i++) sim.tick();

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

  // Keep sim alive but sleeping (alpha→0)
  sim.alpha(0).stop();

  return {
    nodes: rfNodes,
    edges: rfEdges,
    sim,
    simNodes,
    simNodeMap,
    adjacency,
    adjacency2,
    confidenceMap,
  };
}

// ─── Graph Canvas Component ─────────────────────────────────────────

interface GraphCanvasProps {
  mode: "entity" | "full";
  physics: PhysicsParams;
}

function GraphCanvas({ mode, physics }: GraphCanvasProps) {
  const router = useRouter();
  const { fitView } = useReactFlow();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  // Refs for simulation state
  const simRef = useRef<{
    sim: Simulation<SimNode, SimulationLinkDatum<SimNode>>;
    simNodes: SimNode[];
    simNodeMap: Map<string, SimNode>;
    adjacency: Map<string, Set<string>>;
    adjacency2: Map<string, Set<string>>;
    confidenceMap: Map<string, number>;
  } | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastDragUpdateRef = useRef<number>(0);
  const physicsRef = useRef(physics);
  physicsRef.current = physics;

  const { data: entities } = useGraphEntities({
    limit: mode === "entity" ? 50 : 80,
    min_mentions: mode === "entity" ? 1 : 0,
  });

  const { data: edgesData } = useGraphEdges({});

  // Compute layout (pure function + keeps simulation alive)
  const layout = useMemo(
    () => computeLayout(entities ?? [], edgesData ?? []),
    [entities, edgesData],
  );

  // React Flow manages node/edge state
  const [nodes, setNodes, onNodesChange] = useNodesState(layout?.nodes ?? []);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout?.edges ?? []);

  // Re-layout + rebuild sim ref when data changes
  const dataKey = `${entities?.length ?? 0}-${edgesData?.length ?? 0}`;
  useMemo(() => {
    if (!layout || layout.nodes.length === 0) return;

    // Cancel any running settle
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

    setNodes(layout.nodes);
    setEdges(layout.edges);

    // Store simulation ref for drag physics
    simRef.current = {
      sim: layout.sim,
      simNodes: layout.simNodes,
      simNodeMap: layout.simNodeMap,
      adjacency: layout.adjacency,
      adjacency2: layout.adjacency2,
      confidenceMap: layout.confidenceMap,
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataKey]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ─── Drag Physics ──────────────────────────────────────────────────

  /** Sync simulation node positions from React Flow (for non-dragged nodes). */
  const syncSimPositions = useCallback((currentNodes: Node[]) => {
    const state = simRef.current;
    if (!state) return;
    for (const n of currentNodes) {
      const sn = state.simNodeMap.get(n.id);
      if (sn && sn.fx == null) {
        // Only update non-pinned nodes
        sn.x = n.position.x;
        sn.y = n.position.y;
      }
    }
  }, []);

  const onNodeDrag: OnNodeDrag = useCallback(
    (_event, node) => {
      const state = simRef.current;
      if (!state) return;
      const p = physicsRef.current;

      // Cancel any running settle from previous drag
      if (rafRef.current) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }

      // Pin dragged node
      const simNode = state.simNodeMap.get(node.id);
      if (!simNode) return;
      simNode.fx = node.position.x;
      simNode.fy = node.position.y;
      simNode.x = node.position.x;
      simNode.y = node.position.y;

      // Throttle: update neighbors at ~30fps
      const now = Date.now();
      if (now - lastDragUpdateRef.current < 32) return;
      lastDragUpdateRef.current = now;

      // Apply velocity nudge to neighbors based on confidence
      const neighbors1 = state.adjacency.get(node.id);
      const neighbors2 = state.adjacency2.get(node.id);

      if (neighbors1) {
        for (const nId of neighbors1) {
          const sn = state.simNodeMap.get(nId);
          if (!sn || sn.fx != null) continue;
          const conf = state.confidenceMap.get(`${node.id}-${nId}`) ?? 0.5;
          const dx = (node.position.x - (sn.x ?? 0)) * p.neighborStrength * conf * 0.02;
          const dy = (node.position.y - (sn.y ?? 0)) * p.neighborStrength * conf * 0.02;
          sn.vx = (sn.vx ?? 0) + dx;
          sn.vy = (sn.vy ?? 0) + dy;
        }
      }

      if (neighbors2 && p.neighbor2Strength > 0) {
        for (const nId of neighbors2) {
          const sn = state.simNodeMap.get(nId);
          if (!sn || sn.fx != null) continue;
          const dx = (node.position.x - (sn.x ?? 0)) * p.neighbor2Strength * 0.005;
          const dy = (node.position.y - (sn.y ?? 0)) * p.neighbor2Strength * 0.005;
          sn.vx = (sn.vx ?? 0) + dx;
          sn.vy = (sn.vy ?? 0) + dy;
        }
      }

      // Configure sim for drag
      state.sim.velocityDecay(p.velocityDecay);
      state.sim.alpha(p.dragAlpha);

      // Sync tick
      for (let i = 0; i < p.ticksPerDrag; i++) state.sim.tick();
      state.sim.stop();

      // Update neighbor positions in React Flow
      const toUpdate = new Set<string>();
      if (neighbors1) for (const id of neighbors1) toUpdate.add(id);
      if (neighbors2 && p.neighbor2Strength > 0) {
        for (const id of neighbors2) toUpdate.add(id);
      }

      if (toUpdate.size > 0) {
        setNodes((prev) =>
          prev.map((n) => {
            if (!toUpdate.has(n.id)) return n;
            const sn = state.simNodeMap.get(n.id);
            if (!sn) return n;
            return { ...n, position: { x: sn.x ?? 0, y: sn.y ?? 0 } };
          }),
        );
      }
    },
    [setNodes],
  );

  const onNodeDragStop: OnNodeDrag = useCallback(
    (_event, node) => {
      const state = simRef.current;
      if (!state) return;
      const p = physicsRef.current;

      // Unpin dragged node
      const simNode = state.simNodeMap.get(node.id);
      if (simNode) {
        simNode.fx = null;
        simNode.fy = null;
        // Set final position
        simNode.x = node.position.x;
        simNode.y = node.position.y;
      }

      if (p.settleTicks <= 0) return;

      // Sync all current positions into sim before settle
      setNodes((prev) => {
        syncSimPositions(prev);
        return prev;
      });

      // Short RAF settle
      let ticksLeft = p.settleTicks;
      state.sim.velocityDecay(p.velocityDecay);
      state.sim.alpha(p.settleAlpha);

      const settle = () => {
        if (ticksLeft-- <= 0 || !simRef.current) {
          rafRef.current = null;
          return;
        }

        state.sim.tick();
        state.sim.stop();

        setNodes((prev) =>
          prev.map((n) => {
            const sn = state.simNodeMap.get(n.id);
            if (!sn) return n;
            const nx = sn.x ?? 0;
            const ny = sn.y ?? 0;
            // Skip update if position barely changed (< 0.5px)
            if (
              Math.abs(n.position.x - nx) < 0.5 &&
              Math.abs(n.position.y - ny) < 0.5
            ) {
              return n;
            }
            return { ...n, position: { x: nx, y: ny } };
          }),
        );

        rafRef.current = requestAnimationFrame(settle);
      };

      rafRef.current = requestAnimationFrame(settle);
    },
    [setNodes, syncSimPositions],
  );

  // ─── Selection Highlighting ──────────────────────────────────────

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

  // ─── Event Handlers ──────────────────────────────────────────────

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
      {/* Ambient center glow */}
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
        onNodeDrag={onNodeDrag}
        onNodeDragStop={onNodeDragStop}
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
  physics?: PhysicsParams;
}

export function GraphViewer({
  mode = "entity",
  physics = DEFAULT_PHYSICS,
}: GraphViewerProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvas mode={mode} physics={physics} />
    </ReactFlowProvider>
  );
}
