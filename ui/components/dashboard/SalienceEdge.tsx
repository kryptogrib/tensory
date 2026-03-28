"use client";

/* ─── Salience Edge ──────────────────────────────────────────────────
 *
 * Game-quality edge rendering:
 *   1. Computes true node centers via useInternalNode (bypasses Handle system)
 *   2. SVG linearGradient dissolves edge into both nodes
 *   3. Confidence → visual style (solid/dashed, thickness, opacity)
 *   4. Hover tooltip shows rel_type
 *   5. Traveling impulse dot on strong edges
 *
 * Inspired by: Eve Online star map, Obsidian graph, Neo4j Bloom
 * ──────────────────────────────────────────────────────────────────── */

import { memo, useState, useMemo } from "react";
import { type EdgeProps, useInternalNode } from "@xyflow/react";

export type SalienceEdgeData = {
  relType: string;
  confidence: number;
  fact?: string;
};

function getEdgeStyle(confidence: number) {
  if (confidence > 0.7) {
    return { dash: undefined, width: 2, opacity: 0.6, color: "#d97706" };
  }
  if (confidence >= 0.4) {
    return { dash: "6 4", width: 1.2, opacity: 0.35, color: "#d97706" };
  }
  if (confidence >= 0.2) {
    return { dash: "3 5", width: 0.8, opacity: 0.2, color: "#b45309" };
  }
  return { dash: "2 7", width: 0.5, opacity: 0.1, color: "#78716c" };
}

function SalienceEdgeComponent({
  id,
  source,
  target,
  data,
  selected,
  style: externalStyle,
}: EdgeProps) {
  const [hovered, setHovered] = useState(false);
  const edgeData = data as unknown as SalienceEdgeData | undefined;
  const confidence = edgeData?.confidence ?? 0.5;
  const relType = edgeData?.relType ?? "";

  // Compute TRUE node centers — bypasses Handle system entirely
  const sourceNode = useInternalNode(source);
  const targetNode = useInternalNode(target);

  const edgeStyle = useMemo(() => getEdgeStyle(confidence), [confidence]);

  if (!sourceNode || !targetNode) return null;

  // Get absolute center of each node
  const sx = sourceNode.internals.positionAbsolute.x + (sourceNode.measured.width ?? 0) / 2;
  const sy = sourceNode.internals.positionAbsolute.y + (sourceNode.measured.height ?? 0) / 2;
  const tx = targetNode.internals.positionAbsolute.x + (targetNode.measured.width ?? 0) / 2;
  const ty = targetNode.internals.positionAbsolute.y + (targetNode.measured.height ?? 0) / 2;

  const edgePath = `M ${sx} ${sy} L ${tx} ${ty}`;
  const labelX = (sx + tx) / 2;
  const labelY = (sy + ty) / 2;

  const gradientId = `edge-dissolve-${id}`;

  // External opacity from selection highlighting
  const externalOpacity =
    externalStyle && typeof externalStyle === "object" && "opacity" in externalStyle
      ? (externalStyle as { opacity: number }).opacity
      : undefined;

  const finalOpacity = externalOpacity ?? (
    selected
      ? Math.min(edgeStyle.opacity * 2.5, 0.7)
      : hovered
        ? Math.min(edgeStyle.opacity * 2, 0.5)
        : edgeStyle.opacity
  );

  const strokeColor = selected || hovered ? "#d97706" : edgeStyle.color;

  return (
    <g
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Gradient: strong dissolve at both ends */}
      <defs>
        <linearGradient
          id={gradientId}
          gradientUnits="userSpaceOnUse"
          x1={sx} y1={sy}
          x2={tx} y2={ty}
        >
          <stop offset="0%" stopColor={strokeColor} stopOpacity={0} />
          <stop offset="20%" stopColor={strokeColor} stopOpacity={0.7} />
          <stop offset="50%" stopColor={strokeColor} stopOpacity={0.5} />
          <stop offset="80%" stopColor={strokeColor} stopOpacity={0.7} />
          <stop offset="100%" stopColor={strokeColor} stopOpacity={0} />
        </linearGradient>
      </defs>

      {/* Invisible wide path for hover */}
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={18}
        style={{ cursor: "pointer" }}
      />

      {/* Visible edge with dissolve gradient */}
      <path
        id={id}
        d={edgePath}
        fill="none"
        stroke={`url(#${gradientId})`}
        strokeWidth={hovered ? edgeStyle.width * 1.5 : edgeStyle.width}
        strokeDasharray={edgeStyle.dash}
        opacity={finalOpacity}
        strokeLinecap="round"
        style={{ transition: "opacity 0.3s ease, stroke-width 0.2s ease" }}
      />

      {/* Subtle glow on hover */}
      {hovered && (
        <path
          d={edgePath}
          fill="none"
          stroke="#d97706"
          strokeWidth={edgeStyle.width * 3}
          opacity={0.08}
          strokeLinecap="round"
          style={{ filter: "blur(4px)" }}
        />
      )}

      {/* Traveling impulse dot for strong edges */}
      {confidence > 0.6 && (
        <circle
          r={1.5}
          fill="#fbbf24"
          opacity={0.4}
          style={{
            offsetPath: `path('${edgePath}')`,
            animation: `travel-dot ${3 + Math.random() * 2}s linear infinite`,
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
