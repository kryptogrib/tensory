"use client";

import { memo, useMemo } from "react";
import { format } from "date-fns";
import type { TimelineEntry } from "@/lib/types";

interface EntityTimelineProps {
  entity: string;
  entries: TimelineEntry[];
  currentDate: Date;
  onClaimClick?: (claimDate: Date) => void;
}

function EntityTimelineComponent({ entity, entries, currentDate, onClaimClick }: EntityTimelineProps) {
  const supersedeMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const entry of entries) {
      if (entry.supersedes) {
        map.set(entry.claim.id, entry.supersedes);
      }
    }
    return map;
  }, [entries]);

  if (entries.length === 0) {
    return (
      <div style={{ padding: 16, color: "rgb(var(--text-secondary))", fontSize: 12 }}>
        No claims found for {entity}.
      </div>
    );
  }

  return (
    <div style={{ padding: "12px 16px", overflowY: "auto", height: "100%" }}>
      <div style={{
        fontSize: 10, color: "rgb(var(--accent-primary))", marginBottom: 12,
        textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {entity} History
      </div>
      <div style={{ position: "relative", paddingLeft: 16 }}>
        <div style={{
          position: "absolute", left: 4, top: 0, bottom: 0, width: 2,
          background: "rgba(var(--accent-primary), 0.2)",
        }} />
        {entries.map((entry) => {
          const isSuperseded = entry.claim.superseded_at != null;
          const hasSupersededAnother = supersedeMap.has(entry.claim.id);
          const claimDate = new Date(entry.claim.created_at);
          const isAtPlayhead = Math.abs(claimDate.getTime() - currentDate.getTime()) < 86400000;

          return (
            <div
              key={entry.claim.id}
              style={{ position: "relative", marginBottom: 16, cursor: onClaimClick ? "pointer" : "default" }}
              onClick={() => onClaimClick?.(claimDate)}
            >
              <div style={{
                position: "absolute", left: -14, top: 2, width: 8, height: 8, borderRadius: "50%",
                background: isSuperseded
                  ? "rgb(var(--decaying))"
                  : isAtPlayhead ? "rgb(var(--accent-primary))" : "rgb(var(--accent-secondary))",
                boxShadow: isAtPlayhead ? "0 0 6px rgb(var(--accent-primary))" : "none",
              }} />
              {hasSupersededAnother && (
                <div style={{ position: "absolute", left: -20, top: -10, fontSize: 8, color: "rgb(var(--accent-primary))", opacity: 0.5 }}>
                  ╭←
                </div>
              )}
              {isSuperseded && (
                <div style={{ position: "absolute", left: -20, bottom: -6, fontSize: 8, color: "rgb(var(--decaying))", opacity: 0.5 }}>
                  ╰→
                </div>
              )}
              <div style={{ fontSize: 8, color: "rgb(var(--text-muted))", marginBottom: 2 }}>
                {format(claimDate, "MMM d, yyyy")}
              </div>
              <div style={{
                fontSize: 11, lineHeight: 1.4,
                color: isSuperseded ? "rgb(var(--decaying))" : "rgb(var(--text-primary))",
                textDecoration: isSuperseded ? "line-through" : "none",
              }}>
                {entry.claim.text}
              </div>
              <div style={{ fontSize: 8, color: "rgb(var(--text-tertiary))", marginTop: 2 }}>
                {entry.claim.type} · {(entry.claim.confidence * 100).toFixed(0)}%
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export const EntityTimeline = memo(EntityTimelineComponent);
