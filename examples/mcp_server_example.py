"""MCP server for tensory — production-ready design.

Principle: tool descriptions are SHORT (token savings),
extraction happens ON THE SERVER using the same prompt as store.add().

For extraction, the server uses LLM via proxy (CLIProxyAPI)
or directly via Anthropic/OpenAI API. Cost: haiku ~$0.001/request.

Architecture:
    ┌──────────────────────────────────────────────┐
    │  Claude (calling model)                       │
    │  Only sees short tool descriptions            │
    │  (~30 tokens per tool, not 500)               │
    │                                               │
    │  → tensory_add(text="...", source="...")       │
    └──────────────┬───────────────────────────────┘
                   │ MCP call
                   ▼
    ┌──────────────────────────────────────────────┐
    │  tensory MCP server                           │
    │                                               │
    │  1. Receives raw text                         │
    │  2. Calls store.add(text)                     │
    │     → extract.py EXTRACT_PROMPT (fixed)       │
    │     → LLM API via proxy (haiku, cheap)        │
    │     → dedup → embed → collisions              │
    │  3. Returns result                            │
    └──────────────────────────────────────────────┘

Env vars:
    ANTHROPIC_BASE_URL=http://localhost:8317   # CLIProxyAPI
    ANTHROPIC_API_KEY=signal-hunter-local      # proxy key
    TENSORY_DB=memory.db                       # database path

Run:
    python examples/mcp_server_example.py
"""

from __future__ import annotations

import asyncio
from typing import Any


# ══════════════════════════════════════════════════════════════════════════
# TOOL DESCRIPTIONS — short, ~30 tokens each
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
# HANDLERS — extraction on the server, not in tool description
# ══════════════════════════════════════════════════════════════════════════


async def handle_tensory_add(
    store: Any,
    text: str,
    source: str = "mcp:conversation",
) -> dict[str, Any]:
    """Raw text → store.add() → server-side extraction.

    Extraction prompt is the same as in tensory/extract.py.
    LLM call goes through proxy (configured at store creation).
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
    """Pre-extracted claims → store.add_claims() directly. No LLM."""
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
    """Demo: MCP server with server-side extraction."""
    import json

    from tensory import Tensory

    # FakeLLM simulates extraction (in production — use anthropic_from_env())
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

    # ── Count tokens in descriptions
    total_tokens = sum(len(t["description"].split()) for t in TOOLS)
    print(f"\n{BOLD}{CYAN}══ MCP Server: extraction ON THE SERVER ══{RESET}\n")
    print(f"  Tool descriptions: ~{total_tokens} words (~{total_tokens * 2} tokens)")
    print(f"  {DIM}vs ~350 words (~500 tokens) if embedding the extraction prompt{RESET}\n")

    # ── tensory_add — model sends raw text
    print(f"{BOLD}1. tensory_add{RESET} — model sends text, server extracts")
    print(f"   {DIM}Claude: 'Remember this: Google partnered with EigenLayer'{RESET}")
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

    # ── tensory_remember — for cases when the model ALREADY knows the claims
    print(f"{BOLD}2. tensory_remember{RESET} — model already knows the fact, passes directly")
    print(f"   {DIM}For simple facts from conversation (no extraction){RESET}")
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

    # ── Summary
    print(f"\n{BOLD}{CYAN}══ Summary: two tools — two approaches ══{RESET}\n")
    print(f"""
  {BOLD}tensory_add(text){RESET}        — for texts (news, articles, messages)
    Model sends raw text.
    Server performs extraction via extract.py (fixed prompt).
    LLM call via proxy → haiku → ~$0.001.
    Stable result: one prompt → consistent format.

  {BOLD}tensory_remember(claims){RESET} — for facts from conversation
    Model sends pre-extracted claims directly.
    No LLM call, no extraction. Free.
    For: "user said they are 30 years old", "prefers Python".

  {BOLD}Server configuration:{RESET}
    ANTHROPIC_BASE_URL=http://localhost:8317   # CLIProxyAPI
    ANTHROPIC_API_KEY=signal-hunter-local

    from examples.llm_adapters import anthropic_from_env
    store = await Tensory.create("memory.db", llm=anthropic_from_env())
""")


if __name__ == "__main__":
    asyncio.run(demo())
