"""Пример MCP-сервера для tensory.

Это рабочий прототип — показывает как модель взаимодействует с tensory
через MCP tools. Для production нужен Phase 5+++ (отдельный пакет).

Запуск:
    pip install mcp
    python examples/mcp_server_example.py

Модель (Claude/другая) видит эти tools и вызывает их сама.
LLM extraction происходит НА СТОРОНЕ МОДЕЛИ, не в tensory.

Ключевой принцип:
    - tensory_remember: модель САМА извлекает claims из разговора
    - tensory_add_raw: tensory вызывает LLM (нужен ANTHROPIC_API_KEY)
    Оба пути работают, но remember — бесплатный (модель уже оплачена).
"""

from __future__ import annotations

# ── Это то, как tools будут описаны для модели ────────────────────────────
#
# Модель видит JSON Schema каждого tool и решает сама когда вызвать.
# Ниже — описания tools с подробными description (это ключ к качеству).

TOOLS_SCHEMA = [
    {
        "name": "tensory_remember",
        "description": """Store facts in long-term memory. Call this when you encounter
important information in the conversation that should be remembered.

YOU are the extractor — break information into atomic claims before calling.

Rules:
- Each claim = ONE verifiable statement (not a paragraph)
- Always identify entities (people, companies, protocols, tokens)
- Set type: "fact" (verifiable), "experience" (event), "observation" (inference), "opinion" (judgment)
- Set confidence: how sure you are (0.0-1.0)

Examples of good claims:
  ✓ "EigenLayer team grew to 60 engineers" (entities: ["EigenLayer"])
  ✓ "Google partnered with EigenLayer for restaking" (entities: ["Google", "EigenLayer"])
  ✗ "There was some news about EigenLayer" (too vague, no facts)

When to call:
- User shares a fact worth remembering
- You learn something new about an entity
- Conversation reveals a relationship between entities
- Something contradicts what you previously stored""",
        "parameters": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "description": "List of atomic claims to store",
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
                                "description": "Named entities mentioned (people, orgs, protocols)",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["fact", "experience", "observation", "opinion"],
                                "description": "Claim type",
                            },
                            "confidence": {
                                "type": "number",
                                "description": "How confident you are (0.0-1.0)",
                            },
                        },
                        "required": ["text"],
                    },
                },
                "source": {
                    "type": "string",
                    "description": "Where this info came from (e.g. 'user:conversation', 'web:url')",
                },
            },
            "required": ["claims"],
        },
    },
    {
        "name": "tensory_search",
        "description": """Search long-term memory for relevant facts.

Call this when:
- User asks about something you might have stored before
- You need context about an entity or topic
- You want to check if new info contradicts stored facts

Returns claims sorted by relevance with scores.""",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (entity name, topic, or question)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 10)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "tensory_timeline",
        "description": """Show how facts about an entity changed over time.

Call this when:
- User asks "what do we know about X?"
- You want to trace how information evolved
- Checking for contradictions in entity history""",
        "parameters": {
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Entity name to trace",
                },
            },
            "required": ["entity"],
        },
    },
]


# ── Пример как выглядит РЕАЛЬНЫЙ разговор ─────────────────────────────────

EXAMPLE_CONVERSATION = """
=== Как модель использует tensory MCP tools ===

User: "Я узнал что EigenLayer вырос до 60 человек и они заключили партнёрство
       с Google Cloud для рестейкинга"

Claude думает: "Тут два факта + одна relation. Надо запомнить."

Claude вызывает tool:
  tensory_remember(
    claims=[
      {
        "text": "EigenLayer team grew to 60 engineers",
        "entities": ["EigenLayer"],
        "type": "fact",
        "confidence": 0.85
      },
      {
        "text": "Google Cloud partnered with EigenLayer for restaking infrastructure",
        "entities": ["Google Cloud", "EigenLayer"],
        "type": "fact",
        "confidence": 0.9
      }
    ],
    source="user:conversation"
  )

tensory ответ:
  {
    "stored": 2,
    "collisions": [
      {"type": "contradiction", "old": "EigenLayer has 50 members", "score": 0.8}
    ],
    "new_entities": ["Google Cloud"]
  }

Claude отвечает: "Запомнил! Кстати, раньше у нас было что в EigenLayer 50 человек —
                  теперь обновлено до 60. Партнёрство с Google Cloud тоже сохранил."

---

User: "Что мы знаем про EigenLayer?"

Claude думает: "Нужно поискать в памяти."

Claude вызывает tool:
  tensory_search(query="EigenLayer", limit=10)

tensory ответ:
  [
    {"text": "EigenLayer team grew to 60 engineers", "score": 0.95, "salience": 0.9},
    {"text": "Google Cloud partnered with EigenLayer...", "score": 0.91, "salience": 0.85},
    {"text": "EigenLayer has 50 members", "score": 0.88, "salience": 0.1, "superseded": true}
  ]

Claude отвечает: "Вот что я помню про EigenLayer:
                  - Команда выросла до 60 инженеров (раньше было 50)
                  - Партнёрство с Google Cloud для рестейкинга"
"""


# ── Рабочий MCP handler (для fastmcp или mcp SDK) ────────────────────────

async def handle_tensory_remember(
    store: object,  # Tensory instance
    claims: list[dict[str, object]],
    source: str = "mcp:conversation",
) -> dict[str, object]:
    """Handler для tensory_remember tool.

    Модель передаёт готовые claims → tensory хранит, проверяет дубли,
    находит коллизии, создаёт waypoints. БЕЗ LLM вызова.
    """
    from tensory import Claim, Tensory

    assert isinstance(store, Tensory)

    parsed: list[Claim] = []
    for c in claims:
        parsed.append(Claim(
            text=str(c.get("text", "")),
            entities=[str(e) for e in c.get("entities", []) or []],  # type: ignore[union-attr]
            type=str(c.get("type", "fact")),  # type: ignore[arg-type]
            confidence=float(c.get("confidence", 0.9) or 0.9),  # type: ignore[arg-type]
        ))

    result = await store.add_claims(parsed)

    return {
        "stored": len(result.claims),
        "skipped_duplicates": len(parsed) - len(result.claims),
        "collisions": [
            {
                "type": col.type,
                "old_claim": col.claim_b.text,
                "score": col.score,
                "shared_entities": col.shared_entities,
            }
            for col in result.collisions
        ],
        "new_entities": result.new_entities,
    }


async def handle_tensory_search(
    store: object,
    query: str,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Handler для tensory_search tool."""
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
        }
        for r in results
    ]


async def handle_tensory_timeline(
    store: object,
    entity: str,
) -> list[dict[str, object]]:
    """Handler для tensory_timeline tool."""
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


# ── Demo: симулируем MCP-разговор ─────────────────────────────────────────

async def demo_mcp_flow() -> None:
    """Симулирует как модель будет использовать MCP tools."""
    from tensory import Tensory

    print(EXAMPLE_CONVERSATION)

    store = await Tensory.create(":memory:")

    print("=== Симуляция MCP flow ===\n")

    # 1. Модель "запоминает" факты
    print("→ tensory_remember(claims=[...EigenLayer 50 members...])")
    r1 = await handle_tensory_remember(store, [
        {"text": "EigenLayer has 50 team members", "entities": ["EigenLayer"], "type": "fact"},
    ])
    print(f"  ← stored={r1['stored']}, collisions={len(r1['collisions'])}\n")

    # 2. Модель "запоминает" обновлённую информацию
    print("→ tensory_remember(claims=[...EigenLayer 60 members + Google...])")
    r2 = await handle_tensory_remember(store, [
        {"text": "EigenLayer team grew to 60 engineers", "entities": ["EigenLayer"], "type": "fact", "confidence": 0.9},
        {"text": "Google Cloud partnered with EigenLayer for restaking", "entities": ["Google Cloud", "EigenLayer"], "type": "fact"},
    ])
    print(f"  ← stored={r2['stored']}, collisions={len(r2['collisions'])}")
    for col in r2["collisions"]:  # type: ignore[union-attr]
        print(f"     ⚡ {col['type']}: '{col['old_claim']}'")  # type: ignore[index]
    print()

    # 3. Модель "ищет" в памяти
    print("→ tensory_search(query='EigenLayer')")
    results = await handle_tensory_search(store, "EigenLayer")
    for r in results:
        sup = " [SUPERSEDED]" if r["superseded"] else ""
        print(f"  ← [{r['score']}] {r['text']}{sup}")
    print()

    # 4. Timeline
    print("→ tensory_timeline(entity='EigenLayer')")
    timeline = await handle_tensory_timeline(store, "EigenLayer")
    for t in timeline:
        sup = " [SUPERSEDED]" if t["superseded"] else ""
        print(f"  ← {t['text']}{sup}")

    await store.close()
    print("\n✅ MCP flow demo complete!")


if __name__ == "__main__":
    import asyncio
    asyncio.run(demo_mcp_flow())
