"use client";

import { memo, useCallback, useMemo } from "react";
import type { TimelineRange } from "@/lib/types";

interface TimelineSliderProps {
  range: TimelineRange;
  value: Date;
  onChange: (date: Date) => void;
}

function TimelineSliderComponent({ range, value, onChange }: TimelineSliderProps) {
  const minMs = new Date(range.min_date).getTime();
  const maxMs = new Date(range.max_date).getTime();
  const spanMs = maxMs - minMs;
  const currentMs = value.getTime();

  // Determine display granularity based on time span
  const isSameDay = spanMs < 86400000;

  const maxCount = useMemo(
    () => Math.max(1, ...range.event_histogram.map((b) => b.count)),
    [range.event_histogram]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const ms = Number(e.target.value);
      onChange(new Date(ms));
    },
    [onChange]
  );

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    if (isSameDay) {
      // Show time when all data is within one day
      return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
    }
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  const formatTimestamp = (ms: number) => {
    const d = new Date(ms);
    if (isSameDay) {
      return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  return (
    <div style={{
      background: "rgba(var(--bg-surface), 0.82)",
      backdropFilter: "blur(12px)",
      borderTop: "1px solid rgba(var(--accent-primary), 0.06)",
      padding: "8px 16px 12px",
    }}>
      {/* Histogram — only show when multiple buckets */}
      {range.event_histogram.length > 1 && (
        <div style={{ display: "flex", alignItems: "flex-end", gap: 1, height: 32, marginBottom: 4, padding: "0 2px" }}>
          {range.event_histogram.map((bucket) => {
            const height = (bucket.count / maxCount) * 100;
            const bucketMs = new Date(bucket.date).getTime();
            const isAtPlayhead = Math.abs(bucketMs - currentMs) < 86400000;
            return (
              <div
                key={bucket.date}
                style={{
                  flex: 1, height: `${height}%`, minHeight: 2,
                  background: isAtPlayhead ? "rgb(var(--accent-primary))" : "rgba(var(--accent-primary), 0.3)",
                  borderRadius: "1px 1px 0 0", transition: "background 150ms",
                }}
              />
            );
          })}
        </div>
      )}
      {/* Current timestamp */}
      {isSameDay && (
        <div style={{
          textAlign: "center", fontSize: 9, color: "rgb(var(--text-secondary))",
          marginBottom: 4,
        }}>
          {formatTimestamp(currentMs)}
        </div>
      )}
      {/* Slider */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ fontSize: 9, color: "rgb(var(--text-muted))", whiteSpace: "nowrap" }}>
          {formatDate(range.min_date)}
        </span>
        <input type="range" min={minMs} max={maxMs} value={currentMs} onChange={handleChange} style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: "rgb(var(--text-muted))", whiteSpace: "nowrap" }}>
          {formatDate(range.max_date)}
        </span>
      </div>
    </div>
  );
}

export const TimelineSlider = memo(TimelineSliderComponent);
