# Fisher Reranking — TODO

Fisher-Rao reranking is implemented (`metric="auto"|"cosine"|"fisher"`).
Now it needs to be validated on real data and parameters tuned.

## 1. Run LoCoMo A/B Benchmark

Run the benchmark **three times** — cosine, fisher, auto — on the same data.
To exclude differences in extraction, use `--skip-ingest` for subsequent runs.

```bash
# First run (with ingestion)
uv run python -m benchmarks.locomo --conversation 0 --verbose \
    --db benchmarks/locomo/.cache/tensory_fisher_ab.db

# Then manually in answer.py or via patch — compare three metrics.
# Option 1: Temporarily hardcode metric in answer.py:
#   results = await store.search(question, context=context, metric="cosine")
#   results = await store.search(question, context=context, metric="fisher")
#   results = await store.search(question, context=context, metric="auto")
#
# Option 2: Add --metric to CLI (better, 5 lines):
#   parser.add_argument("--metric", choices=["cosine","fisher","auto"], default="auto")
#   → pass to answer_questions() → store.search()
```

### What to Compare

| Metric | Source | What to look for |
|--------|--------|------------------|
| Overall F1 | `results.json` → `scores.overall.f1` | Main indicator |
| Multi-hop F1 | `scores.multi-hop.f1` | Fisher should help most here |
| Single-hop F1 | `scores.single-hop.f1` | Minimal difference expected |
| Response time | `answer.time_sec` | Fisher adds ~5-10% overhead |

### Expected Results

Based on SuperLocalMemory V3 (arXiv:2603.14588):
- **Multi-hop**: +12 pp (biggest gain)
- **Single-hop**: +6 pp
- **Adversarial**: no change (Fisher doesn't affect "unanswerable")

If overall F1 difference cosine vs fisher **< 2 pp** — Fisher is not worth the overhead
at the current data volume. Keep `metric="auto"` as default and revisit when
the database grows.

---

## 2. Parameter Tuning

After running the benchmark, if Fisher shows improvement, tune:

### 2.1. `threshold` in `should_rerank()` (current: 0.05)

This is the score spread threshold at which auto enables Fisher.

```python
# tensory/search.py → should_rerank()
spread = results[0].score - results[min_candidates - 1].score
return spread < threshold  # ← this threshold
```

**How to tune:**
1. Add logging to `store.search()`:
   ```python
   if metric == "auto":
       spread = results[0].score - results[2].score if len(results) >= 3 else 999
       logger.info("Fisher auto: spread=%.4f, rerank=%s", spread, spread < 0.05)
   ```
2. Run the benchmark, collect spreads
3. Build a histogram: at which threshold Fisher helps vs doesn't
4. Typical values:
   - **0.02** — Fisher triggers very rarely (only when results are truly indistinguishable)
   - **0.05** — moderate (current default)
   - **0.10** — frequent (more overhead, but safer)

### 2.2. `temperature` in `_fisher_similarity()` (current: 15.0)

Controls the "sharpness" of Fisher scores.

```python
# tensory/search.py → _fisher_similarity()
return math.exp(-dist / temperature)
```

**How to tune:**
- **High (20-30):** all scores ≈ 0.8-0.95, soft re-ranking
- **Medium (10-15):** normal spread (SLM V3 default)
- **Low (3-7):** sharp separation, only clearly similar items get high scores

If Fisher scores in the benchmark are all > 0.9 — lower temperature to 8-10.
If most are < 0.3 — raise to 20-25.

### 2.3. `VARIANCE_FLOOR` / `VARIANCE_CEIL` (current: 0.05 / 2.0)

Define the "confidence" range for each embedding dimension.

```python
# tensory/search.py
VARIANCE_FLOOR = 0.05   # high confidence (large components)
VARIANCE_CEIL  = 2.0    # low confidence (small components)
```

**When to change:**
- If Fisher barely differs from cosine → **decrease FLOOR** (0.01) or
  **increase CEIL** (5.0) — this amplifies the difference between "important" and "noisy"
  dimensions
- If Fisher re-ranks too aggressively → **bring FLOOR and CEIL closer**
  (e.g., 0.1 / 1.0) — this makes it closer to cosine

**Don't touch** until the benchmark shows a problem. SLM V3 defaults work.

---

## 3. Testing After Tuning

### 3.1. Quick smoke test (after any parameter change)

```bash
uv run pytest tests/test_fisher.py -v  # 25 tests, < 1 sec
```

### 3.2. Full regression (before committing)

```bash
uv run pytest tests/ -v               # 210 tests
uv run pyright tensory/               # type check
uv run ruff check tensory/ tests/     # lint
```

### 3.3. A/B on LoCoMo (when changing threshold/temperature)

```bash
# Run with --skip-ingest to compare search only
uv run python -m benchmarks.locomo --conversation 0 --skip-ingest -v
```

Compare F1 before and after changing a parameter. Record results:

```
threshold=0.05, temperature=15.0: overall F1=0.XXXX, multi-hop=0.XXXX
threshold=0.03, temperature=15.0: overall F1=0.XXXX, multi-hop=0.XXXX
threshold=0.05, temperature=10.0: overall F1=0.XXXX, multi-hop=0.XXXX
```

---

## 4. Next Steps (after validation)

- [ ] Add `--metric` argument to benchmark CLI (`benchmarks/locomo/run.py`)
- [ ] Graduated ramp: `blend = min(claim.usage_count / 10, 1.0)` — Fisher
      weight grows with the number of accesses to a claim (separate PR)
- [ ] Bayesian variance update: `1/var_new = 1/var_old + 1/var_observation` —
      frequently used claims get a more accurate Fisher metric
- [ ] Logging: record `spread` and `rerank_triggered` in stats for
      production monitoring
- [ ] `max_result_tokens` — add to `search_procedural()` as well
