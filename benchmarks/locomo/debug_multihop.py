"""Debug multi-hop search failures — compare routed vs unfiltered search."""

import asyncio
import os
from typing import cast

from benchmarks.locomo.data import load_locomo
from benchmarks.locomo.run_categories import select_qa_by_category
from examples.llm_adapters import anthropic_llm
from tensory.embedder import OpenAIEmbedder
from tensory.extract import LLMProtocol
from tensory.routing import classify_query
from tensory.store import Tensory


async def main() -> None:
    conv = await load_locomo(2)
    selected = select_qa_by_category(conv.qa_items, per_category=5, seed=42)

    store = await Tensory.create(
        "benchmarks/locomo/.cache/tensory_cat_conv2.db",
        llm=cast(
            LLMProtocol,
            anthropic_llm(
                model="claude-haiku-4-5-20251001",
                api_key=os.environ.get("ANTHROPIC_API_KEY"),
                base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            ),
        ),
        embedder=OpenAIEmbedder(
            api_key=os.environ.get("OPENAI_API_KEY"),
            model="text-embedding-3-small",
            dim=1536,
        ),
    )

    contexts = await store._db.get_contexts()
    ctx = contexts[0] if contexts else None

    # Check memory type distribution
    stats = await store.stats()
    print("=== Memory Type Distribution ===")
    print(stats.get("claims_by_memory_type", {}))
    print()

    for qa in selected:
        if qa.category != 2:
            continue

        mt = classify_query(qa.question)

        # Routed search (with memory_type filter)
        res_routed = await store.search(
            qa.question, context=ctx, limit=10, memory_type=mt
        )

        # Unfiltered search (no memory_type filter)
        res_none = await store.search(
            qa.question, context=ctx, limit=10, memory_type=None
        )

        print(f"Q: {qa.question}")
        print(f"Gold: {qa.answer}")
        print(f"Routed to: {mt} -> {len(res_routed)} results")
        print(f"No filter:  None -> {len(res_none)} results")

        if res_none:
            for j, r in enumerate(res_none[:3]):
                temporal = f" [when: {r.claim.temporal}]" if r.claim.temporal else ""
                print(f"  {j+1}. [score={r.score:.3f}]{temporal} {r.claim.text[:120]}")
        print("---")

    await store.close()


asyncio.run(main())
