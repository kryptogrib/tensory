"""Tests for MCP server tools — tests the tool functions directly."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

# Import the MCP tools directly (not through MCP transport)
import tensory_mcp


class FakeLLM:
    async def __call__(self, prompt: str) -> str:
        return json.dumps({
            "claims": [
                {
                    "text": "Test claim extracted by LLM",
                    "type": "fact",
                    "entities": ["TestEntity"],
                    "confidence": 0.9,
                    "relevance": 0.8,
                }
            ],
            "relations": [],
        })


@pytest.fixture(autouse=True)
async def reset_store() -> None:  # type: ignore[misc]
    """Reset the global store before each test."""
    tensory_mcp._store = None
    yield
    if tensory_mcp._store is not None:
        await tensory_mcp._store.close()
        tensory_mcp._store = None


@pytest.fixture
async def init_store() -> None:
    """Initialize store with in-memory DB and FakeLLM."""
    from tensory import Tensory

    store = await Tensory.create(":memory:", llm=FakeLLM())
    tensory_mcp._store = store


# ── tensory_remember ──────────────────────────────────────────────────────


async def test_remember_stores_claims(init_store: None) -> None:
    """tensory_remember stores pre-extracted claims."""
    result_json = await tensory_mcp.tensory_remember([
        {"text": "EigenLayer has 50 team members", "entities": ["EigenLayer"], "type": "fact"},
        {"text": "Lido reached 10M staked ETH", "entities": ["Lido", "ETH"], "type": "fact"},
    ])
    result = json.loads(result_json)

    assert result["stored"] == 2
    assert "EigenLayer" in result["new_entities"]


async def test_remember_empty_list(init_store: None) -> None:
    """tensory_remember with empty list works."""
    result_json = await tensory_mcp.tensory_remember([])
    result = json.loads(result_json)
    assert result["stored"] == 0


# ── tensory_search ────────────────────────────────────────────────────────


async def test_search_returns_results(init_store: None) -> None:
    """tensory_search finds stored claims."""
    await tensory_mcp.tensory_remember([
        {"text": "EigenLayer restaking protocol launched", "entities": ["EigenLayer"]},
    ])

    result_json = await tensory_mcp.tensory_search("EigenLayer")
    results = json.loads(result_json)

    assert len(results) >= 1
    assert "EigenLayer" in results[0]["text"]


async def test_search_empty_query(init_store: None) -> None:
    """tensory_search with no matches returns empty list."""
    result_json = await tensory_mcp.tensory_search("nonexistent_xyz_query")
    results = json.loads(result_json)
    assert results == []


async def test_search_respects_limit(init_store: None) -> None:
    """tensory_search respects the limit parameter."""
    await tensory_mcp.tensory_remember([
        {"text": f"Claim about topic number {i}", "entities": ["Topic"]}
        for i in range(10)
    ])

    result_json = await tensory_mcp.tensory_search("topic", limit=3)
    results = json.loads(result_json)
    assert len(results) <= 3


# ── tensory_timeline ──────────────────────────────────────────────────────


async def test_timeline_returns_history(init_store: None) -> None:
    """tensory_timeline shows entity history."""
    await tensory_mcp.tensory_remember([
        {"text": "EigenLayer launched v1", "entities": ["EigenLayer"]},
        {"text": "EigenLayer launched v2 with major improvements", "entities": ["EigenLayer"]},
    ])

    result_json = await tensory_mcp.tensory_timeline("EigenLayer")
    timeline = json.loads(result_json)

    assert len(timeline) >= 2
    assert all("EigenLayer" in t["text"] for t in timeline)


async def test_timeline_empty_entity(init_store: None) -> None:
    """tensory_timeline for unknown entity returns empty."""
    result_json = await tensory_mcp.tensory_timeline("UnknownEntity")
    timeline = json.loads(result_json)
    assert timeline == []


# ── tensory_stats ─────────────────────────────────────────────────────────


async def test_stats_returns_counts(init_store: None) -> None:
    """tensory_stats returns memory statistics."""
    await tensory_mcp.tensory_remember([
        {"text": "Test claim", "entities": ["Test"]},
    ])

    result_json = await tensory_mcp.tensory_stats()
    stats = json.loads(result_json)

    assert "counts" in stats
    assert stats["counts"]["claims"] == 1
    assert "health" in stats


# ── tensory_health ────────────────────────────────────────────────────────


async def test_health_reports_components(init_store: None) -> None:
    """tensory_health reports component status."""
    result_json = await tensory_mcp.tensory_health()
    health = json.loads(result_json)

    assert "llm" in health
    assert "embedder" in health
    assert "vec_available" in health
    assert "features" in health
    assert health["features"]["fts_search"] is True
    assert health["features"]["collision_detection"] is True


# ── tensory_add (with LLM) ───────────────────────────────────────────────


async def test_add_extracts_claims(init_store: None) -> None:
    """tensory_add extracts claims via LLM."""
    result_json = await tensory_mcp.tensory_add(
        "Google announced partnership with EigenLayer",
        source="test",
    )
    result = json.loads(result_json)

    assert result["stored"] >= 1
    assert "error" not in result


async def test_add_without_llm_returns_error() -> None:
    """tensory_add without LLM returns error."""
    from tensory import Tensory

    store = await Tensory.create(":memory:")  # no LLM
    tensory_mcp._store = store

    result_json = await tensory_mcp.tensory_add("some text")
    result = json.loads(result_json)

    assert "error" in result

    await store.close()
    tensory_mcp._store = None


# ── Collision detection via MCP ───────────────────────────────────────────


async def test_remember_detects_collisions(init_store: None) -> None:
    """Collisions are detected and reported via tensory_remember."""
    await tensory_mcp.tensory_remember([
        {"text": "EigenLayer has 50 team members", "entities": ["EigenLayer"], "type": "fact"},
    ])

    result_json = await tensory_mcp.tensory_remember([
        {"text": "EigenLayer has 65 team members after hiring", "entities": ["EigenLayer"], "type": "fact"},
    ])
    result = json.loads(result_json)

    assert result["stored"] >= 1
    assert result["collisions"] >= 1
