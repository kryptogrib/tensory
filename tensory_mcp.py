"""tensory MCP server — подключается к Claude Code.

Настройка в Claude Code (.claude/settings.json):
    "mcpServers": {
        "tensory": {
            "command": "/Users/chelovek/Work/tensory/.venv/bin/python",
            "args": ["/Users/chelovek/Work/tensory/tensory_mcp.py"],
            "env": {
                "ANTHROPIC_BASE_URL": "http://localhost:8317",
                "ANTHROPIC_API_KEY": "signal-hunter-local"
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tensory-mcp")

mcp = FastMCP("tensory")

# ── Глобальный store (создаётся при первом вызове) ────────────────────────

_store: Any = None
_lock = asyncio.Lock()


async def get_store() -> Any:
    """Lazy init store с LLM через прокси."""
    global _store
    if _store is not None:
        return _store

    async with _lock:
        if _store is not None:
            return _store

        from tensory import Tensory

        # LLM для extraction — через прокси (CLIProxyAPI)
        llm = _make_llm()
        db_path = os.environ.get("TENSORY_DB", "tensory_memory.db")

        _store = await Tensory.create(db_path, llm=llm)
        logger.info("tensory store initialized: %s", db_path)
        return _store


def _make_llm() -> Any:
    """Создаёт LLM adapter из env vars."""
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")

    if not base_url and not api_key:
        logger.warning("No ANTHROPIC_BASE_URL/API_KEY — tensory_add will fail, tensory_remember still works")
        return None

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=api_key or None,
        base_url=base_url or None,  # type: ignore[arg-type]
    )

    async def llm_call(prompt: str) -> str:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    return llm_call


# ══════════════════════════════════════════════════════════════════════════
# MCP TOOLS
# ══════════════════════════════════════════════════════════════════════════


@mcp.tool()
async def tensory_add(text: str, source: str = "conversation") -> str:
    """Store text in long-term memory. Server extracts claims via LLM automatically."""
    store = await get_store()
    try:
        result = await store.add(text, source=f"mcp:{source}")
    except ValueError as e:
        return json.dumps({"error": str(e)})

    return json.dumps({
        "stored": len(result.claims),
        "claims": [
            {"text": c.text, "entities": c.entities, "type": c.type.value}
            for c in result.claims
        ],
        "collisions": [
            {"type": col.type, "existing": col.claim_b.text[:80], "score": col.score}
            for col in result.collisions
        ],
        "new_entities": result.new_entities,
    })


@mcp.tool()
async def tensory_remember(claims: list[dict[str, Any]]) -> str:
    """Store pre-extracted claims directly. No LLM call needed.

    Each claim: {"text": "fact", "entities": ["Entity"], "type": "fact"}
    """
    from tensory import Claim

    store = await get_store()

    parsed = [
        Claim(
            text=str(c.get("text", "")),
            entities=[str(e) for e in (c.get("entities") or [])],
            type=str(c.get("type", "fact")),  # type: ignore[arg-type]
        )
        for c in claims
    ]
    result = await store.add_claims(parsed)

    return json.dumps({
        "stored": len(result.claims),
        "collisions": len(result.collisions),
        "new_entities": result.new_entities,
    })


@mcp.tool()
async def tensory_search(query: str, limit: int = 10) -> str:
    """Search long-term memory for relevant facts."""
    store = await get_store()
    results = await store.search(query, limit=limit)

    return json.dumps([
        {
            "text": r.claim.text,
            "score": round(r.score, 3),
            "entities": r.claim.entities,
            "type": r.claim.type.value,
            "salience": round(r.claim.salience, 3),
        }
        for r in results
    ])


@mcp.tool()
async def tensory_timeline(entity: str) -> str:
    """Show how facts about an entity changed over time."""
    store = await get_store()
    claims = await store.timeline(entity)

    return json.dumps([
        {
            "text": c.text,
            "type": c.type.value,
            "salience": round(c.salience, 3),
            "superseded": c.superseded_at is not None,
            "created_at": c.created_at.isoformat(),
        }
        for c in claims
    ])


@mcp.tool()
async def tensory_stats() -> str:
    """Get memory statistics."""
    store = await get_store()
    stats = await store.stats()
    return json.dumps(stats)


if __name__ == "__main__":
    mcp.run(transport="stdio")
