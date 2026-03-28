"""Smoke test for the tensory MCP server.

Launches the MCP server as a subprocess, sends requests via stdio,
and verifies that all tools work and components are active.

Usage:
    uv run python scripts/test_mcp.py              # Quick smoke test
    uv run python scripts/test_mcp.py --verbose     # With details
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

# MCP client SDK
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ── Configuration (from .mcp.json) ──────────────────────────────────────

SERVER_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "tensory_mcp.py")

SERVER_ENV = {
    **os.environ,
    "ANTHROPIC_BASE_URL": os.environ.get("ANTHROPIC_BASE_URL", "http://localhost:8317"),
    "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "signal-hunter-local"),
    "TENSORY_DB": ":memory:",  # Always clean in-memory DB for tests!
    "TENSORY_MODEL": os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001"),
}

# Add OPENAI_API_KEY if available
if os.environ.get("OPENAI_API_KEY"):
    SERVER_ENV["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"]

VERBOSE = "--verbose" in sys.argv or "-v" in sys.argv


# ── Helpers ──────────────────────────────────────────────────────────────

def ok(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")


def info(msg: str) -> None:
    if VERBOSE:
        print(f"    {msg}")


async def call_tool(session: ClientSession, name: str, args: dict[str, Any]) -> Any:
    """Call an MCP tool and return parsed JSON."""
    result = await session.call_tool(name, args)
    text = result.content[0].text  # type: ignore[union-attr]
    return json.loads(text)


# ── Tests ────────────────────────────────────────────────────────────────

async def test_health(session: ClientSession) -> dict[str, Any]:
    """Check tensory_health — which components are active."""
    print("\n1. Health Check")
    health = await call_tool(session, "tensory_health", {})
    info(json.dumps(health, indent=2))

    if health["llm"]["active"]:
        ok("LLM active")
    else:
        fail("LLM disabled — tensory_add will fail")

    if health["embedder"]["active"]:
        ok(f"Embedder active ({health['embedder']['type']})")
    else:
        fail(f"Embedder disabled ({health['embedder']['type']}) — no vector search!")

    if health["vec_available"]["active"]:
        ok("sqlite-vec loaded")
    else:
        fail("sqlite-vec not available")

    features = health.get("features", {})
    active = sum(1 for v in features.values() if v)
    total = len(features)
    if active == total:
        ok(f"All {total} features active")
    else:
        fail(f"Only {active}/{total} features active: "
             + ", ".join(f"{k}={'ON' if v else 'OFF'}" for k, v in features.items()))

    return health


async def test_remember(session: ClientSession) -> None:
    """Check tensory_remember — storing claims without LLM."""
    print("\n2. Remember (direct claims)")
    result = await call_tool(session, "tensory_remember", {
        "claims": [
            {"text": "Python is a programming language", "entities": ["Python"], "type": "fact"},
            {"text": "User prefers dark themes", "entities": ["User"], "type": "opinion"},
        ]
    })
    info(json.dumps(result))

    if result.get("stored", 0) == 2:
        ok(f"Stored {result['stored']} claims")
    else:
        fail(f"Expected 2 stored, got {result.get('stored')}")


async def test_search(session: ClientSession, health: dict[str, Any]) -> None:
    """Check tensory_search — searching memory."""
    print("\n3. Search")
    results = await call_tool(session, "tensory_search", {"query": "Python", "limit": 5})
    info(json.dumps(results, indent=2))

    if len(results) > 0:
        ok(f"Found {len(results)} results for 'Python'")
        top = results[0]
        info(f"Top result: {top['text']} (score={top['score']})")
    else:
        # Without embeddings, search should still work via FTS
        fail("No results for 'Python' — FTS might be broken")


async def test_stats(session: ClientSession) -> None:
    """Check tensory_stats — statistics."""
    print("\n4. Stats")
    stats = await call_tool(session, "tensory_stats", {})
    info(json.dumps(stats, indent=2))

    counts = stats.get("counts", {})
    if counts.get("claims", 0) >= 2:
        ok(f"Stats OK: {counts['claims']} claims, {counts['entities']} entities")
    else:
        fail(f"Expected ≥2 claims, got {counts.get('claims')}")

    health = stats.get("health", {})
    if health:
        ok(f"Health in stats: llm={health['llm']}, embedder={health['embedder']}, vec={health['vec_available']}")


async def test_add(session: ClientSession, health: dict[str, Any]) -> None:
    """Check tensory_add — storing with LLM extraction."""
    print("\n5. Add (LLM extraction)")
    if not health["llm"]["active"]:
        info("Skipping — LLM not available")
        ok("Skipped (no LLM)")
        return

    result = await call_tool(session, "tensory_add", {
        "text": "Tesla announced record Q4 deliveries of 500,000 vehicles, beating analyst expectations.",
        "source": "smoke-test",
    })
    info(json.dumps(result, indent=2))

    if "error" in result:
        fail(f"LLM extraction failed: {result['error']}")
    elif result.get("stored", 0) > 0:
        ok(f"LLM extracted {result['stored']} claims, entities: {result.get('new_entities', [])}")
    else:
        fail("LLM returned 0 claims")


async def test_timeline(session: ClientSession) -> None:
    """Check tensory_timeline — entity history."""
    print("\n6. Timeline")
    result = await call_tool(session, "tensory_timeline", {"entity": "Python"})
    info(json.dumps(result, indent=2))

    if len(result) > 0:
        ok(f"Timeline for 'Python': {len(result)} entries")
    else:
        fail("No timeline entries for 'Python'")


# ── Main ─────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("Tensory MCP Server — Smoke Test")
    print("=" * 60)

    venv_python = os.path.join(os.path.dirname(__file__), "..", ".venv", "bin", "python")
    server_params = StdioServerParameters(
        command=venv_python,
        args=[SERVER_SCRIPT],
        env=SERVER_ENV,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # List available tools
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            print(f"\nAvailable tools: {tool_names}")

            expected = {"tensory_add", "tensory_remember", "tensory_search",
                        "tensory_timeline", "tensory_stats", "tensory_health"}
            missing = expected - set(tool_names)
            if missing:
                fail(f"Missing tools: {missing}")
            else:
                ok(f"All {len(expected)} tools registered")

            # Run tests
            health = await test_health(session)
            await test_remember(session)
            await test_search(session, health)
            await test_stats(session)
            await test_add(session, health)
            await test_timeline(session)

    print("\n" + "=" * 60)
    print("Done!")


if __name__ == "__main__":
    asyncio.run(main())
