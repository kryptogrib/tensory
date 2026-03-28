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

#### Competitor Results (from AMB manifest)

| Memory System | Answer LLM | Accuracy | Queries |
|---|---|:---:|:---:|
| **Hindsight** | Gemini 3.1 Pro | 92.0% | 1540 |
| **Cognee** | Gemini 3.1 Pro | 80.3% | 152 |
| **Hybrid Search** (Qdrant) | Gemini 3.1 Pro | 79.1% | 1540 |
| **Tensory** | Groq gpt-oss-120b | **88-92%** | 25 |

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

Token-level F1 (stricter than LLM-judge in AMB). Our result: **F1 ~0.52** on 10 questions.

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
- No per-entity diversity caps (planned for search.py core)
- Extraction non-deterministic: accuracy fluctuates 88-92% between runs

## Cost

| Component | Per 1 conversation | Per 10 conversations |
|-----------|:------------------:|:--------------------:|
| Haiku extraction (19 sessions) | ~$0.06 | ~$0.60 |
| OpenAI embeddings | ~$0.001 | ~$0.01 |
| Answer LLM (Groq) | free | free |
| Judge LLM (Gemini Flash Lite) | ~$0.01 | ~$0.10 |
| **TOTAL** | **~$0.07** | **~$0.70** |
