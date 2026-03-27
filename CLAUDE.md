# Tensory

Context-aware memory for AI agents. One file. Built-in collision detection.

## Tech Stack

Python 3.11+, SQLite + sqlite-vec, Pydantic v2, asyncio
Package manager: **uv**
Tooling: pyright (strict), ruff (lint + format), pytest-asyncio

## Commands

```bash
uv sync --all-extras                    # Install all deps
uv run pytest tests/                    # Run all 96 tests
uv run pytest tests/test_store.py::test_name   # Single test
uv run pyright tensory/                 # Type check (strict mode)
uv run ruff check tensory/ tests/       # Lint
uv run ruff format tensory/ tests/      # Format
uv run python examples/demo.py          # Integration demo
```

## Architecture

```
tensory/                 # Library source (11 modules)
  store.py               # Tensory orchestrator — 7 public methods
  models.py              # Pydantic: Episode, Context, Claim, Collision, SearchResult
  schema.py              # SQLite schema (4 layers, WAL, FTS5, sqlite-vec cosine)
  search.py              # Hybrid search (FTS5 + vector + graph → RRF merge)
  collisions.py          # Two-level collision detection (structural + semantic)
  dedup.py               # MinHash/LSH (Apache 2.0 from Graphiti — keep attribution!)
  embedder.py            # Embedder Protocol + OpenAIEmbedder + NullEmbedder
  extract.py             # LLMProtocol + context-aware extraction prompts
  temporal.py            # Superseding, exponential decay, timeline, cleanup
  graph.py               # GraphBackend Protocol + SQLiteGraphBackend (recursive CTEs)
  __init__.py            # Public API exports
tests/                   # One test file per module (96 tests)
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

## Current Status

Phases 1-5 complete. Library is feature-complete and publish-ready (v0.1.0).
96 tests, pyright strict, ruff clean, uv, GitHub Actions CI.
Next: Phase 5+ (Neo4jBackend), Phase 5++ (CARA), Phase 5+++ (MCP server).
