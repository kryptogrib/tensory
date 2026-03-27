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
        embedder = _make_embedder()
        db_path = os.environ.get("TENSORY_DB", "tensory_memory.db")

        _store = await Tensory.create(db_path, llm=llm, embedder=embedder)
        health = _check_health(_store, llm, embedder)
        logger.info("tensory store initialized: %s | health: %s", db_path, json.dumps(health))
        return _store


def _check_health(store: Any, llm: Any, embedder: Any) -> dict[str, Any]:
    """Проверяет какие компоненты активны. Логирует WARNING для отключённых."""
    from tensory.embedder import NullEmbedder

    health: dict[str, Any] = {
        "llm": llm is not None,
        "embedder": not isinstance(store._embedder, NullEmbedder),
        "vec_available": getattr(store, "_vec_available", False),
        "db_path": str(getattr(store, "_path", "unknown")),
    }

    # Громкие предупреждения для отключённых компонентов
    if not health["llm"]:
        logger.warning("⚠️  LLM DISABLED — tensory_add() will fail (no claim extraction)")
    if not health["embedder"]:
        logger.warning("⚠️  EMBEDDER DISABLED — no vector search, no waypoints, no surprise scoring")
    if not health["vec_available"]:
        logger.warning("⚠️  sqlite-vec UNAVAILABLE — vector search impossible even with embedder")

    active = sum(1 for v in health.values() if v is True)
    total = 3  # llm, embedder, vec
    if active == total:
        logger.info("✅ All %d components active", total)
    else:
        logger.warning("⚠️  Only %d/%d components active — memory running in degraded mode", active, total)

    return health


def _make_embedder() -> Any:
    """Создаёт OpenAIEmbedder если есть OPENAI_API_KEY, иначе NullEmbedder."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("No OPENAI_API_KEY — using NullEmbedder (no vector search)")
        return None  # Tensory.create() подставит NullEmbedder

    from tensory.embedder import OpenAIEmbedder

    base_url = os.environ.get("OPENAI_BASE_URL")
    logger.info("OpenAIEmbedder initialized (base_url=%s)", base_url or "default")
    return OpenAIEmbedder(api_key=api_key, base_url=base_url)


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
    """Get memory statistics and health status."""
    store = await get_store()
    stats = await store.stats()

    # Добавляем health info к статистике
    from tensory.embedder import NullEmbedder

    stats["health"] = {
        "llm": store._llm is not None,
        "embedder": not isinstance(store._embedder, NullEmbedder),
        "vec_available": getattr(store, "_vec_available", False),
    }
    return json.dumps(stats)


@mcp.tool()
async def tensory_health() -> str:
    """Check which memory components are active. Use this to diagnose issues."""
    store = await get_store()
    from tensory.embedder import NullEmbedder

    embedder_type = type(store._embedder).__name__
    health = {
        "llm": {
            "active": store._llm is not None,
            "detail": "LLM extraction for tensory_add()" if store._llm else "DISABLED — tensory_add() will fail",
        },
        "embedder": {
            "active": not isinstance(store._embedder, NullEmbedder),
            "type": embedder_type,
            "detail": f"{embedder_type} (dim={store._embedder.dim})",
        },
        "vec_available": {
            "active": getattr(store, "_vec_available", False),
            "detail": "sqlite-vec loaded" if getattr(store, "_vec_available", False) else "sqlite-vec NOT loaded",
        },
        "features": {
            "vector_search": not isinstance(store._embedder, NullEmbedder) and getattr(store, "_vec_available", False),
            "fts_search": True,
            "graph_search": True,
            "collision_detection": True,
            "waypoints": not isinstance(store._embedder, NullEmbedder),
            "surprise_scoring": not isinstance(store._embedder, NullEmbedder),
        },
    }
    return json.dumps(health, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
