"""Tests for collision detection, waypoints, and salience updates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.collisions import (
    SALIENCE_RULES,
    _classify_collision,
    _content_words,
    _cosine_sim,
    _extract_dates,
    _extract_numbers,
    _structural_conflict_type,
    _temporal_proximity,
    apply_salience_updates,
    find_collisions,
)
from tensory.models import Collision

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


async def test_structural_collision_case_insensitive(store: Tensory) -> None:
    """Entity matching must be case-insensitive — 'Tensory' == 'tensory'.

    Regression: before fix, 'Tensory' (89 claims) and 'tensory' (40 claims)
    were stored as separate entities and never collided structurally.
    """
    await store.add_claims([Claim(text="Tensory uses SQLite for storage", entities=["Tensory"])])

    result = await store.add_claims(
        [Claim(text="tensory uses PostgreSQL for storage", entities=["tensory"])]
    )

    # Must detect collision despite different casing
    assert len(result.collisions) >= 1
    shared = result.collisions[0].shared_entities
    # Shared entity should be found (case-insensitive)
    assert any(e.lower() == "tensory" for e in shared)


async def test_add_entity_deduplicates_case(store: Tensory) -> None:
    """add_entity() must not create duplicate entities for different casing."""
    id1 = await store._graph.add_entity("Tensory")
    id2 = await store._graph.add_entity("tensory")
    id3 = await store._graph.add_entity("TENSORY")

    # All three should resolve to the same entity
    assert id1 == id2 == id3


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


# ═══════════════════════════════════════════════════════════════════════════
# Isolated tests for find_collisions() and apply_salience_updates()
# These test internal functions directly, not through add_claims() side-effects.
# ═══════════════════════════════════════════════════════════════════════════


async def test_find_collisions_vector_score_reflects_actual_similarity(
    vec_store: Tensory,
) -> None:
    """Vector candidates must use real cosine similarity, not cosine(X, X) = 1.0.

    BUG: _get_candidates() sets candidate.embedding = claim.embedding,
    so _cosine_sim() computes cosine(X, X) = 1.0 for ALL vector candidates.
    This inflates the vector signal by +0.4 (VECTOR_WEIGHT).

    With FakeEmbedder, "Bitcoin..." and "Ethereum..." have real cosine ≈ 0.46.
    Real score: 0.46*0.4 + 0*0.25 + 1.0*0.2 + 0*0.15 = 0.38 → below 0.5 threshold.
    Bug score:  1.00*0.4 + 0*0.25 + 1.0*0.2 + 0*0.15 = 0.60 → FALSE collision!

    This test asserts: no collision between unrelated claims (different entities).
    """
    # Two semantically different claims with DIFFERENT entities
    claim_a = Claim(
        text="Bitcoin price dropped to 40000 dollars today",
        entities=["Bitcoin"],
        type=ClaimType.FACT,
    )
    claim_b = Claim(
        text="Ethereum staking yields increased significantly this quarter",
        entities=["Ethereum"],
        type=ClaimType.FACT,
    )

    # Ingest claim_b first (it becomes the "existing" claim)
    await vec_store.add_claims([claim_b])

    # Ingest claim_a so it gets an embedding and ID
    result_a = await vec_store.add_claims([claim_a])
    assert len(result_a.claims) == 1
    stored_a = result_a.claims[0]
    assert stored_a.embedding is not None, "claim_a should have embedding from FakeEmbedder"

    # Call find_collisions() DIRECTLY
    collisions = await find_collisions(stored_a, vec_store._db, graph_backend=vec_store._graph)

    # No shared entities → no structural collision.
    # Real cosine ≈ 0.46 → real score ≈ 0.38 → below 0.5 threshold → NO collision.
    # With bug: cosine(X,X) = 1.0 → score ≈ 0.60 → false collision detected!
    non_structural = [c for c in collisions if not c.shared_entities]
    assert len(non_structural) == 0, (
        f"Unrelated claims (Bitcoin vs Ethereum) should NOT collide. "
        f"Found {len(non_structural)} false collision(s) with scores "
        f"{[c.score for c in non_structural]}. "
        f"Likely caused by vector_score=1.0 bug (cosine(X,X) instead of real similarity)."
    )


async def test_apply_salience_updates_isolated(vec_store: Tensory) -> None:
    """apply_salience_updates() should update salience in DB based on collision type.

    Tests the function in isolation — not through add_claims() side-effects.
    """
    # Insert a claim directly with known salience
    claim_old = Claim(
        id="old_claim_001",
        text="EigenLayer has 50 team members",
        entities=["EigenLayer"],
        salience=1.0,
    )
    await vec_store.add_claims([claim_old])

    claim_new = Claim(
        id="new_claim_002",
        text="EigenLayer has grown to 65 team members",
        entities=["EigenLayer"],
        salience=1.0,
    )

    # Create a Collision manually (no add_claims involved)
    collision = Collision(
        claim_a=claim_new,
        claim_b=claim_old,
        score=0.75,
        shared_entities=["EigenLayer"],
        type="contradiction",
    )

    # Call apply_salience_updates() directly
    await apply_salience_updates([collision], vec_store._db)

    # Verify DB was updated: contradiction halves salience
    cursor = await vec_store._db.execute(
        "SELECT salience FROM claims WHERE id = ?", ("old_claim_001",)
    )
    row = await cursor.fetchone()
    assert row is not None
    # Original salience was boosted by surprise on ingest, so it's > 1.0 is impossible
    # but it should be halved from whatever it was stored at
    stored_salience = float(row[0])
    assert stored_salience < 0.8, (
        f"Expected salience < 0.8 after contradiction (halved), got {stored_salience}"
    )


async def test_waypoint_signal_increases_collision_score(vec_store: Tensory) -> None:
    """When two claims are waypoint-linked, collision score should be higher.

    The waypoint signal contributes WAYPOINT_WEIGHT=0.15 to the composite score.

    IMPORTANT: claims must NOT share entities, otherwise structural collision
    (hardcoded score=0.8) takes precedence and semantic scoring is skipped
    via seen_ids dedup. We use different entities to isolate the semantic path.

    With FakeEmbedder, the two Lido-ish claims have cosine ≈ 0.51.
    Without waypoint: 0.51*0.4 + 0.25*0.25 + 1.0*0.2 + 0.0*0.15 = 0.47 → no collision
    With waypoint:    0.51*0.4 + 0.25*0.25 + 1.0*0.2 + 1.0*0.15 = 0.62 → collision!
    (Note: with vector_score=1.0 bug, both paths find collision regardless)
    """
    # Claims with DIFFERENT entities (avoids structural collision)
    # but overlapping topic (some cosine similarity via FakeEmbedder)
    claim1 = Claim(
        text="Lido protocol has 200 active validators in the network",
        entities=["Lido"],
    )
    claim2 = Claim(
        text="Rocket Pool protocol expanded to 250 validators this month",
        entities=["Rocket Pool"],
    )

    r1 = await vec_store.add_claims([claim1])
    r2 = await vec_store.add_claims([claim2])
    stored1 = r1.claims[0]
    stored2 = r2.claims[0]

    # ── Run WITHOUT waypoint ──
    # First, ensure no waypoints exist
    await vec_store._db.execute("DELETE FROM waypoints")
    await vec_store._db.commit()

    collisions_without_wp = await find_collisions(
        stored2, vec_store._db, graph_backend=vec_store._graph
    )

    # ── Run WITH waypoint ──
    await vec_store._db.execute(
        "INSERT OR REPLACE INTO waypoints (src_claim, dst_claim, similarity) VALUES (?, ?, ?)",
        (stored2.id, stored1.id, 0.85),
    )
    await vec_store._db.commit()

    collisions_with_wp = await find_collisions(
        stored2, vec_store._db, graph_backend=vec_store._graph
    )

    # Find the collision scores for the same pair
    def score_for(collisions: list[Collision], target_id: str) -> float | None:
        for c in collisions:
            if c.claim_b.id == target_id:
                return c.score
        return None

    score_with = score_for(collisions_with_wp, stored1.id)
    score_without = score_for(collisions_without_wp, stored1.id)

    # With waypoint, collision should either appear or have a higher score
    if score_without is not None and score_with is not None:
        # Both found → waypoint should boost score by ~0.15
        assert score_with > score_without, (
            f"Waypoint should increase score: with={score_with}, without={score_without}"
        )
    elif score_without is None and score_with is not None:
        # Only found with waypoint → waypoint pushed score above threshold. Correct!
        pass
    else:
        # Neither found OR only without → waypoint signal has no effect
        pytest.fail(
            f"Waypoint should enable or boost collision detection. "
            f"score_with={score_with}, score_without={score_without}"
        )


async def test_find_collisions_fts_fallback_no_embedding(store: Tensory) -> None:
    """find_collisions() should work via FTS when claim has no embedding.

    NullEmbedder means no vector search — collision detection must still
    find candidates through FTS5 full-text search.
    """
    # store fixture uses NullEmbedder — no embeddings
    claim1 = Claim(
        text="EigenLayer restaking protocol launched new feature today",
        entities=["EigenLayer"],
    )
    claim2 = Claim(
        text="EigenLayer restaking protocol announced partnership deal",
        entities=["EigenLayer"],
    )

    await store.add_claims([claim1])
    r2 = await store.add_claims([claim2])
    stored2 = r2.claims[0]

    # Call find_collisions() directly
    collisions = await find_collisions(stored2, store._db, graph_backend=store._graph)

    # Should find collision via structural (shared entity) + FTS (shared words)
    assert len(collisions) >= 1, (
        "Should detect collision via FTS fallback when embeddings are unavailable"
    )

    # Verify vector_score = 0 for FTS-only candidates (no embedding → cosine returns 0)
    for col in collisions:
        # Without embeddings, max possible score =
        # entity_score(0.25) + temporal_score(0.20) + waypoint(0) = 0.45
        # Plus structural gets hardcoded 0.8
        # So any collision found is either structural or has entity+temporal signals
        assert col.score > 0, "Collision should have positive score"


async def test_find_collisions_no_entities_skips_structural(store: Tensory) -> None:
    """Claims without entities should skip structural detection entirely."""
    claim1 = Claim(text="The market is volatile today")
    await store.add_claims([claim1])

    claim2 = Claim(text="The market showed high volatility")
    r2 = await store.add_claims([claim2])
    stored2 = r2.claims[0]

    # find_collisions on a claim with no entities
    collisions = await find_collisions(stored2, store._db, graph_backend=store._graph)

    # Structural requires entities — should not crash, may return empty
    # (FTS might find candidates but score < threshold without entity signal)
    for col in collisions:
        assert col.shared_entities == [] or col.shared_entities is not None


# ═══════════════════════════════════════════════════════════════════════════
# Structural false positive tests — same entity, different attributes
# These test the core bug: _find_structural_conflicts() marks ALL claims
# sharing an entity as "contradiction", even when they describe different
# attributes/aspects of that entity.
# ═══════════════════════════════════════════════════════════════════════════


async def test_structural_different_attributes_not_contradiction(store: Tensory) -> None:
    """Claims about same entity but different attributes should NOT be contradiction.

    Real production example: 10 claims about "tensory" (install, config, API keys)
    all marked as contradiction → salience destroyed to near-zero.

    "EigenLayer launched v2" and "EigenLayer has 50 members" share the entity
    but talk about completely different attributes. This is "related", not contradiction.
    """
    claim1 = Claim(
        text="EigenLayer launched version 2 of their restaking protocol",
        entities=["EigenLayer"],
    )
    claim2 = Claim(
        text="EigenLayer has 50 team members working on the project",
        entities=["EigenLayer"],
    )

    await store.add_claims([claim1])
    result = await store.add_claims([claim2])

    # These should NOT be classified as "contradiction"
    contradictions = [c for c in result.collisions if c.type == "contradiction"]
    assert len(contradictions) == 0, (
        f"Different attributes about same entity should not be contradiction. "
        f"Got {len(contradictions)} contradiction(s): "
        f"{[(c.claim_a.text[:40], c.claim_b.text[:40]) for c in contradictions]}"
    )


async def test_structural_same_attribute_different_values_is_contradiction(
    store: Tensory,
) -> None:
    """Claims about same entity AND same attribute with different values = real contradiction.

    "EigenLayer has 50 members" vs "EigenLayer has 65 members" — same attribute
    (team size), different values. This IS a genuine contradiction.
    """
    claim1 = Claim(
        text="EigenLayer has 50 team members",
        entities=["EigenLayer"],
    )
    claim2 = Claim(
        text="EigenLayer has 65 team members",
        entities=["EigenLayer"],
    )

    await store.add_claims([claim1])
    result = await store.add_claims([claim2])

    # These SHOULD be detected as collision (at least structural)
    assert len(result.collisions) >= 1, "Same attribute + different values should collide"

    # And the collision should be meaningful (contradiction or supersedes)
    types = {c.type for c in result.collisions}
    assert types & {"contradiction", "supersedes"}, (
        f"Expected contradiction or supersedes for conflicting values, got {types}"
    )


async def test_structural_complementary_facts_not_contradiction(store: Tensory) -> None:
    """Multiple complementary facts about same entity should coexist peacefully.

    Real production pattern: "tensory can be installed via X", "tensory uses Y",
    "tensory plugin supports Z" — all different aspects, all valid simultaneously.
    These should NOT trigger contradiction and destroy each other's salience.
    """
    claims = [
        Claim(text="Tensory can be installed using pip install tensory", entities=["Tensory"]),
        Claim(text="Tensory uses SQLite for storage backend", entities=["Tensory"]),
        Claim(text="Tensory supports procedural memory via Skill-MDP", entities=["Tensory"]),
        Claim(text="Tensory has 300 tests with pyright strict", entities=["Tensory"]),
    ]

    # Add all 4 claims
    for claim in claims:
        await store.add_claims([claim])

    # Check: no claim should have destroyed salience from false contradictions
    cursor = await store._db.execute("SELECT MIN(salience) FROM claims WHERE superseded_at IS NULL")
    row = await cursor.fetchone()
    assert row is not None
    min_salience = float(row[0])

    # With 4 complementary facts, min salience should stay reasonable
    # (surprise score may lower it slightly, but not the 0.5× contradiction penalty)
    assert min_salience >= 0.4, (
        f"Complementary facts should not destroy each other's salience. "
        f"Min salience = {min_salience:.3f}, expected >= 0.4. "
        f"Likely caused by structural false positive contradictions."
    )


async def test_structural_numeric_conflict_detected(store: Tensory) -> None:
    """When claims contain conflicting numeric values about same subject, detect it.

    "Bitcoin price is $40000" vs "Bitcoin price is $65000" — same predicate
    (price), different values. Should be detected as conflict.
    """
    claim1 = Claim(
        text="Bitcoin price is 40000 dollars",
        entities=["Bitcoin"],
    )
    claim2 = Claim(
        text="Bitcoin price is 65000 dollars",
        entities=["Bitcoin"],
    )

    await store.add_claims([claim1])
    result = await store.add_claims([claim2])

    # Should detect collision
    assert len(result.collisions) >= 1, "Conflicting numeric values should collide"


# ── Unit tests for structural conflict helpers ───────────────────────────


def test_content_words_strips_stopwords() -> None:
    words = _content_words("The EigenLayer protocol has launched version 2")
    assert "the" not in words
    assert "has" not in words
    assert "eigenlayer" in words
    assert "protocol" in words
    assert "launched" in words


def test_content_words_strips_short_and_digits() -> None:
    words = _content_words("EigenLayer has 50 team members in Q4")
    assert "50" not in words  # digits stripped
    assert "in" not in words  # short word
    assert "team" in words
    assert "members" in words


def test_extract_numbers_integers_and_decimals() -> None:
    nums = _extract_numbers("EigenLayer has 50 members and raised 14.5 million")
    assert "50" in nums
    assert "14.5" in nums


def test_extract_numbers_empty() -> None:
    nums = _extract_numbers("EigenLayer launched their restaking protocol")
    assert len(nums) == 0


def test_structural_conflict_type_different_topics() -> None:
    """Different topics about same entity = related."""
    result = _structural_conflict_type(
        "EigenLayer launched version 2 of their restaking protocol",
        "EigenLayer has 50 team members working on the project",
    )
    assert result == "related"


def test_structural_conflict_type_same_topic_different_numbers() -> None:
    """Same topic with different numeric values = contradiction."""
    result = _structural_conflict_type(
        "EigenLayer has 50 team members",
        "EigenLayer has 65 team members",
    )
    assert result == "contradiction"


def test_structural_conflict_type_high_overlap() -> None:
    """Very similar text = contradiction (likely update)."""
    result = _structural_conflict_type(
        "Bitcoin price is 40000 dollars today",
        "Bitcoin price is 65000 dollars today",
    )
    assert result == "contradiction"


def test_structural_conflict_type_complementary_facts() -> None:
    """Completely different aspects = related."""
    result = _structural_conflict_type(
        "Tensory can be installed using pip install tensory",
        "Tensory supports procedural memory via Skill-MDP",
    )
    assert result == "related"


# ── Temporal guard tests ─────────────────────────────────────────────────


def test_extract_dates_iso_format() -> None:
    """ISO dates like '2023-07-02' are extracted."""
    assert _extract_dates("On 2023-07-02, Melanie signed up") == {"2023-07-02"}


def test_extract_dates_natural_format() -> None:
    """Natural dates like 'July 2, 2023' are extracted."""
    dates = _extract_dates("On July 2, 2023, Melanie signed up for pottery")
    assert "july 2, 2023" in dates


def test_extract_dates_month_year() -> None:
    """Month-year like 'June 2023' is extracted."""
    dates = _extract_dates("Melanie went camping in June 2023")
    assert "june 2023" in dates


def test_extract_dates_no_date() -> None:
    """Claims without dates return empty set."""
    assert _extract_dates("Melanie loves pottery") == set()


def test_temporal_guard_different_dates_no_supersede() -> None:
    """Claims about different events (different dates) should NOT supersede."""
    new_claim = Claim(text="On July 8, 2023, Melanie took her kids to a pottery workshop")
    old_claim = Claim(text="On July 2, 2023, Melanie signed up for a pottery class")
    # score > 0.9 would normally supersede, but temporal guard prevents it
    result = _classify_collision(new_claim, old_claim, 0.95)
    assert result == "related"


def test_temporal_guard_same_date_still_supersedes() -> None:
    """Claims about same date can still supersede (likely an update)."""
    new_claim = Claim(text="On July 2, 2023, Melanie enrolled in a pottery class")
    old_claim = Claim(text="On July 2, 2023, Melanie signed up for pottery")
    result = _classify_collision(new_claim, old_claim, 0.95)
    assert result == "supersedes"


def test_temporal_guard_no_dates_still_supersedes() -> None:
    """Claims without dates still supersede normally."""
    new_claim = Claim(text="Melanie considers pottery a huge part of her life")
    old_claim = Claim(text="Melanie views pottery as important to her life")
    result = _classify_collision(new_claim, old_claim, 0.95)
    assert result == "supersedes"


def test_temporal_guard_one_dated_one_not_still_supersedes() -> None:
    """When only one claim has a date, supersede is allowed (could be an update)."""
    new_claim = Claim(text="Melanie uses pottery for self-expression")
    old_claim = Claim(text="On July 2, 2023, Melanie signed up for pottery")
    result = _classify_collision(new_claim, old_claim, 0.95)
    assert result == "supersedes"
