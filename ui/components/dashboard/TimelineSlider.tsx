"use client";

import { memo, useCallback, useMemo, useRef, useEffect, useState } from "react";
import type { TimelineRange } from "@/lib/types";

interface TimelineSliderProps {
  range: TimelineRange;
  value: Date;
  onChange: (date: Date) => void;
}

function TimelineSliderComponent({ range, value, onChange }: TimelineSliderProps) {
  const minMs = new Date(range.min_date).getTime();
  const maxMs = new Date(range.max_date).getTime();
  const spanMs = maxMs - minMs || 1;
  const currentMs = value.getTime();
  const progress = Math.max(0, Math.min(100, ((currentMs - minMs) / spanMs) * 100));
  const trackRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);

  const isSameDay = spanMs < 86400000;

  // Convert mouse X to date
  const xToDate = useCallback(
    (clientX: number) => {
      const track = trackRef.current;
      if (!track) return;
      const rect = track.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
      onChange(new Date(minMs + pct * spanMs));
    },
    [minMs, spanMs, onChange],
  );

  // Document-level mouse tracking while dragging (cursor can leave track)
  useEffect(() => {
    if (!isDragging) return;
    const handleMouseMove = (e: MouseEvent) => {
      e.preventDefault();
      xToDate(e.clientX);
    };
    const handleMouseUp = () => setIsDragging(false);
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, xToDate]);

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setIsDragging(true);
      xToDate(e.clientX);
    },
    [xToDate],
  );

  const formatLabel = (iso: string) => {
    const d = new Date(iso);
    if (isSameDay) {
      return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  const formatCurrent = (ms: number) => {
    const d = new Date(ms);
    if (isSameDay) {
      return d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    }
    return d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  };

  // Histogram
  const maxCount = useMemo(
    () => Math.max(1, ...range.event_histogram.map((b) => b.count)),
    [range.event_histogram],
  );
  const showHistogram = range.event_histogram.length > 1;

  // Active entity count (from progress) for display
  const entityPct = Math.round(progress);

  return (
    <div
      style={{
        background: "rgba(10, 9, 8, 0.92)",
        backdropFilter: "blur(12px)",
        borderTop: "1px solid rgba(217, 119, 6, 0.06)",
        padding: "6px 16px 10px",
      }}
    >
      {/* Histogram */}
      {showHistogram && (
        <div
          style={{
            display: "flex",
            alignItems: "flex-end",
            gap: 1,
            height: 24,
            marginBottom: 6,
          }}
        >
          {range.event_histogram.map((bucket) => {
            const height = Math.max(4, (bucket.count / maxCount) * 100);
            const bucketMs = new Date(bucket.date).getTime();
            const pct = ((bucketMs - minMs) / spanMs) * 100;
            const isNearPlayhead = Math.abs(pct - progress) < 5;
            return (
              <div
                key={bucket.date}
                style={{
                  flex: 1,
                  height: `${height}%`,
                  background: isNearPlayhead
                    ? "#d97706"
                    : "rgba(217, 119, 6, 0.25)",
                  borderRadius: "1px 1px 0 0",
                  transition: "background 150ms",
                }}
              />
            );
          })}
        </div>
      )}

      {/* Current time display */}
      <div
        style={{
          textAlign: "center",
          fontSize: 10,
          color: "#8a7e72",
          marginBottom: 6,
          letterSpacing: "0.02em",
        }}
      >
        {formatCurrent(currentMs)}
        <span style={{ marginLeft: 8, color: "#4a4540", fontSize: 9 }}>
          {entityPct}%
        </span>
      </div>

      {/* Custom track + playhead — tall hit area */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontSize: 9, color: "#4a4540", whiteSpace: "nowrap" }}>
          {formatLabel(range.min_date)}
        </span>

        {/* Track wrapper — large click/drag area */}
        <div
          ref={trackRef}
          onMouseDown={handleMouseDown}
          style={{
            flex: 1,
            height: 28,
            display: "flex",
            alignItems: "center",
            cursor: "pointer",
            userSelect: "none",
            touchAction: "none",
          }}
        >
          {/* Visual track (thin line inside tall hit area) */}
          <div
            style={{
              width: "100%",
              height: 6,
              background: "#1a1918",
              borderRadius: 3,
              position: "relative",
              border: "1px solid rgba(217, 119, 6, 0.08)",
            }}
          >
            {/* Progress fill */}
            <div
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                height: "100%",
                width: `${progress}%`,
                background:
                  "linear-gradient(90deg, rgba(217, 119, 6, 0.15), rgba(217, 119, 6, 0.4))",
                borderRadius: 3,
              }}
            />
            {/* Playhead */}
            <div
              style={{
                position: "absolute",
                top: "50%",
                left: `${progress}%`,
                transform: "translate(-50%, -50%)",
                width: 16,
                height: 16,
                borderRadius: "50%",
                background: "#d97706",
                boxShadow: isDragging
                  ? "0 0 12px rgba(217, 119, 6, 0.8)"
                  : "0 0 8px rgba(217, 119, 6, 0.5)",
                border: "2px solid #0a0908",
                transition: isDragging ? "none" : "left 50ms",
              }}
            />
          </div>
        </div>

        <span style={{ fontSize: 9, color: "#4a4540", whiteSpace: "nowrap" }}>
          {formatLabel(range.max_date)}
        </span>
      </div>
    </div>
  );
}

export const TimelineSlider = memo(TimelineSliderComponent);
