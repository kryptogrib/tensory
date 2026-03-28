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
  if (mentions >= 16) return 12;
  if (mentions >= 8) return 11;
  if (mentions >= 3) return 10;
  return 9;
}

function PulseNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as PulseNodeData;
  const { label, mentionCount, claimCount } = nodeData;

  const ringCount = useMemo(() => getPulseRingCount(mentionCount), [mentionCount]);
  const size = useMemo(() => getNodeSize(mentionCount), [mentionCount]);
  const salience = useMemo(() => getSalience(mentionCount), [mentionCount]);
  const labelSize = useMemo(() => getLabelSize(mentionCount), [mentionCount]);

  const coreSize = size * 0.35;
  const boundarySize = size * 0.7;
  // Fixed square container — edges will target the center of this
  const boxSize = size * 2;

  return (
    <div
      className="group relative"
      style={{
        width: boxSize,
        height: boxSize,
        transition: "transform 0.2s ease",
      }}
    >
      {/* Center handle — both source and target at exact 50%/50% of this box */}
      <Handle
        type="target"
        position={Position.Top}
        id="center-target"
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          transform: "translate(-50%, -50%)",
          width: 1,
          height: 1,
          minWidth: 0,
          minHeight: 0,
          opacity: 0,
          border: "none",
          background: "transparent",
          pointerEvents: "none",
          padding: 0,
        }}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="center-source"
        style={{
          position: "absolute",
          left: "50%",
          top: "50%",
          transform: "translate(-50%, -50%)",
          width: 1,
          height: 1,
          minWidth: 0,
          minHeight: 0,
          opacity: 0,
          border: "none",
          background: "transparent",
          pointerEvents: "none",
          padding: 0,
        }}
      />

      {/* Visual container — centered in the box */}
      <div
        className="absolute transition-transform duration-200 ease-out group-hover:scale-[1.15]"
        style={{
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: boxSize,
          height: boxSize,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        {/* Glow halo — every node gets one, brighter for high-mention */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            width: boundarySize * 3,
            height: boundarySize * 3,
            borderRadius: "50%",
            background: `radial-gradient(circle, rgba(217,119,6,${0.06 + salience * 0.1}) 0%, rgba(217,119,6,${0.02 + salience * 0.03}) 40%, transparent 70%)`,
            pointerEvents: "none",
          }}
        />

        {/* Pulse rings */}
        <div style={{ position: "relative", width: boxSize * 0.7, height: boxSize * 0.7 }}>
          {Array.from({ length: ringCount }).map((_, i) => (
            <div
              key={i}
              style={{
                position: "absolute",
                top: "50%",
                left: "50%",
                transform: "translate(-50%, -50%)",
                width: boundarySize + 8,
                height: boundarySize + 8,
                borderRadius: "50%",
                border: `1px solid rgba(217, 119, 6, ${0.25 + salience * 0.2})`,
                animation: `pulse-ring ${2.5 + i * 0.5}s ease-out infinite`,
                animationDelay: `${i * 0.8}s`,
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
              transform: "translate(-50%, -50%)",
              width: boundarySize,
              height: boundarySize,
              borderRadius: "50%",
              border: `1px solid rgba(217, 119, 6, ${selected ? 0.5 : 0.2})`,
              animation: "breathe 4s ease-in-out infinite",
              background: selected
                ? "rgba(217, 119, 6, 0.1)"
                : `rgba(217, 119, 6, ${0.03 + salience * 0.04})`,
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
              background: `rgba(217, 119, 6, ${Math.min(salience + 0.2, 1)})`,
              boxShadow: `0 0 ${10 + salience * 16}px rgba(217, 119, 6, ${salience * 0.7}), 0 0 ${25 + salience * 30}px rgba(217, 119, 6, ${salience * 0.25}), 0 0 ${40 + salience * 40}px rgba(217, 119, 6, ${salience * 0.08})`,
              animation: "glow-pulse 3s ease-in-out infinite",
            }}
          />
        </div>

        {/* Label */}
        <span
          className="text-center leading-tight"
          style={{
            fontFamily: "'SF Mono', Monaco, 'Cascadia Code', 'Fira Code', monospace",
            fontSize: labelSize,
            fontWeight: mentionCount >= 8 ? 600 : 400,
            color: selected ? "#f5e6d3" : mentionCount >= 5 ? "#e8c89a" : "#a89880",
            maxWidth: boxSize + 30,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
            marginTop: 2,
          }}
        >
          {label}
        </span>

        {/* Claim count */}
        {claimCount != null && claimCount > 0 && (
          <span
            style={{
              fontFamily: "'SF Mono', Monaco, monospace",
              fontSize: 8,
              color: "#4a4540",
              marginTop: 1,
            }}
          >
            {claimCount} claims
          </span>
        )}
      </div>
    </div>
  );
}

export const PulseNode = memo(PulseNodeComponent);
