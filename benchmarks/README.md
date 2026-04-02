# Benchmarks

Tensory is evaluated via [Open Memory Benchmark (AMB)](https://github.com/vectorize-io/agent-memory-benchmark).

## Setup

```bash
# Clone AMB next to tensory/
cd ~/Work
git clone https://github.com/vectorize-io/agent-memory-benchmark
cd agent-memory-benchmark
uv sync
```

Tensory is installed as an editable dependency (`tensory = { path = "../tensory", editable = true }`).

## Running

```bash
# Full LoCoMo eval (10 conversations, 1540 queries)
uv run omb run --dataset locomo --split locomo10 --memory tensory --llm anthropic

# Single conversation (e.g. conv-26)
uv run omb run --dataset locomo --split locomo10 --memory tensory --llm anthropic -c conv-26

# Skip ingestion (reuse existing DB, iterate on answer/search)
uv run omb run --dataset locomo --split locomo10 --memory tensory --llm anthropic --skip-ingestion

# Only re-run failed queries
uv run omb run --dataset locomo --split locomo10 --memory tensory --llm anthropic --only-failed

# Custom run name for A/B comparison
uv run omb run --dataset locomo --split locomo10 --memory tensory --llm anthropic -n tensory-experiment-v2
```

## Results

Results are saved to `agent-memory-benchmark/outputs/locomo/<run-name>/rag/locomo10.json`.

See [docs/benchmark-results.md](../docs/benchmark-results.md) for latest numbers.

## Extraction Quality

`eval_extraction.py` (gitignored) tests Tensory's extraction prompts against hand-labeled cases.
Used by Weco for automated prompt optimization.
