"use client";

import { useReactFlow, useStore } from "@xyflow/react";
import { useCallback } from "react";

function ZoomButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="cursor-pointer px-2 py-1 text-[0.6rem] transition-colors hover:brightness-125"
      style={{
        color: "#8a7e72",
        fontFamily: "'SF Mono', Monaco, monospace",
        background: "transparent",
        border: "none",
      }}
    >
      {label}
    </button>
  );
}

export function ZoomControls() {
  const { zoomIn, zoomOut, fitView } = useReactFlow();
  const zoom = useStore((s) => s.transform[2]);

  const handleZoomIn = useCallback(() => {
    zoomIn({ duration: 200 });
  }, [zoomIn]);

  const handleZoomOut = useCallback(() => {
    zoomOut({ duration: 200 });
  }, [zoomOut]);

  const handleFitView = useCallback(() => {
    fitView({ duration: 300, padding: 0.2 });
  }, [fitView]);

  return (
    <div
      className="flex items-center gap-0 rounded-md"
      style={{
        background: "rgba(10, 9, 8, 0.82)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid rgba(217, 119, 6, 0.06)",
      }}
    >
      <ZoomButton label="-" onClick={handleZoomOut} />
      <span
        className="px-2 text-[0.55rem]"
        style={{
          color: "#6b6560",
          fontFamily: "'SF Mono', Monaco, monospace",
          borderLeft: "1px solid rgba(217, 119, 6, 0.06)",
          borderRight: "1px solid rgba(217, 119, 6, 0.06)",
          minWidth: 40,
          textAlign: "center",
        }}
      >
        {Math.round(zoom * 100)}%
      </span>
      <ZoomButton label="+" onClick={handleZoomIn} />
      <div style={{ borderLeft: "1px solid rgba(217, 119, 6, 0.06)" }}>
        <button
          onClick={handleFitView}
          className="cursor-pointer px-2 py-1 transition-colors hover:brightness-125"
          style={{
            color: "#8a7e72",
            background: "transparent",
            border: "none",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
          title="Fit to view"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round">
            <rect x="3" y="3" width="8" height="8" rx="1" />
            <path d="M1 4V2a1 1 0 0 1 1-1h2" />
            <path d="M10 1h2a1 1 0 0 1 1 1v2" />
            <path d="M13 10v2a1 1 0 0 1-1 1h-2" />
            <path d="M4 13H2a1 1 0 0 1-1-1v-2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
