"""Tests for TensoryService — read-only dashboard query layer.

Tests cover:
- Dashboard stats aggregation
- Claims pagination with filters
- Single claim detail retrieval
- Search delegation
- Graph entity/edge/subgraph queries
- Entity-scoped claim lookups
"""

from __future__ import annotations

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.service import TensoryService


@pytest.fixture
async def service() -> TensoryService:
    """Create an in-memory Tensory with seed data and wrap in TensoryService."""
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    await store.add_claims(
        [
            Claim(text="Google builds AI chips", entities=["Google"], type=ClaimType.FACT),
            Claim(text="Meta launches Llama 4", entities=["Meta"], type=ClaimType.FACT),
            Claim(text="AI hype is overblown", entities=["AI"], type=ClaimType.OPINION),
        ]
    )
    yield svc  # type: ignore[misc]
    await store.close()


# ── Stats ────────────────────────────────────────────────────────────────


async def test_get_stats(service: TensoryService) -> None:
    """DashboardStats has expected fields and values."""
    stats = await service.get_stats()
    assert stats.counts["claims"] == 3
    assert stats.counts["entities"] == 3
    assert stats.claims_by_type.get("fact", 0) == 2
    assert stats.claims_by_type.get("opinion", 0) == 1
    assert stats.avg_salience > 0.0
    assert len(stats.recent_claims) <= 5
    assert len(stats.recent_claims) == 3
    assert len(stats.hot_entities) <= 5
    assert len(stats.hot_entities) == 3


# ── Claims list / pagination ─────────────────────────────────────────────


async def test_list_claims_pagination(service: TensoryService) -> None:
    """Pagination returns correct slice and total."""
    page = await service.list_claims(offset=0, limit=2)
    assert len(page.items) == 2
    assert page.total == 3
    assert page.offset == 0
    assert page.limit == 2


async def test_list_claims_type_filter(service: TensoryService) -> None:
    """Type filter narrows results."""
    page = await service.list_claims(type_filter="opinion")
    assert page.total == 1
    assert page.items[0].type == ClaimType.OPINION


async def test_list_claims_entity_filter(service: TensoryService) -> None:
    """Entity filter returns only claims linked to that entity."""
    page = await service.list_claims(entity_filter="Google")
    assert page.total == 1
    assert "Google" in page.items[0].entities


async def test_list_claims_sort_validation(service: TensoryService) -> None:
    """Invalid sort_by raises ValueError."""
    with pytest.raises(ValueError, match="sort_by"):
        await service.list_claims(sort_by="invalid_column")


# ── Single claim detail ──────────────────────────────────────────────────


async def test_get_claim(service: TensoryService) -> None:
    """Fetch a claim by ID and verify ClaimDetail structure."""
    # Get a claim ID from list
    page = await service.list_claims(limit=1)
    claim_id = page.items[0].id

    detail = await service.get_claim(claim_id)
    assert detail.claim.id == claim_id
    assert detail.claim.text
    assert isinstance(detail.collisions, list)
    assert isinstance(detail.waypoints, list)
    assert isinstance(detail.related_entities, list)


async def test_get_claim_not_found(service: TensoryService) -> None:
    """Missing claim raises ValueError."""
    with pytest.raises(ValueError, match="not found"):
        await service.get_claim("nonexistent_id")


# ── Search ───────────────────────────────────────────────────────────────


async def test_search_claims(service: TensoryService) -> None:
    """FTS search returns relevant results."""
    results = await service.search_claims("Google")
    assert len(results) >= 1
    assert any("Google" in r.claim.text for r in results)


# ── Graph entities ───────────────────────────────────────────────────────


async def test_get_graph_entities(service: TensoryService) -> None:
    """Graph entities list returns EntityNode objects."""
    entities = await service.get_graph_entities()
    assert len(entities) >= 1
    assert entities[0].name
    assert entities[0].mention_count >= 1


async def test_get_graph_edges(service: TensoryService) -> None:
    """Graph edges returns a list (may be empty with no relations)."""
    edges = await service.get_graph_edges()
    assert isinstance(edges, list)


async def test_get_entity_subgraph(service: TensoryService) -> None:
    """Subgraph returns a SubGraph with nodes and edges lists."""
    sg = await service.get_entity_subgraph("Google")
    assert isinstance(sg.nodes, list)
    assert isinstance(sg.edges, list)


# ── Entity claims ────────────────────────────────────────────────────────


async def test_get_entity_claims(service: TensoryService) -> None:
    """Claims for a specific entity are returned."""
    claims = await service.get_entity_claims("Google")
    assert len(claims) == 1
    assert "Google" in claims[0].entities
