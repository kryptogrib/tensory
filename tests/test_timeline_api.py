"""Tests for timeline service methods and API endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tensory.models import Claim, ClaimType
from tensory.service import TensoryService, TimelineEntry
from tensory.store import Tensory


@pytest.fixture
async def service_with_timeline() -> TensoryService:
    """Service with claims that form a supersede chain."""
    store = await Tensory.create(":memory:")
    now = datetime.now(timezone.utc)
    old_claim = Claim(
        id="claim-old",
        text="ETH price is $2400",
        type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.9,
        created_at=now - timedelta(days=10),
    )
    new_claim = Claim(
        id="claim-new",
        text="ETH price is $2800",
        type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.95,
        created_at=now - timedelta(days=5),
    )
    other_claim = Claim(
        id="claim-other",
        text="ETH uses proof of stake",
        type=ClaimType.FACT,
        entities=["Ethereum"],
        confidence=0.99,
        created_at=now - timedelta(days=3),
    )
    await store.add_claims([old_claim, new_claim, other_claim])
    db = store.db
    assert db is not None
    await db.execute(
        "UPDATE claims SET superseded_at = ?, superseded_by = ? WHERE id = ?",
        (now - timedelta(days=5), "claim-new", "claim-old"),
    )
    await db.commit()
    svc = TensoryService(store)
    yield svc  # type: ignore[misc]
    await store.close()


async def test_entity_timeline_returns_chronological_order(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline("Ethereum")
    assert len(entries) >= 2
    dates = [e.claim.created_at for e in entries]
    assert dates == sorted(dates)


async def test_entity_timeline_includes_superseded(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline(
        "Ethereum", include_superseded=True
    )
    ids = [e.claim.id for e in entries]
    assert "claim-old" in ids


async def test_entity_timeline_supersedes_reverse_lookup(
    service_with_timeline: TensoryService,
) -> None:
    entries = await service_with_timeline.get_entity_timeline("Ethereum")
    entry_map = {e.claim.id: e for e in entries}
    new_entry = entry_map.get("claim-new")
    assert new_entry is not None
    assert new_entry.supersedes == "claim-old"


async def test_graph_snapshot_filters_by_date(
    service_with_timeline: TensoryService,
) -> None:
    now = datetime.now(timezone.utc)
    early = now - timedelta(days=30)
    snapshot = await service_with_timeline.get_graph_snapshot(early)
    assert len(snapshot.active_nodes) == 0
    assert len(snapshot.ghost_nodes) >= 1


async def test_graph_snapshot_ghost_nodes(
    service_with_timeline: TensoryService,
) -> None:
    now = datetime.now(timezone.utc)
    snapshot = await service_with_timeline.get_graph_snapshot(now)
    assert len(snapshot.active_nodes) >= 1
    ghost_names = [n.name for n in snapshot.ghost_nodes]
    active_names = [n.name for n in snapshot.active_nodes]
    assert not set(ghost_names) & set(active_names)


async def test_graph_snapshot_superseded_excluded(
    service_with_timeline: TensoryService,
) -> None:
    now = datetime.now(timezone.utc)
    snapshot = await service_with_timeline.get_graph_snapshot(now)
    assert snapshot.stats["superseded"] >= 1


async def test_timeline_range_histogram(
    service_with_timeline: TensoryService,
) -> None:
    result = await service_with_timeline.get_timeline_range()
    assert result.min_date is not None
    assert result.max_date is not None
    assert result.min_date <= result.max_date
    assert len(result.event_histogram) >= 1
    total_events = sum(b.count for b in result.event_histogram)
    assert total_events >= 3


async def test_timeline_range_empty_db() -> None:
    store = await Tensory.create(":memory:")
    svc = TensoryService(store)
    result = await svc.get_timeline_range()
    assert result.min_date == result.max_date
    assert len(result.event_histogram) == 0
    await store.close()
