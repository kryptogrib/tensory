"""tensory integration demo — run this to see everything in action.

Usage:
    python examples/demo.py                    # without LLM (manual claims)
    OPENAI_API_KEY=sk-... python examples/demo.py --llm   # with LLM extraction
"""

from __future__ import annotations

import asyncio
import os
import sys


# ── Output colors ─────────────────────────────────────────────────────────

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def section(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'═' * 60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'═' * 60}{RESET}\n")


def ok(msg: str) -> None:
    print(f"  {GREEN}✓{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ── LLM adapters ─────────────────────────────────────────────────────────


class FakeLLM:
    """Fake LLM for testing without an API key.

    Returns hardcoded JSON — as if an LLM analyzed the text.
    In production, replace with OpenAI/Anthropic/Ollama.
    """

    async def __call__(self, prompt: str) -> str:
        import json

        # Simple heuristic: different responses for different texts
        if "EigenLayer" in prompt and "Google" in prompt:
            return json.dumps({
                "claims": [
                    {
                        "text": "Google partnered with EigenLayer for cloud restaking infrastructure",
                        "type": "fact",
                        "entities": ["Google", "EigenLayer"],
                        "temporal": "March 2026",
                        "confidence": 0.9,
                        "relevance": 0.95,
                    },
                    {
                        "text": "EigenLayer team expanded to 60 engineers",
                        "type": "fact",
                        "entities": ["EigenLayer"],
                        "temporal": "Q1 2026",
                        "confidence": 0.85,
                        "relevance": 0.7,
                    },
                ],
                "relations": [
                    {
                        "from": "Google",
                        "to": "EigenLayer",
                        "type": "PARTNERED_WITH",
                        "fact": "Google Cloud provides infrastructure for EigenLayer restaking",
                    }
                ],
            })
        elif "Lido" in prompt:
            return json.dumps({
                "claims": [
                    {
                        "text": "Lido protocol reached 10 million staked ETH milestone",
                        "type": "experience",
                        "entities": ["Lido", "ETH"],
                        "temporal": "February 2026",
                        "confidence": 0.95,
                        "relevance": 0.9,
                    },
                ],
                "relations": [],
            })
        else:
            return json.dumps({
                "claims": [
                    {
                        "text": prompt.split("TEXT:")[-1].strip()[:100],
                        "type": "fact",
                        "entities": [],
                        "confidence": 0.7,
                        "relevance": 0.5,
                    }
                ],
                "relations": [],
            })


def make_openai_llm() -> object:
    """Create an LLM adapter for OpenAI. Requires OPENAI_API_KEY."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("  pip install tensory[openai]  — for the OpenAI adapter")
        sys.exit(1)

    client = AsyncOpenAI()

    async def openai_llm(prompt: str) -> str:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # cheap and fast
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return openai_llm


# ── Main demo ────────────────────────────────────────────────────────────


async def demo_without_llm() -> None:
    """Full demo without LLM — adding claims manually."""
    from tensory import Claim, ClaimType, Tensory

    section("1. Create store (in-memory)")
    store = await Tensory.create(":memory:")
    ok("Store created (SQLite in-memory, FTS5, sqlite-vec)")

    # ── Context ───────────────────────────────────────────────────────
    section("2. Create research context")
    ctx = await store.create_context(
        goal="Track DeFi team movements and protocol partnerships",
        domain="crypto",
    )
    ok(f"Context: '{ctx.goal}'")
    ok(f"ID: {ctx.id[:12]}...")

    # ── Add claims ────────────────────────────────────────────────────
    section("3. Add claims (manual mode, no LLM)")
    r1 = await store.add_claims(
        [
            Claim(
                text="EigenLayer has 50 team members",
                entities=["EigenLayer"],
                type=ClaimType.FACT,
            ),
            Claim(
                text="Google partnered with EigenLayer for cloud restaking",
                entities=["Google", "EigenLayer"],
                type=ClaimType.FACT,
            ),
            Claim(
                text="BREAKING: critical vulnerability found in DeFi protocol",
                entities=["DeFi"],
                type=ClaimType.EXPERIENCE,
            ),
        ],
        context_id=ctx.id,
    )
    for c in r1.claims:
        sentiment = c.metadata.get("sentiment", "?")
        urgent = " 🚨 URGENT" if c.metadata.get("urgent") else ""
        ok(f"[{c.type.value}] {c.text}")
        info(f"  salience={c.salience:.2f}  sentiment={sentiment}{urgent}")

    # ── Search ────────────────────────────────────────────────────────
    section("4. Hybrid search")
    results = await store.search("EigenLayer")
    ok(f"Found: {len(results)} results for 'EigenLayer'")
    for r in results:
        ok(f"[score={r.score:.3f}] {r.claim.text}")

    # ── Collision detection ───────────────────────────────────────────
    section("5. Collision detection — adding a contradiction")
    info("Adding: 'EigenLayer has 65 team members' (conflicts with '50 members')")
    r2 = await store.add_claims([
        Claim(
            text="EigenLayer has 65 team members after hiring spree",
            entities=["EigenLayer"],
            type=ClaimType.FACT,
        ),
    ])
    if r2.collisions:
        ok(f"Detected {len(r2.collisions)} collisions!")
        for col in r2.collisions:
            print(f"    {YELLOW}⚡ {col.type}{RESET}: '{col.claim_b.text[:50]}...'")
            print(f"       score={col.score}  shared={col.shared_entities}")
    else:
        info("No collisions detected (structural collision triggers when entities match)")

    # ── Dedup ─────────────────────────────────────────────────────────
    section("6. Deduplication — duplicate claim is blocked")
    r3 = await store.add_claims([
        Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
    ])
    if len(r3.claims) == 0:
        ok("Duplicate blocked! (MinHash/LSH dedup)")
    else:
        info("Claim added (text was sufficiently different)")

    # ── Timeline ──────────────────────────────────────────────────────
    section("7. Timeline — entity history")
    timeline = await store.timeline("EigenLayer")
    ok(f"Timeline for EigenLayer: {len(timeline)} claims")
    for i, c in enumerate(timeline):
        superseded = " [SUPERSEDED]" if c.superseded_at else ""
        print(f"    {i + 1}. {c.text}{superseded}")

    # ── Stats ─────────────────────────────────────────────────────────
    section("8. Stats")
    stats = await store.stats()
    ok(f"Claims: {stats['counts']['claims']}")
    ok(f"Entities: {stats['counts']['entities']}")
    ok(f"Waypoints: {stats['counts']['waypoints']}")
    ok(f"Avg salience: {stats['avg_salience']}")
    ok(f"By type: {stats['claims_by_type']}")

    # ── Consolidation ─────────────────────────────────────────────────
    section("9. Consolidation (grouping into observations)")
    obs = await store.consolidate(days=30, min_cluster=2)
    if obs:
        ok(f"Created {len(obs)} observation(s)")
        for o in obs:
            print(f"    📝 {o.text}")
    else:
        info("Not enough claims with shared entities for clustering")

    await store.close()
    print(f"\n{GREEN}{BOLD}  ✅ Demo completed successfully!{RESET}\n")


async def demo_with_llm(use_real_llm: bool = False) -> None:
    """Demo with LLM extraction — automatic claim extraction from text."""
    from tensory import Tensory

    llm = make_openai_llm() if use_real_llm else FakeLLM()
    llm_name = "OpenAI gpt-4o-mini" if use_real_llm else "FakeLLM (built-in)"

    section(f"LLM EXTRACTION (via {llm_name})")

    store = await Tensory.create(":memory:", llm=llm)  # type: ignore[arg-type]

    # ── Context ───────────────────────────────────────────────────────
    ctx = await store.create_context(
        goal="Track DeFi team movements and protocol partnerships",
        domain="crypto",
    )

    # ── add() — text → automatic extraction ────────────────────────────
    section("10. store.add() — raw text → claims (LLM extraction)")
    info("Text: 'Google announced partnership with EigenLayer for cloud restaking...'")

    result = await store.add(
        "Google announced partnership with EigenLayer for cloud restaking. "
        "The EigenLayer team has expanded to 60 engineers this quarter.",
        source="reddit:r/defi",
        context=ctx,
    )

    ok(f"Episode saved: {result.episode_id[:12]}...")
    ok(f"Extracted {len(result.claims)} claims:")
    for c in result.claims:
        print(f"    → [{c.type.value}] {c.text}")
        print(f"      entities={c.entities}  confidence={c.confidence}")

    if result.relations:
        ok(f"Extracted {len(result.relations)} relations:")
        for rel in result.relations:
            print(f"    → {rel.from_entity} —[{rel.rel_type}]→ {rel.to_entity}")

    # ── reevaluate() — same text, different context ────────────────────
    section("11. store.reevaluate() — same text, different 'lens'")
    tech_ctx = await store.create_context(
        goal="Track Big Tech AI and cloud strategy",
        domain="tech",
    )
    info(f"New context: '{tech_ctx.goal}'")

    # For FakeLLM: swap the response for the new context
    if isinstance(llm, FakeLLM):
        import json

        original_call = llm.__call__

        async def switched_call(prompt: str) -> str:
            if "Big Tech" in prompt or "cloud strategy" in prompt:
                return json.dumps({
                    "claims": [
                        {
                            "text": "Google is expanding cloud infrastructure partnerships in Web3",
                            "type": "observation",
                            "entities": ["Google"],
                            "confidence": 0.8,
                            "relevance": 0.9,
                        }
                    ],
                    "relations": [],
                })
            return await original_call(prompt)

        llm.__call__ = switched_call  # type: ignore[assignment]

    reeval = await store.reevaluate(result.episode_id, tech_ctx)
    ok(f"Re-extracted {len(reeval.claims)} claims via new context:")
    for c in reeval.claims:
        print(f"    → [{c.type.value}] {c.text}")

    # ── Final stats ───────────────────────────────────────────────────
    section("12. Final statistics")
    stats = await store.stats()
    ok(f"Episodes: {stats['counts']['episodes']}")
    ok(f"Claims: {stats['counts']['claims']}")
    ok(f"Entities: {stats['counts']['entities']}")
    ok(f"Relations: {stats['counts']['entity_relations']}")

    await store.close()
    print(f"\n{GREEN}{BOLD}  ✅ LLM Demo completed!{RESET}\n")


async def main() -> None:
    use_real_llm = "--llm" in sys.argv

    if use_real_llm and not os.environ.get("OPENAI_API_KEY"):
        print(f"{YELLOW}⚠ OPENAI_API_KEY not set. Usage:{RESET}")
        print(f"  OPENAI_API_KEY=sk-... python examples/demo.py --llm")
        print(f"  Or without --llm for FakeLLM\n")
        sys.exit(1)

    # Part 1: without LLM
    await demo_without_llm()

    # Part 2: with LLM
    await demo_with_llm(use_real_llm=use_real_llm)


if __name__ == "__main__":
    asyncio.run(main())
