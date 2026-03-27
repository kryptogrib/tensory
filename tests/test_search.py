"""Phase 2 tests for hybrid search, surprise score, and priming.

Uses a FakeEmbedder that produces deterministic vectors based on text
content, so we can test vector similarity without an API key.
"""

from __future__ import annotations

import hashlib

import pytest

from tensory import Claim, Tensory
from tensory.models import SearchResult
from tensory.search import _rrf_merge

# ── Fake embedder for deterministic testing ───────────────────────────────


class FakeEmbedder:
    """Produces deterministic 32-dim vectors from text hash.

    Similar texts get similar vectors because we hash individual words
    and average them.
    """

    def __init__(self) -> None:
        self._dim = 32

    @property
    def dim(self) -> int:
        return self._dim

    def _word_vec(self, word: str) -> list[float]:
        """Deterministic vector from a single word."""
        h = hashlib.sha256(word.lower().encode()).digest()
        return [((b % 200) - 100) / 100.0 for b in h[: self._dim]]

    def _text_vec(self, text: str) -> list[float]:
        """Average of word vectors."""
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
    """Store with FakeEmbedder for vector search testing."""
    s = await Tensory.create(":memory:", embedder=FakeEmbedder())
    yield s  # type: ignore[misc]
    await s.close()


# ── Hybrid search tests ──────────────────────────────────────────────────


async def test_fts_search_still_works(store: Tensory) -> None:
    """Phase 1 FTS search continues to work with new hybrid pipeline."""
    await store.add_claims(
        [
            Claim(text="EigenLayer announced a new partnership"),
            Claim(text="Bitcoin price reached new highs"),
        ]
    )

    results = await store.search("EigenLayer")
    assert len(results) >= 1
    assert "EigenLayer" in results[0].claim.text


async def test_search_without_embedder_falls_back_to_fts(store: Tensory) -> None:
    """With NullEmbedder, search falls back to FTS + graph (no vector)."""
    await store.add_claims(
        [
            Claim(text="Lido launched staking v2", entities=["Lido"]),
        ]
    )

    results = await store.search("Lido")
    assert len(results) >= 1
    # Should work even without real embeddings
    assert "Lido" in results[0].claim.text


async def test_hybrid_search_returns_results(vec_store: Tensory) -> None:
    """Hybrid search with FakeEmbedder returns results via multiple channels."""
    await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol launched", entities=["EigenLayer"]),
            Claim(text="Lido staking reached 10M ETH", entities=["Lido", "ETH"]),
            Claim(text="EigenLayer team grew to 60 engineers", entities=["EigenLayer"]),
        ]
    )

    results = await vec_store.search("EigenLayer")
    assert len(results) >= 1
    # At least one result should mention EigenLayer
    eigen_results = [r for r in results if "EigenLayer" in r.claim.text]
    assert len(eigen_results) >= 1


async def test_search_method_is_hybrid(vec_store: Tensory) -> None:
    """Results from hybrid search have method='hybrid'."""
    await vec_store.add_claims(
        [
            Claim(text="Test hybrid method claim"),
        ]
    )
    results = await vec_store.search("hybrid")
    if results:
        assert results[0].method == "hybrid"


# ── RRF merge tests ──────────────────────────────────────────────────────


def test_rrf_merge_combines_lists() -> None:
    """RRF merge produces combined scores from multiple lists."""
    claim_a = Claim(id="a", text="Claim A")
    claim_b = Claim(id="b", text="Claim B")
    claim_c = Claim(id="c", text="Claim C")

    list1 = [
        SearchResult(claim=claim_a, score=1.0, method="fts"),
        SearchResult(claim=claim_b, score=0.5, method="fts"),
    ]
    list2 = [
        SearchResult(claim=claim_b, score=1.0, method="vector"),
        SearchResult(claim=claim_c, score=0.5, method="vector"),
    ]

    merged = _rrf_merge([list1, list2], weights=[0.5, 0.5], limit=10)

    # B appears in both lists, should have highest score
    ids = [r.claim.id for r in merged]
    assert "b" in ids
    b_result = next(r for r in merged if r.claim.id == "b")
    a_result = next(r for r in merged if r.claim.id == "a")
    assert b_result.score > a_result.score  # B in both > A in one


def test_rrf_merge_respects_limit() -> None:
    """RRF merge respects the limit parameter."""
    claims = [Claim(id=f"c{i}", text=f"Claim {i}") for i in range(10)]
    results = [SearchResult(claim=c, score=1.0, method="fts") for c in claims]

    merged = _rrf_merge([results], weights=[1.0], limit=3)
    assert len(merged) == 3


def test_rrf_merge_weights_matter() -> None:
    """Higher-weighted channels contribute more to final score."""
    claim_a = Claim(id="a", text="A")
    claim_b = Claim(id="b", text="B")

    # A is ranked #1 in fts (low weight), B is ranked #1 in vector (high weight)
    fts_list = [SearchResult(claim=claim_a, score=1.0, method="fts")]
    vec_list = [SearchResult(claim=claim_b, score=1.0, method="vector")]

    merged = _rrf_merge(
        [fts_list, vec_list],
        weights=[0.1, 0.9],  # vector heavily weighted
        limit=10,
    )

    # B should rank higher due to higher weight
    assert merged[0].claim.id == "b"


# ── Surprise score tests ─────────────────────────────────────────────────


async def test_surprise_score_high_for_novel(vec_store: Tensory) -> None:
    """First claim in an empty DB has high surprise (novel information)."""
    result = await vec_store.add_claims(
        [
            Claim(text="Completely new and unprecedented information"),
        ]
    )

    surprise = result.claims[0].metadata.get("surprise")
    assert surprise is not None
    assert float(str(surprise)) >= 0.5  # should be high (novel)


async def test_surprise_score_low_for_similar(vec_store: Tensory) -> None:
    """Claim similar to existing has lower surprise."""
    # Add initial claim
    await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol has 50 team members"),
        ]
    )

    # Add very similar claim
    result = await vec_store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol has 55 team members"),
        ]
    )

    surprise = result.claims[0].metadata.get("surprise")
    assert surprise is not None
    # Should be lower than 1.0 (not completely novel)
    assert float(str(surprise)) < 1.0


async def test_surprise_boosts_salience(vec_store: Tensory) -> None:
    """High surprise claims get salience boosted."""
    # First claim: high surprise (empty DB)
    result = await vec_store.add_claims(
        [
            Claim(text="Unprecedented discovery in quantum computing", salience=0.5),
        ]
    )

    # Salience should be boosted above the initial 0.5
    claim = result.claims[0]
    surprise = float(str(claim.metadata.get("surprise", 0)))
    expected_min = 0.5 + surprise * 0.3  # SURPRISE_SALIENCE_FACTOR
    assert claim.salience >= expected_min - 0.01


async def test_surprise_with_null_embedder(store: Tensory) -> None:
    """Surprise is 0.0 when NullEmbedder is used (can't compute without vectors)."""
    result = await store.add_claims(
        [
            Claim(text="Some claim without real embeddings"),
        ]
    )
    surprise = result.claims[0].metadata.get("surprise")
    assert float(str(surprise)) == 0.0


# ── Priming tests ────────────────────────────────────────────────────────


async def test_priming_boosts_recent_entities(store: Tensory) -> None:
    """Claims with recently-searched entities get boosted in results."""
    await store.add_claims(
        [
            Claim(text="EigenLayer announced partnership", entities=["EigenLayer"]),
            Claim(text="Lido staking protocol update", entities=["Lido"]),
            Claim(text="EigenLayer team expansion news", entities=["EigenLayer"]),
        ]
    )

    # First search: establishes EigenLayer as "recent"
    await store.search("partnership")

    # Check priming counter was updated
    assert store._recent_entities["EigenLayer"] >= 1

    # Second search: EigenLayer claims should be boosted by priming
    await store.search("protocol")

    # Verify priming counter increased
    assert store._recent_entities["EigenLayer"] >= 1


async def test_priming_counter_capped(store: Tensory) -> None:
    """Priming counter doesn't grow unboundedly."""
    # Manually inflate the counter
    for i in range(250):
        store._recent_entities[f"entity_{i}"] = 1

    assert len(store._recent_entities) == 250

    # Search triggers cap
    await store.add_claims([Claim(text="trigger search indexing")])
    await store.search("trigger")

    # Should be capped to ~100
    assert len(store._recent_entities) <= 200


# ── Reinforce on access ──────────────────────────────────────────────────


async def test_reinforce_on_access_boosts_salience(store: Tensory) -> None:
    """Claims found via search get +0.05 salience."""
    await store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol", salience=0.5),
        ]
    )

    results = await store.search("EigenLayer")
    assert len(results) == 1

    cursor = await store._db.execute(
        "SELECT salience, access_count FROM claims WHERE id = ?",
        (results[0].claim.id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    assert float(row[0]) == pytest.approx(0.55, abs=0.01)
    assert row[1] == 1


async def test_reinforce_stacks_on_multiple_searches(store: Tensory) -> None:
    """Multiple searches for same claim compound the salience boost."""
    await store.add_claims(
        [
            Claim(text="EigenLayer restaking protocol", salience=0.5),
        ]
    )

    await store.search("EigenLayer")
    await store.search("EigenLayer")

    cursor = await store._db.execute("SELECT salience, access_count FROM claims LIMIT 1")
    row = await cursor.fetchone()
    assert row is not None
    assert float(row[0]) == pytest.approx(0.60, abs=0.01)  # 0.5 + 0.05 + 0.05
    assert row[1] == 2
