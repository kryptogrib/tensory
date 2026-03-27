"""tensory integration demo — run this to see everything in action.

Usage:
    python examples/demo.py                    # без LLM (ручные claims)
    OPENAI_API_KEY=sk-... python examples/demo.py --llm   # с LLM extraction
"""

from __future__ import annotations

import asyncio
import os
import sys


# ── Цвета для вывода ──────────────────────────────────────────────────────

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


# ── LLM адаптеры ─────────────────────────────────────────────────────────


class FakeLLM:
    """Имитация LLM для тестирования без API ключа.

    Возвращает захардкоженный JSON — как будто LLM проанализировал текст.
    В production замени на OpenAI/Anthropic/Ollama.
    """

    async def __call__(self, prompt: str) -> str:
        import json

        # Простая эвристика: разные ответы для разных текстов
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
    """Создаёт LLM адаптер для OpenAI. Нужен OPENAI_API_KEY."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("  pip install tensory[openai]  — для OpenAI адаптера")
        sys.exit(1)

    client = AsyncOpenAI()

    async def openai_llm(prompt: str) -> str:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # дешёвый и быстрый
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return openai_llm


# ── Основной demo ────────────────────────────────────────────────────────


async def demo_without_llm() -> None:
    """Полная демо без LLM — добавляем claims вручную."""
    from tensory import Claim, ClaimType, Tensory

    section("1. Создаём store (in-memory)")
    store = await Tensory.create(":memory:")
    ok("Store создан (SQLite in-memory, FTS5, sqlite-vec)")

    # ── Контекст ──────────────────────────────────────────────────────
    section("2. Создаём research context")
    ctx = await store.create_context(
        goal="Track DeFi team movements and protocol partnerships",
        domain="crypto",
    )
    ok(f"Context: '{ctx.goal}'")
    ok(f"ID: {ctx.id[:12]}...")

    # ── Добавляем claims ──────────────────────────────────────────────
    section("3. Добавляем claims (ручной режим, без LLM)")
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

    # ── Поиск ─────────────────────────────────────────────────────────
    section("4. Hybrid search")
    results = await store.search("EigenLayer")
    ok(f"Найдено: {len(results)} результатов для 'EigenLayer'")
    for r in results:
        ok(f"[score={r.score:.3f}] {r.claim.text}")

    # ── Collision detection ───────────────────────────────────────────
    section("5. Collision detection — добавляем противоречие")
    info("Добавляем: 'EigenLayer has 65 team members' (конфликт с '50 members')")
    r2 = await store.add_claims([
        Claim(
            text="EigenLayer has 65 team members after hiring spree",
            entities=["EigenLayer"],
            type=ClaimType.FACT,
        ),
    ])
    if r2.collisions:
        ok(f"Обнаружено {len(r2.collisions)} коллизий!")
        for col in r2.collisions:
            print(f"    {YELLOW}⚡ {col.type}{RESET}: '{col.claim_b.text[:50]}...'")
            print(f"       score={col.score}  shared={col.shared_entities}")
    else:
        info("Коллизий не обнаружено (structural collision сработает если entities совпадают)")

    # ── Dedup ─────────────────────────────────────────────────────────
    section("6. Deduplication — повторный claim блокируется")
    r3 = await store.add_claims([
        Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
    ])
    if len(r3.claims) == 0:
        ok("Дубликат заблокирован! (MinHash/LSH dedup)")
    else:
        info("Claim добавлен (текст достаточно отличался)")

    # ── Timeline ──────────────────────────────────────────────────────
    section("7. Timeline — история entity")
    timeline = await store.timeline("EigenLayer")
    ok(f"Timeline для EigenLayer: {len(timeline)} claims")
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
    section("9. Consolidation (группировка в observations)")
    obs = await store.consolidate(days=30, min_cluster=2)
    if obs:
        ok(f"Создано {len(obs)} observation(s)")
        for o in obs:
            print(f"    📝 {o.text}")
    else:
        info("Не хватает claims с общими entities для кластеризации")

    await store.close()
    print(f"\n{GREEN}{BOLD}  ✅ Demo завершено успешно!{RESET}\n")


async def demo_with_llm(use_real_llm: bool = False) -> None:
    """Demo с LLM extraction — автоматическое извлечение claims из текста."""
    from tensory import Tensory

    llm = make_openai_llm() if use_real_llm else FakeLLM()
    llm_name = "OpenAI gpt-4o-mini" if use_real_llm else "FakeLLM (встроенный)"

    section(f"LLM EXTRACTION (через {llm_name})")

    store = await Tensory.create(":memory:", llm=llm)  # type: ignore[arg-type]

    # ── Контекст ──────────────────────────────────────────────────────
    ctx = await store.create_context(
        goal="Track DeFi team movements and protocol partnerships",
        domain="crypto",
    )

    # ── add() — текст → автоматическое извлечение ─────────────────────
    section("10. store.add() — raw text → claims (LLM extraction)")
    info("Текст: 'Google announced partnership with EigenLayer for cloud restaking...'")

    result = await store.add(
        "Google announced partnership with EigenLayer for cloud restaking. "
        "The EigenLayer team has expanded to 60 engineers this quarter.",
        source="reddit:r/defi",
        context=ctx,
    )

    ok(f"Episode сохранён: {result.episode_id[:12]}...")
    ok(f"Извлечено {len(result.claims)} claims:")
    for c in result.claims:
        print(f"    → [{c.type.value}] {c.text}")
        print(f"      entities={c.entities}  confidence={c.confidence}")

    if result.relations:
        ok(f"Извлечено {len(result.relations)} relations:")
        for rel in result.relations:
            print(f"    → {rel.from_entity} —[{rel.rel_type}]→ {rel.to_entity}")

    # ── reevaluate() — тот же текст, другой контекст ──────────────────
    section("11. store.reevaluate() — тот же текст, другая 'линза'")
    tech_ctx = await store.create_context(
        goal="Track Big Tech AI and cloud strategy",
        domain="tech",
    )
    info(f"Новый контекст: '{tech_ctx.goal}'")

    # Для FakeLLM: подменяем ответ для нового контекста
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
    ok(f"Re-extracted {len(reeval.claims)} claims через новый контекст:")
    for c in reeval.claims:
        print(f"    → [{c.type.value}] {c.text}")

    # ── Финальные stats ───────────────────────────────────────────────
    section("12. Финальная статистика")
    stats = await store.stats()
    ok(f"Episodes: {stats['counts']['episodes']}")
    ok(f"Claims: {stats['counts']['claims']}")
    ok(f"Entities: {stats['counts']['entities']}")
    ok(f"Relations: {stats['counts']['entity_relations']}")

    await store.close()
    print(f"\n{GREEN}{BOLD}  ✅ LLM Demo завершено!{RESET}\n")


async def main() -> None:
    use_real_llm = "--llm" in sys.argv

    if use_real_llm and not os.environ.get("OPENAI_API_KEY"):
        print(f"{YELLOW}⚠ OPENAI_API_KEY не установлен. Используй:{RESET}")
        print(f"  OPENAI_API_KEY=sk-... python examples/demo.py --llm")
        print(f"  Или без --llm для FakeLLM\n")
        sys.exit(1)

    # Часть 1: без LLM
    await demo_without_llm()

    # Часть 2: с LLM
    await demo_with_llm(use_real_llm=use_real_llm)


if __name__ == "__main__":
    asyncio.run(main())
