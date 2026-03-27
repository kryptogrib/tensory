"""MCP-сервер для tensory.

Ключевая проблема: если модель сама решает как извлекать claims —
результат каждый раз разный. Решение: extraction prompt ВСТРОЕН
в tool description. Модель видит точные инструкции и формат.

Два подхода:

1. tensory_add (РЕКОМЕНДУЕМЫЙ)
   Tool description содержит extraction prompt.
   Модель видит инструкцию → извлекает по формату → передаёт structured claims.
   Prompt одинаковый каждый раз = детерминированный результат.
   Стоимость: $0 extra (модель уже оплачена).

2. tensory_add_raw
   Принимает сырой текст. tensory сам вызывает LLM через API.
   Идентичен store.add() из pipeline-режима.
   Стоимость: дополнительный API вызов.

Запуск:
    python examples/mcp_server_example.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any


# ══════════════════════════════════════════════════════════════════════════
# EXTRACTION PROMPT — встроен в tool description
# ══════════════════════════════════════════════════════════════════════════
#
# Это ТОТ ЖЕ промпт что в tensory/extract.py, но в формате tool description.
# Модель читает его каждый раз при вызове tool → результат предсказуемый.

TENSORY_ADD_TOOL = {
    "name": "tensory_add",
    "description": """Store information in long-term memory.

BEFORE calling this tool, you MUST extract claims from the text using these rules:

EXTRACTION RULES:
1. Break text into ATOMIC claims (one fact per claim)
2. Each claim must be a single verifiable statement
3. Identify ALL named entities (people, companies, protocols, tokens, places)
4. Classify each claim:
   - "fact" — verifiable statement ("EigenLayer has 60 engineers")
   - "experience" — event that happened ("Protocol launched on March 1")
   - "observation" — inference ("This suggests growing adoption")
   - "opinion" — subjective judgment ("The team seems strong")
5. Rate confidence 0.0-1.0 (how reliable is the source?)
6. Extract temporal info if present ("Q1 2026", "March 2026", "yesterday")
7. Identify entity relationships (who did what to whom)

EXAMPLES:
  Text: "Google partnered with EigenLayer for cloud restaking. Team grew to 60."

  claims: [
    {"text": "Google partnered with EigenLayer for cloud restaking infrastructure",
     "entities": ["Google", "EigenLayer"], "type": "fact", "confidence": 0.9,
     "temporal": "2026"},
    {"text": "EigenLayer team grew to 60 engineers",
     "entities": ["EigenLayer"], "type": "fact", "confidence": 0.85,
     "temporal": "2026"}
  ]
  relations: [
    {"from_entity": "Google", "to_entity": "EigenLayer",
     "rel_type": "PARTNERED_WITH", "fact": "Cloud restaking infrastructure partnership"}
  ]

BAD examples (DO NOT do this):
  ✗ "There was some news about EigenLayer" — too vague
  ✗ "Google and EigenLayer did stuff" — no specific fact
  ✗ Entire paragraph as one claim — must be atomic""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "description": "Atomic claims extracted from text (see rules above)",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "One atomic verifiable statement",
                        },
                        "entities": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Named entities: people, companies, protocols, tokens",
                        },
                        "type": {
                            "type": "string",
                            "enum": ["fact", "experience", "observation", "opinion"],
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "Source reliability (0.0-1.0)",
                        },
                        "temporal": {
                            "type": "string",
                            "description": "When this happened (null if unknown)",
                        },
                    },
                    "required": ["text", "entities", "type", "confidence"],
                },
            },
            "relations": {
                "type": "array",
                "description": "Entity relationships extracted from text",
                "items": {
                    "type": "object",
                    "properties": {
                        "from_entity": {"type": "string"},
                        "to_entity": {"type": "string"},
                        "rel_type": {
                            "type": "string",
                            "description": "PARTNERED_WITH, INVESTED_IN, DEPARTED_FROM, BUILT_ON, ACQUIRED, etc.",
                        },
                        "fact": {
                            "type": "string",
                            "description": "Human-readable description",
                        },
                    },
                    "required": ["from_entity", "to_entity", "rel_type"],
                },
            },
            "source": {
                "type": "string",
                "description": "Source: 'user:conversation', 'web:url', 'file:path'",
            },
            "context_goal": {
                "type": "string",
                "description": "Research goal to filter relevance (optional)",
            },
        },
        "required": ["claims"],
    },
}

TENSORY_ADD_RAW_TOOL = {
    "name": "tensory_add_raw",
    "description": """Store raw text — tensory will extract claims automatically via LLM.

Use this when you want tensory's built-in extraction (same prompt every time).
Requires ANTHROPIC_API_KEY or other LLM configured on the server.

Prefer tensory_add (structured) over this — it's free and equally consistent.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Raw text to extract claims from",
            },
            "source": {
                "type": "string",
                "description": "Source identifier",
            },
        },
        "required": ["text"],
    },
}

TENSORY_SEARCH_TOOL = {
    "name": "tensory_search",
    "description": """Search long-term memory for relevant facts.
Returns claims sorted by relevance with collision/supersession info.""",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results (default 10)"},
        },
        "required": ["query"],
    },
}

TENSORY_TIMELINE_TOOL = {
    "name": "tensory_timeline",
    "description": "Show how facts about an entity changed over time.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "Entity name"},
        },
        "required": ["entity"],
    },
}


# ══════════════════════════════════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════════════════════════════════


async def handle_tensory_add(
    store: Any,
    claims: list[dict[str, Any]],
    relations: list[dict[str, Any]] | None = None,
    source: str = "mcp:conversation",
    context_goal: str | None = None,
) -> dict[str, Any]:
    """Handler для tensory_add — structured claims от модели.

    Extraction prompt встроен в tool description → модель каждый раз
    видит одинаковые инструкции → результат предсказуемый.
    """
    from tensory import Claim, Tensory
    from tensory.models import EntityRelation

    assert isinstance(store, Tensory)

    # Парсим claims
    parsed_claims: list[Claim] = []
    for c in claims:
        parsed_claims.append(
            Claim(
                text=str(c.get("text", "")),
                entities=[str(e) for e in (c.get("entities") or [])],
                type=str(c.get("type", "fact")),  # type: ignore[arg-type]
                confidence=float(c.get("confidence", 0.9) or 0.9),
                temporal=str(c["temporal"]) if c.get("temporal") else None,
            )
        )

    # Парсим relations и добавляем в граф
    if relations:
        for rel in relations:
            from_id = await store._graph.add_entity(str(rel["from_entity"]))
            to_id = await store._graph.add_entity(str(rel["to_entity"]))
            await store._graph.add_edge(
                from_id,
                to_id,
                str(rel.get("rel_type", "RELATED_TO")),
                {"fact": str(rel.get("fact", ""))},
            )

    # Контекст (если указан)
    context_id: str | None = None
    if context_goal:
        ctx = await store.create_context(goal=context_goal)
        context_id = ctx.id

    # Основной pipeline: dedup → embed → surprise → store → collisions → waypoints
    result = await store.add_claims(parsed_claims, context_id=context_id)

    return {
        "stored": len(result.claims),
        "skipped_duplicates": len(parsed_claims) - len(result.claims),
        "collisions": [
            {
                "type": col.type,
                "existing_claim": col.claim_b.text,
                "score": col.score,
                "shared_entities": col.shared_entities,
            }
            for col in result.collisions
        ],
        "new_entities": result.new_entities,
    }


async def handle_tensory_add_raw(
    store: Any,
    text: str,
    source: str = "mcp:raw",
) -> dict[str, Any]:
    """Handler для tensory_add_raw — сырой текст, extraction внутри tensory."""
    from tensory import Tensory

    assert isinstance(store, Tensory)

    result = await store.add(text, source=source)
    return {
        "stored": len(result.claims),
        "claims": [c.text for c in result.claims],
        "relations": len(result.relations),
        "collisions": len(result.collisions),
    }


async def handle_tensory_search(
    store: Any,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Handler для tensory_search."""
    from tensory import Tensory

    assert isinstance(store, Tensory)

    results = await store.search(query, limit=limit)
    return [
        {
            "text": r.claim.text,
            "score": round(r.score, 3),
            "entities": r.claim.entities,
            "type": r.claim.type.value,
            "salience": round(r.claim.salience, 3),
            "superseded": r.claim.superseded_at is not None,
            "confidence": r.claim.confidence,
        }
        for r in results
    ]


async def handle_tensory_timeline(
    store: Any,
    entity: str,
) -> list[dict[str, Any]]:
    """Handler для tensory_timeline."""
    from tensory import Tensory

    assert isinstance(store, Tensory)

    claims = await store.timeline(entity)
    return [
        {
            "text": c.text,
            "type": c.type.value,
            "salience": round(c.salience, 3),
            "superseded": c.superseded_at is not None,
            "created_at": c.created_at.isoformat(),
        }
        for c in claims
    ]


# ══════════════════════════════════════════════════════════════════════════
# DEMO — симулируем как модель вызывает tools
# ══════════════════════════════════════════════════════════════════════════

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def demo() -> None:
    from tensory import Tensory

    store = await Tensory.create(":memory:")

    print(f"\n{BOLD}{CYAN}══ MCP Flow: extraction prompt ВСТРОЕН в tool ══{RESET}\n")
    print(f"""{DIM}Модель видит tool description с extraction rules:
  - Break into atomic claims
  - Identify entities
  - Classify type + confidence
  - Extract temporal info
  - Identify relations

Это ТОТ ЖЕ промпт что в tensory/extract.py.
Модель видит его каждый раз → результат предсказуемый.{RESET}
""")

    # ── Шаг 1: модель видит текст и вызывает tensory_add
    print(f"{BOLD}Шаг 1:{RESET} User говорит: 'Google партнёрится с EigenLayer, команда 60 человек'")
    print(f"{DIM}Модель читает extraction rules из tool description...{RESET}")
    print(f"{YELLOW}→ tensory_add(claims=[...], relations=[...]){RESET}\n")

    r1 = await handle_tensory_add(
        store,
        claims=[
            {
                "text": "Google partnered with EigenLayer for cloud restaking",
                "entities": ["Google", "EigenLayer"],
                "type": "fact",
                "confidence": 0.9,
                "temporal": "2026",
            },
            {
                "text": "EigenLayer team grew to 60 engineers",
                "entities": ["EigenLayer"],
                "type": "fact",
                "confidence": 0.85,
                "temporal": "Q1 2026",
            },
        ],
        relations=[
            {
                "from_entity": "Google",
                "to_entity": "EigenLayer",
                "rel_type": "PARTNERED_WITH",
                "fact": "Cloud restaking infrastructure partnership",
            }
        ],
    )
    print(f"  {GREEN}✓{RESET} stored={r1['stored']} collisions={len(r1['collisions'])}")
    print(f"  {GREEN}✓{RESET} new_entities={r1['new_entities']}\n")

    # ── Шаг 2: противоречащая информация
    print(f"{BOLD}Шаг 2:{RESET} User: 'Нет, в EigenLayer сейчас 45 человек, было сокращение'")
    print(f"{YELLOW}→ tensory_add(claims=[...]){RESET}\n")

    r2 = await handle_tensory_add(
        store,
        claims=[
            {
                "text": "EigenLayer reduced team to 45 engineers after layoffs",
                "entities": ["EigenLayer"],
                "type": "fact",
                "confidence": 0.8,
                "temporal": "March 2026",
            },
        ],
    )
    print(f"  {GREEN}✓{RESET} stored={r2['stored']} collisions={len(r2['collisions'])}")
    for col in r2["collisions"]:
        print(f"  {YELLOW}⚡ {col['type']}{RESET}: '{col['existing_claim'][:60]}'")
    print()

    # ── Шаг 3: search
    print(f"{BOLD}Шаг 3:{RESET} User: 'Что мы знаем про EigenLayer?'")
    print(f"{YELLOW}→ tensory_search(query='EigenLayer'){RESET}\n")

    results = await handle_tensory_search(store, "EigenLayer")
    for r in results:
        sup = f" {DIM}[SUPERSEDED]{RESET}" if r["superseded"] else ""
        print(f"  [{r['score']}] {r['text']}{sup}")
        print(f"  {DIM}  confidence={r['confidence']} salience={r['salience']} entities={r['entities']}{RESET}")
    print()

    # ── Шаг 4: timeline
    print(f"{BOLD}Шаг 4:{RESET} User: 'Покажи историю изменений'")
    print(f"{YELLOW}→ tensory_timeline(entity='EigenLayer'){RESET}\n")

    timeline = await handle_tensory_timeline(store, "EigenLayer")
    for i, t in enumerate(timeline, 1):
        sup = f" {DIM}[SUPERSEDED]{RESET}" if t["superseded"] else ""
        print(f"  {i}. {t['text']}{sup}")
    print()

    await store.close()

    # ── Сравнение подходов
    print(f"{BOLD}{CYAN}══ Сравнение: почему prompt в tool description работает ══{RESET}\n")
    print(f"""
{BOLD}Проблема:{RESET}
  Без фиксированного промпта модель каждый раз извлекает по-разному:
    Вызов 1: "EigenLayer has 60 people"     → entities: ["EigenLayer"]
    Вызов 2: "Team of sixty at EigenLayer"  → entities: ["Team", "EigenLayer"]
    Вызов 3: "60 engineers"                 → entities: []  ← потеряли entity!

{BOLD}Решение:{RESET}
  Extraction rules встроены в tool description (inputSchema + description).
  Модель видит их КАЖДЫЙ раз при вызове tool.

    Tool description:
      "Identify ALL named entities (people, companies, protocols, tokens)"
      "Each claim must be a single verifiable statement"
      "Classify: fact | experience | observation | opinion"

    → Модель следует правилам → результат стабильный.

{BOLD}Это аналог store.add():{RESET}
    store.add("text")  →  EXTRACT_PROMPT (фиксированный) → LLM → claims
    tensory_add(...)   →  Tool description (фиксированный) → модель → claims
                          ↑ тот же промпт, но в другом месте

{BOLD}Два режима — одинаковый результат:{RESET}

    Pipeline (из кода):
      text → tensory/extract.py EXTRACT_PROMPT → API call → claims → store

    MCP (от модели):
      text → tool description (тот же prompt) → модель сама → claims → store

    Промпт один и тот же. Формат один и тот же.
    Разница: кто платит за LLM call.
""")


if __name__ == "__main__":
    asyncio.run(demo())
