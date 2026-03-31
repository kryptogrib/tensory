"use client";

import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

interface GhostNodeData {
  name: string;
  type: string | null;
  first_seen: string;
  [key: string]: unknown;
}

function GhostNodeComponent({ data }: NodeProps) {
  const d = data as GhostNodeData;
  const size = 32;

  return (
    <div style={{ width: size, height: size, position: "relative", display: "flex", alignItems: "center", justifyContent: "center" }}>
      <Handle type="target" position={Position.Top} style={{ opacity: 0, top: "50%", left: "50%" }} />
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0, top: "50%", left: "50%" }} />
      <div style={{
        width: size, height: size, borderRadius: "50%",
        border: "1.5px dashed rgb(var(--text-muted))",
        opacity: 0.2, position: "absolute", top: 0, left: 0,
      }} />
      <div style={{
        position: "absolute", top: size + 4, left: "50%", transform: "translateX(-50%)",
        whiteSpace: "nowrap", fontSize: 8, color: "rgb(var(--text-muted))", opacity: 0.3, pointerEvents: "none",
      }}>
        {d.name}
      </div>
    </div>
  );
}

export const GhostNode = memo(GhostNodeComponent);
