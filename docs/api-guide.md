# API Guide

Full API walkthrough for the tensory Python library.

## Initialize

Create a store with an embedder for vector search and an LLM function for claim extraction.

```python
from tensory import Tensory, Claim, Context
from tensory.embedder import OpenAIEmbedder

store = await Tensory.create(
    "memory.db",
    llm=my_llm_fn,                                    # any async (str) -> str
    embedder=OpenAIEmbedder(api_key="sk-..."),         # or dim=512 for cheaper
)
```

## Create Context

A research context is the lens that shapes what gets extracted. The goal and domain tell the extraction pipeline what matters.

```python
ctx = await store.create_context(
    goal="Track DeFi team movements and protocol partnerships",
    domain="crypto",
)
```

## Add Content

Two modes for ingesting information.

### Mode 1: Raw text with auto-extraction

Pass raw text and a context. The LLM extracts claims, relations, and detects collisions with existing knowledge -- all relative to the context lens.

```python
result = await store.add(
    "Google announced partnership with EigenLayer for cloud restaking...",
    source="reddit:r/defi",
    context=ctx,
)
# result.claims      — extracted claims
# result.relations   — entity relations
# result.collisions  — auto-detected conflicts
```

### Mode 2: Pre-extracted claims

Already have structured claims? Skip the LLM entirely.

```python
await store.add_claims([
    Claim(text="EigenLayer team grew to 60", entities=["EigenLayer"])
])
```

## Search

Hybrid search combines vector similarity, full-text search, and graph traversal. Results are weighted by the active context.

```python
results = await store.search("EigenLayer", context=ctx)
```

## Timeline

Track how facts about an entity evolved over time.

```python
history = await store.timeline("EigenLayer")
```

## Re-evaluate

Same source text, different research goal -- produces different claims. Useful when you revisit raw episodes under a new analytical lens.

```python
tech_ctx = await store.create_context(goal="Track Big Tech AI strategy")
new_claims = await store.reevaluate(episode_id=result.episode_id, context=tech_ctx)
```

## Maintenance

Cleanup stale data, inspect store health, profile sources, and consolidate recurring patterns.

```python
await store.cleanup(max_age_days=90)
stats = await store.stats()
source_profile = await store.source_stats("reddit:r/defi")
observations = await store.consolidate(days=7, min_cluster=3)
```
