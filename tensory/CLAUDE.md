# tensory/ — Library Source

13 modules implementing claim-native memory with hybrid search.

## Search Pipeline (search.py)

```
Query → FTS5 + Vector + Graph (parallel)
            ↓
      RRF merge (3x over-fetch)
            ↓
    Embeddings available?
     ↙              ↘
   YES                NO
_mmr_rerank()    _entity_diverse_filter()
(λ=0.7)          (max 3 per entity)
     ↘              ↙
    Final top-k results
```

- NEVER remove MMR fallback to entity-cap — NullEmbedder users rely on it
- `_cosine_sim()` is pure Python (no numpy). OpenAI vectors are pre-normalized but we norm anyway for safety
- `_load_candidate_embeddings()` handles both binary (sqlite-vec) and JSON embedding formats
- Over-fetch factor is 3x — hardcoded in `hybrid_search()`. If changed, update tests

## Modules

| Module | Purpose | Key pattern |
|--------|---------|-------------|
| `store.py` | Orchestrator | `Tensory.create()` async factory, 10 public methods |
| `search.py` | Hybrid search | 3 parallel channels → RRF → MMR diversity |
| `models.py` | Data models | Pydantic v2, `Claim` is the core unit |
| `schema.py` | DB schema | WAL + FTS5 + sqlite-vec, schema v2 migration |
| `collisions.py` | Conflict detection | Structural (entity overlap) + semantic (LLM) |
| `dedup.py` | MinHash/LSH | Apache 2.0 from Graphiti — KEEP attribution |
| `embedder.py` | Embedding protocol | Structural subtyping, no ABC |
| `extract.py` | LLM extraction | `LLMProtocol = async (str) -> str` |
| `chunking.py` | Text splitting | Token estimation, topic segmentation |
| `temporal.py` | Time handling | Superseding, decay, timeline |
| `graph.py` | Entity graph | SQLiteGraphBackend with recursive CTEs |
| `prompts.py` | LLM prompts | All prompts in one place |

## Critical Invariants

- `add_claims()` stores embeddings via `json.dumps(claim.embedding)` into sqlite-vec
- `add_entity()` commits immediately (FK constraints require it)
- Search channels that fail → return `[]`, NEVER raise
- `claim.entities` populated from DB via `load_claim_entities()` after search, not stored on model
- FTS5 query sanitization in `_sanitize_fts_query()` — strips `?`, `'`, `*` and other FTS5 operators
