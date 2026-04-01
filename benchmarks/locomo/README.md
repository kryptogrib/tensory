# LoCoMo Benchmark for Tensory

Testing Tensory on the LoCoMo benchmark (Long-term Conversational Memory, ACL 2024).

## Two Ways to Run

### 1. AMB (Agent Memory Benchmark) — recommended

Standard industry benchmark framework by Vectorize.io. Fair comparison with Hindsight, Cognee, Mem0, and others.

**Location:** `/Users/chelovek/Work/agent-memory-benchmark/`

#### Required Keys in `.env`

```bash
# /Users/chelovek/Work/agent-memory-benchmark/.env
GEMINI_API_KEY=...          # Required (AMB checks at startup)
OPENAI_API_KEY=...          # For embeddings (text-embedding-3-small)
ANTHROPIC_API_KEY=...       # For Haiku extraction (via proxy)
ANTHROPIC_BASE_URL=http://localhost:8317  # CLIProxyAPI proxy
GROQ_API_KEY=...            # Free model for answers (default)
OPENROUTER_API_KEY=sk-or-...  # For choosing any answer model
```

#### Run Commands

```bash
cd /Users/chelovek/Work/agent-memory-benchmark

# Quick test (3 questions, ~3 min, ~$0.01)
OMB_ANSWER_LLM=openrouter \
OMB_ANSWER_MODEL=meta-llama/llama-4-scout-17b-16e-instruct \
OMB_JUDGE_LLM=openrouter \
OMB_JUDGE_MODEL=google/gemini-2.5-flash-lite \
uv run omb run --dataset locomo --split locomo10 --memory tensory --query-limit 3

# 25 questions (~5 min, ~$0.06 extraction + answer model)
# Same env vars, just --query-limit 25

# Full benchmark (1540 questions, ~30 min, ~$0.50-2.00)
# Same env vars, no --query-limit
```

#### Choosing the Answer Model (OMB_ANSWER_LLM + OMB_ANSWER_MODEL)

| Option | Env vars | Cost | Note |
|--------|----------|------|------|
| **Groq (default)** | not set | Free | 30 req/min limit |
| **Groq via OpenRouter** | `openrouter` + `meta-llama/llama-4-scout-17b-16e-instruct` | ~$0.10/1540q | No limits |
| **Gemini Pro (like Hindsight)** | `openrouter` + `google/gemini-2.5-pro` | ~$1.00/1540q | Honest comparison |
| **Gemini Flash** | `openrouter` + `google/gemini-2.5-flash` | ~$0.20/1540q | Good balance |
| **Claude Sonnet** | `openrouter` + `anthropic/claude-sonnet-4` | ~$3.00/1540q | Expensive |
| **GPT-4o-mini** | `openai` + `gpt-4o-mini` | ~$0.30/1540q | Requires OPENAI_API_KEY |

#### Choosing the Judge Model (OMB_JUDGE_LLM + OMB_JUDGE_MODEL)

Recommended: `google/gemini-2.5-flash-lite` via openrouter (same as competitors).

#### What You Get

- `outputs/locomo/tensory/rag/locomo10.json` — full result with per-question accuracy
- Accuracy table in terminal
- Cost summary from Tensory provider

#### Results (AMB, April 2025)

| Memory System | Answer LLM | Accuracy | Queries |
|---|---|:---:|:---:|
| **Hindsight** | Gemini Pro | 92.0% | 1540 |
| **Tensory** | Sonnet 4 | **82.2%** | 152 |
| **Cognee** | Gemini Pro | 80.3% | 152 |
| **Hybrid Search** (Qdrant) | Gemini Pro | 79.1% | 1540 |

Per-category (Tensory, 152 queries):

| Category | Accuracy |
|---|:---:|
| Temporal | 92.1% |
| Open-domain | 92.1% |
| Single-hop | 78.9% |
| Multi-hop | 65.8% |

---

### 2. Custom Runner — for quick iteration

Simple pipeline for debugging extraction/search without AMB overhead.

**Location:** `benchmarks/locomo/` in tensory repo

#### Required Keys in `.env`

```bash
# /Users/chelovek/Work/tensory/.env
OPENAI_API_KEY=...          # For embeddings
ANTHROPIC_API_KEY=...       # For Haiku extraction + Sonnet answers
ANTHROPIC_BASE_URL=http://localhost:8317
```

#### Commands

```bash
cd /Users/chelovek/Work/tensory

# Full run (ingest + answer), 10 questions
uv run python -m benchmarks.locomo --conversation 0 --limit 10 -v

# Answers only (skip ingest, reuse existing DB)
uv run python -m benchmarks.locomo --conversation 0 --limit 10 --skip-ingest -v

# Questions 6-10 (offset + limit)
uv run python -m benchmarks.locomo --conversation 0 --offset 5 --limit 5 --skip-ingest -v
```

#### CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--conversation` | 0 | Conversation index (0-9) |
| `--limit` | all | Max questions |
| `--offset` | 0 | Skip N questions |
| `--search-limit` | 10 | Claims per search query |
| `--skip-ingest` | false | Reuse existing DB |
| `--db` | `.cache/tensory_locomo.db` | Database path |
| `-v` | false | Verbose logging |

#### Metric

Token-level F1 (stricter than LLM-judge in AMB). Useful for fast iteration on extraction/search quality.

---

## Tensory Architecture in AMB

```
LoCoMo JSON → AMB loads Documents (with session timestamps)
    │
    ▼
TensoryMemoryProvider.ingest()
    ├─ Prepend [Session date: ...] to content
    ├─ store.add() → Haiku extracts claims with dates in text
    └─ OpenAI embeds claims
    │
    ▼
TensoryMemoryProvider.retrieve()
    ├─ store.search() → hybrid FTS5 + vector + graph → RRF
    └─ Returns top-k claims as Documents
    │
    ▼
AMB Answer LLM (Groq/Gemini/etc) generates answer
    │
    ▼
AMB Judge LLM evaluates CORRECT/WRONG
```

**Key optimizations (already implemented):**
1. Session date injection — session dates prepended to content for temporal reasoning
2. Temporal extraction prompt — LLM embeds absolute dates in claim text
3. FTS5 query sanitization — special characters ?, ' don't break search
4. Cost tracking — provider tracks LLM + embedding costs

**Known limitations:**
- Entity crowding: popular entities (Caroline+counseling) flood out rare facts
- Extraction non-deterministic: accuracy fluctuates 88-92% between runs

---

## Search Pipeline Optimizations (April 2025)

### Problem: Multi-hop F1 = 0.00

Root cause: `classify_query("When did X?")` returned `MemoryType.EPISODIC`, but all 306 claims were stored as `semantic` (extraction never sets memory_type). Hard SQL filter `WHERE memory_type = 'episodic'` returned 0 results for every temporal question.

### Fix 1: Soft Boost Instead of Hard Filter

**File:** `tensory/search.py`

Removed `memory_type` from SQL WHERE clauses in all 3 search channels (FTS, vector, graph). Instead, `memory_type` is now a post-RRF score boost (1.3x) for matching claims. All claims are always retrieved; matching ones rank higher.

`search_procedural()` retains a hard post-filter (guarantees PROCEDURAL-only results).

**Result:** Multi-hop 0.00 → 0.31

### Fix 2: Temporal Boost

**File:** `tensory/search.py` — `_apply_temporal_boost()`

When query is temporal ("When did X?"), claims with explicit dates in text (e.g. "On 5 August 2023, ...") get 1.25x score boost. Date detection via regex on claim text.

**Result:** Multi-hop 0.31 → 0.39 (Q7 "5K charity run" fixed: 0.05 → 0.50)

### Fix 3: Entity Relevance Boost

**File:** `tensory/search.py` — `_apply_entity_relevance_boost()`

Claims mentioning capitalized words from the query (likely entity names) get 1.15x boost. Addresses entity confusion (e.g. "What did Maria do?" now promotes Maria claims over John claims).

### Category Runner

**File:** `benchmarks/locomo/run_categories.py`

New benchmark runner that selects N QA items per category (single-hop, multi-hop, temporal, open-domain, adversarial) from specified conversations. Ensures balanced category coverage.

```bash
# 5 questions per category from conversation 2
uv run python benchmarks/locomo/run_categories.py --conversations 2 --per-category 5 -v

# 10 per category from conversations 0, 2, 5
uv run python benchmarks/locomo/run_categories.py --conversations 0 2 5 --per-category 10 -v
```

### Benchmark Results

#### AMB LLM-judge (152 queries, April 2025)

Models: Haiku 4.5 (extraction), Sonnet 4 (answer + judge), text-embedding-3-small (embeddings).

| Category | Accuracy | Queries |
|---|:---:|:---:|
| Temporal | **92.1%** | 38 |
| Open-domain | **92.1%** | 38 |
| Single-hop | 78.9% | 38 |
| Multi-hop | 65.8% | 38 |
| **Overall** | **82.2%** | **152** |

#### Custom runner F1 (Conv 2 / conv-41, 5 per category)

| Category | Before (hard filter) | After (soft boost + temporal + entity) |
|---|:---:|:---:|
| single-hop | 0.636 | 0.551 |
| **multi-hop** | **0.000** | **0.389** |
| temporal | 0.409 | 0.300 |
| open-domain | 0.614 | 0.474 |
| adversarial | 0.824 | 0.616 |
| **OVERALL** | **0.497** | **0.466** |

Note: F1 is stricter than LLM-judge accuracy. Score variance ~±0.1 due to extraction non-determinism.

### Failure Analysis

| Failure type | Count | Fixable in search? |
|---|:---:|:---:|
| Answer LLM errors (wrong inference, over-answer) | 4 | No |
| Retrieval miss (claim exists but not in top-10) | 2 | Partially |
| Wrong fact retrieved (Coco vs Shadow) | 1 | Temporal ordering needed |
| Extraction miss (fact not extracted from text) | 1 | No |
| Format mismatch ("Not specified" vs "unanswerable") | 1 | No |

### Fix 4: Deterministic ClaimType → MemoryType Mapping

**File:** `tensory/extract.py` — `CLAIM_TO_MEMORY_TYPE`

All claims previously defaulted to `memory_type=semantic` because the extraction prompt never asked for it. Added deterministic mapping:
- `experience` → `episodic` (events with time/place context)
- `fact/observation/opinion` → `semantic` (stable knowledge)

This activates the 1.3x memory-type boost for temporal queries (which route to episodic) and makes ~37% of claims episodic.

**Result:** 85% → 90% on 20-query test.

### Fix 5: Expanded Temporal Detection

**File:** `tensory/search.py`

- Temporal query regex now matches seasonal references: "for the summer", "last winter", "this fall"
- Date-in-text regex now detects month+year patterns: "July 2023", "During March 2024"

Note: "planning to/for" was tested but reverted — too many false positives on non-temporal queries.

### Future Improvements

1. **Multi-hop graph traversal** — chain entities from query through graph paths, collect claims along path. Uses existing `find_path()` in graph.py. This is the biggest accuracy bottleneck (65.8%).
2. **Cross-encoder reranking** — rerank top-20 claims for precision
3. **Answer prompt tuning** — structured context with entity groups and temporal annotations
4. **Specificity scoring** — penalize generic claims ("John values kindness") vs specific ("John renovated community center")

## Cost

| Component | Per 1 conversation | Per 10 conversations |
|-----------|:------------------:|:--------------------:|
| Haiku extraction (19 sessions) | ~$0.06 | ~$0.60 |
| OpenAI embeddings | ~$0.001 | ~$0.01 |
| Answer LLM (Groq) | free | free |
| Judge LLM (Gemini Flash Lite) | ~$0.01 | ~$0.10 |
| **TOTAL** | **~$0.07** | **~$0.70** |
