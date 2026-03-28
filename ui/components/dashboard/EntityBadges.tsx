"use client";

import { useStats } from "@/hooks/use-stats";
import { HudWindow } from "./HudWindow";
import type { EntityNode } from "@/lib/types";

function Badge({ entity, maxMentions }: { entity: EntityNode; maxMentions: number }) {
  const ratio = maxMentions > 0 ? entity.mention_count / maxMentions : 0.5;
  const opacity = 0.5 + ratio * 0.5;

  return (
    <span
      className="inline-block rounded px-2 py-0.5 text-[0.65rem] transition-opacity"
      style={{
        background: "rgba(217, 119, 6, 0.06)",
        border: "1px solid rgba(217, 119, 6, 0.1)",
        color: "#f5e6d3",
        opacity,
      }}
    >
      {entity.name}
    </span>
  );
}

function LoadingSkeleton() {
  return (
    <div className="flex flex-wrap gap-1.5 px-3 pb-3">
      {[1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="h-5 animate-pulse rounded"
          style={{
            width: `${40 + i * 12}px`,
            background: "rgba(217, 119, 6, 0.08)",
          }}
        />
      ))}
    </div>
  );
}

export function EntityBadges() {
  const { data, isLoading } = useStats();

  const entities = data?.hot_entities ?? [];
  const maxMentions = Math.max(...entities.map((e) => e.mention_count), 1);

  return (
    <HudWindow title="ACTIVE ENTITIES">
      {isLoading ? (
        <LoadingSkeleton />
      ) : entities.length === 0 ? (
        <div className="px-3 pb-3 text-[0.65rem]" style={{ color: "#6b6560" }}>
          No entities tracked
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5 px-3 pb-3">
          {entities.map((entity) => (
            <Badge key={entity.id} entity={entity} maxMentions={maxMentions} />
          ))}
        </div>
      )}
    </HudWindow>
  );
}
