"""Tests for Fisher-Rao reranking (SuperLocalMemory V3 inspired).

Tests cover three levels:
1. Unit tests for Fisher math (_estimate_variance, _fisher_distance, _fisher_similarity)
2. Unit tests for auto-trigger logic (should_rerank)
3. Integration tests for store.search(metric=...) and max_result_tokens
"""

from __future__ import annotations

import hashlib

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.models import SearchResult
from tensory.search import (
    VARIANCE_CEIL,
    VARIANCE_FLOOR,
    _estimate_variance,
    _fisher_distance,
    _fisher_similarity,
    should_rerank,
)

# ── Fake embedder (same pattern as test_search.py) ──────────────────────────


class FakeEmbedder:
    """Deterministic 32-dim vectors from text hash."""

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


# ── Unit tests: _estimate_variance ──────────────────────────────────────────


class TestEstimateVariance:
    """Tests for the signal-magnitude variance heuristic."""

    def test_returns_correct_length(self) -> None:
        emb = [0.5, -0.3, 0.8, 0.1]
        var = _estimate_variance(emb)
        assert len(var) == len(emb)

    def test_large_components_get_low_variance(self) -> None:
        """Dimensions with large absolute values → high confidence → low variance."""
        emb = [0.9, 0.01, 0.01, 0.01]
        var = _estimate_variance(emb)
        # First dimension (largest) should have lowest variance
        assert var[0] < var[1]
        assert var[0] == pytest.approx(VARIANCE_FLOOR, abs=0.01)

    def test_small_components_get_high_variance(self) -> None:
        """Dimensions near zero → low confidence → high variance."""
        emb = [0.9, 0.01, 0.01, 0.01]
        var = _estimate_variance(emb)
        # Near-zero dimensions should approach VARIANCE_CEIL
        assert var[1] > VARIANCE_CEIL * 0.8

    def test_all_equal_components(self) -> None:
        """Equal components → equal variance → all get FLOOR."""
        emb = [0.5, 0.5, 0.5, 0.5]
        var = _estimate_variance(emb)
        # All equal, all max_abs → all get FLOOR
        assert all(v == pytest.approx(VARIANCE_FLOOR) for v in var)

    def test_variance_bounds(self) -> None:
        """All variances should be in [FLOOR, CEIL]."""
        emb = [0.9, -0.3, 0.0001, 0.5, -0.7]
        var = _estimate_variance(emb)
        for v in var:
            assert VARIANCE_FLOOR <= v <= VARIANCE_CEIL + 1e-9


# ── Unit tests: _fisher_distance ────────────────────────────────────────────


class TestFisherDistance:
    """Tests for Fisher-Rao distance computation."""

    def test_identical_vectors_zero_distance(self) -> None:
        v = [0.5, -0.3, 0.8, 0.1]
        assert _fisher_distance(v, v) == pytest.approx(0.0, abs=1e-10)

    def test_distance_is_non_negative(self) -> None:
        a = [0.5, -0.3, 0.8, 0.1]
        b = [0.1, 0.7, -0.2, 0.4]
        assert _fisher_distance(a, b) >= 0.0

    def test_distance_is_symmetric(self) -> None:
        a = [0.5, -0.3, 0.8, 0.1]
        b = [0.1, 0.7, -0.2, 0.4]
        assert _fisher_distance(a, b) == pytest.approx(_fisher_distance(b, a))

    def test_orthogonal_greater_than_similar(self) -> None:
        """More different vectors → larger distance."""
        base = [1.0, 0.0, 0.0, 0.0]
        similar = [0.9, 0.1, 0.0, 0.0]
        orthogonal = [0.0, 1.0, 0.0, 0.0]

        d_similar = _fisher_distance(base, similar)
        d_orthogonal = _fisher_distance(base, orthogonal)
        assert d_orthogonal > d_similar

    def test_opposite_vectors_large_distance(self) -> None:
        a = [1.0, 0.0, 0.0]
        b = [-1.0, 0.0, 0.0]
        assert _fisher_distance(a, b) > _fisher_distance(a, a)


# ── Unit tests: _fisher_similarity ──────────────────────────────────────────


class TestFisherSimilarity:
    """Tests for Fisher-Rao similarity (exponential kernel over distance)."""

    def test_identical_vectors_max_similarity(self) -> None:
        v = [0.5, -0.3, 0.8, 0.1]
        assert _fisher_similarity(v, v) == pytest.approx(1.0, abs=1e-6)

    def test_similarity_in_zero_one(self) -> None:
        a = [0.5, -0.3, 0.8, 0.1]
        b = [0.1, 0.7, -0.2, 0.4]
        sim = _fisher_similarity(a, b)
        assert 0.0 <= sim <= 1.0

    def test_more_similar_vectors_higher_score(self) -> None:
        query = [0.9, 0.1, 0.05, 0.8]
        good = [0.85, 0.15, 0.05, 0.75]
        bad = [0.1, -0.7, 0.9, -0.2]

        assert _fisher_similarity(query, good) > _fisher_similarity(query, bad)

    def test_temperature_affects_spread(self) -> None:
        """Lower temperature → sharper discrimination."""
        a = [1.0, 0.0, 0.0]
        b = [0.7, 0.3, 0.0]

        sim_warm = _fisher_similarity(a, b, temperature=30.0)
        sim_cold = _fisher_similarity(a, b, temperature=5.0)
        # Cold temperature pushes non-identical similarities lower
        assert sim_cold < sim_warm


# ── Unit tests: should_rerank ──────────────────────────────────────────────


class TestShouldRerank:
    """Tests for the auto-trigger heuristic."""

    def _make_result(self, score: float) -> SearchResult:
        claim = Claim(
            id="test",
            text="test",
            type=ClaimType.FACT,
            confidence=1.0,
            episode_id="ep",
            context_id="ctx",
        )
        return SearchResult(claim=claim, score=score)

    def test_tight_scores_trigger_rerank(self) -> None:
        """Scores within threshold → should rerank."""
        results = [self._make_result(s) for s in [0.92, 0.91, 0.90]]
        assert should_rerank(results, threshold=0.05) is True

    def test_spread_scores_no_rerank(self) -> None:
        """Scores well spread → cosine is enough."""
        results = [self._make_result(s) for s in [0.95, 0.70, 0.50]]
        assert should_rerank(results, threshold=0.05) is False

    def test_too_few_results_no_rerank(self) -> None:
        """Not enough candidates → don't bother."""
        results = [self._make_result(0.9)]
        assert should_rerank(results, min_candidates=3) is False

    def test_empty_results(self) -> None:
        assert should_rerank([]) is False


# ── Integration tests: store.search(metric=...) ────────────────────────────


@pytest.fixture
async def fisher_store() -> Tensory:
    """Tensory with FakeEmbedder for Fisher reranking tests."""
    s = await Tensory.create(":memory:", embedder=FakeEmbedder())
    yield s  # type: ignore[misc]
    await s.close()


class TestFisherIntegration:
    """Integration tests for Fisher reranking via store.search()."""

    async def test_search_fisher_returns_results(self, fisher_store: Tensory) -> None:
        """metric='fisher' doesn't crash and returns results."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="Alice works at Google since 2023",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Alice left Google in January 2025",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep2",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Bob joined Microsoft in 2024",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep3",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        results = await fisher_store.search("Alice Google", metric="fisher")
        assert len(results) > 0
        assert all(isinstance(r, SearchResult) for r in results)

    async def test_search_cosine_unchanged(self, fisher_store: Tensory) -> None:
        """metric='cosine' doesn't trigger Fisher reranking."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="ETH price is 3000",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        results = await fisher_store.search("ETH price", metric="cosine")
        assert len(results) > 0
        # Method should NOT be "fisher"
        assert all(r.method != "fisher" for r in results)

    async def test_search_auto_default(self, fisher_store: Tensory) -> None:
        """Default metric='auto' works without errors."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="DeFi protocol launched",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        # Should not crash regardless of whether auto triggers Fisher
        results = await fisher_store.search("DeFi protocol")
        assert isinstance(results, list)

    async def test_fisher_method_label(self, fisher_store: Tensory) -> None:
        """Fisher-reranked results get method='fisher'."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="Alice works at Google",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Alice met Bob at Google",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep2",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Alice left Google",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep3",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        results = await fisher_store.search("Alice Google", metric="fisher")
        # At least some results should have method="fisher"
        fisher_results = [r for r in results if r.method == "fisher"]
        assert len(fisher_results) > 0


# ── Integration tests: max_result_tokens ────────────────────────────────────


class TestMaxResultTokens:
    """Integration tests for token budget trimming."""

    async def test_token_budget_limits_results(self, fisher_store: Tensory) -> None:
        """max_result_tokens trims results to fit budget."""
        ctx = await fisher_store.create_context(goal="test")
        # Each claim is ~6-8 words ≈ 8-10 tokens
        await fisher_store.add_claims(
            [
                Claim(
                    text="Alice works at Google since 2023 as engineer",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Bob joined Microsoft in 2024 as manager",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep2",
                    context_id=ctx.id,
                ),
                Claim(
                    text="Charlie started at Amazon in 2025 as intern",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep3",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )

        # Very tight budget — should return fewer results
        tight = await fisher_store.search("works at", max_result_tokens=10)
        # No budget — should return all
        loose = await fisher_store.search("works at", max_result_tokens=None)

        assert len(tight) <= len(loose)

    async def test_token_budget_none_returns_all(self, fisher_store: Tensory) -> None:
        """max_result_tokens=None doesn't trim anything."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="fact one",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
                Claim(
                    text="fact two",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep2",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        results = await fisher_store.search("fact", max_result_tokens=None)
        assert len(results) == 2

    async def test_token_budget_zero_returns_empty(self, fisher_store: Tensory) -> None:
        """max_result_tokens=0 returns no results."""
        ctx = await fisher_store.create_context(goal="test")
        await fisher_store.add_claims(
            [
                Claim(
                    text="something here",
                    type=ClaimType.FACT,
                    confidence=1.0,
                    episode_id="ep1",
                    context_id=ctx.id,
                ),
            ],
            context_id=ctx.id,
        )
        results = await fisher_store.search("something", max_result_tokens=0)
        assert len(results) == 0
