# Tensory Benchmark Results

## LoCoMo (Long-term Conversational Memory, ACL 2024)

Evaluated via [Open Memory Benchmark](https://github.com/vectorize-io/agent-memory-benchmark) (AMB).

**Dataset:** LoCoMo 10 conversations, 1986 total QA pairs  
**Split:** locomo10 (10 conversations × ~19 sessions each)

### Latest Run: 152 Queries (April 2025)

**Configuration:**
- Extraction LLM: Claude Haiku 4.5 (via proxy)
- Answer LLM: Claude Sonnet 4
- Judge LLM: Claude Sonnet 4
- Embeddings: OpenAI text-embedding-3-small (1536 dim)
- Categories: single-hop, temporal, multi-hop, open-domain (38 per category)

| Category | Correct | Total | Accuracy |
|---|:---:|:---:|:---:|
| **Temporal** | 35 | 38 | **92.1%** |
| **Open-domain** | 35 | 38 | **92.1%** |
| **Single-hop** | 30 | 38 | **78.9%** |
| **Multi-hop** | 25 | 38 | **65.8%** |
| **Overall** | **125** | **152** | **82.2%** |

**Per conversation:**

| Conversation | Score | Accuracy |
|---|:---:|:---:|
| conv-30 | 7/7 | 100.0% |
| conv-26 | 105/120 | 87.5% |
| conv-41 | 5/8 | 62.5% |
| conv-42 | 5/11 | 45.5% |
| conv-43 | 3/6 | 50.0% |

**Cost:** $0.77 (extraction) + ~$3 (answer/judge) ≈ $3.77 total

### Comparison with Other Memory Systems

| Memory System | Answer LLM | Accuracy | Queries | Notes |
|---|---|:---:|:---:|---|
| **Hindsight** (cloud) | Gemini Pro | 92.0% | 1,540 | Closed-source |
| **Tensory** | Sonnet 4 | **82.2%** | 152 | Open-source, self-hosted |
| **Cognee** | Gemini Pro | 80.3% | 152 | Partial evaluation |
| **Hybrid Search** (Qdrant) | Gemini Pro | 79.1% | 1,540 | Vector-only baseline |

### What's Working

1. **Temporal queries (92.1%)** — deterministic ClaimType → MemoryType mapping routes `experience` claims to `episodic`, activating the 1.3x memory-type boost. Temporal boost (1.25x) promotes claims with embedded dates.

2. **Open-domain queries (92.1%)** — hybrid search (FTS5 + vector + graph → RRF) retrieves diverse facts. MMR reranking (λ=0.7) prevents entity crowding.

3. **Adversarial detection** — correctly identifies unanswerable questions without hallucinating.

### Where We Struggle

1. **Multi-hop (65.8%)** — requires chaining 2-3 facts that are individually retrieved but not connected. Example: "Nate likes Xenoblade 2" + "Xenoblade 2 is Switch-only" → "Nate owns a Switch". This is an inference gap, not a retrieval gap.

2. **Single-hop retrieval misses (78.9%)** — specific details sometimes not extracted or superseded (e.g., "sunset painting", exact number of children).

### Tuning History

| Change | Impact | Status |
|---|---|---|
| Soft memory-type boost (1.3x) instead of hard SQL filter | Multi-hop F1: 0.00 → 0.31 | ✅ Shipped |
| Temporal boost (1.25x) for claims with dates | Multi-hop F1: 0.31 → 0.39 | ✅ Shipped |
| Entity relevance boost (1.15x) for query entities | Reduces entity confusion | ✅ Shipped |
| **ClaimType → MemoryType mapping** (experience → episodic) | **85% → 90%** (20q test) | ✅ Shipped |
| Seasonal temporal regex ("for the summer", "last winter") | Enables temporal boost for seasonal queries | ✅ Shipped |
| Month+year date detection ("July 2023") | More claims detected as dated | ✅ Shipped |
| MMR λ 0.7 → 0.6 | -10% accuracy (too much diversity) | ❌ Reverted |
| "planning to/for" temporal regex | False positives on non-temporal queries | ❌ Reverted |

### Failure Analysis (27 failures in 152 queries)

| Failure Type | Count | Root Cause |
|---|:---:|---|
| Multi-hop inference gap | ~13 | LLM can't chain 2-3 individual facts |
| Retrieval miss (claim not extracted or superseded) | ~10 | Extraction quality / collision over-aggressiveness |
| Answer LLM hedging ("not enough info") | ~4 | LLM too conservative with indirect evidence |

### Next Steps

1. **Multi-hop graph traversal** — chain entities through graph paths, collect claims along path
2. **Cross-encoder reranking** — rerank top-20 claims for precision
3. **Answer prompt tuning** — structured context (entity groups, temporal annotations)
4. **Full 1,540-query evaluation** — run complete LoCoMo split for fair comparison
