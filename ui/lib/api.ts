import type {
  DashboardStats,
  PaginatedClaims,
  EntityNode,
  EdgeData,
  SubGraph,
  SearchResult,
  ClaimDetail,
  TimelineEntry,
  GraphSnapshot,
  TimelineRange,
  EntityTimestamp,
} from "./types";

// In production (static export served by FastAPI) — same origin, no prefix needed.
// In dev mode (next dev) — proxy to separate API server.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    throw new Error(`API error ${res.status}: ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const entries = Object.entries(params).filter(
    ([, v]) => v !== undefined && v !== ""
  );
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(
    entries.map(([k, v]) => [k, String(v)])
  ).toString();
}

export async function fetchStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>("/api/stats");
}

export async function fetchClaims(params: {
  offset?: number;
  limit?: number;
  type?: string;
  entity?: string;
  min_confidence?: number;
  min_salience?: number;
  sort_by?: string;
  sort_dir?: string;
}): Promise<PaginatedClaims> {
  return apiFetch<PaginatedClaims>(`/api/claims${qs(params)}`);
}

export async function fetchGraphEntities(params: {
  limit?: number;
  min_mentions?: number;
}): Promise<EntityNode[]> {
  return apiFetch<EntityNode[]>(`/api/graph/entities${qs(params)}`);
}

export async function fetchGraphEdges(params: {
  entity?: string;
}): Promise<EdgeData[]> {
  return apiFetch<EdgeData[]>(`/api/graph/edges${qs(params)}`);
}

export async function fetchSubgraph(
  entity: string,
  depth?: number
): Promise<SubGraph> {
  return apiFetch<SubGraph>(
    `/api/graph/subgraph${qs({ entity, depth })}`
  );
}

export async function searchClaims(
  q: string,
  limit?: number
): Promise<SearchResult[]> {
  return apiFetch<SearchResult[]>(`/api/search${qs({ q, limit })}`);
}

export async function fetchClaimDetail(id: string): Promise<ClaimDetail> {
  return apiFetch<ClaimDetail>(`/api/claims/${encodeURIComponent(id)}`);
}

export async function fetchEntityTimeline(
  entity: string,
  params?: { include_superseded?: boolean; limit?: number }
): Promise<TimelineEntry[]> {
  return apiFetch<TimelineEntry[]>(
    `/api/timeline/${encodeURIComponent(entity)}${qs(params ?? {})}`
  );
}

export async function fetchGraphSnapshot(at: string): Promise<GraphSnapshot> {
  return apiFetch<GraphSnapshot>(
    `/api/timeline/snapshot/at${qs({ at })}`
  );
}

export async function fetchTimelineRange(): Promise<TimelineRange> {
  return apiFetch<TimelineRange>("/api/timeline/range/bounds");
}

export async function fetchEntityTimestamps(): Promise<EntityTimestamp[]> {
  return apiFetch<EntityTimestamp[]>("/api/timeline/entity-timestamps");
}
