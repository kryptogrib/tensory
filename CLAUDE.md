# Tensory

Context-aware memory for AI agents. One file. Built-in collision detection.

## Tech Stack

Python 3.11+, SQLite + sqlite-vec, Pydantic, asyncio
Tooling: pyright (strict), ruff (lint + format), pytest-asyncio

## Commands

```bash
pip install -e ".[openai]"              # Install with OpenAI embedder
pytest tests/                            # Run all tests
pytest tests/test_store.py::test_name   # Single test
pyright tensory/                         # Type check (strict mode)
ruff check tensory/ tests/              # Lint
ruff format tensory/ tests/             # Format
```

## Architecture

```
tensory/                 # Library source
  store.py               # Tensory orchestrator (main class)
  models.py              # Pydantic: Episode, Context, Claim, Collision
  schema.py              # SQLite schema (4 layers: raw, claims, graph, context)
  search.py              # Hybrid search (FTS5 + vector + graph → RRF)
  collisions.py          # Two-level collision detection (structural + semantic)
  dedup.py               # MinHash/LSH (Apache 2.0 from Graphiti — keep attribution!)
  embedder.py            # Pluggable: OpenAIEmbedder / NullEmbedder
  extract.py             # Context-aware LLM extraction
  temporal.py            # Superseding, decay, timeline, cleanup
  graph.py               # GraphBackend Protocol + SQLiteGraphBackend
tests/                   # One test file per module
plans/tensory-plan.md    # Full plan with references
docs/                    # Documentation guides
```

For details and reference implementations: `plans/tensory-plan.md` → "Обязательные reference implementations по модулям" — READ BEFORE WRITING CODE

## Documentation

Rules for writing/maintaining docs: `docs/documentation-guide.md`

## Conventions

- MUST: type annotations on ALL functions
- MUST: `dedup.py` keeps Apache 2.0 attribution header
- NEVER: bare `Exception`; use specific subclasses
- Python/testing rules auto-loaded from `.claude/rules/`

## Gotchas

- sqlite-vec loads via `await db.enable_load_extension(True)` + `await db.load_extension(sqlite_vec.loadable_path())`. Direct `_conn` access fails (thread safety).
- sqlite-vec default distance is L2, NOT cosine. Schema uses `distance_metric=cosine` explicitly.
- `NullEmbedder` returns zero vectors → vector search returns nothing (deterministic). Surprise score = 0.0 without real embeddings.
- FTS5 content-sync tables need triggers (INSERT/DELETE/UPDATE) to stay in sync. See `schema.py` `_FTS_TRIGGERS`.
- Dedup Jaccard at 3-gram shingles: even 1-word differences drop Jaccard to ~0.76. Threshold 0.9 is strict — only near-identical texts match.
- `add_entity()` commits immediately (needed for FK constraints on `entity_relations`).
- `reevaluate()` with same LLM output gets blocked by dedup. Different context should produce different extraction (real LLM does, test FakeLLM needs switching responses).
- Claims table FKs on `episode_id`/`context_id` removed — `add_claims()` accepts orphan claims without episodes.
- `OpenAIEmbedder` uses `Any` type for client (optional dep not installed during type checking). Pyright ignores via cast.
- Search channels that fail → return empty list, don't crash (graceful degradation)
- Collision detection is zero-LLM (algorithmic). LLM verification is the app's job, not library's

## Current Status

Phases 1-5 complete. Library is feature-complete and publish-ready (v0.1.0).
96 tests, pyright strict clean, ruff clean, GitHub Actions CI configured.
Next: Phase 5+ (Neo4jBackend), Phase 5++ (CARA), Phase 5+++ (MCP server).
