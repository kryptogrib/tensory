"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchGraphEntities, fetchGraphEdges, fetchSubgraph } from "@/lib/api";

export function useGraphEntities(params: {
  limit?: number;
  min_mentions?: number;
}) {
  return useQuery({
    queryKey: ["graph-entities", params],
    queryFn: () => fetchGraphEntities(params),
  });
}

export function useGraphEdges(params: { entity?: string }) {
  return useQuery({
    queryKey: ["graph-edges", params],
    queryFn: () => fetchGraphEdges(params),
  });
}

export function useSubgraph(entity: string | null, depth?: number) {
  return useQuery({
    queryKey: ["subgraph", entity, depth],
    queryFn: () => fetchSubgraph(entity!, depth),
    enabled: !!entity,
  });
}
