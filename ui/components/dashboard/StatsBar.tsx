"use client";

import { useStats } from "@/hooks/use-stats";
import { HudWindow } from "./HudWindow";

function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

function LoadingSkeleton() {
  return (
    <div className="flex items-center gap-4 px-4 py-2.5">
      {[1, 2, 3, 4].map((i) => (
        <div
          key={i}
          className="h-3 w-16 animate-pulse rounded"
          style={{ background: "rgba(217, 119, 6, 0.15)" }}
        />
      ))}
    </div>
  );
}

export function StatsBar() {
  const { data, isLoading, isError } = useStats();

  if (isLoading) {
    return (
      <HudWindow>
        <LoadingSkeleton />
      </HudWindow>
    );
  }

  if (isError || !data) {
    return (
      <HudWindow>
        <div className="px-4 py-2.5 text-[0.7rem]" style={{ color: "#fca5a5" }}>
          $ API unreachable
        </div>
      </HudWindow>
    );
  }

  const totalClaims = data.counts?.claims ?? 0;
  const entities = data.counts?.entities ?? 0;
  const collisions = data.counts?.collisions ?? 0;
  const avgSalience = data.avg_salience ?? 0;

  return (
    <HudWindow>
      <div className="flex items-center justify-between px-4 py-2.5">
        <div className="flex items-center gap-1 overflow-x-auto text-[0.8rem]">
          {/* Prompt symbol */}
          <span style={{ color: "#4a4540" }}>$</span>

          {/* Claims */}
          <span className="ml-2" style={{ color: "#8a7e72" }}>
            claims
          </span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {formatNumber(totalClaims)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Salience */}
          <span style={{ color: "#8a7e72" }}>salience</span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {avgSalience.toFixed(2)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Entities */}
          <span style={{ color: "#8a7e72" }}>entities</span>
          <span className="font-bold" style={{ color: "#f5e6d3" }}>
            {formatNumber(entities)}
          </span>

          <span className="mx-2" style={{ color: "#4a4540" }}>
            |
          </span>

          {/* Collisions */}
          <span style={{ color: "#8a7e72" }}>collisions</span>
          <span className="font-bold" style={{ color: "#fca5a5" }}>
            {formatNumber(collisions)}
          </span>
        </div>

        {/* Search placeholder */}
        <div
          className="ml-4 flex flex-shrink-0 items-center gap-1.5 rounded px-2 py-1 text-[0.65rem]"
          style={{
            border: "1px solid rgba(217, 119, 6, 0.1)",
            color: "#6b6560",
          }}
        >
          <span>search</span>
          <kbd
            className="rounded px-1 py-0.5 text-[0.55rem]"
            style={{ background: "rgba(217, 119, 6, 0.06)" }}
          >
            ⌘K
          </kbd>
        </div>
      </div>
    </HudWindow>
  );
}
