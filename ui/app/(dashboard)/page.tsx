"use client";

import { StatsBar } from "@/components/dashboard/StatsBar";
import { LiveFeed } from "@/components/dashboard/LiveFeed";
import { EntityBadges } from "@/components/dashboard/EntityBadges";

export default function HomePage() {
  return (
    <div className="relative h-full w-full" style={{ background: "#0a0908" }}>
      {/* Graph canvas placeholder */}
      <div className="flex h-full items-center justify-center">
        <p className="text-[0.7rem]" style={{ color: "#4a4540" }}>
          graph canvas
        </p>
      </div>

      {/* HUD overlay */}
      {/* Stats bar — top */}
      <div className="pointer-events-auto absolute inset-x-0 top-0 z-10 p-3">
        <StatsBar />
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
