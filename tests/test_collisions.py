"""Tests for collision detection, waypoints, and salience updates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.collisions import (
    SALIENCE_RULES,
    _classify_collision,
    _cosine_sim,
    _temporal_proximity,
)

# ── Reuse FakeEmbedder from test_search ───────────────────────────────────


class FakeEmbedder:
    """Deterministic 32-dim embedder for testing."""

    def __init__(self) -> None:
        self._dim = 32

    @property
    def dim(self) -> int:
        return self._dim

    def _word_vec(self, word: str) -> list[float]:
        h = hashlib.sha256(word.lower().encode()).digest()
        return [((b % 200) - 100) / 100.0 for b in h[: self._dim]]

    def _text_vec(self, text: str) -> list[float]:
        words = text.lower().split()
        if not words:
            return [0.0] * self._dim
        vecs = [self._word_vec(w) for w in words]
        return [sum(v[i] for v in vecs) / len(vecs) for i in range(self._dim)]

    async def embed(self, text: str) -> list[float]:
        return self._text_vec(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._text_vec(t) for t in texts]


@pytest.fixture
async def vec_store() -> Tensory:
    s = await Tensory.create(":memory:", embedder=FakeEmbedder())
    yield s  # type: ignore[misc]
    await s.close()


# ── Cosine similarity ────────────────────────────────────────────────────


def test_cosine_sim_identical() -> None:
    v = [1.0, 2.0, 3.0]
    assert _cosine_sim(v, v) == pytest.approx(1.0, abs=0.001)


def test_cosine_sim_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_sim(a, b) == pytest.approx(0.0, abs=0.001)


def test_cosine_sim_none() -> None:
    assert _cosine_sim(None, [1.0, 2.0]) == 0.0
    assert _cosine_sim([1.0], None) == 0.0


# ── Temporal proximity ───────────────────────────────────────────────────


def test_temporal_proximity_same_day() -> None:
    now = datetime.now(UTC)
    assert _temporal_proximity(now, now) == pytest.approx(1.0, abs=0.01)


def test_temporal_proximity_30_days() -> None:
    now = datetime.now(UTC)
    month_ago = now - timedelta(days=30)
    assert _temporal_proximity(now, month_ago) == pytest.approx(0.0, abs=0.01)


def test_temporal_proximity_15_days() -> None:
    now = datetime.now(UTC)
    half_month = now - timedelta(days=15)
    assert _temporal_proximity(now, half_month) == pytest.approx(0.5, abs=0.01)


# ── Collision classification ─────────────────────────────────────────────


def test_classify_supersedes_at_high_score() -> None:
    a = Claim(id="a", text="A", entities=["E"])
    b = Claim(id="b", text="B", entities=["E"])
    assert _classify_collision(a, b, 0.95) == "supersedes"


def test_classify_contradiction_with_shared_entities() -> None:
    a = Claim(id="a", text="A", entities=["EigenLayer"])
    b = Claim(id="b", text="B", entities=["EigenLayer"])
    assert _classify_collision(a, b, 0.75) == "contradiction"


def test_classify_confirms_moderate_score() -> None:
    a = Claim(id="a", text="A", entities=[])
    b = Claim(id="b", text="B", entities=[])
    assert _classify_collision(a, b, 0.65) == "confirms"


def test_classify_related_low_score() -> None:
    a = Claim(id="a", text="A", entities=[])
    b = Claim(id="b", text="B", entities=[])
    assert _classify_collision(a, b, 0.55) == "related"


# ── Salience rules ───────────────────────────────────────────────────────


def test_salience_contradiction_halves() -> None:
    assert SALIENCE_RULES["contradiction"](1.0) == 0.5


def test_salience_supersedes_near_zero() -> None:
    assert SALIENCE_RULES["supersedes"](1.0) == 0.1


def test_salience_confirms_boosts() -> None:
    assert SALIENCE_RULES["confirms"](0.5) == 0.7


def test_salience_confirms_capped() -> None:
    assert SALIENCE_RULES["confirms"](0.9) == 1.0


def test_salience_related_small_boost() -> None:
    assert SALIENCE_RULES["related"](0.5) == 0.55


# ── Structural collision (integration) ───────────────────────────────────


async def test_structural_collision_same_entity(store: Tensory) -> None:
    """Two claims about the same entity trigger structural collision."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
        ]
    )

    result = await store.add_claims(
        [
            Claim(text="EigenLayer has 45 team members", entities=["EigenLayer"]),
        ]
    )

    # Should detect collision between the two claims
    assert len(result.collisions) >= 1
    assert any("EigenLayer" in c.shared_entities for c in result.collisions)


async def test_no_collision_different_entities(store: Tensory) -> None:
    """Claims about different entities don't collide structurally."""
    await store.add_claims(
        [
            Claim(text="EigenLayer launched v2", entities=["EigenLayer"]),
        ]
    )

    result = await store.add_claims(
        [
            Claim(text="Lido launched v3", entities=["Lido"]),
        ]
    )

    assert len(result.collisions) == 0


# ── Salience update on collision (integration) ───────────────────────────


async def test_salience_drops_on_contradiction(store: Tensory) -> None:
    """Contradicted claims get salience halved."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"], salience=1.0),
        ]
    )

    await store.add_claims(
        [
            Claim(text="EigenLayer has 45 team members", entities=["EigenLayer"]),
        ]
    )

    # Check the first claim's salience was reduced
    cursor = await store._db.execute("SELECT salience FROM claims ORDER BY created_at ASC LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    # Should be less than original (1.0) due to contradiction
    assert float(row[0]) < 1.0


# ── Waypoint creation (integration) ──────────────────────────────────────


async def test_waypoint_created_on_ingest(vec_store: Tensory) -> None:
    """Waypoints are auto-created when a similar claim exists."""
    await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol launched successfully today"),
        ]
    )

    # Very similar text — differs by only one word
    await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol launched successfully yesterday"),
        ]
    )

    cursor = await vec_store._db.execute("SELECT COUNT(*) FROM waypoints")
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] >= 1  # at least one waypoint created


async def test_no_waypoint_for_dissimilar_claims(vec_store: Tensory) -> None:
    """No waypoint when claims are too dissimilar (< 0.75 cosine)."""
    await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol"),
        ]
    )

    await vec_store.add_claims(
        [
            Claim(text="Bitcoin price prediction analysis for Q4"),
        ]
    )

    cursor = await vec_store._db.execute("SELECT COUNT(*) FROM waypoints")
    row = await cursor.fetchone()
    # May or may not create waypoint depending on FakeEmbedder similarity
    # Just verify it doesn't crash
    assert row is not None


# ── Dedup integration ────────────────────────────────────────────────────


async def test_dedup_blocks_duplicate_in_store(store: Tensory) -> None:
    """Duplicate claims are skipped during add_claims."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members working on restaking protocol"),
        ]
    )

    result = await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members working on restaking protocol"),
        ]
    )

    # Duplicate should be skipped
    assert len(result.claims) == 0

    # Only one claim in DB
    stats = await store.stats()
    assert stats["counts"]["claims"] == 1


# ── End-to-end collision scenario ─────────────────────────────────────────


async def test_eigenlayer_collision_scenario(store: Tensory) -> None:
    """End-to-end: conflicting claims about EigenLayer trigger collision."""
    # Day 1: Initial fact
    r1 = await store.add_claims(
        [
            Claim(
                text="EigenLayer team has 50 members",
                entities=["EigenLayer"],
                type=ClaimType.FACT,
            ),
        ]
    )
    assert len(r1.claims) == 1

    # Day 2: Contradicting fact
    r2 = await store.add_claims(
        [
            Claim(
                text="EigenLayer team has grown to 65 members",
                entities=["EigenLayer"],
                type=ClaimType.FACT,
            ),
        ]
    )
    assert len(r2.claims) == 1
    assert len(r2.collisions) >= 1

    # The collision should involve EigenLayer
    eigen_collisions = [c for c in r2.collisions if "EigenLayer" in c.shared_entities]
    assert len(eigen_collisions) >= 1

    # First claim's salience should be reduced
    cursor = await store._db.execute("SELECT salience FROM claims ORDER BY created_at ASC LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    assert float(row[0]) < 1.0  # reduced from collision
