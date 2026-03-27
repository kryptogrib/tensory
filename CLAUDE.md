# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**tensory** — an embedded, claim-native memory library for AI agents. Context-aware extraction, collision detection, zero external dependencies by default (single SQLite file).

Tagline: "Context-aware memory for AI agents. One file. Built-in collision detection."

Status: **Pre-implementation** — the architecture plan is complete at `plans/tensory-plan.md`. No source code exists yet.

## Core Principles

1. `pip install tensory` works **without Docker, without Neo4j**
2. **Raw never dies** — original text (episodes) stored forever; claims are re-extractable with new contexts
3. **Context-aware extraction** — same text → different claims depending on user's research goal
4. **LLM on write, algorithms on read** — extract/relate with LLM; search/collisions are algorithmic

## Architecture: 4 Storage Layers

```
Layer 0: RAW       — episodes (raw text, source, url). Never deleted.
Layer 1: CLAIMS    — atomic claims + embeddings + salience. Link to episode + context.
Layer 2: GRAPH     — entities + LLM-extracted relations + waypoints.
Layer 3: CONTEXT   — user research goals as extraction lenses + relevance scores.
```

The "context as lens" pattern is the core innovation: a Context defines *why* the user is reading, and claims are extracted relative to that goal. One episode can yield different claims under different contexts via `reevaluate()`.

## Tech Stack

- **Python 3.11+**, strict typing (pyright strict mode)
- **SQLite** with WAL mode, FTS5 (keyword search), sqlite-vec (vector embeddings)
- **aiosqlite** for async concurrent access
- **Pydantic v2** for all data models
- **Hatchling** build system
- Optional extras: `openai` (embedder), `neo4j` (enterprise graph backend)

## Build & Development Commands

```bash
# Install (once pyproject.toml exists)
pip install -e ".[openai]"

# Tests
pytest tests/
pytest tests/test_store.py               # single test file
pytest tests/test_store.py::test_name    # single test

# Type checking
pyright tensory/

# Linting (planned Phase 5)
ruff check tensory/ tests/
ruff format tensory/ tests/
```

## Module Responsibilities

| File | Role | Key patterns |
|---|---|---|
| `store.py` | Main orchestrator (`Tensory` class) | 7 public methods: `create_context`, `add`, `add_claims`, `search`, `timeline`, `reevaluate`, `stats`/`cleanup` |
| `schema.py` | SQLite schema (all 4 layers) | WAL pragma, FTS5, vec0, schema versioning with migrations |
| `models.py` | Pydantic models | Episode, Context, Claim (with salience/decay), EntityRelation, Collision, IngestResult, SearchResult |
| `extract.py` | Context-aware LLM extraction | Prompt includes research goal + domain; extracts claims with type, confidence, temporal, relations |
| `dedup.py` | MinHash/LSH deduplication | Entropy gate (low entropy → exact match only). Adapted from Graphiti (Apache 2.0, attribution required) |
| `embedder.py` | Pluggable embeddings | `Embedder` Protocol + `OpenAIEmbedder` + `NullEmbedder` |
| `search.py` | Hybrid search + RRF merge | 3 parallel channels (vector + FTS + graph), weighted Reciprocal Rank Fusion |
| `collisions.py` | Two-level collision detection | Level 1: structural (same entity + overlapping validity). Level 2: semantic (vector + entity + temporal + waypoint scores) |
| `temporal.py` | Time-based operations | Superseding, timeline, exponential decay cleanup, auto-supersede at collision score > 0.9 |
| `graph.py` | Graph backend abstraction | `GraphBackend` Protocol + `SQLiteGraphBackend` (recursive CTEs, default) + future `Neo4jBackend` |

## Cognitive Mechanisms (Zero-LLM)

These are algorithmic, not LLM-based (~285 lines total):
- **Salience + decay**: exponential decay per ClaimType (FACT=0.005, OPINION=0.020)
- **Surprise score**: novelty detection via mean vector distance from existing claims
- **Priming**: in-memory Counter of recently-searched entities boosts related results
- **Reinforce on access**: +0.05 salience when claim is found via search
- **Waypoints**: auto-created 1-hop links to most similar claim (cosine ≥ 0.75)
- **Structural collision**: same entity + overlapping temporal validity = auto-conflict
- **Consolidation**: Union-Find clustering → OBSERVATION claims (template-based, no LLM)
- **Source fingerprinting**: per-source reliability profiles (confirmed_ratio, avg_surprise)

## Collision Salience Rules

```python
"contradiction" → salience × 0.5
"supersedes"    → salience × 0.1
"confirms"      → salience + 0.2 (capped at 1.0)
"related"       → salience + 0.05 (capped at 1.0)
```

## Implementation Phases

- **Phase 1** (Days 1-2): Core storage, salience, schema, GraphBackend, sentiment tagging
- **Phase 2** (Days 2-3): Vector search, hybrid RRF, surprise, priming, reinforce-on-access
- **Phase 3** (Days 3-4): Dedup, collision detection, waypoints
- **Phase 4** (Days 4-5): LLM extraction, temporal ops, consolidation, source fingerprinting
- **Phase 5** (Days 5-6): pyproject.toml, README, CI, publishing
- **Phase 5+**: Neo4jBackend, LLM-based reflect + CARA, MCP server

## Key Design Decisions

- **GraphBackend is a Protocol** — `SQLiteGraphBackend` (recursive CTEs) is default; `Neo4jBackend` is optional enterprise extra
- **Kuzu is discontinued** (Oct 2025) — removed from plan entirely
- **Dedup code from Graphiti** — Apache 2.0, attribution header required in `dedup.py`
- **Search weights are configurable**: default vector=0.4, fts=0.3, graph=0.3
- **Collision scoring formula**: `vector×0.4 + entity×0.25 + temporal×0.2 + waypoint×0.15`
- **Graceful degradation**: search channels that fail return empty lists, don't crash

## Reference Implementations

When implementing, study these sources (cited in the plan):
- **Graphiti** — dedup helpers, GraphBackend pattern, temporal invalidation
- **OpenMemory HSG** — salience/decay model, waypoint graph, structural collision detection
- **Hindsight** — TEMPR parallel retrieval, reflect() semantics, CARA prompts
- **sqlite-vec** — vector embedding setup, hybrid search with FTS5
