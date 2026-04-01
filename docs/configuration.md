# Configuration

All configuration for embeddings, LLM providers, and storage backends.

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

## Graph Backends

Default: **SQLiteGraphBackend** — uses recursive CTEs, zero dependencies, sufficient for <100K claims.

```python
# Default — everything in one SQLite file
store = await Tensory.create("memory.db")

# Enterprise — Neo4j (planned)
# store = await Tensory.create("memory.db", graph_backend=Neo4jBackend("bolt://localhost:7687"))
```

## Environment Variables

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
