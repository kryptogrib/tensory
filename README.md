# tensory

**Embedded, claim-native memory for AI agents. Single SQLite file. Built-in collision detection.**

82.2% LoCoMo accuracy | 330+ tests | pyright strict | MIT

[![PyPI](https://img.shields.io/pypi/v/tensory)](https://pypi.org/project/tensory/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/tensory)](https://pypi.org/project/tensory/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/kryptogrib/tensory/actions/workflows/ci.yml/badge.svg)](https://github.com/kryptogrib/tensory/actions/workflows/ci.yml)

[Plugin](plugins/claude-code/README.md) | [Benchmarks](docs/benchmark-results.md) | [API Guide](docs/api-guide.md) | [Architecture](docs/architecture.md) | [Dashboard](#dashboard)

## Quickstart

### Claude Code plugin (recommended)

Memory works automatically — no tool descriptions in context, no manual search calls:

```bash
claude plugin install --source github kryptogrib/tensory --path plugins/claude-code
```

On install, Claude Code asks for your API keys. That's it — memory activates on every session.

> Full plugin docs: [plugins/claude-code/README.md](plugins/claude-code/README.md)

### Python library

```bash
pip install tensory
```

```python
from tensory import Tensory, Claim

store = await Tensory.create("memory.db")
await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])
results = await store.search("EigenLayer")
```

Extras: `pip install "tensory[mcp]"` | `"tensory[ui]"` | `"tensory[all]"`

<details>
<summary><b>MCP server</b> — for Claude Desktop, Cursor, and other MCP clients</summary>

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

Provides 7 tools: `tensory_add`, `tensory_remember`, `tensory_search`, `tensory_timeline`, `tensory_stats`, `tensory_health`, `tensory_reset`.

> The plugin approach is preferred — hooks work automatically, while MCP tools require the agent to call them and their descriptions consume context tokens.

</details>

## Why tensory

| Library | Strength | Gap |
|---|---|---|
| **[Mem0](https://github.com/mem0ai/mem0)** | Simple API, good DX | Chunk-based, no collision detection |
| **[Graphiti/Zep](https://github.com/getzep/graphiti)** | Temporal knowledge graph | Requires Neo4j, heavy infra |
| **[Cognee](https://github.com/topoteretes/cognee)** | Pipeline architecture | Complex setup, no contradiction resolution |
| **[Letta/MemGPT](https://github.com/letta-ai/letta)** | Context window management | Agent framework, not a memory library |
| **Hindsight** | Best benchmarks (92% LoCoMo) | Closed-source cloud service |

tensory: single `pip install`, atomic claim extraction, contradiction detection, temporal reasoning — zero infrastructure.

## Features

- **Claim-native storage** — extracts atomic, verifiable statements instead of raw text chunks
- **Context-aware extraction** — same text yields different claims depending on research goal ([details](docs/context-lens.md))
- **Built-in collision detection** — finds contradictions and superseding facts automatically ([details](docs/cognitive-mechanisms.md))
- **Cognitive mechanisms** — salience decay, surprise scoring, priming — all algorithmic, zero LLM calls ([details](docs/cognitive-mechanisms.md))
- **Hybrid search** — FTS5 + vector + graph traversal, merged via RRF, diversified via MMR ([details](docs/architecture.md#search-pipeline))
- **Pluggable LLM and embeddings** — OpenAI, Anthropic, Ollama, or bring your own ([details](docs/configuration.md))
- **Web dashboard** — entity graph explorer, claims browser, memory stats
- **Full cognitive stack** — episodic + semantic + procedural memory + reflection

## Architecture

```
Layer 0: RAW       — episodes (raw text). Never deleted.
Layer 1: CLAIMS    — atomic claims + embeddings + salience.
Layer 2: GRAPH     — entities + relations + waypoints.
Layer 3: CONTEXT   — research goals as extraction lenses.
```

Everything lives in a single SQLite file. No Docker, no Neo4j, no external services required.

> Deep dive: [docs/architecture.md](docs/architecture.md)

## Example

```python
from tensory import Tensory, Context
from tensory.embedder import OpenAIEmbedder

store = await Tensory.create(
    "memory.db",
    llm=my_llm_fn,                                    # any async (str) -> str
    embedder=OpenAIEmbedder(api_key="sk-..."),
)

# Create a research context — the lens for extraction
ctx = await store.create_context(
    goal="Track DeFi team movements and protocol partnerships",
    domain="crypto",
)

# Raw text → auto-extract claims relative to context
result = await store.add(
    "Google announced partnership with EigenLayer for cloud restaking...",
    source="reddit:r/defi",
    context=ctx,
)
# result.claims, result.relations, result.collisions

# Hybrid search — vector + FTS + graph, context-weighted
results = await store.search("EigenLayer", context=ctx)

# Timeline — how facts about an entity evolved
history = await store.timeline("EigenLayer")
```

> Full API reference: [docs/api-guide.md](docs/api-guide.md)

## Dashboard

```bash
uvx --from "tensory[ui]" tensory-dashboard --db ~/.local/share/tensory/memory.db
```

Open **http://localhost:7770** — entity graph explorer, claims browser, memory stats.

<details>
<summary><b>Docker</b></summary>

```bash
docker run -d -p 7770:7770 --name tensory-dashboard \
  -v ~/.local/share/tensory:/data \
  --restart unless-stopped \
  ghcr.io/kryptogrib/tensory
```

</details>

## Benchmarks

Tested on [LoCoMo](https://arxiv.org/abs/2401.17753) (Long-term Conversational Memory, ACL 2024):

| Memory System | Accuracy | Queries | Notes |
|---|:---:|:---:|---|
| **Hindsight** (cloud) | 92.0% | 1,540 | Closed-source |
| **Tensory** | **82.2%** | 152 | Open-source, single-file SQLite |
| **Cognee** | 80.3% | 152 | Partial evaluation |
| **Hybrid Search** (Qdrant) | 79.1% | 1,540 | Vector-only baseline |

Extraction cost: ~$0.08/conversation (Haiku + embeddings).

> Full breakdown, per-category results, failure analysis: [docs/benchmark-results.md](docs/benchmark-results.md)

## Configuration

```bash
cp .env.example .env
```

| Variable | Purpose | Required |
|---|---|---|
| `OPENAI_API_KEY` | Embeddings + LLM extraction via OpenAI | Only if using OpenAI |
| `ANTHROPIC_API_KEY` | LLM extraction via Anthropic/proxy | Only if using Anthropic |
| `ANTHROPIC_BASE_URL` | Proxy URL (CLIProxyAPI, LiteLLM) | Optional |
| `TENSORY_MODEL` | Model for extraction | Default: claude-haiku-4-5-20251001 |

> Full configuration guide: [docs/configuration.md](docs/configuration.md)

## Status

**Alpha.** 330+ tests, pyright strict, ruff clean, CI on every push.

What's next:

- Full LoCoMo evaluation (1,540 questions) for definitive comparison
- Multi-hop graph traversal — chain facts across entity relationships
- Cross-encoder reranking for retrieval precision
- Session-aware diversification (SSD) for sequential agent queries
- Research agent built on tensory as a reference application

## Development

```bash
uv sync --all-extras                    # Install all deps
uv run pytest tests/                    # Run all tests
uv run pyright tensory/                 # Type check (strict mode)
uv run ruff check tensory/ tests/       # Lint
uv run ruff format tensory/ tests/      # Format
```

## License

MIT

## Attribution

Deduplication logic adapted from [Graphiti](https://github.com/getzep/graphiti) (Apache-2.0 License, Copyright 2024 Zep Software, Inc.)
