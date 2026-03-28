"use client";

import { HudWindow } from "./HudWindow";

interface GraphControlsProps {
  mode: "entity" | "full";
  onModeChange: (mode: "entity" | "full") => void;
}

function ControlButton({
  active,
  label,
  onClick,
}: {
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="cursor-pointer px-3 py-1.5 text-left text-[0.6rem] uppercase tracking-wider transition-colors"
      style={{
        borderLeft: active
          ? "2px solid #d97706"
          : "2px solid rgba(120, 113, 108, 0.08)",
        background: active ? "rgba(217, 119, 6, 0.05)" : "transparent",
        color: active ? "#f5e6d3" : "#8a7e72",
        fontFamily: "'SF Mono', Monaco, monospace",
      }}
    >
      {label}
    </button>
  );
}

export function GraphControls({ mode, onModeChange }: GraphControlsProps) {
  return (
    <HudWindow title="View">
      <div className="flex flex-col gap-0.5 px-1 pb-2">
        <ControlButton
          active={mode === "entity"}
          label="Entity"
          onClick={() => onModeChange("entity")}
        />
        <ControlButton
          active={mode === "full"}
          label="Full Graph"
          onClick={() => onModeChange("full")}
        />
        <div
          className="my-1 mx-3"
          style={{
            height: 1,
            background: "rgba(217, 119, 6, 0.06)",
          }}
        />
        <ControlButton active={false} label="Depth: 2" onClick={() => {}} />
        <ControlButton active={false} label="Show Weak" onClick={() => {}} />
      </div>
    </HudWindow>
  );
}
