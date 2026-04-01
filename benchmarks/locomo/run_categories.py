"""Run LoCoMo benchmark with category-filtered QA across multiple conversations.

Runs N conversations, picking 10 QA items per category from each.
This gives diverse dialogue coverage for each check type.

Usage:
    uv run python benchmarks/locomo/run_categories.py
    uv run python benchmarks/locomo/run_categories.py --conversations 0 2 5
    uv run python benchmarks/locomo/run_categories.py --per-category 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from benchmarks.locomo.answer import answer_questions
from benchmarks.locomo.data import CATEGORY_NAMES, Conversation, QAItem, load_locomo
from benchmarks.locomo.ingest import ingest_conversation
from benchmarks.locomo.score import BenchmarkResult
from examples.llm_adapters import anthropic_llm
from tensory.embedder import OpenAIEmbedder
from tensory.extract import LLMProtocol
from tensory.store import Tensory

logger = logging.getLogger(__name__)

RESULTS_DIR = Path("benchmarks/locomo/results")


def select_qa_by_category(
    qa_items: list[QAItem],
    per_category: int = 10,
    seed: int = 42,
) -> list[QAItem]:
    """Select up to `per_category` QA items from each category.

    Groups QA items by category, shuffles within each group,
    then takes up to `per_category` from each.

    Returns flattened list preserving category order (1→5).
    """
    by_cat: dict[int, list[QAItem]] = defaultdict(list)
    for qa in qa_items:
        by_cat[qa.category].append(qa)

    rng = random.Random(seed)
    selected: list[QAItem] = []

    for cat in sorted(by_cat.keys()):
        items = by_cat[cat]
        rng.shuffle(items)
        picked = items[:per_category]
        selected.extend(picked)
        cat_name = CATEGORY_NAMES.get(cat, f"cat-{cat}")
        logger.info(
            "  Category %d (%s): %d/%d available → picked %d",
            cat, cat_name, len(items), len(items), len(picked),
        )

    return selected


async def run_single_conversation(
    conversation_idx: int,
    *,
    per_category: int = 10,
    search_limit: int = 10,
    seed: int = 42,
) -> dict[str, Any]:
    """Run benchmark on one conversation with category-balanced QA."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    # ── Load data ─────────────────────────────────────────────────────────
    logger.info("Loading conversation %d...", conversation_idx)
    conversation = await load_locomo(conversation_idx)
    logger.info(
        "Loaded %s: %d sessions, %d QA items",
        conversation.sample_id,
        len(conversation.sessions),
        len(conversation.qa_items),
    )

    # ── Select QA items by category ───────────────────────────────────────
    qa_items = select_qa_by_category(
        conversation.qa_items,
        per_category=per_category,
        seed=seed,
    )
    logger.info("Selected %d QA items (%d per category)", len(qa_items), per_category)

    # ── Setup Tensory ─────────────────────────────────────────────────────
    extraction_llm = cast(LLMProtocol, anthropic_llm(
        model="claude-haiku-4-5-20251001",
        api_key=api_key,
        base_url=base_url,
    ))

    answer_llm = cast(LLMProtocol, anthropic_llm(
        model="claude-sonnet-4-20250514",
        api_key=api_key,
        base_url=base_url,
    ))

    embedder = OpenAIEmbedder(
        api_key=os.environ.get("OPENAI_API_KEY"),
        model="text-embedding-3-small",
        dim=1536,
    )

    db_path = f"benchmarks/locomo/.cache/tensory_cat_conv{conversation_idx}.db"
    db = Path(db_path)
    if db.exists():
        db.unlink()
    db.parent.mkdir(parents=True, exist_ok=True)

    store = await Tensory.create(db_path, llm=extraction_llm, embedder=embedder)

    # ── Create context ────────────────────────────────────────────────────
    context = await store.create_context(
        goal="Remember everything from this conversation for answering questions later",
        domain="personal-conversation",
        description=(
            f"Conversation between {conversation.speaker_a} and "
            f"{conversation.speaker_b}. Track all facts, events, experiences, "
            "opinions, and temporal details."
        ),
    )

    # ── Ingest ────────────────────────────────────────────────────────────
    logger.info("Ingesting %d sessions...", len(conversation.sessions))
    t0 = time.time()
    ingest_stats = await ingest_conversation(store, conversation, context=context)
    ingest_time = time.time() - t0
    logger.info(
        "Ingestion done in %.1fs: %d claims, %d entities",
        ingest_time,
        ingest_stats.total_claims,
        ingest_stats.total_entities,
    )

    # ── Answer QA ─────────────────────────────────────────────────────────
    logger.info("Answering %d questions...", len(qa_items))
    t0 = time.time()
    benchmark_result = await answer_questions(
        store, qa_items, answer_llm,
        context=context,
        search_limit=search_limit,
    )
    answer_time = time.time() - t0

    summary = benchmark_result.summary()
    store_stats = await store.stats()
    await store.close()

    return {
        "conversation": conversation.sample_id,
        "conversation_idx": conversation_idx,
        "scores": summary,
        "qa_selected": len(qa_items),
        "per_category": per_category,
        "ingest": {
            "sessions": ingest_stats.sessions_ingested,
            "claims": ingest_stats.total_claims,
            "entities": ingest_stats.total_entities,
            "time_sec": round(ingest_time, 1),
        },
        "answer": {
            "questions": len(qa_items),
            "time_sec": round(answer_time, 1),
        },
        "store_stats": store_stats,
    }


def _print_conversation_result(result: dict[str, Any]) -> None:
    """Print results for one conversation."""
    print(f"\n{'─' * 60}")
    print(f"  {result['conversation']} (conv {result['conversation_idx']})")
    print(f"{'─' * 60}")

    scores = result["scores"]
    print(f"  {'Category':<15} {'Count':>6} {'F1':>8}")
    print(f"  {'-' * 32}")

    for name in ["single-hop", "multi-hop", "temporal", "open-domain", "adversarial"]:
        if name in scores:
            s = scores[name]
            print(f"  {name:<15} {s['count']:>6} {s['f1']:>8.4f}")

    if "overall" in scores:
        print(f"  {'-' * 32}")
        o = scores["overall"]
        print(f"  {'OVERALL':<15} {o['count']:>6} {o['f1']:>8.4f}")

    ingest = result["ingest"]
    answer = result["answer"]
    print(f"  Ingest: {ingest['claims']} claims / {ingest['time_sec']}s")
    print(f"  Answer: {answer['questions']} questions / {answer['time_sec']}s")


def _print_aggregate(all_results: list[dict[str, Any]]) -> None:
    """Print aggregated scores across all conversations."""
    print("\n" + "=" * 60)
    print("  AGGREGATE RESULTS")
    print("=" * 60)

    # Aggregate by category
    cat_scores: dict[str, list[float]] = defaultdict(list)
    cat_counts: dict[str, int] = defaultdict(int)

    for result in all_results:
        for name, data in result["scores"].items():
            if name == "overall":
                continue
            cat_scores[name].extend([data["f1"]] * data["count"])
            cat_counts[name] += data["count"]

    print(f"\n{'Category':<15} {'Total Q':>8} {'Avg F1':>8}")
    print("-" * 34)

    all_f1: list[float] = []
    for name in ["single-hop", "multi-hop", "temporal", "open-domain", "adversarial"]:
        if name in cat_scores:
            scores = cat_scores[name]
            avg = sum(scores) / len(scores) if scores else 0
            print(f"{name:<15} {cat_counts[name]:>8} {avg:>8.4f}")
            all_f1.extend(scores)

    if all_f1:
        print("-" * 34)
        print(f"{'OVERALL':<15} {len(all_f1):>8} {sum(all_f1) / len(all_f1):>8.4f}")

    total_ingest = sum(r["ingest"]["time_sec"] for r in all_results)
    total_answer = sum(r["answer"]["time_sec"] for r in all_results)
    total_claims = sum(r["ingest"]["claims"] for r in all_results)
    print(f"\nTotal: {total_claims} claims ingested, "
          f"{total_ingest:.0f}s ingest + {total_answer:.0f}s answer = "
          f"{total_ingest + total_answer:.0f}s total")

    print("=" * 60)


async def main_async(
    conversations: list[int],
    per_category: int,
    search_limit: int,
) -> None:
    """Run benchmark across multiple conversations sequentially."""
    all_results: list[dict[str, Any]] = []

    for conv_idx in conversations:
        print(f"\n{'=' * 60}")
        print(f"  Starting conversation {conv_idx}...")
        print(f"{'=' * 60}")

        result = await run_single_conversation(
            conv_idx,
            per_category=per_category,
            search_limit=search_limit,
        )
        all_results.append(result)
        _print_conversation_result(result)

    # Save aggregate
    _print_aggregate(all_results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    convs_str = "_".join(str(c) for c in conversations)
    result_file = RESULTS_DIR / f"categories_{convs_str}_n{per_category}.json"
    result_file.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nResults saved to {result_file}")


def main() -> None:
    """CLI entry point."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser(
        description="Run LoCoMo benchmark with category-balanced QA"
    )
    parser.add_argument(
        "--conversations", type=int, nargs="+", default=[0, 2, 5],
        help="Conversation indices to run (default: 0 2 5)",
    )
    parser.add_argument(
        "--per-category", type=int, default=10,
        help="QA questions per category (default: 10)",
    )
    parser.add_argument(
        "--search-limit", type=int, default=10,
        help="Claims per search query (default: 10)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(main_async(
        conversations=args.conversations,
        per_category=args.per_category,
        search_limit=args.search_limit,
    ))


if __name__ == "__main__":
    main()
