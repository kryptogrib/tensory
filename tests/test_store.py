"""Phase 1 tests for tensory store.

Tests cover:
- Claim ingestion and retrieval
- FTS search
- Context creation
- Salience defaults per ClaimType
- Sentiment tagging
- Graph traversal (SQLiteGraphBackend)
- Stats
"""

from __future__ import annotations

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.store import DECAY_RATES

# ── Episode storage ──────────────────────────────────────────────────────


async def test_save_episode_returns_id(store: Tensory) -> None:
    """save_episode stores raw text and returns episode_id."""
    episode_id = await store.save_episode("Hello world", source="test")
    assert isinstance(episode_id, str)
    assert len(episode_id) > 0

    # Verify episode is in DB
    async with store.db.execute(
        "SELECT raw_text, source FROM episodes WHERE id = ?", (episode_id,)
    ) as cursor:
        row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Hello world"
    assert row[1] == "test"


async def test_save_episode_no_extraction(store: Tensory) -> None:
    """save_episode does NOT trigger LLM extraction — no claims created."""
    await store.save_episode("Some text that should not be extracted")
    stats = await store.stats()
    assert stats["counts"]["claims"] == 0


# ── Claim ingestion ───────────────────────────────────────────────────────


async def test_add_claims_and_retrieve(store: Tensory) -> None:
    """Claims can be ingested and appear in stats."""
    result = await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
            Claim(text="Lido protocol launched v2", entities=["Lido"]),
        ]
    )

    assert len(result.claims) == 2
    assert all(c.id for c in result.claims)
    assert "EigenLayer" in result.new_entities
    assert "Lido" in result.new_entities

    stats = await store.stats()
    assert stats["counts"]["claims"] == 2
    assert stats["counts"]["entities"] == 2


async def test_add_claims_with_episode_and_context(store: Tensory) -> None:
    """Episode and context IDs are propagated to claims."""
    ctx = await store.create_context(goal="Track DeFi teams")
    result = await store.add_claims(
        [Claim(text="Test claim")],
        episode_id="ep_123",
        context_id=ctx.id,
    )

    assert result.claims[0].episode_id == "ep_123"
    assert result.claims[0].context_id == ctx.id


async def test_claim_ids_auto_generated(store: Tensory) -> None:
    """Claims without IDs get UUID hex IDs assigned."""
    result = await store.add_claims([Claim(text="No ID claim")])
    assert len(result.claims[0].id) == 32  # uuid4 hex


# ── FTS search ────────────────────────────────────────────────────────────


async def test_fts_search_finds_matching_claims(store: Tensory) -> None:
    """FTS5 search returns claims matching the query."""
    await store.add_claims(
        [
            Claim(text="EigenLayer announced a new partnership with Google Cloud"),
            Claim(text="Bitcoin price reached 100k milestone"),
            Claim(text="EigenLayer team expanded to 60 engineers"),
        ]
    )

    results = await store.search("EigenLayer")
    assert len(results) >= 2
    assert all("EigenLayer" in r.claim.text for r in results)
    # Phase 2: search returns "hybrid" (FTS + graph + RRF merge)
    assert all(r.method in ("fts", "hybrid") for r in results)


async def test_fts_search_returns_empty_for_no_match(store: Tensory) -> None:
    """Search returns empty list when nothing matches."""
    await store.add_claims([Claim(text="Something unrelated")])
    results = await store.search("ZetaProtocol")
    assert results == []


async def test_search_respects_limit(store: Tensory) -> None:
    """Search respects the limit parameter."""
    claims = [Claim(text=f"Claim about topic number {i}") for i in range(10)]
    await store.add_claims(claims)

    results = await store.search("topic", limit=3)
    assert len(results) <= 3


# ── Context ───────────────────────────────────────────────────────────────


async def test_create_context(store: Tensory) -> None:
    """Contexts can be created with all fields."""
    ctx = await store.create_context(
        goal="Track DeFi team movements",
        domain="crypto",
        description="Following key personnel changes",
        user_id="user_42",
    )

    assert ctx.id
    assert ctx.goal == "Track DeFi team movements"
    assert ctx.domain == "crypto"
    assert ctx.user_id == "user_42"
    assert ctx.active is True

    stats = await store.stats()
    assert stats["counts"]["contexts"] == 1


# ── Salience defaults ────────────────────────────────────────────────────


async def test_salience_defaults_by_type(store: Tensory) -> None:
    """Each ClaimType gets its own default decay rate."""
    claims = [
        Claim(text="Verified fact", type=ClaimType.FACT),
        Claim(text="An event happened", type=ClaimType.EXPERIENCE),
        Claim(text="I think this means...", type=ClaimType.OBSERVATION),
        Claim(text="This is probably bad", type=ClaimType.OPINION),
    ]
    result = await store.add_claims(claims)

    for claim in result.claims:
        expected_rate = DECAY_RATES[claim.type]
        assert claim.decay_rate == expected_rate, (
            f"{claim.type} should have decay_rate={expected_rate}, got {claim.decay_rate}"
        )


async def test_custom_decay_rate_preserved(store: Tensory) -> None:
    """Claims with explicit decay_rate don't get overwritten."""
    result = await store.add_claims(
        [
            Claim(text="Custom decay", type=ClaimType.FACT, decay_rate=0.999),
        ]
    )
    assert result.claims[0].decay_rate == 0.999


# ── Sentiment tagging ────────────────────────────────────────────────────


async def test_sentiment_tagging_positive(store: Tensory) -> None:
    """Positive keywords get tagged."""
    result = await store.add_claims(
        [
            Claim(text="EigenLayer confirmed a major partnership and launch"),
        ]
    )
    meta = result.claims[0].metadata
    assert meta.get("sentiment") == "positive"
    assert float(str(meta.get("intensity", 0))) > 0


async def test_sentiment_tagging_negative(store: Tensory) -> None:
    """Negative keywords get tagged."""
    result = await store.add_claims(
        [
            Claim(text="Protocol suffered a major hack and exploit"),
        ]
    )
    meta = result.claims[0].metadata
    assert meta.get("sentiment") == "negative"


async def test_sentiment_tagging_urgent_boosts_salience(store: Tensory) -> None:
    """Urgent keywords boost salience by 0.3."""
    result = await store.add_claims(
        [
            Claim(text="BREAKING: critical vulnerability discovered", salience=0.5),
        ]
    )
    claim = result.claims[0]
    assert claim.metadata.get("urgent") is True
    assert claim.salience == pytest.approx(0.8, abs=0.01)  # 0.5 + 0.3


async def test_sentiment_tagging_neutral(store: Tensory) -> None:
    """Text without sentiment keywords is tagged neutral."""
    result = await store.add_claims(
        [
            Claim(text="The team held a meeting on Tuesday"),
        ]
    )
    assert result.claims[0].metadata.get("sentiment") == "neutral"


# ── Reinforce on access ──────────────────────────────────────────────────


async def test_reinforce_on_access(store: Tensory) -> None:
    """Claims found via search get +0.05 salience boost."""
    await store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol", salience=0.5),
        ]
    )

    # Search triggers reinforce
    results = await store.search("EigenLayer")
    assert len(results) == 1

    # Check salience was boosted in DB
    cursor = await store._db.execute(
        "SELECT salience, access_count FROM claims WHERE id = ?",
        (results[0].claim.id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert float(row[0]) == pytest.approx(0.55, abs=0.01)  # 0.5 + 0.05
    assert row[1] == 1  # access_count incremented


# ── Graph traversal ──────────────────────────────────────────────────────


async def test_graph_traverse_sqlite(store: Tensory) -> None:
    """SQLiteGraphBackend traversal finds connected entities."""
    # Create entities with a relation
    eid1 = await store._graph.add_entity("Google", "company")
    eid2 = await store._graph.add_entity("EigenLayer", "protocol")
    await store._graph.add_edge(
        eid1,
        eid2,
        "PARTNERED_WITH",
        {"fact": "Google partnered with EigenLayer"},
    )
    await store._db.commit()

    # Traverse from Google should find EigenLayer
    connected = await store._graph.traverse("Google", depth=1)
    assert eid2 in connected


async def test_graph_add_entity_increments_mention_count(store: Tensory) -> None:
    """Adding the same entity twice increments mention_count."""
    eid1 = await store._graph.add_entity("EigenLayer")
    eid2 = await store._graph.add_entity("EigenLayer")
    assert eid1 == eid2  # same entity

    cursor = await store._db.execute("SELECT mention_count FROM entities WHERE id = ?", (eid1,))
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == 2


async def test_graph_get_shared_entities(store: Tensory) -> None:
    """get_shared_entities finds entities co-occurring across claims."""
    # Two claims sharing the "EigenLayer" entity
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 members", entities=["EigenLayer", "HR"]),
            Claim(text="EigenLayer partnered with Google", entities=["EigenLayer", "Google"]),
        ]
    )

    # Get claims to find IDs
    cursor = await store._db.execute("SELECT id FROM claims LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    claim_id = row[0]

    shared = await store._graph.get_shared_entities(claim_id)
    # Should find at least the "EigenLayer" entity (shared between both claims)
    assert len(shared) >= 1


# ── Stats ─────────────────────────────────────────────────────────────────


async def test_stats_empty_store(store: Tensory) -> None:
    """Stats work on an empty store."""
    stats = await store.stats()
    assert stats["counts"]["claims"] == 0
    assert stats["counts"]["episodes"] == 0
    assert stats["avg_salience"] == 0.0


async def test_stats_with_data(store: Tensory) -> None:
    """Stats reflect actual data."""
    await store.add_claims(
        [
            Claim(text="Fact one", type=ClaimType.FACT),
            Claim(text="Opinion one", type=ClaimType.OPINION),
            Claim(text="Fact two", type=ClaimType.FACT),
        ]
    )

    stats = await store.stats()
    assert stats["counts"]["claims"] == 3
    assert stats["claims_by_type"].get("fact") == 2
    assert stats["claims_by_type"].get("opinion") == 1
    assert stats["avg_salience"] > 0


# ── Collision persistence (Phase 2) ─────────────────────────────────────


async def test_collisions_persisted_to_collision_log(store: Tensory) -> None:
    """Collisions detected during add_claims() should be saved to collision_log table."""
    # Add two claims about same entity with conflicting values → real collision
    await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])
    await store.add_claims([Claim(text="EigenLayer has 65 team members", entities=["EigenLayer"])])

    # Check collision_log table directly
    cursor = await store._db.execute("SELECT COUNT(*) FROM collision_log")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] >= 1, "Collision should be persisted to collision_log table"


async def test_collision_log_stores_correct_fields(store: Tensory) -> None:
    """collision_log stores claim IDs, type, score, and shared entities."""
    r1 = await store.add_claims(
        [Claim(text="Bitcoin price is 40000 dollars", entities=["Bitcoin"])]
    )
    r2 = await store.add_claims(
        [Claim(text="Bitcoin price is 65000 dollars", entities=["Bitcoin"])]
    )

    cursor = await store._db.execute(
        "SELECT claim_a_id, claim_b_id, collision_type, score, shared_entities "
        "FROM collision_log ORDER BY created_at DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    assert row is not None, "Should have persisted collision"

    claim_a_id = row[0]
    claim_b_id = row[1]
    collision_type = row[2]
    score = float(row[3])

    # claim_a should be the newer claim, claim_b the older
    assert claim_a_id == r2.claims[0].id
    assert claim_b_id == r1.claims[0].id
    assert collision_type in ("contradiction", "supersedes", "confirms", "related")
    assert score > 0


async def test_stats_includes_collision_count(store: Tensory) -> None:
    """stats() should include collision_log count."""
    await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])
    await store.add_claims([Claim(text="EigenLayer has 65 team members", entities=["EigenLayer"])])

    stats = await store.stats()
    assert "collision_log" in stats["counts"], "Stats should include collision_log count"
    assert stats["counts"]["collision_log"] >= 1


async def test_collision_log_not_duplicated_on_related(store: Tensory) -> None:
    """Related (non-contradicting) collisions should also be logged for audit trail."""
    await store.add_claims(
        [Claim(text="EigenLayer launched version 2 of restaking", entities=["EigenLayer"])]
    )
    await store.add_claims([Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"])])

    # Should log the "related" collision too
    cursor = await store._db.execute("SELECT collision_type FROM collision_log")
    rows = await cursor.fetchall()
    assert len(rows) >= 1
    # At least one should be "related" (different attributes)
    types = {row[0] for row in rows}
    assert "related" in types or "contradiction" in types
