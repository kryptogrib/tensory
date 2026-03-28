export type ClaimType = "fact" | "experience" | "observation" | "opinion";

export interface Claim {
  id: string;
  text: string;
  entities: string[];
  type: ClaimType;
  confidence: number;
  relevance: number;
  salience: number;
  temporal: string | null;
  metadata: Record<string, unknown>;
  episode_id: string | null;
  context_id: string | null;
  created_at: string;
  superseded_at: string | null;
  superseded_by: string | null;
  valid_from: string | null;
  valid_to: string | null;
}

export interface EntityNode {
  id: string;
  name: string;
  type: string | null;
  mention_count: number;
  first_seen: string;
}

export interface EdgeData {
  from_entity: string;
  to_entity: string;
  rel_type: string;
  fact: string;
  confidence: number;
  created_at: string;
  expired_at: string | null;
}

export interface SubGraph {
  nodes: EntityNode[];
  edges: EdgeData[];
}

export interface DashboardStats {
  counts: Record<string, number>;
  claims_by_type: Record<string, number>;
  avg_salience: number;
  recent_claims: Claim[];
  hot_entities: EntityNode[];
}

export interface PaginatedClaims {
  items: Claim[];
  total: number;
  offset: number;
  limit: number;
}

export interface SearchResult {
  claim: Claim;
  score: number;
  relevance: number;
  method: string;
}

export interface ClaimDetail {
  claim: Claim;
  episode: Episode | null;
  collisions: Collision[];
  waypoints: string[];
  related_entities: EntityRelation[];
}

export interface Episode {
  id: string;
  raw_text: string;
  source: string;
  source_url: string | null;
  fetched_at: string;
}

export interface EntityRelation {
  from_entity: string;
  to_entity: string;
  rel_type: string;
  fact: string;
  confidence: number;
  created_at: string;
  expired_at: string | null;
}

export interface Collision {
  claim_a: Claim;
  claim_b: Claim;
  score: number;
  shared_entities: string[];
  temporal_distance: number | null;
  type: string;
}
