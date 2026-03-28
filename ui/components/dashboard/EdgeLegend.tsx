"use client";

import { HudWindow } from "./HudWindow";

function LegendRow({
  label,
  color,
  dashStyle,
  width,
}: {
  label: string;
  color: string;
  dashStyle?: string;
  width: number;
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="flex w-10 items-center justify-center">
        <svg width={40} height={6}>
          <line
            x1={0}
            y1={3}
            x2={40}
            y2={3}
            stroke={color}
            strokeWidth={width}
            strokeDasharray={dashStyle}
            opacity={0.6}
          />
        </svg>
      </div>
      <span
        className="text-[0.55rem] uppercase tracking-wider"
        style={{
          color: "#6b6560",
          fontFamily: "'SF Mono', Monaco, monospace",
        }}
      >
        {label}
      </span>
    </div>
  );
}

export function EdgeLegend() {
  return (
    <HudWindow title="Edges">
      <div className="flex flex-col gap-1.5 px-3 pb-2">
        <LegendRow label="strong" color="#d97706" width={1.5} />
        <LegendRow label="moderate" color="#d97706" dashStyle="6 3" width={0.8} />
        <LegendRow label="decaying" color="#78716c" dashStyle="3 5" width={0.4} />
      </div>
    </HudWindow>
  );
}
