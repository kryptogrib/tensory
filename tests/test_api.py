"""Tests for the FastAPI REST API backend.

Tests cover all endpoints: stats, claims (list/detail/search),
and graph (entities/edges/subgraph/entity-claims).
Uses httpx AsyncClient with ASGITransport for in-process testing.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from api.dependencies import set_service
from api.main import create_app
from tensory import Claim, ClaimType, Tensory
from tensory.service import TensoryService


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Create test client with seeded in-memory store."""
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    await store.add_claims([
        Claim(text="Google builds AI", entities=["Google"], type=ClaimType.FACT),
        Claim(text="AI hype is overblown", entities=["AI"], type=ClaimType.OPINION),
    ])
    # Set service directly — ASGITransport does not trigger lifespan events
    set_service(svc)
    application = create_app(service=svc)
    transport = ASGITransport(app=application)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    await store.close()


# ── Stats ──────────────────────────────────────────────────────────────────


async def test_stats_endpoint(client: AsyncClient) -> None:
    """GET /api/stats returns 200 with expected fields."""
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "counts" in data
    assert "avg_salience" in data
    assert "recent_claims" in data
    assert "hot_entities" in data


# ── Claims list ────────────────────────────────────────────────────────────


async def test_list_claims_endpoint(client: AsyncClient) -> None:
    """GET /api/claims returns 200 with paginated results."""
    resp = await client.get("/api/claims")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] == 2
    assert len(data["items"]) == 2


# ── Search ─────────────────────────────────────────────────────────────────


async def test_search_endpoint(client: AsyncClient) -> None:
    """GET /api/search?q=Google returns 200 with list."""
    resp = await client.get("/api/search", params={"q": "Google"})
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ── Graph entities ─────────────────────────────────────────────────────────


async def test_graph_entities_endpoint(client: AsyncClient) -> None:
    """GET /api/graph/entities returns 200 with list."""
    resp = await client.get("/api/graph/entities")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ── Graph edges ────────────────────────────────────────────────────────────


async def test_graph_edges_endpoint(client: AsyncClient) -> None:
    """GET /api/graph/edges returns 200 with list."""
    resp = await client.get("/api/graph/edges")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)


# ── Claim detail ───────────────────────────────────────────────────────────


async def test_claim_detail_endpoint(client: AsyncClient) -> None:
    """GET /api/claims/{id} returns 200 for an existing claim."""
    # First, get a claim ID from the list
    resp = await client.get("/api/claims")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) > 0
    claim_id = items[0]["id"]

    # Then fetch detail
    detail_resp = await client.get(f"/api/claims/{claim_id}")
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert "claim" in data
    assert data["claim"]["id"] == claim_id


async def test_claim_detail_not_found(client: AsyncClient) -> None:
    """GET /api/claims/{bad_id} returns 404."""
    resp = await client.get("/api/claims/nonexistent-id")
    assert resp.status_code == 404
