"use client";

import { useState, useCallback, useMemo, useEffect } from "react";
import {
  ReactFlow,
  ReactFlowProvider,
  Background,
  type Node,
  type Edge,
  type OnNodeDrag,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTimelineRange, useEntityTimeline, useEntityTimestamps } from "@/hooks/use-timeline";
import { useGraphLayout } from "@/hooks/use-graph-layout";
import { useGraphEntities, useGraphEdges } from "@/hooks/use-graph";
import { TimelineSlider } from "./TimelineSlider";
import { EntityTimeline } from "./EntityTimeline";
import { GhostNode } from "./GhostNode";
import { PulseNode } from "./PulseNode";
import { SalienceEdge } from "./SalienceEdge";
import { ZoomControls } from "./ZoomControls";
import { HudWindow } from "./HudWindow";

import type { EntityNode } from "@/lib/types";

/* ─── Timeline Page Orchestrator ──────────────────────────────────────
 *
 * Manages:
 *   - selectedDate state (slider position)
 *   - selectedEntity state (entity panel selection)
 *   - Debounced snapshot fetching (150ms)
 *   - Bi-directional sync between slider and entity timeline
 *
 * Layout:
 *   ┌──────────────────────────────────────────┐
 *   │ Entity Panel (300px)  │  Graph (flex-1)  │
 *   │                       │                  │
 *   │ [entity picker]       │  [ReactFlow]     │
 *   │ [branching timeline]  │                  │
 *   │ [stats bar]           │                  │
 *   │                       ├─────────────────-│
 *   │                       │ [TimelineSlider] │
 *   └──────────────────────────────────────────┘
 * ──────────────────────────────────────────── */

const nodeTypes = {
  pulse: PulseNode,
  ghost: GhostNode,
} as const;

const edgeTypes = {
  salience: SalienceEdge,
} as const;

export function TimelinePage() {
  // ── State ──────────────────────────────────
  const [selectedDate, setSelectedDate] = useState<Date | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [entitySearch, setEntitySearch] = useState("");

  // ── Data fetching (all loaded ONCE, no per-slider API calls) ──
  const { data: timelineRange } = useTimelineRange();
  const { data: entityEntries } = useEntityTimeline(selectedEntity);
  const { data: allGraphEntities } = useGraphEntities({ limit: 500, min_mentions: 1 });
  const { data: allGraphEdges } = useGraphEdges({});
  const { data: entityTimestamps } = useEntityTimestamps();

  // Build entity_id → earliest_at map for instant client-side filtering
  const entityEarliestMap = useMemo(() => {
    const map = new Map<string, number>(); // entity_id → ms
    if (!entityTimestamps) return map;
    for (const et of entityTimestamps) {
      map.set(et.entity_id, new Date(et.earliest_at).getTime());
    }
    return map;
  }, [entityTimestamps]);

  // Initialize slider at max_date when range loads
  useEffect(() => {
    if (timelineRange && selectedDate === null) {
      setSelectedDate(new Date(timelineRange.max_date));
    }
  }, [timelineRange, selectedDate]);

  // Slider change — instant, no API calls (client-side filtering)
  const handleDateChange = useCallback((date: Date) => {
    setSelectedDate(date);
  }, []);

  // ── Layout: compute ONCE from full graph, not per snapshot ───
  const { layout } = useGraphLayout(allGraphEntities, allGraphEdges);

  // Active entity IDs — computed CLIENT-SIDE from entityEarliestMap + selectedDate
  // No API call, instant on every slider movement
  const activeEntityIds = useMemo(() => {
    if (!selectedDate || entityEarliestMap.size === 0) return new Set<string>();
    const cutoffMs = selectedDate.getTime();
    const active = new Set<string>();
    for (const [entityId, earliestMs] of entityEarliestMap) {
      if (earliestMs <= cutoffMs) active.add(entityId);
    }
    return active;
  }, [selectedDate, entityEarliestMap]);

  // Apply active/ghost types to pre-computed layout positions (no physics recompute!)
  const flowNodes = useMemo<Node[]>(() => {
    if (!layout) return [];
    // If no snapshot loaded yet, show all as active
    if (activeEntityIds.size === 0) return layout.nodes;
    return layout.nodes.map((node) => {
      const isActive = activeEntityIds.has(node.id);
      return {
        ...node,
        type: isActive ? "pulse" : "ghost",
        data: isActive
          ? node.data
          : {
              name: (node.data as Record<string, unknown>).label as string,
              type: (node.data as Record<string, unknown>).entityType as string | null,
              first_seen: "",
            },
      };
    });
  }, [layout, activeEntityIds]);

  // Edges: show all from layout, dim edges between ghost nodes
  const flowEdges = useMemo<Edge[]>(() => {
    if (!layout) return [];
    if (activeEntityIds.size === 0) return layout.edges;
    return layout.edges.map((edge) => {
      const srcActive = activeEntityIds.has(edge.source);
      const tgtActive = activeEntityIds.has(edge.target);
      const bothActive = srcActive && tgtActive;
      return {
        ...edge,
        style: bothActive ? undefined : { opacity: 0.08 },
      };
    });
  }, [layout, activeEntityIds]);

  // ── Node click → select entity ─────────────
  const handleNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    const label = node.id.startsWith("ghost-")
      ? ((node.data as Record<string, unknown>).name as string)
      : ((node.data as Record<string, unknown>).label as string);
    if (label) {
      setSelectedEntity(label);
    }
  }, []);

  // ── Claim click in entity timeline → jump slider
  const handleClaimClick = useCallback((claimDate: Date) => {
    setSelectedDate(claimDate);
  }, []);

  // ── Drag handlers (pin/unpin via simulation ref) ──
  const handleNodeDrag: OnNodeDrag = useCallback(() => {
    // Basic drag — nodes are repositioned by ReactFlow automatically.
    // For full physics drag, wire up simRef from useGraphLayout.
  }, []);

  // ── Entity picker list (from full graph, not snapshot) ──
  const entityNames = useMemo(() => {
    if (!allGraphEntities) return [];
    return [...allGraphEntities]
      .sort((a, b) => b.mention_count - a.mention_count)
      .map((e) => e.name);
  }, [allGraphEntities]);

  const filteredEntityNames = useMemo(() => {
    if (!entitySearch) return entityNames;
    const q = entitySearch.toLowerCase();
    return entityNames.filter((n) => n.toLowerCase().includes(q));
  }, [entityNames, entitySearch]);

  // Stats computed client-side
  const stats = useMemo(() => ({
    active_entities: activeEntityIds.size,
    total_entities: allGraphEntities?.length ?? 0,
  }), [activeEntityIds, allGraphEntities]);

  if (!timelineRange || !selectedDate) {
    return (
      <div
        className="flex h-full w-full items-center justify-center"
        style={{ background: "#0a0908", color: "rgb(var(--text-secondary))", fontSize: 12 }}
      >
        Loading timeline...
      </div>
    );
  }

  return (
    <ReactFlowProvider>
    <div className="flex h-full w-full" style={{ background: "#0a0908" }}>
      {/* ── Left: Entity Panel ──────────────────── */}
      <div
        className="flex h-full flex-shrink-0 flex-col"
        style={{
          width: 300,
          borderRight: "1px solid rgba(217, 119, 6, 0.06)",
          background: "rgba(10, 9, 8, 0.95)",
        }}
      >
        {/* Entity Picker */}
        <HudWindow title={`Entity (${entityNames.length})`}>
          {/* Search */}
          <div style={{ padding: "4px 12px" }}>
            <input
              type="text"
              placeholder="Search entities..."
              value={entitySearch}
              onChange={(e) => setEntitySearch(e.target.value)}
              className="w-full rounded px-2 py-1"
              style={{
                fontSize: 10,
                background: "rgba(217, 119, 6, 0.05)",
                border: "1px solid rgba(217, 119, 6, 0.1)",
                color: "rgb(var(--text-primary))",
                outline: "none",
              }}
            />
          </div>
          <div style={{ padding: "4px 12px 8px", maxHeight: 180, overflowY: "auto" }}>
            {filteredEntityNames.length === 0 ? (
              <div style={{ fontSize: 10, color: "rgb(var(--text-muted))", padding: "4px 0" }}>
                {entityNames.length === 0 ? "No entities at this date." : "No matches."}
              </div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {filteredEntityNames.map((name) => (
                  <button
                    key={name}
                    onClick={() => setSelectedEntity(name)}
                    className="cursor-pointer rounded px-2 py-0.5 transition-colors"
                    style={{
                      fontSize: 9,
                      border: selectedEntity === name
                        ? "1px solid rgba(217, 119, 6, 0.4)"
                        : "1px solid rgba(217, 119, 6, 0.1)",
                      background: selectedEntity === name
                        ? "rgba(217, 119, 6, 0.1)"
                        : "transparent",
                      color: selectedEntity === name ? "#d97706" : "rgb(var(--text-secondary))",
                    }}
                  >
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </HudWindow>

        {/* Entity Timeline */}
        <div style={{ flex: 1, overflow: "hidden" }}>
          {selectedEntity && entityEntries ? (
            <EntityTimeline
              entity={selectedEntity}
              entries={entityEntries}
              currentDate={selectedDate}
              onClaimClick={handleClaimClick}
            />
          ) : (
            <div style={{
              padding: 16,
              fontSize: 11,
              color: "rgb(var(--text-muted))",
              textAlign: "center",
              marginTop: 32,
            }}>
              Click a node or select an entity to view its timeline.
            </div>
          )}
        </div>

        {/* Stats Bar */}
        <div
          style={{
            padding: "8px 12px",
            borderTop: "1px solid rgba(217, 119, 6, 0.06)",
            display: "flex",
            gap: 16,
            fontSize: 9,
            color: "rgb(var(--text-muted))",
          }}
        >
          <span>Active: {stats.active_entities}</span>
          <span>Total: {stats.total_entities}</span>
        </div>
      </div>

      {/* ── Right: Graph + Slider ───────────────── */}
      <div className="relative flex flex-1 flex-col" style={{ minWidth: 0 }}>
        {/* Graph canvas */}
        <div className="relative flex-1">
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodeClick={handleNodeClick}
            onNodeDrag={handleNodeDrag}
            fitView
            fitViewOptions={{ padding: 0.2, maxZoom: 1.5 }}
            minZoom={0.05}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
            style={{ background: "#0a0908" }}
          >
            <Background
              gap={40}
              size={0.5}
              color="rgba(217, 119, 6, 0.03)"
            />
          </ReactFlow>

          {/* ZoomControls outside ReactFlow but inside ReactFlowProvider */}
          <div className="pointer-events-auto absolute right-3 top-3 z-10">
            <ZoomControls />
          </div>

          {/* Date display — top center */}
          <div
            className="pointer-events-none absolute left-1/2 top-3 z-10 -translate-x-1/2 rounded px-3 py-1"
            style={{
              background: "rgba(10, 9, 8, 0.82)",
              backdropFilter: "blur(12px)",
              border: "1px solid rgba(217, 119, 6, 0.06)",
              fontSize: 11,
              color: "rgb(var(--text-secondary))",
              fontFamily: "'SF Mono', Monaco, monospace",
            }}
          >
            {selectedDate.toLocaleDateString("en-US", {
              year: "numeric",
              month: "long",
              day: "numeric",
            })}
          </div>
        </div>

        {/* Timeline Slider — bottom */}
        <TimelineSlider
          range={timelineRange}
          value={selectedDate}
          onChange={handleDateChange}
        />
      </div>
    </div>
    </ReactFlowProvider>
  );
}
