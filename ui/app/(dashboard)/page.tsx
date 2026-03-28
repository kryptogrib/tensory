"use client";

import { useState } from "react";
import { StatsBar } from "@/components/dashboard/StatsBar";
import { LiveFeed } from "@/components/dashboard/LiveFeed";
import { EntityBadges } from "@/components/dashboard/EntityBadges";
import { GraphViewer } from "@/components/dashboard/GraphViewer";
import { GraphControls } from "@/components/dashboard/GraphControls";
import { EdgeLegend } from "@/components/dashboard/EdgeLegend";
import {
  PhysicsTuner,
  DEFAULT_PHYSICS,
  type PhysicsParams,
} from "@/components/dashboard/PhysicsTuner";

export default function HomePage() {
  const [mode, setMode] = useState<"entity" | "full">("entity");
  const [physics, setPhysics] = useState<PhysicsParams>(DEFAULT_PHYSICS);

  return (
    <div className="relative h-full w-full" style={{ background: "#0a0908" }}>
      {/* Graph canvas — full screen background */}
      <GraphViewer mode={mode} physics={physics} />

      {/* HUD overlay */}
      {/* Stats bar — top */}
      <div className="pointer-events-auto absolute inset-x-0 top-0 z-10 p-3">
        <StatsBar />
      </div>

      {/* Edge legend — top left, below stats */}
      <div className="pointer-events-auto absolute left-3 top-16 z-10 w-36">
        <EdgeLegend />
      </div>

      {/* Graph controls + Physics tuner — top right column */}
      <div className="pointer-events-auto absolute right-3 top-16 z-10 flex flex-col gap-2 w-56">
        <GraphControls mode={mode} onModeChange={setMode} />
        <PhysicsTuner params={physics} onChange={setPhysics} />
      </div>

      {/* Entity badges — bottom left */}
      <div className="pointer-events-auto absolute bottom-3 left-3 z-10 w-64">
        <EntityBadges />
      </div>

      {/* Live feed — bottom right */}
      <div className="pointer-events-auto absolute bottom-3 right-3 z-10 w-72">
        <LiveFeed />
      </div>
    </div>
  );
}
