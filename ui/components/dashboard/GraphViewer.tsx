"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
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
} from "d3-force";

import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import type { EntityNode, EdgeData } from "@/lib/types";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { CursorGlow } from "./CursorGlow";
import { ZoomControls } from "./ZoomControls";

const nodeTypes = { pulse: PulseNode };
const edgeTypes = { salience: SalienceEdge };

/* ─── d3-force Live Physics ──────────────────────────────────────────
 *
 * Uses d3-force simulation running in real time:
 *   - forceManyBody: nodes repel each other (electrostatic)
 *   - forceLink: edges act as springs pulling connected nodes
 *   - forceCenter: keeps the graph centered
 *   - forceCollide: prevents node overlap
 *   - forceX/Y: gentle gravity toward center
 *
 * Dragging a node pins it (fx/fy), releasing unpins it.
 * The simulation runs continuously via requestAnimationFrame.
 * ──────────────────────────────────────────────────────────────────── */

interface SimNode extends SimulationNodeDatum {
  id: string;
  data: {
    label: string;
    mentionCount: number;
    claimCount: number;
    entityType: string | null;
  };
}

function useForceLayout(
  entities: EntityNode[],
  edgeData: EdgeData[],
) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const simulationRef = useRef<ReturnType<typeof forceSimulation<SimNode>> | null>(null);
  const animFrameRef = useRef<number>(0);
  const simNodesRef = useRef<SimNode[]>([]);

  useEffect(() => {
    if (!entities.length) {
      setNodes([]);
      setEdges([]);
      return;
    }

    // Build name → id map
    const idByName = new Map<string, string>();
    for (const e of entities) idByName.set(e.name, e.id);

    // Create simulation nodes
    const simNodes: SimNode[] = entities.map((entity, i) => {
      // Initialize in a circle for faster convergence
      const angle = (i / entities.length) * 2 * Math.PI;
      const r = 150 + Math.random() * 50;
      return {
        id: entity.id,
        x: Math.cos(angle) * r,
        y: Math.sin(angle) * r,
        data: {
          label: entity.name,
          mentionCount: entity.mention_count,
          claimCount: 0,
          entityType: entity.type,
        },
      };
    });
    simNodesRef.current = simNodes;

    // Create simulation links
    const simLinks: SimulationLinkDatum<SimNode>[] = [];
    const rfEdges: Edge[] = [];
    let edgeIdx = 0;

    for (const edge of edgeData) {
      const sourceId = idByName.get(edge.from_entity);
      const targetId = idByName.get(edge.to_entity);
      if (!sourceId || !targetId || sourceId === targetId) continue;

      const source = simNodes.find((n) => n.id === sourceId);
      const target = simNodes.find((n) => n.id === targetId);
      if (!source || !target) continue;

      simLinks.push({ source, target });
      rfEdges.push({
        id: `e-${edgeIdx++}-${sourceId}-${targetId}`,
        source: sourceId,
        target: targetId,
        type: "salience",
        data: {
          relType: edge.rel_type,
          confidence: edge.confidence,
          fact: edge.fact,
        },
      });
    }
    setEdges(rfEdges);

    // --- Configure forces ---
    const n = simNodes.length;
    // More nodes → more spread. Scale charge and distance.
    const chargeStrength = Math.min(-300, -150 * Math.sqrt(n));
    const linkDistance = Math.max(120, 60 + n * 4);
    const collideRadius = 40 + n * 0.5;

    const sim = forceSimulation<SimNode>(simNodes)
      .force(
        "link",
        forceLink<SimNode, SimulationLinkDatum<SimNode>>(simLinks)
          .id((d) => d.id)
          .distance(linkDistance)
          .strength(0.4),
      )
      .force("charge", forceManyBody<SimNode>().strength(chargeStrength).distanceMax(800))
      .force("center", forceCenter(0, 0).strength(0.05))
      .force("collide", forceCollide<SimNode>(collideRadius).strength(0.7))
      // Gentle pull to center to prevent disconnected clusters from flying away
      .force("x", forceX<SimNode>(0).strength(0.03))
      .force("y", forceY<SimNode>(0).strength(0.03))
      .alphaDecay(0.01) // Slow decay = longer settling, smoother
      .velocityDecay(0.3); // Friction

    simulationRef.current = sim;

    // --- Render loop via requestAnimationFrame ---
    function tick() {
      setNodes(
        simNodes.map((sn) => ({
          id: sn.id,
          type: "pulse" as const,
          position: { x: sn.x ?? 0, y: sn.y ?? 0 },
          data: sn.data,
        })),
      );
      animFrameRef.current = requestAnimationFrame(tick);
    }

    // Start the loop
    animFrameRef.current = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(animFrameRef.current);
      sim.stop();
    };
  }, [entities, edgeData]);

  // Drag handlers — pin/unpin nodes in the simulation
  const onNodeDragStart: OnNodeDrag = useCallback((_event, node) => {
    const sim = simulationRef.current;
    if (!sim) return;
    // Reheat simulation for responsive dragging
    sim.alphaTarget(0.3).restart();
    const simNode = simNodesRef.current.find((n) => n.id === node.id);
    if (simNode) {
      simNode.fx = node.position.x;
      simNode.fy = node.position.y;
    }
  }, []);

  const onNodeDrag: OnNodeDrag = useCallback((_event, node) => {
    const simNode = simNodesRef.current.find((n) => n.id === node.id);
    if (simNode) {
      simNode.fx = node.position.x;
      simNode.fy = node.position.y;
    }
  }, []);

  const onNodeDragStop: OnNodeDrag = useCallback((_event, node) => {
    const sim = simulationRef.current;
    if (!sim) return;
    sim.alphaTarget(0); // Cool down
    const simNode = simNodesRef.current.find((n) => n.id === node.id);
    if (simNode) {
      // Unpin — let physics take over again
      simNode.fx = null;
      simNode.fy = null;
    }
  }, []);

  return { nodes, edges, onNodeDragStart, onNodeDrag, onNodeDragStop };
}

// ─── Graph Canvas Component ─────────────────────────────────────────

interface GraphCanvasProps {
  mode: "entity" | "full";
}

function GraphCanvas({ mode }: GraphCanvasProps) {
  const router = useRouter();
  const { fitView } = useReactFlow();
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const hasFitRef = useRef(false);

  const { data: entities } = useGraphEntities({
    limit: mode === "entity" ? 50 : 80,
    min_mentions: mode === "entity" ? 1 : 0,
  });

  const { data: edgesData } = useGraphEdges({});

  const {
    nodes: simNodes,
    edges: simEdges,
    onNodeDragStart,
    onNodeDrag,
    onNodeDragStop,
  } = useForceLayout(entities ?? [], edgesData ?? []);

  // Fit view once after first data load + settle
  useEffect(() => {
    if (simNodes.length > 0 && !hasFitRef.current) {
      const t = setTimeout(() => {
        fitView({ padding: 0.3, duration: 600 });
        hasFitRef.current = true;
      }, 800); // wait for simulation to settle a bit
      return () => clearTimeout(t);
    }
  }, [simNodes.length, fitView]);

  // Apply selection highlighting
  const displayNodes = useMemo(() => {
    if (!selectedNode) return simNodes;

    const connected = new Set<string>([selectedNode]);
    for (const e of simEdges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connected.add(e.source);
        connected.add(e.target);
      }
    }

    return simNodes.map((n) => ({
      ...n,
      style: connected.has(n.id)
        ? { opacity: 1 }
        : { opacity: 0.15, transition: "opacity 0.3s ease" },
    }));
  }, [simNodes, simEdges, selectedNode]);

  const displayEdges = useMemo(() => {
    if (!selectedNode) return simEdges;

    const connectedEdges = new Set<string>();
    for (const e of simEdges) {
      if (e.source === selectedNode || e.target === selectedNode) {
        connectedEdges.add(e.id);
      }
    }

    return simEdges.map((e) => ({
      ...e,
      style: connectedEdges.has(e.id)
        ? { opacity: 1 }
        : { opacity: 0.05, transition: "opacity 0.3s ease" },
    }));
  }, [simEdges, selectedNode]);

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
      <CursorGlow />
      <ReactFlow
        nodes={displayNodes}
        edges={displayEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodeClick={onNodeClick}
        onNodeDoubleClick={onNodeDoubleClick}
        onNodeDragStart={onNodeDragStart}
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
}

export function GraphViewer({ mode = "entity" }: GraphViewerProps) {
  return (
    <ReactFlowProvider>
      <GraphCanvas mode={mode} />
    </ReactFlowProvider>
  );
}
