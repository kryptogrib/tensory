"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import {
  ReactFlow,
  Background,
  type Node,
  type Edge,
  type OnNodeDrag,
  type NodeMouseHandler,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTimelineRange, useGraphSnapshot, useEntityTimeline } from "@/hooks/use-timeline";
import { useGraphLayout } from "@/hooks/use-graph-layout";
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
  const [debouncedDateStr, setDebouncedDateStr] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Data fetching ──────────────────────────
  const { data: timelineRange } = useTimelineRange();
  const { data: snapshot } = useGraphSnapshot(debouncedDateStr);
  const { data: entityEntries } = useEntityTimeline(selectedEntity);

  // Initialize slider at max_date when range loads
  useEffect(() => {
    if (timelineRange && selectedDate === null) {
      const maxDate = new Date(timelineRange.max_date);
      setSelectedDate(maxDate);
      setDebouncedDateStr(timelineRange.max_date);
    }
  }, [timelineRange, selectedDate]);

  // Debounced date change → fetch snapshot
  const handleDateChange = useCallback((date: Date) => {
    setSelectedDate(date);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setDebouncedDateStr(date.toISOString());
    }, 150);
  }, []);

  // Cleanup debounce on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  // ── Build entity list for layout ───────────
  const allEntities = useMemo<EntityNode[]>(() => {
    if (!snapshot) return [];
    const active = snapshot.active_nodes ?? [];
    const ghost = (snapshot.ghost_nodes ?? []).map((g) => ({
      ...g,
      id: `ghost-${g.id}`,
    }));
    return [...active, ...ghost];
  }, [snapshot]);

  const edgeData = useMemo(() => snapshot?.edges ?? [], [snapshot]);

  // ── Layout via d3-force ────────────────────
  const { layout } = useGraphLayout(allEntities, edgeData);

  // Build final nodes with correct types (pulse vs ghost)
  const flowNodes = useMemo<Node[]>(() => {
    if (!layout) return [];
    return layout.nodes.map((node) => ({
      ...node,
      type: node.id.startsWith("ghost-") ? "ghost" : "pulse",
      data: node.id.startsWith("ghost-")
        ? {
            name: (node.data as Record<string, unknown>).label as string,
            type: (node.data as Record<string, unknown>).entityType as string | null,
            first_seen: "",
          }
        : node.data,
    }));
  }, [layout]);

  const flowEdges = useMemo<Edge[]>(() => layout?.edges ?? [], [layout]);

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
    setDebouncedDateStr(claimDate.toISOString());
  }, []);

  // ── Drag handlers (pin/unpin via simulation ref) ──
  const handleNodeDrag: OnNodeDrag = useCallback(() => {
    // Basic drag — nodes are repositioned by ReactFlow automatically.
    // For full physics drag, wire up simRef from useGraphLayout.
  }, []);

  // ── Entity picker list ─────────────────────
  const entityNames = useMemo(() => {
    if (!snapshot) return [];
    return (snapshot.active_nodes ?? [])
      .sort((a, b) => b.mention_count - a.mention_count)
      .map((e) => e.name);
  }, [snapshot]);

  // Stats from snapshot
  const stats = snapshot?.stats ?? { claims: 0, superseded: 0 };

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
        <HudWindow title="Entity">
          <div style={{ padding: "4px 12px 8px", maxHeight: 120, overflowY: "auto" }}>
            {entityNames.length === 0 ? (
              <div style={{ fontSize: 10, color: "rgb(var(--text-muted))", padding: "4px 0" }}>
                No entities at this date.
              </div>
            ) : (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {entityNames.map((name) => (
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
          <span>Claims: {stats.claims}</span>
          <span>Superseded: {stats.superseded}</span>
          <span>Entities: {(snapshot?.active_nodes ?? []).length}</span>
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
            minZoom={0.1}
            maxZoom={3}
            proOptions={{ hideAttribution: true }}
            style={{ background: "#0a0908" }}
          >
            <Background
              gap={40}
              size={0.5}
              color="rgba(217, 119, 6, 0.03)"
            />
            {/* ZoomControls must be inside ReactFlow for useReactFlow() context */}
            <div className="pointer-events-auto absolute right-3 top-3 z-10">
              <ZoomControls />
            </div>
          </ReactFlow>

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
  );
}
