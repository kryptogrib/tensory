"""MCP-сервер для tensory — production-ready дизайн.

Принцип: tool descriptions КОРОТКИЕ (экономия токенов),
extraction происходит НА СЕРВЕРЕ через тот же промпт что store.add().

Для extraction сервер использует LLM через прокси (CLIProxyAPI)
или напрямую через Anthropic/OpenAI API. Стоимость: haiku ~$0.001/запрос.

Архитектура:
    ┌──────────────────────────────────────────────┐
    │  Claude (вызывающая модель)                   │
    │  Видит только короткие tool descriptions      │
    │  (~30 токенов на tool, не 500)                │
    │                                               │
    │  → tensory_add(text="...", source="...")       │
    └──────────────┬───────────────────────────────┘
                   │ MCP call
                   ▼
    ┌──────────────────────────────────────────────┐
    │  tensory MCP server                           │
    │                                               │
    │  1. Получает сырой text                       │
    │  2. Вызывает store.add(text)                  │
    │     → extract.py EXTRACT_PROMPT (фиксирован)  │
    │     → LLM API через прокси (haiku, дёшево)    │
    │     → dedup → embed → collisions              │
    │  3. Возвращает результат                      │
    └──────────────────────────────────────────────┘

Env vars:
    ANTHROPIC_BASE_URL=http://localhost:8317   # CLIProxyAPI
    ANTHROPIC_API_KEY=signal-hunter-local      # прокси-ключ
    TENSORY_DB=memory.db                       # путь к БД

Запуск:
    python examples/mcp_server_example.py
"""

from __future__ import annotations

import asyncio
from typing import Any


# ══════════════════════════════════════════════════════════════════════════
# TOOL DESCRIPTIONS — короткие, ~30 токенов каждый
# ══════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "tensory_add",
        "description": "Store text in long-term memory. Server extracts claims automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to remember"},
                "source": {"type": "string", "description": "Where from (e.g. 'user', 'web:url')"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "tensory_remember",
        "description": "Store pre-extracted claims directly (skip server-side extraction).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "entities": {"type": "array", "items": {"type": "string"}},
                            "type": {"type": "string", "enum": ["fact", "experience", "observation", "opinion"]},
                        },
                        "required": ["text"],
                    },
                },
            },
            "required": ["claims"],
        },
    },
    {
        "name": "tensory_search",
        "description": "Search long-term memory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "tensory_timeline",
        "description": "Show how facts about an entity changed over time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string"},
            },
            "required": ["entity"],
        },
    },
    {
        "name": "tensory_stats",
        "description": "Get memory statistics.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


# ══════════════════════════════════════════════════════════════════════════
# HANDLERS — extraction на сервере, не в tool description
# ══════════════════════════════════════════════════════════════════════════


async def handle_tensory_add(
    store: Any,
    text: str,
    source: str = "mcp:conversation",
) -> dict[str, Any]:
    """Сырой текст → store.add() → extraction на сервере.

    Extraction prompt — тот же что в tensory/extract.py.
    LLM вызов через прокси (настроен при создании store).
    """
    from tensory import Tensory

    assert isinstance(store, Tensory)

    result = await store.add(text, source=source)
    return {
        "stored": len(result.claims),
        "claims": [
            {"text": c.text, "entities": c.entities, "type": c.type.value}
            for c in result.claims
        ],
        "collisions": [
            {"type": col.type, "existing": col.claim_b.text, "score": col.score}
            for col in result.collisions
        ],
        "new_entities": result.new_entities,
    }


async def handle_tensory_remember(
    store: Any,
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """Pre-extracted claims → store.add_claims() напрямую. Без LLM."""
    from tensory import Claim, Tensory

    assert isinstance(store, Tensory)

    parsed = [
        Claim(
            text=str(c.get("text", "")),
            entities=[str(e) for e in (c.get("entities") or [])],
            type=str(c.get("type", "fact")),  # type: ignore[arg-type]
        )
        for c in claims
    ]
    result = await store.add_claims(parsed)
    return {
        "stored": len(result.claims),
        "collisions": len(result.collisions),
    }


async def handle_tensory_search(
    store: Any,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
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
        }
        for r in results
    ]


async def handle_tensory_timeline(
    store: Any,
    entity: str,
) -> list[dict[str, Any]]:
    from tensory import Tensory

    assert isinstance(store, Tensory)

    claims = await store.timeline(entity)
    return [
        {
            "text": c.text,
            "type": c.type.value,
            "salience": round(c.salience, 3),
            "superseded": c.superseded_at is not None,
        }
        for c in claims
    ]


async def handle_tensory_stats(store: Any) -> dict[str, Any]:
    from tensory import Tensory

    assert isinstance(store, Tensory)
    return await store.stats()


# ══════════════════════════════════════════════════════════════════════════
# DEMO
# ══════════════════════════════════════════════════════════════════════════

GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


async def demo() -> None:
    """Демо: MCP server с extraction на сервере."""
    import json

    from tensory import Tensory

    # FakeLLM имитирует extraction (в production — anthropic_from_env())
    class FakeLLM:
        async def __call__(self, prompt: str) -> str:
            if "EigenLayer" in prompt:
                return json.dumps({
                    "claims": [
                        {"text": "Google partnered with EigenLayer for cloud restaking",
                         "type": "fact", "entities": ["Google", "EigenLayer"],
                         "confidence": 0.9, "relevance": 0.95},
                        {"text": "EigenLayer team expanded to 60 engineers",
                         "type": "fact", "entities": ["EigenLayer"],
                         "confidence": 0.85, "relevance": 0.7},
                    ],
                    "relations": [
                        {"from": "Google", "to": "EigenLayer",
                         "type": "PARTNERED_WITH", "fact": "Cloud restaking partnership"}
                    ],
                })
            return json.dumps({"claims": [], "relations": []})

    store = await Tensory.create(":memory:", llm=FakeLLM())  # type: ignore[arg-type]

    # ── Подсчёт токенов в descriptions
    total_tokens = sum(len(t["description"].split()) for t in TOOLS)
    print(f"\n{BOLD}{CYAN}══ MCP Server: extraction НА СЕРВЕРЕ ══{RESET}\n")
    print(f"  Tool descriptions: ~{total_tokens} слов (~{total_tokens * 2} токенов)")
    print(f"  {DIM}vs ~350 слов (~500 токенов) если встраивать extraction prompt{RESET}\n")

    # ── tensory_add — модель передаёт сырой текст
    print(f"{BOLD}1. tensory_add{RESET} — модель передаёт текст, сервер извлекает")
    print(f"   {DIM}Claude: 'Запомни это: Google партнёрится с EigenLayer'{RESET}")
    print(f"   {YELLOW}→ tensory_add(text='Google partnered with EigenLayer...'){RESET}\n")

    r1 = await handle_tensory_add(
        store,
        "Google announced partnership with EigenLayer for cloud restaking. "
        "The EigenLayer team has expanded to 60 engineers this quarter.",
        source="user:conversation",
    )
    print(f"   {GREEN}✓{RESET} stored={r1['stored']} claims:")
    for c in r1["claims"]:
        print(f"     → [{c['type']}] {c['text']}")
        print(f"       {DIM}entities={c['entities']}{RESET}")
    print()

    # ── tensory_remember — для случаев когда модель УЖЕ знает claims
    print(f"{BOLD}2. tensory_remember{RESET} — модель уже знает факт, передаёт напрямую")
    print(f"   {DIM}Для простых фактов из разговора (без extraction){RESET}")
    print(f"   {YELLOW}→ tensory_remember(claims=[...]){RESET}\n")

    r2 = await handle_tensory_remember(
        store,
        [{"text": "User is interested in DeFi protocols", "entities": ["DeFi"], "type": "observation"}],
    )
    print(f"   {GREEN}✓{RESET} stored={r2['stored']}\n")

    # ── tensory_search
    print(f"{BOLD}3. tensory_search{RESET}")
    print(f"   {YELLOW}→ tensory_search(query='EigenLayer'){RESET}\n")

    results = await handle_tensory_search(store, "EigenLayer")
    for r in results:
        print(f"   [{r['score']}] {r['text']}")
    print()

    # ── tensory_stats
    print(f"{BOLD}4. tensory_stats{RESET}")
    stats = await handle_tensory_stats(store)
    print(f"   {GREEN}✓{RESET} claims={stats['counts']['claims']} entities={stats['counts']['entities']}")

    await store.close()

    # ── Итог
    print(f"\n{BOLD}{CYAN}══ Итог: два tool'а — два подхода ══{RESET}\n")
    print(f"""
  {BOLD}tensory_add(text){RESET}        — для текстов (новости, статьи, сообщения)
    Модель передаёт сырой текст.
    Сервер делает extraction через extract.py (фиксированный промпт).
    LLM вызов через прокси → haiku → ~$0.001.
    Результат стабильный: один промпт → одинаковый формат.

  {BOLD}tensory_remember(claims){RESET} — для фактов из разговора
    Модель передаёт готовые claims напрямую.
    Без LLM вызова, без extraction. Бесплатно.
    Для: "пользователь сказал что ему 30 лет", "предпочитает Python".

  {BOLD}Настройка сервера:{RESET}
    ANTHROPIC_BASE_URL=http://localhost:8317   # CLIProxyAPI
    ANTHROPIC_API_KEY=signal-hunter-local

    from examples.llm_adapters import anthropic_from_env
    store = await Tensory.create("memory.db", llm=anthropic_from_env())
""")


if __name__ == "__main__":
    asyncio.run(demo())
