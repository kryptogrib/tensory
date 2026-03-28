"use client";

import { useStats } from "@/hooks/use-stats";
import { HudWindow } from "./HudWindow";
import { formatDistanceToNow } from "date-fns";
import type { Claim, ClaimType } from "@/lib/types";

const TYPE_COLORS: Record<ClaimType, string> = {
  fact: "#d97706",
  opinion: "#b45309",
  observation: "#ea580c",
  experience: "#a3e635",
};

function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "...";
}

function ClaimRow({ claim }: { claim: Claim }) {
  const borderColor = TYPE_COLORS[claim.type] ?? "#d97706";
  const opacity = claim.salience < 0.3 ? 0.5 : claim.salience < 0.6 ? 0.75 : 1;
  const createdAt = claim.created_at ? formatDistanceToNow(new Date(claim.created_at), { addSuffix: true }) : "";

  return (
    <div
      className="px-3 py-2 transition-opacity"
      style={{
        borderLeft: `2px solid ${borderColor}`,
        opacity,
      }}
    >
      <div className="text-[0.7rem] leading-snug" style={{ color: "#f5e6d3" }}>
        {truncate(claim.text, 50)}
      </div>
      <div className="mt-0.5 text-[0.6rem]" style={{ color: "#6b6560" }}>
        {claim.type} &middot; {claim.salience.toFixed(2)} &middot; {createdAt}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-2 px-3 pb-3">
      {[1, 2, 3].map((i) => (
        <div key={i} className="flex flex-col gap-1">
          <div
            className="h-3 w-full animate-pulse rounded"
            style={{ background: "rgba(217, 119, 6, 0.1)" }}
          />
          <div
            className="h-2 w-2/3 animate-pulse rounded"
            style={{ background: "rgba(217, 119, 6, 0.06)" }}
          />
        </div>
      ))}
    </div>
  );
}

export function LiveFeed() {
  const { data, isLoading } = useStats();

  const claims = data?.recent_claims?.slice(0, 5) ?? [];

  return (
    <HudWindow
      title="LIVE FEED"
      action={{ label: "all \u2192", onClick: () => {} }}
    >
      {isLoading ? (
        <LoadingSkeleton />
      ) : claims.length === 0 ? (
        <div className="px-3 pb-3 text-[0.65rem]" style={{ color: "#6b6560" }}>
          No claims yet
        </div>
      ) : (
        <div className="flex flex-col gap-0.5 pb-2">
          {claims.map((claim) => (
            <ClaimRow key={claim.id} claim={claim} />
          ))}
        </div>
      )}
    </HudWindow>
  );
}
