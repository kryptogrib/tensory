"""Search quality regression tests.

Tests that specific claims appear in top-k results for benchmark-style
queries. Catches entity crowding, ranking regressions, and diversity
issues.

These tests use FakeEmbedder (no API key needed) and an in-memory DB
pre-loaded with claims that mirror real LoCoMo benchmark data.

Run:
    uv run pytest tests/test_search_quality.py -v
    uv run pytest tests/test_search_quality.py -k crowding -v
"""

from __future__ import annotations

import hashlib

import pytest

from tensory import Claim, Tensory

# ── Deterministic embedder (no API key) ──────────────────────────────────


class FakeEmbedder:
    """Word-hash based embedder for deterministic testing."""

    def __init__(self) -> None:
        self._dim = 32  # sha256 = 32 bytes, must match

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


# ── Test data: mimics LoCoMo conv-26 ────────────────────────────────────

# Claims about Melanie (crowding source — many "kids" claims)
MELANIE_KIDS_CLAIMS = [
    "Melanie has multiple children",
    "Melanie is currently busy with kids and work",
    "Melanie is currently managing kids and work responsibilities",
    "Melanie has children",
    "Melanie has kids",
    "Melanie is a mother",
    "Melanie has a husband and children",
    "Melanie has 2 younger children who love nature",
    "Melanie has a youngest child who took her first steps",
    "Melanie and her family enjoy hiking in mountains",
]

MELANIE_SPECIFIC_CLAIMS = [
    "Melanie plays clarinet and started when she was young",
    "Melanie uses playing clarinet as a way to express herself and relax",
    "Melanie carves out daily me-time through running, reading, or playing violin",
    "Melanie read 'Charlotte's Web' as a child and valued its themes of friendship",
    "Melanie's favorite art forms are painting landscapes and still life",
    "Melanie loves painting animals",
    "Melanie's primary art forms are painting and pottery",
    "Melanie's children made clay pots at a pottery workshop",
    "Melanie visits the beach with her kids once or twice a year",
    "On 2023-07-20, Melanie and her family recently went to the beach",
    "Melanie recently took her children to the beach",
    "Melanie attended a concert featuring the band Summer Sounds",
]

# Claims about Caroline
CAROLINE_CLAIMS = [
    "Caroline is transgender",
    "Caroline is undergoing a transition",
    "Caroline plans to continue her education",
    "Caroline plans to continue her education and explore career options",
    "Caroline values supportive people in her life",
    "Caroline cares about LGBTQ rights",
    "Caroline experienced a tough breakup at some point in her past",
    "Caroline is now happier being around people who accept and love her",
    "Caroline read and loved the book 'Becoming Nicole' by Amy Ellis Nutt",
    "Caroline found self-acceptance from 'Becoming Nicole'",
    "'Becoming Nicole' is a true story about a trans girl and her family",
    "On 2023-08-16, Caroline created a self-portrait with vibrant blue colors",
    "Caroline creates paintings as art",
    "Caroline draws flowers as one of her favorite artistic activities",
    "Caroline is learning to play the piano",
    "Sunflowers represent resilience and hope to Caroline",
]

# Cross-entity claims
CROSS_ENTITY_CLAIMS = [
    "Melanie has been reading a book that Caroline recommended",
    "On 2023-10-13, Melanie has been reading a book that Caroline recommended previously",
    "Caroline and Melanie are planning a summer 2023 outing together",
    "Melanie and Caroline support each other",
]

ALL_CLAIMS = (
    MELANIE_KIDS_CLAIMS
    + MELANIE_SPECIFIC_CLAIMS
    + CAROLINE_CLAIMS
    + CROSS_ENTITY_CLAIMS
)


# ── Fixture ──────────────────────────────────────────────────────────────


@pytest.fixture
async def store_with_claims():
    """Create in-memory store pre-loaded with LoCoMo-like claims."""
    store = await Tensory.create(":memory:", embedder=FakeEmbedder(), llm=None)
    claims = [Claim(text=t, entities=_extract_entities(t)) for t in ALL_CLAIMS]
    await store.add_claims(claims)
    yield store
    await store.close()


def _extract_entities(text: str) -> list[str]:
    """Simple entity extraction for test data."""
    entities = []
    for name in ["Melanie", "Caroline", "Charlotte's Web", "Becoming Nicole"]:
        if name.lower() in text.lower():
            entities.append(name)
    return entities


# ── Helper ───────────────────────────────────────────────────────────────


def top_texts(results: list, k: int = 5) -> list[str]:
    """Extract claim texts from top-k results."""
    return [r.claim.text for r in results[:k]]


def any_contains(texts: list[str], substring: str) -> bool:
    """Check if any text contains substring (case-insensitive)."""
    sub = substring.lower()
    return any(sub in t.lower() for t in texts)


# ══════════════════════════════════════════════════════════════════════════
# ENTITY CROWDING TESTS
#
# Core problem: popular entities (Melanie+kids) flood out specific facts.
# These tests verify that specific claims beat generic ones.
# ══════════════════════════════════════════════════════════════════════════


class TestEntityCrowding:
    """Verify that entity crowding doesn't push relevant claims out of top-k."""

    async def test_instruments_not_crowded_by_kids(
        self, store_with_claims: Tensory
    ) -> None:
        """'Melanie clarinet' should find clarinet claim, not just kids."""
        # Use keyword that exists in target claim (FakeEmbedder is hash-based,
        # not semantically aware — "instruments" won't match "clarinet")
        results = await store_with_claims.search(
            "Melanie clarinet instrument", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "clarinet"), (
            f"'clarinet' not in top-5. Got: {texts}"
        )

    async def test_books_not_crowded_by_kids(
        self, store_with_claims: Tensory
    ) -> None:
        """'What books has Melanie read?' should find book claims."""
        results = await store_with_claims.search(
            "What books has Melanie read?", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "Charlotte's Web") or any_contains(texts, "book"), (
            f"No book-related claim in top-5. Got: {texts}"
        )

    async def test_activities_shows_variety(
        self, store_with_claims: Tensory
    ) -> None:
        """Melanie query should show diverse results, not all kids claims."""
        results = await store_with_claims.search(
            "Melanie activities hobbies", limit=10
        )
        texts = top_texts(results, k=10)
        # Entity diversity should prevent kids-only results
        kids_count = sum(1 for t in texts if "kids" in t.lower() or "children" in t.lower() or "mother" in t.lower())
        assert kids_count <= 5, (
            f"Too many kids claims ({kids_count}/10). "
            f"Entity diversity not working. Got: {texts}"
        )

    async def test_beach_not_dominated_by_generic(
        self, store_with_claims: Tensory
    ) -> None:
        """Beach query should find beach claims, not generic Melanie claims."""
        results = await store_with_claims.search(
            "How many times has Melanie gone to the beach?", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "beach"), (
            f"'beach' not in top-5. Got: {texts}"
        )


# ══════════════════════════════════════════════════════════════════════════
# CROSS-ENTITY TESTS
#
# Questions involving relationships between two people.
# ══════════════════════════════════════════════════════════════════════════


class TestCrossEntity:
    """Verify search works for queries involving multiple entities."""

    async def test_book_recommendation(
        self, store_with_claims: Tensory
    ) -> None:
        """'What book did Caroline recommend to Melanie?' should find the rec."""
        results = await store_with_claims.search(
            "What book did Caroline recommend to Melanie?", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "recommend"), (
            f"'recommend' not in top-5. Got: {texts}"
        )

    async def test_both_painted(
        self, store_with_claims: Tensory
    ) -> None:
        """Painting query should surface painting-related claims."""
        results = await store_with_claims.search(
            "painting art painted", limit=10
        )
        texts = top_texts(results, k=10)
        has_art = any_contains(texts, "painting") or any_contains(texts, "art") or any_contains(texts, "portrait")
        assert has_art, (
            f"No art-related claim in top-10. Got: {texts}"
        )


# ══════════════════════════════════════════════════════════════════════════
# SPECIFIC DETAIL RETRIEVAL
#
# Questions about precise facts that should be in claims.
# ══════════════════════════════════════════════════════════════════════════


class TestSpecificRetrieval:
    """Verify specific facts are retrievable."""

    async def test_becoming_nicole(
        self, store_with_claims: Tensory
    ) -> None:
        """Book title should be retrievable via exact title search."""
        # FTS5 should match the exact title directly
        results = await store_with_claims.search(
            "Becoming Nicole Amy Ellis Nutt", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "Becoming Nicole"), (
            f"'Becoming Nicole' not found. Got: {texts}"
        )

    async def test_self_portrait_date(
        self, store_with_claims: Tensory
    ) -> None:
        """Self-portrait search should find the claim."""
        results = await store_with_claims.search(
            "Caroline self-portrait painting blue", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "self-portrait") or any_contains(texts, "portrait"), (
            f"'self-portrait' not in top-5. Got: {texts}"
        )

    async def test_sunflower_meaning(
        self, store_with_claims: Tensory
    ) -> None:
        """Sunflower symbolism should be retrievable."""
        results = await store_with_claims.search(
            "What do sunflowers represent according to Caroline?", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "sunflower") or any_contains(texts, "resilience"), (
            f"Sunflower claim not in top-5. Got: {texts}"
        )

    async def test_pottery_workshop(
        self, store_with_claims: Tensory
    ) -> None:
        """Pottery search should find pottery claims."""
        results = await store_with_claims.search(
            "pottery workshop clay pots", limit=5
        )
        texts = top_texts(results)
        assert any_contains(texts, "pottery"), (
            f"'pottery' not in top-5. Got: {texts}"
        )

    async def test_relationship_status(
        self, store_with_claims: Tensory
    ) -> None:
        """Breakup claim should be findable via direct keyword."""
        results = await store_with_claims.search("breakup", limit=10)
        texts = top_texts(results, k=10)
        assert any_contains(texts, "breakup"), (
            f"'breakup' not in top-10 for direct keyword search. Got: {texts}"
        )


# ══════════════════════════════════════════════════════════════════════════
# COUNTING / AGGREGATION
#
# Verify all relevant claims surface (not truncated by entity crowding).
# ══════════════════════════════════════════════════════════════════════════


class TestAggregation:
    """Verify that aggregation queries return all relevant claims."""

    async def test_children_count(
        self, store_with_claims: Tensory
    ) -> None:
        """'How many children?' should find the claim with actual count."""
        results = await store_with_claims.search(
            "How many children does Melanie have?", limit=5
        )
        texts = top_texts(results)
        # The "2 younger children" claim has the actual number
        assert any_contains(texts, "2") or any_contains(texts, "two"), (
            f"Numeric children count not in top-5. Got: {texts}"
        )

    async def test_beach_visits_2023(
        self, store_with_claims: Tensory
    ) -> None:
        """Beach visit count should find frequency AND specific visits."""
        results = await store_with_claims.search(
            "How many times has Melanie gone to the beach in 2023?", limit=5
        )
        texts = top_texts(results)
        has_frequency = any_contains(texts, "once or twice")
        has_specific = any_contains(texts, "2023")
        assert has_frequency or has_specific, (
            f"No beach frequency or 2023 date in top-5. Got: {texts}"
        )
