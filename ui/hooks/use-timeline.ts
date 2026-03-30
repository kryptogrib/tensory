"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import {
  fetchEntityTimeline,
  fetchGraphSnapshot,
  fetchTimelineRange,
} from "@/lib/api";

export function useTimelineRange() {
  return useQuery({
    queryKey: ["timeline-range"],
    queryFn: fetchTimelineRange,
  });
}

export function useGraphSnapshot(at: string | null) {
  return useQuery({
    queryKey: ["graph-snapshot", at],
    queryFn: () => fetchGraphSnapshot(at!),
    enabled: !!at,
    placeholderData: keepPreviousData,
  });
}

export function useEntityTimeline(entity: string | null) {
  return useQuery({
    queryKey: ["entity-timeline", entity],
    queryFn: () => fetchEntityTimeline(entity!),
    enabled: !!entity,
  });
}
