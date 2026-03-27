# tensory

**Context-aware memory for AI agents. One file. Built-in collision detection.**

```bash
pip install tensory
```

## Quick Start

```python
from tensory import Tensory, Claim

store = await Tensory.create("memory.db")
await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])
results = await store.search("EigenLayer")
```

## What is tensory?

An embedded, claim-native memory library for AI agents. Instead of storing raw text chunks, tensory extracts **atomic claims** — verifiable statements with entities, confidence, and temporal validity.

- **One file** — single SQLite database, no Docker, no Neo4j required
- **Context-aware extraction** — same text yields different claims depending on *why* you're reading it
- **Built-in collision detection** — automatically finds contradictions and superseding facts
- **Cognitive mechanisms** — salience decay, surprise scoring, priming, all without LLM calls
- **Pluggable LLM & embeddings** — OpenAI, Anthropic (with proxy), Ollama, or bring your own

## Architecture: 4 Storage Layers

```
Layer 0: RAW       — episodes (raw text). Never deleted.
Layer 1: CLAIMS    — atomic claims + embeddings + salience.
Layer 2: GRAPH     — entities + relations + waypoints.
Layer 3: CONTEXT   — research goals as extraction lenses.
```

## Full API Example

```python
from tensory import Tensory, Claim, Context
from tensory.embedder import OpenAIEmbedder

# Initialize with embedder + LLM
store = await Tensory.create(
    "memory.db",
    llm=my_llm_fn,                                    # any async (str) -> str
    embedder=OpenAIEmbedder(api_key="sk-..."),         # or dim=512 for cheaper
)

# Create a research context — the lens for extraction
ctx = await store.create_context(
    goal="Track DeFi team movements and protocol partnerships",
    domain="crypto",
)

# Mode 1: Raw text → auto-extract claims relative to context
result = await store.add(
    "Google announced partnership with EigenLayer for cloud restaking...",
    source="reddit:r/defi",
    context=ctx,
)
# result.claims      — extracted claims
# result.relations   — entity relations
# result.collisions  — auto-detected conflicts

# Mode 2: Pre-extracted claims (no LLM needed)
await store.add_claims([
    Claim(text="EigenLayer team grew to 60", entities=["EigenLayer"])
])

# Search — hybrid (vector + FTS + graph), context-weighted
results = await store.search("EigenLayer", context=ctx)

# Timeline — how facts about an entity evolved
history = await store.timeline("EigenLayer")

# Re-evaluate — same text, different research goal → different claims
tech_ctx = await store.create_context(goal="Track Big Tech AI strategy")
new_claims = await store.reevaluate(episode_id=result.episode_id, context=tech_ctx)

# Maintenance
await store.cleanup(max_age_days=90)
stats = await store.stats()
source_profile = await store.source_stats("reddit:r/defi")
observations = await store.consolidate(days=7, min_cluster=3)
```

## Embeddings

OpenAI `text-embedding-3-small` recommended — $0.02/1M tokens (~$0.20 per 100K claims):

```python
from tensory.embedder import OpenAIEmbedder

# Standard (1536 dims)
embedder = OpenAIEmbedder(api_key="sk-...")

# Cost-optimized (512 dims — native Matryoshka reduction, 3x smaller storage)
embedder = OpenAIEmbedder(api_key="sk-...", dim=512)

# Via proxy (CLIProxyAPI, LiteLLM, etc.)
embedder = OpenAIEmbedder(base_url="http://localhost:8317", api_key="local-key")

# No embeddings (FTS + graph search still work)
store = await Tensory.create("memory.db")  # NullEmbedder by default
```

## LLM Extraction

Any async function `(str) -> str` works as LLM. Ready-made adapters in `examples/llm_adapters.py`:

```python
from examples.llm_adapters import anthropic_llm, openai_llm, ollama_llm

# OpenAI
store = await Tensory.create("memory.db", llm=openai_llm())

# Anthropic via proxy (as in openHunter)
store = await Tensory.create("memory.db", llm=anthropic_llm(
    base_url="http://localhost:8317", api_key="local-key",
))

# Ollama (free, local)
store = await Tensory.create("memory.db", llm=ollama_llm("llama3.1"))

# Or from env vars (ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY)
from examples.llm_adapters import anthropic_from_env
store = await Tensory.create("memory.db", llm=anthropic_from_env())
```

## Context as Lens

The core innovation: a **Context** defines *why* you're reading. One episode can yield completely different claims under different contexts via `reevaluate()`.

```python
# Same news article...
crypto_ctx = await store.create_context(goal="Track DeFi protocols")
tech_ctx = await store.create_context(goal="Track Big Tech AI strategy")

result = await store.add("Google partners with EigenLayer...", context=crypto_ctx)
# → Claims about EigenLayer, restaking, DeFi partnerships

new_claims = await store.reevaluate(result.episode_id, context=tech_ctx)
# → Claims about Google's cloud strategy, AI infrastructure moves
```

## Cognitive Mechanisms

All algorithmic, zero LLM calls:

| Mechanism | What it does |
|---|---|
| **Salience + decay** | Claims fade over time (exponential, per-type rates) |
| **Surprise score** | Novel claims get salience boost |
| **Priming** | Recently-searched entities boost related results |
| **Reinforce on access** | Searched claims get stronger (+0.05 salience) |
| **Waypoints** | Auto-link similar claims (cosine >= 0.75) |
| **Structural collision** | Same entity + different value = auto-conflict |
| **Consolidation** | Cluster claims into OBSERVATION summaries |
| **Source fingerprinting** | Per-source reliability profiles |
| **Sentiment tagging** | Keyword-based sentiment + urgency detection |

## Collision Detection

Two-level, zero LLM:

1. **Structural** — same entities + overlapping temporal validity
2. **Semantic** — weighted composite: vector (40%) + entity overlap (25%) + temporal proximity (20%) + waypoint link (15%)

Salience updates on collision:
- `contradiction` → salience x 0.5
- `supersedes` → salience x 0.1
- `confirms` → salience + 0.2
- `related` → salience + 0.05

## Hybrid Search

Three parallel channels merged via Reciprocal Rank Fusion (RRF):

| Channel | Weight | Method |
|---|---|---|
| Vector | 0.4 | sqlite-vec cosine similarity |
| FTS | 0.3 | SQLite FTS5 full-text search |
| Graph | 0.3 | Entity traversal via recursive CTEs |

Weights are configurable. Any channel that fails returns empty results (graceful degradation).

## Graph Backends

Default: **SQLiteGraphBackend** — uses recursive CTEs, zero dependencies, sufficient for <100K claims.

```python
# Default — everything in one SQLite file
store = await Tensory.create("memory.db")

# Enterprise — Neo4j (planned)
# store = await Tensory.create("memory.db", graph_backend=Neo4jBackend("bolt://localhost:7687"))
```

## Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

| Variable | Purpose | Required |
|---|---|---|
| `OPENAI_API_KEY` | Embeddings + LLM extraction via OpenAI | Only if using OpenAI |
| `ANTHROPIC_API_KEY` | LLM extraction via Anthropic/proxy | Only if using Anthropic |
| `ANTHROPIC_BASE_URL` | Proxy URL (CLIProxyAPI etc.) | Optional |
| `TENSORY_MODEL` | Model for extraction | Default: claude-haiku-4-5-20251001 |

## Development

```bash
# Install all dependencies
uv sync --all-extras

# Run tests (96 tests)
uv run pytest tests/ -v

# Type checking (strict mode)
uv run pyright tensory/

# Linting
uv run ruff check tensory/ tests/
uv run ruff format tensory/ tests/

# Integration demo (no API keys needed)
uv run python examples/demo.py

# Demo with real LLM
OPENAI_API_KEY=sk-... uv run python examples/demo.py --llm
```

## License

MIT

## Attribution

Deduplication logic adapted from [Graphiti](https://github.com/getzep/graphiti) (Apache-2.0 License, Copyright 2024 Zep Software, Inc.)
