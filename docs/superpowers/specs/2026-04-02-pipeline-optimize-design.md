# Pipeline Optimization Design

**Date:** 2026-04-02
**Branch:** `pipeline-optimize` (from main + entity normalization cherry-pick)
**Goal:** Improve overall accuracy (82% → 87%+), reduce cost, fix multi-hop (65.8%)

## Context

Weco-optimized extraction prompts on `prompt-optimize` branch degraded accuracy from 82.2% to 67.1% (AMB, 152 queries). Root cause analysis:

1. **Claim inflation:** 697 → 1,215 claims (+74%), longer avg text (70 → 94 chars), flooding retrieval with noise
2. **Lost relationship claims:** atomicity rule destroyed cross-entity links ("X recommended Y to Z")
3. **Retrieval miss dominance:** 12/25 regressions were claims existing in DB but not surfaced by search

Baseline extraction is already good (82-86%). The ROI is in pipeline improvements, not prompt overhauls.

## Approach: Three Independent Phases

### Phase 1: Extraction — Minimal Targeted Prompt Edits

**File:** `tensory/prompts.py` (EXTRACT_WITH_CONTEXT, EXTRACT_GENERIC)

Add only two rules to baseline prompts:

1. **Verbatim rule (short):** "Preserve exact country names, city names, numbers, amounts, and object names from the text. Do not generalize specific details into broader categories."
   - Proven: open-domain +18% in custom runner test
   - Keep it to 2 sentences, not the 10-line STRICT VERBATIM block from Weco

2. **Relationship instruction:** "When entities interact, extract relationship claims (e.g., 'Caroline recommended Becoming Nicole to Melanie')."
   - Addresses the 8 extraction-miss regressions where link claims were lost

**NOT included:** atomicity splitting, coreference resolution, high precision filtering, few-shot examples. These caused claim inflation.

**Success criteria:** claim count stays within ±15% of baseline (697), accuracy ≥ 82% on AMB 152q.

### Phase 2: Answer Prompt Tuning

**File:** AMB answer prompt or Tensory retrieve response format

Improve how retrieved claims are presented to the answer LLM:

1. **Entity grouping:** cluster claims by entity before presenting to LLM
2. **Multi-hop instruction:** "Chain related facts together. If Claim A says 'X likes game Y' and Claim B says 'game Y is platform-exclusive', you can infer X owns that platform."
3. **Confidence signal:** include claim confidence scores in context

**Testing:** `--skip-ingestion` in AMB — reuses existing DB, only re-runs answer+judge. Fast iteration (~10 min per run).

**Success criteria:** multi-hop accuracy ≥ 75% (from 65.8%), no regression in other categories.

### Phase 3: Multi-hop Graph Traversal

**File:** `tensory/search.py` — new search channel

When query contains multiple entities or is classified as multi-hop:

1. Extract entities from query
2. Use existing `find_path()` in `graph.py` to find paths between entity pairs
3. Collect claims along each path (claims attached to intermediate entities)
4. Add as additional channel to RRF fusion

**Success criteria:** multi-hop accuracy ≥ 80%, overall ≥ 87%.

## Testing Strategy

| Level | Tool | Queries | Time | Cost | Use for |
|-------|------|---------|------|------|---------|
| Quick | custom runner | 25 | 5 min | $0.07 | Fast iteration, claim count check |
| Full | AMB | 152 | 40 min | $3-4 | Validation of winners |

**Rules:**
- Each phase tested independently before combining
- Quick test first, full AMB only for changes that pass quick test
- Same answer/judge models for all comparisons (Sonnet 4 via OpenRouter)
- Track claim count per run — inflation = regression signal

## Baseline Numbers (to beat)

| Metric | main (AMB 127q) | main (AMB 152q) |
|--------|:---:|:---:|
| Overall | 85.8% | 82.2% |
| Temporal | 95% | 92.1% |
| Open-domain | 84% | 92.1% |
| Single-hop | 76% | 78.9% |
| Multi-hop | 92% (13q only) | 65.8% |

Note: 127q and 152q runs used different query sets and possibly different conversations.
