"""LoCoMo benchmark runner — full pipeline.

Usage:
    uv run python -m benchmarks.locomo
    uv run python -m benchmarks.locomo --conversation 0 --limit 10

Environment variables:
    ANTHROPIC_API_KEY    — Anthropic API key (or proxy key)
    ANTHROPIC_BASE_URL   — Proxy URL (optional)
    OPENAI_API_KEY       — OpenAI API key (for embeddings)

Pipeline:
    1. Load LoCoMo conversation
    2. Create Tensory store with Haiku (extraction) + OpenAI (embeddings)
    3. Ingest all sessions
    4. Answer all QA questions with Sonnet
    5. Print F1 scores per category
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, cast

from benchmarks.locomo.answer import answer_questions
from benchmarks.locomo.data import load_locomo
from benchmarks.locomo.ingest import ingest_conversation
from examples.llm_adapters import anthropic_llm
from tensory.embedder import OpenAIEmbedder
from tensory.extract import LLMProtocol
from tensory.store import Tensory

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("benchmarks/locomo/results")


async def run_benchmark(
    *,
    conversation_idx: int = 0,
    qa_limit: int | None = None,
    db_path: str = "benchmarks/locomo/.cache/tensory_locomo.db",
    search_limit: int = 10,
) -> dict[str, Any]:
    """Run the full LoCoMo benchmark pipeline.

    Args:
        conversation_idx: Which conversation to use (0-9).
        qa_limit: Limit number of QA questions (None = all).
        db_path: SQLite database path for Tensory.
        search_limit: Claims per search query.

    Returns:
        Summary dict with scores and stats.
    """
    import os

    # ── 1. Load data ──────────────────────────────────────────────────────
    logger.info("Loading LoCoMo conversation %d...", conversation_idx)
    conversation = await load_locomo(conversation_idx)
    logger.info(
        "Loaded: %s (%d sessions, %d QA items)",
        conversation.sample_id,
        len(conversation.sessions),
        len(conversation.qa_items),
    )

    # ── 2. Setup Tensory ──────────────────────────────────────────────────
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # Haiku for extraction (cheap)
    extraction_llm = cast(LLMProtocol, anthropic_llm(
        model="claude-haiku-4-5-20251001",
        api_key=api_key,
        base_url=base_url,
    ))

    # Sonnet for answering (quality)
    answer_llm = cast(LLMProtocol, anthropic_llm(
        model="claude-sonnet-4-20250514",
        api_key=api_key,
        base_url=base_url,
    ))

    # OpenAI embeddings
    embedder = OpenAIEmbedder(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model="text-embedding-3-small",
        dim=1536,
    )

    # Clean DB for fresh run
    db = Path(db_path)
    if db.exists():
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)

    store = await Tensory.create(
        db_path,
        llm=extraction_llm,
        embedder=embedder,
    )

    # ── 3. Create context ─────────────────────────────────────────────────
    context = await store.create_context(
        goal="Remember everything from this conversation for answering questions later",
        domain="personal-conversation",
        description=(
            f"Conversation between {conversation.speaker_a} and "
            f"{conversation.speaker_b}. Track all facts, events, experiences, "
            "opinions, and temporal details."
        ),
    )

    # ── 4. Ingest ─────────────────────────────────────────────────────────
    logger.info("Ingesting %d sessions...", len(conversation.sessions))
    t0 = time.time()
    ingest_stats = await ingest_conversation(store, conversation, context=context)
    ingest_time = time.time() - t0

    logger.info(
        "Ingestion done in %.1fs: %d sessions, %d claims, %d entities",
        ingest_time,
        ingest_stats.sessions_ingested,
        ingest_stats.total_claims,
        ingest_stats.total_entities,
    )

    if ingest_stats.errors:
        logger.warning("Ingestion errors: %s", ingest_stats.errors)

    # ── 5. Answer QA ──────────────────────────────────────────────────────
    qa_items = conversation.qa_items
    if qa_limit:
        qa_items = qa_items[:qa_limit]

    logger.info("Answering %d questions with Sonnet...", len(qa_items))
    t0 = time.time()
    benchmark_result = await answer_questions(
        store,
        qa_items,
        answer_llm,
        context=context,
        search_limit=search_limit,
    )
    answer_time = time.time() - t0

    # ── 6. Results ────────────────────────────────────────────────────────
    summary = benchmark_result.summary()

    # Store stats
    store_stats = await store.stats()
    await store.close()

    full_result = {
        "conversation": conversation.sample_id,
        "scores": summary,
        "ingest": {
            "sessions": ingest_stats.sessions_ingested,
            "claims": ingest_stats.total_claims,
            "entities": ingest_stats.total_entities,
            "collisions": ingest_stats.total_collisions,
            "errors": ingest_stats.errors,
            "time_sec": round(ingest_time, 1),
        },
        "answer": {
            "questions": len(qa_items),
            "time_sec": round(answer_time, 1),
        },
        "store_stats": store_stats,
    }

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    result_file = RESULTS_DIR / f"{conversation.sample_id}.json"
    result_file.write_text(json.dumps(full_result, indent=2, default=str))
    logger.info("Results saved to %s", result_file)

    return full_result


def _print_results(results: dict[str, Any]) -> None:
    """Pretty-print benchmark results."""
    print("\n" + "=" * 60)
    print(f"  LoCoMo Benchmark: {results['conversation']}")
    print("=" * 60)

    scores = results["scores"]
    print(f"\n{'Category':<15} {'Count':>6} {'F1':>8}")
    print("-" * 32)

    for name in ["single-hop", "multi-hop", "temporal", "open-domain", "adversarial"]:
        if name in scores:
            s = scores[name]
            print(f"{name:<15} {s['count']:>6} {s['f1']:>8.4f}")

    if "overall" in scores:
        print("-" * 32)
        o = scores["overall"]
        print(f"{'OVERALL':<15} {o['count']:>6} {o['f1']:>8.4f}")

    ingest = results["ingest"]
    answer = results["answer"]
    print(f"\nIngestion: {ingest['claims']} claims from {ingest['sessions']} sessions "
          f"in {ingest['time_sec']}s")
    print(f"Answering: {answer['questions']} questions in {answer['time_sec']}s")

    if ingest["errors"]:
        print(f"\nErrors: {len(ingest['errors'])}")
        for e in ingest["errors"]:
            print(f"  - {e}")

    print("=" * 60)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Run LoCoMo benchmark on Tensory")
    parser.add_argument(
        "--conversation", type=int, default=0, help="Conversation index (0-9)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Limit QA questions (for debugging)"
    )
    parser.add_argument(
        "--search-limit", type=int, default=10, help="Claims per search query"
    )
    parser.add_argument(
        "--db", type=str, default="benchmarks/locomo/.cache/tensory_locomo.db",
        help="SQLite database path",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose logging"
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    results = asyncio.run(
        run_benchmark(
            conversation_idx=args.conversation,
            qa_limit=args.limit,
            db_path=args.db,
            search_limit=args.search_limit,
        )
    )

    _print_results(results)


if __name__ == "__main__":
    main()
