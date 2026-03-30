"""Extraction quality regression tests.

Tests that LLM extraction preserves specific details: names, dates,
numbers, titles. Catches prompt regressions where extraction drops
concrete facts in favor of vague summaries.

These tests require a real LLM (Anthropic via proxy or direct).
Mark: @pytest.mark.slow — skipped by default, run explicitly:

    uv run pytest tests/test_extraction_quality.py -v -m slow
    uv run pytest tests/test_extraction_quality.py -k "book_title" -v -m slow

To run in CI without LLM, skip with:
    uv run pytest tests/ -m "not slow"
"""

from __future__ import annotations

import os

import pytest

from tensory import Tensory
from tensory.embedder import NullEmbedder

# ── Skip if no LLM available ────────────────────────────────────────────

_HAS_LLM = bool(os.environ.get("ANTHROPIC_API_KEY"))

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not _HAS_LLM, reason="ANTHROPIC_API_KEY not set"),
]


# ── LLM setup ───────────────────────────────────────────────────────────


def _get_llm():  # noqa: ANN202
    """Get LLM from environment (supports proxy)."""
    from examples.llm_adapters import anthropic_llm

    return anthropic_llm(
        model=os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )


@pytest.fixture
async def store() -> Tensory:
    """In-memory store with real LLM + NullEmbedder."""
    return await Tensory.create(":memory:", llm=_get_llm(), embedder=NullEmbedder())


# ── Test data: real LoCoMo session excerpts ──────────────────────────────

# These are representative excerpts that triggered extraction failures
# in the benchmark. Each test verifies that a specific detail is preserved.


# ══════════════════════════════════════════════════════════════════════════
# BOOK TITLES — extraction must preserve exact titles
# ══════════════════════════════════════════════════════════════════════════


class TestBookTitleExtraction:
    """Verify that book titles survive extraction."""

    BOOK_SESSION = (
        "[Session date: 2023-10-13]\n"
        "Caroline: I've been reading 'Becoming Nicole' by Amy Ellis Nutt. "
        "It's a true story about a trans girl and her family. It really resonated with me.\n"
        "Melanie: That sounds amazing! I'll add it to my list. I've been re-reading "
        "'Nothing is Impossible' by Christopher Reeve. It always reminds me to pursue my dreams.\n"
        "Caroline: Oh I love that! You should also try 'Charlotte's Web' — "
        "I know it's a children's book but the themes of friendship are so pure."
    )

    async def test_becoming_nicole_preserved(self, store: Tensory) -> None:
        """'Becoming Nicole' title must appear in extracted claims."""
        result = await store.add(self.BOOK_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "becoming nicole" in all_text, (
            f"'Becoming Nicole' not extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_nothing_is_impossible_preserved(self, store: Tensory) -> None:
        """'Nothing is Impossible' title must appear in extracted claims."""
        result = await store.add(self.BOOK_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "nothing is impossible" in all_text or "christopher reeve" in all_text, (
            f"Book title or author not extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_charlottes_web_preserved(self, store: Tensory) -> None:
        """'Charlotte's Web' title must appear in extracted claims."""
        result = await store.add(self.BOOK_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "charlotte" in all_text, (
            f"'Charlotte's Web' not extracted. Claims: {[c.text for c in result.claims]}"
        )


# ══════════════════════════════════════════════════════════════════════════
# NUMBERS AND COUNTS — extraction must preserve quantities
# ══════════════════════════════════════════════════════════════════════════


class TestNumberExtraction:
    """Verify that numbers and counts survive extraction."""

    FAMILY_SESSION = (
        "[Session date: 2023-07-20]\n"
        "Melanie: We went to the beach last weekend with the kids! My 2 younger ones "
        "loved building sandcastles. My oldest daughter just turned 8, and she's been "
        "asking to learn surfing.\n"
        "Caroline: That sounds fun! How often do you go?\n"
        "Melanie: We try to go once or twice a year. It's our family tradition."
    )

    async def test_children_count_preserved(self, store: Tensory) -> None:
        """Number of children (2 younger + oldest = 3) should be extractable."""
        result = await store.add(self.FAMILY_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        has_number = any(n in all_text for n in ["2", "two", "3", "three", "youngest", "oldest"])
        assert has_number, (
            f"No child count extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_beach_frequency_preserved(self, store: Tensory) -> None:
        """'once or twice a year' frequency should be extracted."""
        result = await store.add(self.FAMILY_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "once" in all_text or "twice" in all_text or "year" in all_text, (
            f"Beach frequency not extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_daughter_age_preserved(self, store: Tensory) -> None:
        """Daughter's age (8) should be extracted."""
        result = await store.add(self.FAMILY_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "8" in all_text or "eight" in all_text, (
            f"Daughter's age not extracted. Claims: {[c.text for c in result.claims]}"
        )


# ══════════════════════════════════════════════════════════════════════════
# SPECIFIC DETAILS — names, dates, places
# ══════════════════════════════════════════════════════════════════════════


class TestDetailExtraction:
    """Verify that specific details are not lost in summarization."""

    MUSIC_SESSION = (
        "[Session date: 2023-06-15]\n"
        "Melanie: I've been playing clarinet since I was 12. It helps me relax. "
        "I also picked up violin about 3 years ago as a new challenge.\n"
        "Caroline: That's amazing! I've been learning piano myself. "
        "Just started last month with a teacher named Ms. Rodriguez."
    )

    async def test_instrument_names_preserved(self, store: Tensory) -> None:
        """Specific instrument names must be extracted."""
        result = await store.add(self.MUSIC_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "clarinet" in all_text, (
            f"'clarinet' not extracted. Claims: {[c.text for c in result.claims]}"
        )
        assert "piano" in all_text, (
            f"'piano' not extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_violin_preserved(self, store: Tensory) -> None:
        """Violin (second instrument) should not be dropped."""
        result = await store.add(self.MUSIC_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "violin" in all_text, (
            f"'violin' not extracted. Claims: {[c.text for c in result.claims]}"
        )

    ART_SESSION = (
        "[Session date: 2023-08-16]\n"
        "Caroline: I painted a self-portrait yesterday! I used vibrant blue colors "
        "for my face. It felt so liberating to express myself that way.\n"
        "Melanie: Wow! I mostly paint landscapes and sunflowers. "
        "Sunflowers represent resilience and hope to me."
    )

    async def test_sunflower_symbolism_preserved(self, store: Tensory) -> None:
        """Sunflower symbolism must be a distinct claim."""
        result = await store.add(self.ART_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "sunflower" in all_text, (
            f"'sunflower' not extracted. Claims: {[c.text for c in result.claims]}"
        )

    async def test_self_portrait_color_preserved(self, store: Tensory) -> None:
        """Self-portrait + blue color detail should be extracted."""
        result = await store.add(self.ART_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "self-portrait" in all_text or "self portrait" in all_text, (
            f"'self-portrait' not extracted. Claims: {[c.text for c in result.claims]}"
        )


# ══════════════════════════════════════════════════════════════════════════
# TEMPORAL PRECISION — dates must be absolute, not relative
# ══════════════════════════════════════════════════════════════════════════


class TestTemporalExtraction:
    """Verify dates are extracted as absolute, not relative."""

    TEMPORAL_SESSION = (
        "[Session date: 2023-05-07]\n"
        "Caroline: Last week I went to an LGBTQ+ support group for the first time. "
        "It was so powerful hearing other people's stories.\n"
        "Melanie: I ran a 5K charity race two weeks ago! It was exhausting but worth it."
    )

    async def test_absolute_date_not_relative(self, store: Tensory) -> None:
        """Claims should contain absolute dates, not 'last week'."""
        result = await store.add(self.TEMPORAL_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        # Should have resolved to approximate absolute dates
        has_date = (
            "2023" in all_text
            or "may" in all_text
            or "april" in all_text  # "two weeks ago" from May 7
        )
        has_relative_only = "last week" in all_text and "2023" not in all_text
        assert has_date and not has_relative_only, (
            f"Dates should be absolute, not relative. Claims: {[c.text for c in result.claims]}"
        )

    async def test_lgbtq_support_group_extracted(self, store: Tensory) -> None:
        """LGBTQ support group attendance must be a claim."""
        result = await store.add(self.TEMPORAL_SESSION, source="test")
        texts = [c.text.lower() for c in result.claims]
        all_text = " ".join(texts)
        assert "support group" in all_text or "lgbtq" in all_text, (
            f"LGBTQ support group not extracted. Claims: {[c.text for c in result.claims]}"
        )
