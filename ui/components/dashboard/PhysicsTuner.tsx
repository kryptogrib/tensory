"use client";

import { useState, useCallback } from "react";
import { Settings2, ChevronDown, ChevronUp } from "lucide-react";

/** Physics parameters exposed to the user for tuning the "feel" of drag interactions. */
export interface PhysicsParams {
  /** Velocity decay — higher = more resistance (honey-like). Range 0.1–0.95. */
  velocityDecay: number;
  /** How many sync ticks per drag event. Range 1–8. */
  ticksPerDrag: number;
  /** Number of RAF settle ticks on release. Range 0–30. */
  settleTicks: number;
  /** Alpha (energy) injected on drag. Range 0.01–0.5. */
  dragAlpha: number;
  /** Alpha injected for settle phase. Range 0.01–0.3. */
  settleAlpha: number;
  /** 1-hop neighbor follow strength. Range 0–1. */
  neighborStrength: number;
  /** 2-hop neighbor follow strength. Range 0–0.5. */
  neighbor2Strength: number;
}

export const DEFAULT_PHYSICS: PhysicsParams = {
  velocityDecay: 0.6,
  ticksPerDrag: 3,
  settleTicks: 8,
  dragAlpha: 0.1,
  settleAlpha: 0.05,
  neighborStrength: 0.8,
  neighbor2Strength: 0.25,
};

interface SliderRowProps {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
}

function SliderRow({ label, value, min, max, step, onChange }: SliderRowProps) {
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <span
        className="w-[62px] shrink-0 text-[0.5rem] uppercase tracking-wider"
        style={{ color: "#8a7e72" }}
      >
        {label}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="physics-slider h-[3px] min-w-0 flex-1 cursor-pointer appearance-none rounded-full outline-none"
        style={{
          background: `linear-gradient(to right, #d97706 ${pct}%, rgba(74,69,64,0.3) ${pct}%)`,
        }}
      />
      <span
        className="w-[28px] shrink-0 text-right font-mono text-[0.5rem] tabular-nums"
        style={{ color: "#d97706" }}
      >
        {value.toFixed(step < 1 ? 2 : 0)}
      </span>
    </div>
  );
}

interface PhysicsTunerProps {
  params: PhysicsParams;
  onChange: (params: PhysicsParams) => void;
}

export function PhysicsTuner({ params, onChange }: PhysicsTunerProps) {
  const [collapsed, setCollapsed] = useState(true);

  const update = useCallback(
    (key: keyof PhysicsParams, value: number) => {
      onChange({ ...params, [key]: value });
    },
    [params, onChange],
  );

  const reset = useCallback(() => {
    onChange({ ...DEFAULT_PHYSICS });
  }, [onChange]);

  return (
    <div
      className="overflow-hidden rounded-lg"
      style={{
        background: "rgba(10, 9, 8, 0.88)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        border: "1px solid rgba(217, 119, 6, 0.08)",
      }}
    >
      {/* Header */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full cursor-pointer items-center justify-between px-3 py-2"
      >
        <div className="flex items-center gap-2">
          <Settings2 size={10} style={{ color: "#d97706" }} />
          <span
            className="text-[0.6rem] font-bold uppercase tracking-wider"
            style={{ color: "#8a7e72" }}
          >
            Physics Tuner
          </span>
        </div>
        <div className="flex items-center gap-2">
          {!collapsed && (
            <span
              onClick={(e) => {
                e.stopPropagation();
                reset();
              }}
              className="cursor-pointer text-[0.5rem] uppercase tracking-wider transition-colors hover:brightness-125"
              style={{ color: "#d97706" }}
            >
              Reset
            </span>
          )}
          {collapsed ? (
            <ChevronDown size={10} style={{ color: "#6b6560" }} />
          ) : (
            <ChevronUp size={10} style={{ color: "#6b6560" }} />
          )}
        </div>
      </button>

      {/* Sliders */}
      {!collapsed && (
        <div className="px-3 pb-2.5">
          <SliderRow
            label="Viscosity"
            value={params.velocityDecay}
            min={0.1}
            max={0.95}
            step={0.05}
            onChange={(v) => update("velocityDecay", v)}
          />
          <SliderRow
            label="Drag ticks"
            value={params.ticksPerDrag}
            min={1}
            max={8}
            step={1}
            onChange={(v) => update("ticksPerDrag", v)}
          />
          <SliderRow
            label="Settle ticks"
            value={params.settleTicks}
            min={0}
            max={30}
            step={1}
            onChange={(v) => update("settleTicks", v)}
          />
          <SliderRow
            label="Drag α"
            value={params.dragAlpha}
            min={0.01}
            max={0.5}
            step={0.01}
            onChange={(v) => update("dragAlpha", v)}
          />
          <SliderRow
            label="Settle α"
            value={params.settleAlpha}
            min={0.01}
            max={0.3}
            step={0.01}
            onChange={(v) => update("settleAlpha", v)}
          />
          <SliderRow
            label="1-hop pull"
            value={params.neighborStrength}
            min={0}
            max={1}
            step={0.05}
            onChange={(v) => update("neighborStrength", v)}
          />
          <SliderRow
            label="2-hop pull"
            value={params.neighbor2Strength}
            min={0}
            max={0.5}
            step={0.05}
            onChange={(v) => update("neighbor2Strength", v)}
          />
        </div>
      )}
    </div>
  );
}
