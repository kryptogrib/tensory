# Tensory

Context-aware memory for AI agents. One file. Built-in collision detection.
Full cognitive stack: episodic + semantic + procedural memory + reflection.

## Tech Stack

Python 3.11+, SQLite + sqlite-vec, Pydantic v2, asyncio
Package manager: **uv**
Tooling: pyright (strict), ruff (lint + format), pytest-asyncio

## Commands

```bash
uv sync --all-extras                    # Install all deps
uv run pytest tests/                    # Run all 246 tests
uv run pytest tests/test_store.py::test_name   # Single test
uv run pyright tensory/                 # Type check (strict mode)
uv run ruff check tensory/ tests/       # Lint
uv run ruff format tensory/ tests/      # Format
uv run python examples/demo.py          # Integration demo
```

## Architecture

```
tensory/                 # Library source (13 modules)
  store.py               # Tensory orchestrator — 10 public methods
  models.py              # Pydantic: Episode, Context, Claim, MemoryType, ProceduralResult, ...
  schema.py              # SQLite schema v2 (4 layers + procedural, WAL, FTS5, sqlite-vec cosine)
  search.py              # Hybrid search (FTS5 + vector + graph → RRF → MMR diversity) + memory_type filter
  collisions.py          # Two-level collision detection (structural + semantic)
  dedup.py               # MinHash/LSH (Apache 2.0 from Graphiti — keep attribution!)
  embedder.py            # Embedder Protocol + OpenAIEmbedder + NullEmbedder
  extract.py             # LLMProtocol + extraction: claims, procedural, long-text (hybrid)
  chunking.py            # Token estimation, topic segmentation, paragraph split, entity dedup
  temporal.py            # Superseding, exponential decay, timeline, cleanup
  graph.py               # GraphBackend Protocol + SQLiteGraphBackend (recursive CTEs)
  prompts.py             # All LLM prompts: extraction, CARA, procedural, segmentation
  __init__.py            # Public API exports
tests/                   # One test file per module (246 tests)
examples/
  demo.py                # Full integration demo (works without API keys)
  llm_adapters.py        # Ready-to-use: OpenAI, Anthropic (with proxy), Ollama
plans/tensory-plan.md    # Original plan with references
.env.example             # All env vars documented
```

## Environment Variables

See `.env.example`. Key vars:
- `OPENAI_API_KEY` — for OpenAIEmbedder and openai_llm()
- `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` — for Anthropic (supports CLIProxyAPI proxy)
- `TENSORY_MODEL` — model for extraction (default: claude-haiku-4-5-20251001)

## Conventions

- MUST: type annotations on ALL functions (pyright strict)
- MUST: `dedup.py` keeps Apache 2.0 attribution header (Graphiti)
- MUST: use `uv run` for all commands (not bare pytest/pyright)
- Embedder Protocol (not ABC) — structural subtyping, no inheritance needed
- LLMProtocol = any `async (str) -> str` callable
- Graceful degradation: search/vec channels that fail → empty list, no crash

## Gotchas

- sqlite-vec loads via `await db.enable_load_extension(True)` + `await db.load_extension(sqlite_vec.loadable_path())`. Direct `_conn` access fails (thread safety)
- sqlite-vec default distance is L2, NOT cosine. Schema uses `distance_metric=cosine` explicitly
- `OpenAIEmbedder` supports `dim=512` for cheaper storage (native Matryoshka reduction)
- `OpenAIEmbedder` supports `base_url=` for proxy (CLIProxyAPI, LiteLLM, etc.)
- FTS5 content-sync tables need triggers (INSERT/DELETE/UPDATE). See `schema.py` `_FTS_TRIGGERS`
- Dedup Jaccard at 3-gram shingles: 1-word diff drops Jaccard to ~0.76. Threshold 0.9 = strict
- `add_entity()` commits immediately (FK constraints on `entity_relations`)
- `reevaluate()` with same LLM output gets blocked by dedup — real LLMs produce different extraction per context
- Claims table FKs on `episode_id`/`context_id` removed — `add_claims()` accepts orphan claims
- Schema migration v2: `SCHEMA_VERSION = 2`, adds procedural columns. Fresh installs get them in CREATE TABLE; existing DBs get ALTER TABLE via `migrate()`
- `MinHashDedup` works for claim text dedup (long strings), NOT for entity name resolution (short names like "ETH" get Jaccard ≈ 0). Use `normalize_entity()` for entity names
- `chunk_threshold` is per-call on `add()`, not constructor — user controls per text. Default: 3000 tokens
- `estimate_tokens()` uses word count as proxy (~±15%) — no tokenizer dependency
- Topic segmentation returns full text in sections (verbatim copy), not summaries. Lost text = lost claims
- MMR reranking uses stored claim embeddings for diversity. Falls back to entity-cap filter if embeddings unavailable (NullEmbedder)
- `_mmr_rerank()` λ=0.7 default: higher = more relevance, lower = more diversity. Entity-cap fallback uses max_per_entity=3

## Procedural Memory (Phase 6)

Three-type cognitive memory architecture (PlugMem arXiv:2603.03296):
- `MemoryType.EPISODIC` — what happened (raw events)
- `MemoryType.SEMANTIC` — what is true (facts, observations) — default
- `MemoryType.PROCEDURAL` — how to do things (skills with trigger/steps/termination)

Key methods:
- `store.add_procedural(text)` → extracts skills via Skill-MDP (ProcMEM arXiv:2602.01869)
- `store.search_procedural(query)` → filtered search + success_rate re-ranking
- `store.update_skill_feedback(skill_id, outcome=True/False)` → EMA success_rate + auto-deprecate
- `store.search(query, memory_type=MemoryType.PROCEDURAL)` → filter by memory type
- `reflect()` now tracks `evolved_skills` — procedural claims involved in collisions

Schema migration v2 adds procedural columns to claims table (backward compatible).

## Hybrid Extraction (Phase 7)

Long texts are automatically segmented via topic segmentation:
- `store.add(text, chunk_threshold=3000)` — per-call threshold control
- Short text (< threshold): 1 LLM call (existing behavior)
- Long text (≥ threshold): 1 LLM segmentation call → N parallel extraction calls
- `max_segments = max(2, tokens // 3000)` — prevents over-splitting
- Fallback: if LLM segmentation fails → paragraph splitting (no LLM)
- Entity names deduplicated across sections via lowercase normalization

## Documentation

Rules for writing/maintaining docs: `docs/documentation-guide.md`

## Current Status

Phases 1-8 complete. 246 tests, pyright strict, ruff clean, uv, GitHub Actions CI.
- Phase 5+ Neo4jBackend ✅
- Phase 5++ CARA reflect() ✅
- Phase 5+++ MCP server ✅
- Phase 6: Procedural Memory ✅ (Skill-MDP, feedback loop, search_procedural)
- Phase 7: Hybrid Extraction ✅ (topic segmentation, parallel extraction, entity dedup)
- Phase 8: Search Diversity ✅ (MMR reranking, entity-cap fallback, search quality tests)

## Benchmark (LoCoMo / AMB)

AMB provider at `/Users/chelovek/Work/agent-memory-benchmark/src/memory_bench/memory/tensory_provider.py`
Benchmark docs: `benchmarks/locomo/README.md`
- Tensory registered as `tensory` provider in AMB (Open Memory Benchmark)
- Exact token tracking via `TrackingEmbedder` and `_make_tracking_llm()`
- `anthropic` LLM provider added to AMB for proxy-based answer/judge
