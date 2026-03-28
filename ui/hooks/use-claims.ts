"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchClaims, fetchClaimDetail, searchClaims } from "@/lib/api";

export function useClaims(params: {
  offset?: number;
  limit?: number;
  type?: string;
  entity?: string;
  min_confidence?: number;
  min_salience?: number;
  sort_by?: string;
  sort_dir?: string;
}) {
  return useQuery({
    queryKey: ["claims", params],
    queryFn: () => fetchClaims(params),
  });
}

export function useClaimDetail(id: string | null) {
  return useQuery({
    queryKey: ["claim-detail", id],
    queryFn: () => fetchClaimDetail(id!),
    enabled: !!id,
  });
}

export function useSearch(q: string, limit?: number) {
  return useQuery({
    queryKey: ["search", q, limit],
    queryFn: () => searchClaims(q, limit),
    enabled: q.length > 0,
  });
}
