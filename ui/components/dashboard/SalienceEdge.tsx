"use client";

import { memo, useState, useMemo } from "react";
import { getBezierPath, type EdgeProps } from "@xyflow/react";

export type SalienceEdgeData = {
  relType: string;
  confidence: number;
  fact?: string;
};

function getEdgeStyle(confidence: number) {
  if (confidence > 0.7) {
    return { strokeDasharray: undefined, strokeWidth: 1.5, opacity: 0.25, color: "#d97706" };
  }
  if (confidence >= 0.4) {
    return { strokeDasharray: "6 3", strokeWidth: 0.8, opacity: 0.12, color: "#d97706" };
  }
  if (confidence >= 0.2) {
    return { strokeDasharray: "3 5", strokeWidth: 0.4, opacity: 0.05, color: "#78716c" };
  }
  return { strokeDasharray: "2 7", strokeWidth: 0.25, opacity: 0.03, color: "#78716c" };
}

function SalienceEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as unknown as SalienceEdgeData | undefined;
  const confidence = edgeData?.confidence ?? 0.5;
  const relType = edgeData?.relType ?? "";

  const style = useMemo(() => getEdgeStyle(confidence), [confidence]);

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const showTravelDot = confidence > 0.6;

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Invisible wider path for hover target */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={12}
        style={{ cursor: "pointer" }}
      />

      {/* Visible edge */}
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={selected ? "#d97706" : style.color}
        strokeWidth={selected ? style.strokeWidth * 1.5 : style.strokeWidth}
        strokeDasharray={style.strokeDasharray}
        opacity={selected ? Math.min(style.opacity * 3, 0.6) : hovered ? Math.min(style.opacity * 2, 0.5) : style.opacity}
        style={{ transition: "opacity 0.2s ease, stroke-width 0.2s ease" }}
      />

      {/* Traveling impulse dot */}
      {showTravelDot && (
        <circle
          r={1.5}
          fill="#d97706"
          opacity={0.6}
          style={{
            offsetPath: `path('${edgePath}')`,
            animation: "travel-dot 3s linear infinite",
          }}
        />
      )}

      {/* Hover label */}
      {hovered && relType && (
        <g>
          <rect
            x={labelX - 40}
            y={labelY - 10}
            width={80}
            height={20}
            rx={3}
            fill="rgba(10, 9, 8, 0.9)"
            stroke="rgba(217, 119, 6, 0.15)"
            strokeWidth={0.5}
          />
          <text
            x={labelX}
            y={labelY + 3}
            textAnchor="middle"
            style={{
              fontSize: 8,
              fontFamily: "'SF Mono', Monaco, monospace",
              fill: "#8a7e72",
            }}
          >
            {relType}
          </text>
        </g>
      )}
    </g>
  );
}

export const SalienceEdge = memo(SalienceEdgeComponent);
