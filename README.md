# tensory

**Context-aware memory for AI agents. One file. Built-in collision detection.**

> I evaluated every open-source memory library — Mem0, Graphiti/Zep, Cognee, Letta — and none fit what I needed: a **single-file**, **claim-native** memory with built-in contradiction detection, temporal reasoning, and zero infrastructure. So I built Tensory.

```bash
pip install tensory
```

## Install & Run

### 1. Claude Code Plugin — automatic memory (recommended)

Memory works automatically — no tool descriptions in context, no "please search memory":

```bash
claude plugin install --source github kryptogrib/tensory --path plugins/claude-code
```

On install, Claude Code will ask for your API keys. That's it — memory is active.

> **Full integration docs:** [plugins/claude-code/README.md](plugins/claude-code/README.md) — all LLM provider options (including no-API-key mode via Claude Code SDK), configuration matrix, troubleshooting.

**Or ask your agent to install it.** Send this prompt:

> Install the tensory plugin for long-term memory. Run:
>
> ```
> claude plugin install --source github kryptogrib/tensory --path plugins/claude-code
> ```
>
> When prompted, enter these env vars:
> - `OPENAI_API_KEY` — your OpenAI key (for embeddings / vector search)
> - `ANTHROPIC_API_KEY` — your Anthropic key (for LLM claim extraction)
> - `TENSORY_DB` — leave default (`~/.local/share/tensory/memory.db`)
>
> After install, restart the session. Memory now works automatically:
> - Session start → recalls relevant context from past sessions
> - Session end → saves what was learned (claims, decisions, facts)

**How it works:**

| Hook | When | What happens |
|------|------|-------------|
| `SessionStart` | Session opens | Searches memory for project context → injects into Claude's context window |
| `Stop` | Claude finishes responding | Extracts durable claims from conversation → stores with collision detection |

Set `TENSORY_DEBUG=1` in your `.env` to see what's recalled and saved each session.

### 2. Dashboard — see your agent's memory

```bash
uvx --from "tensory[ui]" tensory-dashboard --db ~/.local/share/tensory/memory.db
```

Or via Docker:

```bash
docker run -d -p 7770:7770 --name tensory-dashboard \
  -v ~/.local/share/tensory:/data \
  -e TENSORY_DB_PATH=/data/memory.db \
  --restart unless-stopped \
  ghcr.io/kryptogrib/tensory:latest
```

Open **http://localhost:7770** — entity graph explorer, claims browser, memory stats.

> **Note:** The `-e TENSORY_DB_PATH=/data/memory.db` must match the actual filename in your `~/.local/share/tensory/` directory. The plugin defaults to `memory.db`.

### 3. As a Python library

```bash
pip install tensory                # core (SQLite + search)
pip install "tensory[mcp]"         # + MCP server + plugin hooks
pip install "tensory[ui]"          # + dashboard
pip install "tensory[all]"         # everything
```

<details>
<summary><b>Alternative: MCP Server</b> — for Claude Desktop, Cursor, and other MCP clients</summary>

If your client doesn't support plugins/hooks, use the MCP server directly:

```json
{
  "mcpServers": {
    "tensory": {
      "command": "uvx",
      "args": ["--from", "tensory[mcp]", "tensory-mcp"],
      "env": {
        "TENSORY_DB": "~/.local/share/tensory/memory.db",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

| Variable | Required | Description |
|----------|:--------:|-------------|
| `TENSORY_DB` | Yes | Path to SQLite database file |
| `OPENAI_API_KEY` | Recommended | For embeddings (vector search) |
| `ANTHROPIC_API_KEY` | Optional | For claim extraction via LLM |
| `ANTHROPIC_BASE_URL` | Optional | Proxy URL (CLIProxyAPI, LiteLLM) |

Provides 7 tools: `tensory_add`, `tensory_remember`, `tensory_search`, `tensory_timeline`, `tensory_stats`, `tensory_health`, `tensory_reset`.

> **Note:** The plugin approach is preferred over MCP because hooks work automatically — MCP tools require the agent to decide to call them, and their descriptions consume context tokens on every message.
</details>

## Why not existing solutions?

| Library | What's great | What didn't work for me |
|---|---|---|
| **[Mem0](https://github.com/mem0ai/mem0)** | Simple API, good DX | Chunk-based, no collision detection, no temporal tracking. Lost facts silently. |
| **[Graphiti/Zep](https://github.com/getzep/graphiti)** | Strong knowledge graph, MMR search | Requires Neo4j, heavy infra. Graph-first, not claim-first. |
| **[Cognee](https://github.com/topoteretes/cognee)** | Pipeline architecture | Complex setup, graph-oriented, no built-in contradiction resolution. |
| **[Letta/MemGPT](https://github.com/letta-ai/letta)** | Context window management | Agent framework, not a memory library. Different abstraction level. |
| **Hindsight** | Best benchmark scores (92% LoCoMo) | Closed-source cloud service. Can't self-host or inspect. |

**What I wanted:** embed a SQLite file, extract atomic claims, detect when facts contradict or supersede each other, and search across text + vectors + entity graph — all in one `pip install`.

## Quick Start

```python
from tensory import Tensory, Claim

store = await Tensory.create("memory.db")
await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])
results = await store.search("EigenLayer")
```

## What is tensory?

An embedded, claim-native memory library for AI agents. Instead of storing raw text chunks, Tensory extracts **atomic claims** — verifiable statements with entities, confidence, and temporal validity.

- **One file** — single SQLite database, no Docker, no Neo4j required
- **Context-aware extraction** — same text yields different claims depending on *why* you're reading it
- **Durability-filtered** — only stores claims that change how you think or act; ephemeral noise (test counts, status updates) is automatically dropped
- **Built-in collision detection** — automatically finds contradictions and superseding facts
- **Cognitive mechanisms** — salience decay, surprise scoring, priming, all without LLM calls
- **MMR-diversified search** — hybrid retrieval with entity crowding prevention
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

Three parallel channels merged via Reciprocal Rank Fusion (RRF), then diversified via MMR:

```
FTS5 + Vector + Graph → RRF merge (over-fetch 3x) → MMR reranking → top-k
```

| Channel | Weight | Method |
|---|---|---|
| Vector | 0.4 | sqlite-vec cosine similarity |
| FTS | 0.3 | SQLite FTS5 full-text search |
| Graph | 0.3 | Entity traversal via recursive CTEs |

**MMR reranking** (Maximal Marginal Relevance) prevents entity crowding — when a popular entity with many similar claims dominates results and pushes out specific facts. Falls back to entity-cap filtering when embeddings are unavailable.

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
| `TENSORY_DB` | Database path | Default: `~/.local/share/tensory/memory.db` |
| `TENSORY_DEBUG` | Set to `1` for visible recall/save debug output | Optional |

## Benchmarks

Testing on [LoCoMo](https://arxiv.org/abs/2401.17753) (Long-term Conversational Memory, ACL 2024) via [Open Memory Benchmark](https://github.com/vectorize-io/agent-memory-benchmark):

| Memory System | Accuracy | Queries | Notes |
|---|:---:|:---:|---|
| **Hindsight** (cloud) | 92.0% | 1,540 | Closed-source |
| **Cognee** | 80.3% | 152 | Partial evaluation |
| **Hybrid Search** (Qdrant) | 79.1% | 1,540 | Vector-only baseline |
| **Tensory** | *testing* | 1,540 | Full evaluation in progress |

Tensory extraction cost per conversation: **~$0.12** (Haiku extraction + OpenAI embeddings). Full benchmark is running — results will be published here.

## Status

**Active development.** 322+ tests, pyright strict, ruff clean, CI on every push.

The vision: become the **best open-source memory for AI agents** — a single-file SQLite database that gives your agent real long-term memory with contradiction detection, temporal reasoning, and cognitive mechanisms that work without LLM calls.

### What's done

- Episodic + semantic + procedural memory (full cognitive stack)
- Hybrid search with MMR diversity (FTS5 + vector + graph → RRF → MMR)
- Two-level collision detection (structural + semantic)
- Context-aware extraction (same text, different lens → different claims)
- Durability-based claim filtering (ephemeral noise auto-dropped)
- Topic segmentation for long texts (parallel extraction)
- MCP server for tool-use integration
- Claude Code plugin with automatic memory hooks
- Smart context formatting (entity grouping, temporal annotations, memory-type routing)
- Web dashboard (graph explorer, claims browser, stats) + Docker image
- Debug mode (`TENSORY_DEBUG=1`) for observable recall/save
- LoCoMo benchmark integration (AMB provider with exact cost tracking)

### What's next

- Full benchmark results on LoCoMo (1,540 questions, 10 conversations)
- Per-prompt contextual recall (UserPromptSubmit hook)
- Cross-encoder reranking for retrieval precision
- Research agent built on Tensory as a reference application

## Development

```bash
uv sync --all-extras                    # Install all deps
uv run pytest tests/                    # Run all tests (~322)
uv run pytest tests/test_store.py::test_name   # Single test
uv run pyright tensory/                 # Type check (strict mode)
uv run ruff check tensory/ tests/       # Lint
uv run ruff format tensory/ tests/      # Format
uv run python examples/demo.py          # Integration demo
```

## License

MIT

## Attribution

Deduplication logic adapted from [Graphiti](https://github.com/getzep/graphiti) (Apache-2.0 License, Copyright 2024 Zep Software, Inc.)

---

*Built because no existing memory library did what I needed. If you're building agents that need to remember, contradict, and evolve — give tensory a try.*
