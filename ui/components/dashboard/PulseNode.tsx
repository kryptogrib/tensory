"use client";

import { memo, useMemo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export type PulseNodeData = {
  label: string;
  mentionCount: number;
  claimCount?: number;
  entityType?: string | null;
};

function getPulseRingCount(mentions: number): number {
  if (mentions >= 16) return 3;
  if (mentions >= 8) return 2;
  if (mentions >= 3) return 1;
  return 0;
}

function getNodeSize(mentions: number): number {
  const clamped = Math.min(Math.max(mentions, 1), 50);
  return 40 + (clamped / 50) * 40; // 40px to 80px
}

function getSalience(mentions: number): number {
  return Math.min(0.4 + (mentions / 20) * 0.6, 1);
}

function getLabelSize(mentions: number): number {
  if (mentions >= 16) return 11;
  if (mentions >= 8) return 10;
  if (mentions >= 3) return 9;
  return 8;
}

function PulseNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as PulseNodeData;
  const { label, mentionCount, claimCount } = nodeData;

  const ringCount = useMemo(() => getPulseRingCount(mentionCount), [mentionCount]);
  const size = useMemo(() => getNodeSize(mentionCount), [mentionCount]);
  const salience = useMemo(() => getSalience(mentionCount), [mentionCount]);
  const labelSize = useMemo(() => getLabelSize(mentionCount), [mentionCount]);

  const coreSize = size * 0.4;
  const boundarySize = size * 0.75;
  const totalSize = size * 2.2; // room for pulse rings

  return (
    <div
      className="group relative flex flex-col items-center"
      style={{
        width: totalSize,
        transition: "transform 0.2s ease",
      }}
    >
      {/* Hidden handles at CENTER of node — edges connect to center */}
      <Handle
        type="target"
        position={Position.Top}
        style={{
          opacity: 0,
          width: 1,
          height: 1,
          border: "none",
          background: "transparent",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
        }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        style={{
          opacity: 0,
          width: 1,
          height: 1,
          border: "none",
          background: "transparent",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
        }}
      />

      {/* Node visual container */}
      <div
        className="relative transition-transform duration-200 ease-out group-hover:scale-[1.15]"
        style={{ width: totalSize, height: totalSize }}
      >
        {/* Pulse rings */}
        {Array.from({ length: ringCount }).map((_, i) => (
          <div
            key={i}
            style={{
              position: "absolute",
              top: "50%",
              left: "50%",
              width: boundarySize + 8,
              height: boundarySize + 8,
              borderRadius: "50%",
              border: "1px solid rgba(217, 119, 6, 0.3)",
              animation: `pulse-ring ${2.5 + i * 0.4}s ease-out infinite`,
              animationDelay: `${i * 0.7}s`,
              pointerEvents: "none",
            }}
          />
        ))}

        {/* Boundary circle — breathing */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            width: boundarySize,
            height: boundarySize,
            borderRadius: "50%",
            border: `1px solid rgba(217, 119, 6, ${selected ? 0.4 : 0.12})`,
            animation: "breathe 4s ease-in-out infinite",
            background: selected
              ? "rgba(217, 119, 6, 0.06)"
              : "rgba(217, 119, 6, 0.02)",
          }}
        />

        {/* Core dot */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            width: coreSize,
            height: coreSize,
            borderRadius: "50%",
            background: `rgba(217, 119, 6, ${salience})`,
            boxShadow: `0 0 ${8 + salience * 12}px rgba(217, 119, 6, ${salience * 0.5})`,
            animation: "glow-pulse 3s ease-in-out infinite",
          }}
        />
      </div>

      {/* Label */}
      <span
        className="mt-1 text-center leading-tight"
        style={{
          fontFamily: "'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace",
          fontSize: labelSize,
          color: selected ? "#f5e6d3" : "#8a7e72",
          maxWidth: totalSize + 20,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
      >
        {label}
      </span>

      {/* Claim count */}
      {claimCount != null && claimCount > 0 && (
        <span
          style={{
            fontFamily: "'SF Mono', Monaco, monospace",
            fontSize: 7,
            color: "#4a4540",
            marginTop: 1,
          }}
        >
          {claimCount} claims
        </span>
      )}
    </div>
  );
}

export const PulseNode = memo(PulseNodeComponent);
