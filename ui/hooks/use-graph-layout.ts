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
  // Logarithmic scaling: stabilizes at large N instead of blowing up
  // N=50: charge=-655, link=345, collide=91
  // N=200: charge=-812, link=425, collide=112
  // N=400: charge=-912, link=476, collide=122
  const logN = Math.log2(n + 1);
  const chargeStrength = -200 - 80 * logN;
  const linkDist = 120 + 40 * logN;
  const collideR = 35 + 10 * logN;

  const sim = forceSimulation<SimNode>(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimulationLinkDatum<SimNode>>(simLinks)
        .id((d) => d.nodeId)
        .distance(linkDist)
        .strength(0.5),
    )
    .force("charge", forceManyBody<SimNode>().strength(chargeStrength).distanceMax(linkDist * 4))
    .force("center", forceCenter(0, 0).strength(0.08))
    .force("collide", forceCollide<SimNode>(collideR).strength(0.8))
    .force("x", forceX<SimNode>(0).strength(0.04))
    .force("y", forceY<SimNode>(0).strength(0.04))
    .velocityDecay(0.35)
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
