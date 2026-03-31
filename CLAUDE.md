# Tensory

Context-aware memory for AI agents. Built-in collision detection.
Full cognitive stack: episodic + semantic + procedural memory + reflection.

## Tech Stack

Python 3.11+, SQLite + sqlite-vec, Pydantic v2, asyncio
Package manager: **uv**
Tooling: pyright (strict), ruff (lint + format), pytest-asyncio

## Commands

```bash
uv sync --all-extras                    # Install all deps
uv run pytest tests/                    # Run all tests (~322)
uv run pytest tests/test_store.py::test_name   # Single test
uv run pyright tensory/                 # Type check (strict mode)
uv run ruff check tensory/ tests/       # Lint
uv run ruff format tensory/ tests/      # Format
uv run python examples/demo.py          # Integration demo
```

## Architecture

```
tensory/                 # Library source (15 modules)
  store.py               # Orchestrator — 10 public methods
  models.py              # Pydantic: Episode, Claim, MemoryType, SearchResult, ...
  search.py              # Hybrid search (FTS5 + vector + graph → RRF → MMR)
  extract.py             # LLM extraction with durability-based filtering
  prompts.py             # All LLM prompts (extraction, CARA, procedural, segmentation)
  collisions.py          # Two-level collision detection (structural + semantic)
  dedup.py               # MinHash/LSH — Apache 2.0 from Graphiti, KEEP attribution
  schema.py              # SQLite schema v3 (WAL, FTS5, sqlite-vec cosine)
  embedder.py            # Embedder Protocol + OpenAIEmbedder + NullEmbedder
api/                     # FastAPI dashboard backend (read-only)
ui/                      # Next.js 16 dashboard (see ui/CLAUDE.md)
plugins/claude-code/     # Claude Code plugin (hooks: session-start, stop)
tensory_hook.py          # Hook implementation (recall/save/health)
```

## Environment Variables

See `.env.example`. Key vars:
- `OPENAI_API_KEY` — for OpenAIEmbedder
- `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` — for LLM extraction
- `TENSORY_MODEL` — extraction model (default: claude-haiku-4-5-20251001)
- `TENSORY_DB` — database path (default: `~/.local/share/tensory/memory.db`)
- `TENSORY_DEBUG` — set to `1` for visible recall/save debug output in hooks

## Conventions

- MUST: `uv run` for all commands (not bare pytest/pyright)
- Embedder Protocol (not ABC) — structural subtyping, no inheritance needed
- LLMProtocol = any `async (str) -> str` callable
- Graceful degradation: search/vec channels that fail → empty list, no crash

## Extraction & Durability

Claims are filtered by temporal durability during extraction:
- `permanent` / `long-term` → stored (decisions, how things work, gotchas)
- `short-term` → dropped (test counts, status updates, ephemeral metrics)
- Prompt principle: "Would recalling this change how I think or act?"
- Claims must be SELF-CONTAINED — understandable without original text

## Gotchas

- sqlite-vec loads via `db.enable_load_extension(True)` + `db.load_extension(sqlite_vec.loadable_path())`. Direct `_conn` access fails (thread safety)
- sqlite-vec distance is L2 by default, NOT cosine. Schema sets `distance_metric=cosine`
- FTS5 content-sync tables need triggers (INSERT/DELETE/UPDATE). See `schema.py` `_FTS_TRIGGERS`
- Dedup Jaccard at 3-gram shingles: 1-word diff drops Jaccard to ~0.76. Threshold 0.9 = strict
- `MinHashDedup` works for claim text dedup (long strings), NOT for entity names (too short). Use `normalize_entity()` for entity names
- `add_entity()` commits immediately (FK constraints on `entity_relations`)
- Claims table FKs on `episode_id`/`context_id` removed — `add_claims()` accepts orphan claims
- `chunk_threshold` is per-call on `add()`, not constructor. Default: 3000 tokens
- MMR reranking uses stored claim embeddings. Falls back to entity-cap filter with NullEmbedder
- `claim.temporal` is often None — formatter falls back to `valid_from` → `created_at`
- Plugin env var is `TENSORY_DB`, API env var is `TENSORY_DB_PATH` (API checks both with fallback)
- Python `os.getenv()` does NOT expand `~` — always use `os.path.expanduser()`

## Plugin (Claude Code)

- Hooks: `session-start.sh` (recall) → `stop.sh` (save)
- Recall query = `os.path.basename(cwd)` (project folder name)
- Save captures `last_assistant_message` from hook input JSON
- `TENSORY_DEBUG=1` adds visible debug block to recall + stderr output on save
- Docker dashboard: `ghcr.io/kryptogrib/tensory:latest` on port 7770
- Docker needs `-e TENSORY_DB_PATH=/data/memory.db -v ~/.local/share/tensory:/data`

## Documentation

Rules for writing/maintaining docs: `docs/documentation-guide.md`

## Benchmark (LoCoMo / AMB)

AMB provider: `../agent-memory-benchmark/src/memory_bench/memory/tensory_provider.py`
Benchmark docs: `benchmarks/locomo/README.md`
