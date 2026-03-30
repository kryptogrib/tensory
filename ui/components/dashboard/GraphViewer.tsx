"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  type Node,
  type NodeMouseHandler,
  type OnNodeDrag,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useRouter } from "next/navigation";

import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import { useGraphLayout } from "@/hooks/use-graph-layout";
import type { PhysicsParams } from "./PhysicsTuner";
import { DEFAULT_PHYSICS } from "./PhysicsTuner";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { CursorGlow } from "./CursorGlow";
import { ZoomControls } from "./ZoomControls";

const nodeTypes = { pulse: PulseNode };
const edgeTypes = { salience: SalienceEdge };

// ─── Graph Canvas Component ─────────────────────────────────────────

interface GraphCanvasProps {
  mode: "entity" | "full";
  physics: PhysicsParams;
}

function GraphCanvas({ mode, physics }: GraphCanvasProps) {
  const router = useRouter();
  const { fitView } = useReactFlow();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const lastDragUpdateRef = useRef<number>(0);
  const physicsRef = useRef(physics);
  physicsRef.current = physics;

  const { data: entities } = useGraphEntities({
    limit: mode === "entity" ? 50 : 80,
    min_mentions: mode === "entity" ? 1 : 0,
  });

  const { data: edgesData } = useGraphEdges({});

  // Use extracted layout hook
  const { layout, simRef, rafRef } = useGraphLayout(entities, edgesData);

  // React Flow manages node/edge state
  const [nodes, setNodes, onNodesChange] = useNodesState(layout?.nodes ?? []);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layout?.edges ?? []);

  // Sync React Flow state when layout changes
  const dataKey = `${entities?.length ?? 0}-${edgesData?.length ?? 0}`;
  useMemo(() => {
    if (!layout || layout.nodes.length === 0) return;
    setNodes(layout.nodes);
    setEdges(layout.edges);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataKey]);

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
  }, [simRef]);

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
    [setNodes, simRef, rafRef],
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
    [setNodes, syncSimPositions, simRef, rafRef],
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
