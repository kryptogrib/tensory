"use client";

import { useCallback, useMemo, useState, useEffect } from "react";
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

/**
 * Lay out nodes in concentric circles, sorted by mention_count DESC.
 * Center node is the most mentioned entity.
 */
function layoutNodes(entities: EntityNode[]): Node[] {
  if (entities.length === 0) return [];

  const sorted = [...entities].sort((a, b) => b.mention_count - a.mention_count);
  const centerX = 0;
  const centerY = 0;

  return sorted.map((entity, i) => {
    let x: number;
    let y: number;

    if (i === 0) {
      x = centerX;
      y = centerY;
    } else {
      // Concentric rings: ~6 per first ring, ~12 per second, etc.
      const ring = Math.ceil(Math.sqrt(i / 3));
      const radius = ring * 200;
      // Count nodes in this ring for even spacing
      const ringStart = Math.round(3 * (ring - 1) * (ring - 1));
      const ringCapacity = Math.round(3 * (2 * ring - 1));
      const posInRing = i - ringStart;
      const angle = (posInRing / ringCapacity) * 2 * Math.PI - Math.PI / 2;
      // Add slight jitter for organic feel
      const jitter = (Math.sin(i * 7.3) * 20);
      x = centerX + Math.cos(angle) * radius + jitter;
      y = centerY + Math.sin(angle) * radius + jitter;
    }

    return {
      id: entity.id,
      type: "pulse",
      position: { x, y },
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

  const initialNodes = useMemo(
    () => layoutNodes(entities ?? []),
    [entities]
  );

  const initialEdges = useMemo(
    () => buildEdges(edgesData ?? [], entities ?? []),
    [edgesData, entities]
  );

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Sync when data changes
  useEffect(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);

  useEffect(() => {
    setEdges(initialEdges);
  }, [initialEdges, setEdges]);

  // Dim unconnected nodes/edges on selection
  useEffect(() => {
    if (!selectedNode) {
      // Reset all
      setNodes((nds) =>
        nds.map((n) => ({ ...n, selected: false }))
      );
      setEdges((eds) =>
        eds.map((e) => ({ ...e, selected: false }))
      );
      return;
    }

    const connectedEdgeIds = new Set<string>();
    const connectedNodeIds = new Set<string>([selectedNode]);

    edges.forEach((e) => {
      if (e.source === selectedNode || e.target === selectedNode) {
        connectedEdgeIds.add(e.id);
        connectedNodeIds.add(e.source);
        connectedNodeIds.add(e.target);
      }
    });

    setNodes((nds) =>
      nds.map((n) => ({
        ...n,
        selected: connectedNodeIds.has(n.id),
        style: connectedNodeIds.has(n.id)
          ? { opacity: 1 }
          : { opacity: 0.2, transition: "opacity 0.3s ease" },
      }))
    );

    setEdges((eds) =>
      eds.map((e) => ({
        ...e,
        selected: connectedEdgeIds.has(e.id),
      }))
    );
  }, [selectedNode, edges, setNodes, setEdges]);

  const onNodeClick: NodeMouseHandler = useCallback(
    (_event, node) => {
      setSelectedNode((prev) => (prev === node.id ? null : node.id));
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
  }, []);

  return (
    <div className="relative h-full w-full" style={{ background: "#0a0908" }}>
      <CursorGlow />
      <ReactFlow
        nodes={nodes}
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
