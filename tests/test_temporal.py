"""Tests for temporal.py and Phase 4 store methods."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.temporal import apply_decay, supersede

# ── Fake LLM ──────────────────────────────────────────────────────────────


class FakeLLM:
    """Returns pre-configured extraction response."""

    def __init__(self) -> None:
        self.response = json.dumps(
            {
                "claims": [
                    {
                        "text": "EigenLayer has 50 team members",
                        "type": "fact",
                        "entities": ["EigenLayer"],
                        "confidence": 0.9,
                        "relevance": 0.8,
                    },
                    {
                        "text": "Google partnered with EigenLayer",
                        "type": "fact",
                        "entities": ["Google", "EigenLayer"],
                        "confidence": 0.85,
                        "relevance": 0.9,
                    },
                ],
                "relations": [
                    {
                        "from": "Google",
                        "to": "EigenLayer",
                        "type": "PARTNERED_WITH",
                        "fact": "Google partnered with EigenLayer for restaking",
                    }
                ],
            }
        )

    async def __call__(self, prompt: str) -> str:
        return self.response


@pytest.fixture
async def llm_store() -> Tensory:
    """Store with FakeLLM for extraction testing."""
    s = await Tensory.create(":memory:", llm=FakeLLM())
    yield s  # type: ignore[misc]
    await s.close()


# ── store.add() tests ────────────────────────────────────────────────────


async def test_add_text_extracts_claims(llm_store: Tensory) -> None:
    """add() extracts claims from raw text via LLM."""
    ctx = await llm_store.create_context(goal="Track DeFi teams", domain="crypto")

    result = await llm_store.add(
        "Google announced partnership with EigenLayer for cloud restaking...",
        source="reddit:r/defi",
        context=ctx,
    )

    assert result.episode_id
    assert len(result.claims) >= 1
    assert len(result.relations) >= 1

    # Episode should be stored
    stats = await llm_store.stats()
    assert stats["counts"]["episodes"] == 1


async def test_add_without_llm_raises(store: Tensory) -> None:
    """add() without LLM raises ValueError."""
    with pytest.raises(ValueError, match="LLM required"):
        await store.add("some text")


async def test_add_stores_episode(llm_store: Tensory) -> None:
    """Raw text is stored as episode (Layer 0 — raw never dies)."""
    result = await llm_store.add("Raw text content", source="test")

    cursor = await llm_store._db.execute(
        "SELECT raw_text, source FROM episodes WHERE id = ?",
        (result.episode_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Raw text content"
    assert row[1] == "test"


# ── reevaluate() tests ───────────────────────────────────────────────────


async def test_reevaluate_extracts_new_claims() -> None:
    """reevaluate() re-extracts from old episode with new context."""
    # First LLM returns DeFi claims
    llm1_response = json.dumps(
        {
            "claims": [
                {
                    "text": "EigenLayer DeFi team tracking",
                    "type": "fact",
                    "entities": ["EigenLayer"],
                }
            ],
            "relations": [],
        }
    )

    class SwitchingLLM:
        def __init__(self) -> None:
            self.call_count = 0

        async def __call__(self, prompt: str) -> str:
            self.call_count += 1
            if self.call_count == 1:
                return llm1_response
            # Second call returns different claims for new context
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "Google AI strategy partnership",
                            "type": "fact",
                            "entities": ["Google"],
                        }
                    ],
                    "relations": [],
                }
            )

    store = await Tensory.create(":memory:", llm=SwitchingLLM())
    ctx1 = await store.create_context(goal="Track DeFi teams")
    r1 = await store.add("EigenLayer and Google news...", context=ctx1)

    ctx2 = await store.create_context(goal="Track Big Tech AI")
    r2 = await store.reevaluate(r1.episode_id, ctx2)

    assert r2.episode_id == r1.episode_id
    assert len(r2.claims) >= 1
    await store.close()


async def test_reevaluate_nonexistent_episode(llm_store: Tensory) -> None:
    """reevaluate() on missing episode raises ValueError."""
    ctx = await llm_store.create_context(goal="Test")
    with pytest.raises(ValueError, match="not found"):
        await llm_store.reevaluate("nonexistent_id", ctx)


# ── timeline() tests ─────────────────────────────────────────────────────


async def test_timeline_shows_claims(store: Tensory) -> None:
    """timeline() returns claims about an entity in chronological order."""
    await store.add_claims(
        [
            Claim(text="EigenLayer v1 launched", entities=["EigenLayer"]),
            Claim(text="EigenLayer v2 announced", entities=["EigenLayer"]),
            Claim(text="Lido update", entities=["Lido"]),
        ]
    )

    tl = await store.timeline("EigenLayer")
    assert len(tl) == 2
    assert all("EigenLayer" in c.text for c in tl)


async def test_timeline_excludes_superseded(store: Tensory) -> None:
    """timeline() can exclude superseded claims."""
    r = await store.add_claims(
        [
            Claim(text="EigenLayer has 50 members", entities=["EigenLayer"]),
            Claim(text="EigenLayer has 60 members", entities=["EigenLayer"]),
        ]
    )

    # Manually supersede the first
    await supersede(r.claims[0].id, r.claims[1].id, store._db)

    tl_all = await store.timeline("EigenLayer", include_superseded=True)
    tl_active = await store.timeline("EigenLayer", include_superseded=False)

    assert len(tl_all) == 2
    assert len(tl_active) == 1


# ── supersede() tests ────────────────────────────────────────────────────


async def test_supersede_marks_old_claim(store: Tensory) -> None:
    """supersede() marks old claim with timestamp and reference."""
    r = await store.add_claims(
        [
            Claim(text="Old fact", entities=["X"]),
            Claim(text="New fact", entities=["X"]),
        ]
    )

    await supersede(r.claims[0].id, r.claims[1].id, store._db)

    cursor = await store._db.execute(
        "SELECT superseded_at, superseded_by, salience FROM claims WHERE id = ?",
        (r.claims[0].id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row["superseded_at"] is not None
    assert row["superseded_by"] == r.claims[1].id
    assert float(row["salience"]) < 0.5  # salience * 0.1


# ── apply_decay() tests ──────────────────────────────────────────────────


async def test_decay_reduces_salience(store: Tensory) -> None:
    """apply_decay() reduces salience based on time elapsed."""
    await store.add_claims(
        [
            Claim(text="Old claim", type=ClaimType.OPINION),
        ]
    )

    # Manually set created_at to 30 days ago
    thirty_days_ago = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    await store._db.execute(
        "UPDATE claims SET created_at = ?, last_accessed = NULL",
        (thirty_days_ago,),
    )
    await store._db.commit()

    updated = await apply_decay(store._db)
    assert updated >= 1

    cursor = await store._db.execute("SELECT salience FROM claims LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    # OPINION decay_rate=0.020, 30 days → e^(-0.020 * 30) ≈ 0.549
    assert float(row[0]) < 0.6


# ── consolidate() tests ──────────────────────────────────────────────────


async def test_consolidate_creates_observations(store: Tensory) -> None:
    """consolidate() groups claims with shared entities into observations."""
    # Create distinct claims sharing entities (avoid dedup triggering)
    await store.add_claims(
        [
            Claim(
                text="EigenLayer announced a major protocol upgrade in March",
                entities=["EigenLayer", "Protocol"],
            ),
            Claim(
                text="The EigenLayer team presented their protocol roadmap at ETHDenver",
                entities=["EigenLayer", "Protocol"],
            ),
            Claim(
                text="EigenLayer protocol audit was completed by Trail of Bits",
                entities=["EigenLayer", "Protocol"],
            ),
        ]
    )

    obs = await store.consolidate(days=30, min_cluster=3)
    assert len(obs) >= 1
    assert obs[0].type == ClaimType.OBSERVATION
    assert "Pattern:" in obs[0].text
    assert obs[0].salience == pytest.approx(0.8, abs=0.05)


async def test_consolidate_ignores_small_clusters(store: Tensory) -> None:
    """consolidate() ignores clusters smaller than min_cluster."""
    await store.add_claims(
        [
            Claim(text="Claim A", entities=["X", "Y"]),
            Claim(text="Claim B", entities=["X", "Y"]),
        ]
    )

    obs = await store.consolidate(days=30, min_cluster=3)
    assert len(obs) == 0


# ── source_stats() tests ─────────────────────────────────────────────────


async def test_source_stats_empty(store: Tensory) -> None:
    """source_stats() returns zeros for unknown source."""
    stats = await store.source_stats("unknown_source")
    assert stats["total_claims"] == 0
    assert stats["avg_salience"] == 0.0


async def test_source_stats_with_data(llm_store: Tensory) -> None:
    """source_stats() returns profile for known source."""
    await llm_store.add(
        "EigenLayer news text here",
        source="reddit:r/defi",
    )

    stats = await llm_store.source_stats("reddit:r/defi")
    assert stats["source"] == "reddit:r/defi"
    assert stats["total_claims"] >= 1
    assert stats["avg_salience"] > 0


# ── cleanup() tests ──────────────────────────────────────────────────────


async def test_cleanup_removes_old_superseded(store: Tensory) -> None:
    """cleanup() removes old superseded low-salience claims."""
    r = await store.add_claims(
        [
            Claim(text="Old superseded claim"),
        ]
    )

    # Supersede it and make it old
    await store._db.execute(
        """UPDATE claims SET
           superseded_at = '2020-01-01', superseded_by = 'newer',
           salience = 0.001, created_at = '2020-01-01'
           WHERE id = ?""",
        (r.claims[0].id,),
    )
    await store._db.commit()

    removed = await store.cleanup(max_age_days=1)
    assert removed >= 1
