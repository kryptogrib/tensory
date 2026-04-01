# Architecture

Tensory stores memory as structured claims inside a single SQLite database. Raw text enters at the bottom layer, gets refined into atomic claims with embeddings, links into a knowledge graph, and surfaces through a hybrid search pipeline that merges three retrieval channels.

## Storage Layers

```
Layer 0: RAW       — episodes (raw text). Never deleted.
Layer 1: CLAIMS    — atomic claims + embeddings + salience.
Layer 2: GRAPH     — entities + relations + waypoints.
Layer 3: CONTEXT   — research goals as extraction lenses.
```

### Layer 0: RAW (Episodes)

Every piece of text ingested into Tensory is stored verbatim as an **episode**. Episodes are append-only and never deleted — they serve as the ground-truth audit trail. All higher layers derive from episodes, so the raw source is always available for re-extraction or verification.

### Layer 1: CLAIMS (Atomic Claims)

The extraction pipeline decomposes episodes into **atomic claims** — single, verifiable statements. Each claim carries:

- **Embedding vector** — dense representation for semantic search (via sqlite-vec).
- **Salience score** — a decaying relevance weight, updated automatically on collision:
  - `contradiction` → salience × 0.5
  - `supersedes` → salience × 0.1
  - `confirms` → salience + 0.2
  - `related` → salience + 0.05
- **Temporal metadata** — timestamps and validity windows.
- **Entity references** — links to the graph layer.

Salience decay, surprise scoring, and priming all operate at this layer without additional LLM calls.

### Layer 2: GRAPH (Entities, Relations, Waypoints)

Claims reference **entities** (people, places, concepts) and **relations** between them. The graph layer also maintains **waypoints** — high-connectivity nodes that act as navigation anchors during graph traversal. Entity and relation data powers the graph search channel and collision detection.

### Layer 3: CONTEXT (Research Goals)

A **context** defines *why* the agent is reading. The same raw text yields different claims depending on the active research goal. Contexts act as extraction lenses — they bias the LLM toward claims relevant to the current objective, filtering noise at ingestion time rather than at query time.

## Search Pipeline

Three parallel channels merged via Reciprocal Rank Fusion (RRF), then diversified via MMR:

```
FTS5 + Vector + Graph → RRF merge (over-fetch 3x) → MMR reranking → top-k
```

### Channel Weights

| Channel | Weight | Method |
|---------|--------|--------|
| Vector  | 0.4    | sqlite-vec cosine similarity |
| FTS     | 0.3    | SQLite FTS5 full-text search |
| Graph   | 0.3    | Entity traversal via recursive CTEs |

Weights are configurable per query.

### RRF Merge

Each channel returns a ranked list. Reciprocal Rank Fusion combines them by scoring each claim as `1 / (k + rank)` across all channels, then sorting by total score. The pipeline over-fetches 3× the requested `top-k` to give MMR enough candidates to diversify.

### MMR Reranking

**Maximal Marginal Relevance** prevents entity crowding — the failure mode where a popular entity with many similar claims dominates results and pushes out specific, high-value facts. MMR iteratively selects claims that balance relevance against redundancy with already-selected results.

When embeddings are unavailable, the pipeline falls back to entity-cap filtering (limiting how many claims from the same entity can appear in the final result set).

### Graceful Degradation

Any channel that fails returns empty results instead of crashing the search. This means:

- No embedder configured → vector channel returns `[]`, FTS and graph still work.
- FTS index missing → FTS channel returns `[]`, vector and graph still work.
- Graph traversal error → graph channel returns `[]`, vector and FTS still work.

The remaining channels carry the query. Search never raises on a single-channel failure.

## Graph Backend

Default: **SQLiteGraphBackend** — uses recursive CTEs for traversal, zero external dependencies, sufficient for <100K claims.

```python
# Default — everything in one SQLite file
store = await Tensory.create("memory.db")

# Enterprise — Neo4j (planned)
# store = await Tensory.create("memory.db", graph_backend=Neo4jBackend("bolt://localhost:7687"))
```

The SQLite backend keeps the single-file deployment story intact: one `.db` file contains episodes, claims, embeddings, FTS index, and graph data. For deployments exceeding ~100K claims where graph traversal latency matters, a Neo4j backend is planned to handle deeper multi-hop queries.
