"use client";

import { useMemo, useRef, useEffect } from "react";
import {
  type Node,
  type Edge,
} from "@xyflow/react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceRadial,
  forceX,
  forceY,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
  type Simulation,
} from "d3-force";

import type { EntityNode, EdgeData } from "@/lib/types";

/* ─── d3-force Layout + Live Simulation ────────────────────────────────
 *
 * The simulation runs synchronously at mount for initial layout (300 ticks),
 * then stays ALIVE in a useRef (alpha=0, sleeping). On drag:
 *   - onNodeDrag:  pin fx/fy, sync-tick 2-3 times, update neighbor positions
 *   - onNodeDragStop: unpin, short RAF settle (8 ticks over ~150ms)
 *
 * This avoids continuous render loops while giving floaty, meditative physics.
 * ──────────────────────────────────────────────────────────────────── */

export interface SimNode extends SimulationNodeDatum {
  nodeId: string;
  label: string;
  mentionCount: number;
  entityType: string | null;
}

/** Return value from layout computation -- includes the live simulation. */
export interface LayoutResult {
  nodes: Node[];
  edges: Edge[];
  sim: Simulation<SimNode, SimulationLinkDatum<SimNode>>;
  simNodes: SimNode[];
  simNodeMap: Map<string, SimNode>;
  /** Adjacency: nodeId -> Set of 1-hop neighbor nodeIds */
  adjacency: Map<string, Set<string>>;
  /** 2-hop adjacency: nodeId -> Set of 2-hop neighbor nodeIds (excluding 1-hop) */
  adjacency2: Map<string, Set<string>>;
  /** Edge confidence map: "srcId-tgtId" -> confidence */
  confidenceMap: Map<string, number>;
}

export function computeLayout(
  entities: EntityNode[],
  edgeData: EdgeData[],
): LayoutResult | null {
  if (entities.length === 0) return null;

  const n = entities.length;
  const idByName = new Map<string, string>();
  for (const e of entities) idByName.set(e.name, e.id);

  // Create sim nodes -- initialize on a circle for faster convergence
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
  // Identify isolated nodes (degree 0) vs connected
  const degreeMap = new Map<string, number>();
  for (const sn of simNodes) degreeMap.set(sn.nodeId, 0);
  for (const link of simLinks) {
    const src = (link.source as SimNode).nodeId;
    const tgt = (link.target as SimNode).nodeId;
    degreeMap.set(src, (degreeMap.get(src) ?? 0) + 1);
    degreeMap.set(tgt, (degreeMap.get(tgt) ?? 0) + 1);
  }

  const connectedCount = [...degreeMap.values()].filter((d) => d > 0).length;
  const logC = Math.log2(Math.max(connectedCount, 2));

  // Connected nodes: tight clusters via strong link force
  const linkDist = 80 + 20 * logC;
  const collideR = 30 + 5 * logC;

  // Charge: connected nodes repel moderately, isolated nodes repel less
  const connectedCharge = -150 - 50 * logC;
  const isolatedCharge = connectedCharge * 0.3;

  // Peripheral radius for isolated nodes
  const peripheryR = Math.max(300, linkDist * connectedCount * 0.15);

  const sim = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(simLinks)
        .id((d) => d.nodeId)
        .distance(linkDist)
        .strength(1.2), // Strong — pull connected nodes tight
    )
    .force(
      "charge",
      forceManyBody<SimNode>()
        .strength((d) => {
          const degree = degreeMap.get((d as SimNode).nodeId) ?? 0;
          return degree > 0 ? connectedCharge : isolatedCharge;
        })
        .distanceMax(linkDist * 5),
    )
    .force("center", forceCenter(0, 0).strength(0.05))
    .force("collide", forceCollide<SimNode>(collideR).strength(0.7))
    // Connected nodes: pull toward center
    .force(
      "x",
      forceX<SimNode>(0).strength((d) => {
        const degree = degreeMap.get((d as SimNode).nodeId) ?? 0;
        return degree > 0 ? 0.08 : 0.01;
      }),
    )
    .force(
      "y",
      forceY<SimNode>(0).strength((d) => {
        const degree = degreeMap.get((d as SimNode).nodeId) ?? 0;
        return degree > 0 ? 0.08 : 0.01;
      }),
    )
    // Isolated nodes: push to periphery ring
    .force(
      "radial",
      forceRadial<SimNode>(
        (d) => {
          const degree = degreeMap.get((d as SimNode).nodeId) ?? 0;
          return degree > 0 ? 0 : peripheryR;
        },
        0,
        0,
      ).strength((d) => {
        const degree = degreeMap.get((d as SimNode).nodeId) ?? 0;
        return degree > 0 ? 0 : 0.3;
      }),
    )
    .velocityDecay(0.4)
    .stop();

  // --- Position cache: restore from localStorage for stable layouts ---
  const TICKS = 300;
  const sortedIds = simNodes.map((s) => s.nodeId).sort();
  // Use a hash of node ids (first 200 chars) as cache key
  const cacheKey = `tensory-layout-${sortedIds.join(",").slice(0, 200)}`;
  let usedCache = false;

  try {
    const cached = localStorage.getItem(cacheKey);
    if (cached) {
      const positions = JSON.parse(cached) as Record<
        string,
        { x: number; y: number }
      >;
      for (const sn of simNodes) {
        const pos = positions[sn.nodeId];
        if (pos) {
          sn.x = pos.x;
          sn.y = pos.y;
        }
      }
      // Fewer ticks needed — positions already good
      for (let i = 0; i < 50; i++) sim.tick();
      usedCache = true;
    }
  } catch {
    // localStorage unavailable (private mode, etc.) — ignore
  }

  if (!usedCache) {
    for (let i = 0; i < TICKS; i++) sim.tick();
  }

  // Save positions to cache
  try {
    const posMap: Record<string, { x: number; y: number }> = {};
    for (const sn of simNodes) {
      posMap[sn.nodeId] = { x: sn.x ?? 0, y: sn.y ?? 0 };
    }
    localStorage.setItem(cacheKey, JSON.stringify(posMap));
  } catch {
    // localStorage full or unavailable — ignore
  }

  // Build React Flow nodes from final positions
  const rfNodes: Node[] = simNodes.map((sn) => {
    const degree = degreeMap.get(sn.nodeId) ?? 0;
    const isIsolated = degree === 0;
    return {
      id: sn.nodeId,
      type: "pulse",
      position: { x: sn.x ?? 0, y: sn.y ?? 0 },
      data: {
        label: sn.label,
        // Isolated nodes appear smaller (lower mention count → smaller PulseNode)
        mentionCount: isIsolated
          ? Math.min(sn.mentionCount, 1)
          : sn.mentionCount,
        claimCount: 0,
        entityType: sn.entityType,
      },
      // Dim isolated nodes
      style: isIsolated ? { opacity: 0.4 } : undefined,
    };
  });

  // Keep sim alive but sleeping (alpha->0)
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

/** Ref shape for simulation state used by drag handlers. */
export interface SimulationState {
  sim: Simulation<SimNode, SimulationLinkDatum<SimNode>>;
  simNodes: SimNode[];
  simNodeMap: Map<string, SimNode>;
  adjacency: Map<string, Set<string>>;
  adjacency2: Map<string, Set<string>>;
  confidenceMap: Map<string, number>;
}

/**
 * Hook that runs d3-force layout synchronously in useMemo and manages
 * the simulation ref for drag physics.
 *
 * Returns the layout result, a simRef for drag handlers, and a rafRef
 * for settle animation cleanup.
 */
export function useGraphLayout(
  entities: EntityNode[] | undefined,
  edgeData: EdgeData[] | undefined,
) {
  // Compute layout (pure function + keeps simulation alive)
  const layout = useMemo(
    () => computeLayout(entities ?? [], edgeData ?? []),
    [entities, edgeData],
  );

  // Refs for simulation state
  const simRef = useRef<SimulationState | null>(null);
  const rafRef = useRef<number | null>(null);

  // Re-layout + rebuild sim ref when data changes
  const dataKey = `${entities?.length ?? 0}-${edgeData?.length ?? 0}`;
  useMemo(() => {
    if (!layout || layout.nodes.length === 0) return;

    // Cancel any running settle
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }

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

  return { layout, simRef, rafRef };
}
