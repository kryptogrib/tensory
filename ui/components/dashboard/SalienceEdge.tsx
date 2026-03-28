"use client";

import { memo, useState, useMemo } from "react";
import { type EdgeProps } from "@xyflow/react";

export type SalienceEdgeData = {
  relType: string;
  confidence: number;
  fact?: string;
};

function getEdgeStyle(confidence: number) {
  if (confidence > 0.7) {
    return { strokeDasharray: undefined, strokeWidth: 1.8, opacity: 0.35, color: "#d97706" };
  }
  if (confidence >= 0.4) {
    return { strokeDasharray: "8 4", strokeWidth: 1.1, opacity: 0.18, color: "#d97706" };
  }
  if (confidence >= 0.2) {
    return { strokeDasharray: "4 6", strokeWidth: 0.7, opacity: 0.1, color: "#b45309" };
  }
  return { strokeDasharray: "2 8", strokeWidth: 0.4, opacity: 0.05, color: "#78716c" };
}

function SalienceEdgeComponent({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  selected,
  style: externalStyle,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as unknown as SalienceEdgeData | undefined;
  const confidence = edgeData?.confidence ?? 0.5;
  const relType = edgeData?.relType ?? "";

  const edgeStyle = useMemo(() => getEdgeStyle(confidence), [confidence]);

  // Simple straight path
  const edgePath = `M ${sourceX} ${sourceY} L ${targetX} ${targetY}`;
  const labelX = (sourceX + targetX) / 2;
  const labelY = (sourceY + targetY) / 2;

  // Unique gradient ID per edge
  const gradientId = `edge-fade-${id}`;

  // External opacity from selection highlighting
  const externalOpacity =
    externalStyle && typeof externalStyle === "object" && "opacity" in externalStyle
      ? (externalStyle as { opacity: number }).opacity
      : undefined;

  const finalOpacity = externalOpacity ?? (
    selected
      ? Math.min(edgeStyle.opacity * 3, 0.7)
      : hovered
        ? Math.min(edgeStyle.opacity * 2.5, 0.5)
        : edgeStyle.opacity
  );

  const strokeColor = selected || hovered ? "#d97706" : edgeStyle.color;

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Gradient: fades at both ends so edge dissolves into nodes */}
      <defs>
        <linearGradient
          id={gradientId}
          x1={sourceX}
          y1={sourceY}
          x2={targetX}
          y2={targetY}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor={strokeColor} stopOpacity={0} />
          <stop offset="12%" stopColor={strokeColor} stopOpacity={1} />
          <stop offset="88%" stopColor={strokeColor} stopOpacity={1} />
          <stop offset="100%" stopColor={strokeColor} stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* Invisible wider path for easier hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={16}
        style={{ cursor: "pointer" }}
      />

      {/* Visible edge with dissolving gradient */}
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={hovered ? edgeStyle.strokeWidth * 1.5 : edgeStyle.strokeWidth}
        strokeDasharray={edgeStyle.strokeDasharray}
        opacity={finalOpacity}
        strokeLinecap="round"
        style={{ transition: "opacity 0.3s ease, stroke-width 0.2s ease" }}
      />

      {/* Traveling impulse dot for strong edges */}
      {confidence > 0.6 && (
        <circle
          r={1.5}
          fill="#fbbf24"
          opacity={0.5}
          style={{
            offsetPath: `path('${edgePath}')`,
            animation: `travel-dot ${2.5 + Math.random() * 2}s linear infinite`,
          }}
        />
      )}

      {/* Hover tooltip */}
      {hovered && relType && (
        <g>
          <rect
            x={labelX - 45}
            y={labelY - 11}
            width={90}
            height={22}
            rx={4}
            fill="rgba(10, 9, 8, 0.92)"
            stroke="rgba(217, 119, 6, 0.2)"
            strokeWidth={0.5}
          />
          <text
            x={labelX}
            y={labelY + 3}
            textAnchor="middle"
            style={{
              fontSize: 9,
              fontFamily: "'SF Mono', Monaco, monospace",
              fill: "#d97706",
              fontWeight: 500,
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
