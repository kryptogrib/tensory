"""Tests for chunking — token estimation, paragraph splitting, segmentation."""

from __future__ import annotations

import json


def test_estimate_tokens_short() -> None:
    """estimate_tokens returns approximate token count."""
    from tensory.chunking import estimate_tokens

    assert estimate_tokens("hello world") == 2


def test_estimate_tokens_long() -> None:
    """Longer text returns proportional token estimate."""
    from tensory.chunking import estimate_tokens

    text = "word " * 1000
    result = estimate_tokens(text)
    assert 900 <= result <= 1100


def test_max_segments_formula() -> None:
    """max_segments is proportional to token count, minimum 2."""
    from tensory.chunking import compute_max_segments

    assert compute_max_segments(100) == 2
    assert compute_max_segments(3000) == 2
    assert compute_max_segments(6000) == 2
    assert compute_max_segments(9000) == 3
    assert compute_max_segments(15000) == 5


def test_split_by_paragraphs() -> None:
    """split_by_paragraphs splits on double newlines."""
    from tensory.chunking import split_by_paragraphs

    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    sections = split_by_paragraphs(text, max_sections=2)
    assert len(sections) == 2
    assert "First paragraph." in sections[0]
    assert "Third paragraph." in sections[1]


def test_split_by_paragraphs_no_split_needed() -> None:
    """Single paragraph returns as-is."""
    from tensory.chunking import split_by_paragraphs

    text = "Just one paragraph with no double newlines."
    sections = split_by_paragraphs(text, max_sections=5)
    assert len(sections) == 1
    assert sections[0] == text


def test_build_section_header() -> None:
    """build_section_header creates context header for a section."""
    from tensory.chunking import build_section_header

    header = build_section_header(
        document_date="2026-03-15",
        section_index=2,
        total_sections=5,
        section_title="Market Analysis",
    )
    assert "2026-03-15" in header
    assert "3 of 5" in header
    assert "Market Analysis" in header


# ── Fake LLM for segmentation ───────────────────────────────────────────


class FakeSegmentLLM:
    """Returns topic segmentation JSON."""

    def __init__(self, num_sections: int = 3) -> None:
        self.num_sections = num_sections
        self.call_count = 0

    async def __call__(self, prompt: str) -> str:
        self.call_count += 1
        sections = []
        for i in range(self.num_sections):
            sections.append(
                {
                    "title": f"Topic {i + 1}",
                    "text": f"Content of section {i + 1}. Some details here.",
                }
            )
        return json.dumps({"sections": sections})


# ── Segmentation tests ──────────────────────────────────────────────────


async def test_segment_text_returns_sections() -> None:
    """segment_text returns list of (title, text) tuples."""
    from tensory.chunking import segment_text

    text = "Section 1 content.\n\nSection 2 content.\n\nSection 3 content."
    llm = FakeSegmentLLM(num_sections=2)
    sections = await segment_text(text, llm, max_segments=3)

    assert len(sections) == 2
    assert all(isinstance(s, tuple) and len(s) == 2 for s in sections)
    assert sections[0][0] == "Topic 1"
    assert "Content of section 1" in sections[0][1]


async def test_segment_text_respects_max_segments() -> None:
    """segment_text caps at max_segments even if LLM returns more."""
    from tensory.chunking import segment_text

    text = "A long text with many topics."
    llm = FakeSegmentLLM(num_sections=10)
    sections = await segment_text(text, llm, max_segments=3)

    assert len(sections) <= 3


async def test_segment_text_fallback_on_llm_failure() -> None:
    """segment_text falls back to paragraph splitting on LLM error."""
    from tensory.chunking import segment_text

    async def broken_llm(prompt: str) -> str:
        raise RuntimeError("LLM offline")

    text = "Para one.\n\nPara two.\n\nPara three."
    sections = await segment_text(text, broken_llm, max_segments=3)

    assert len(sections) >= 2
    assert all(isinstance(s, tuple) for s in sections)


def test_segmentation_prompt_has_placeholders() -> None:
    """TOPIC_SEGMENTATION_PROMPT has required placeholders."""
    from tensory.prompts import TOPIC_SEGMENTATION_PROMPT

    assert "{text}" in TOPIC_SEGMENTATION_PROMPT
    assert "{max_segments}" in TOPIC_SEGMENTATION_PROMPT


# ── Entity normalization tests ───────────────────────────────────────────


def test_normalize_entity_basic() -> None:
    """normalize_entity lowercases and strips whitespace."""
    from tensory.chunking import normalize_entity

    assert normalize_entity("  Bitcoin  ") == "bitcoin"
    assert normalize_entity("ETHEREUM") == "ethereum"
    assert normalize_entity("EigenLayer") == "eigenlayer"


def test_normalize_entity_preserves_structure() -> None:
    """normalize_entity keeps meaningful separators."""
    from tensory.chunking import normalize_entity

    assert normalize_entity("Vitalik Buterin") == "vitalik buterin"
    assert normalize_entity("BTC/USDT") == "btc/usdt"


def test_deduplicate_entities() -> None:
    """deduplicate_entities merges similar entity names."""
    from tensory.chunking import deduplicate_entities

    entities = ["Bitcoin", "bitcoin", "BITCOIN", "Ethereum", "ethereum"]
    unique = deduplicate_entities(entities)

    assert len(unique) == 2
    assert "Bitcoin" in unique
    assert "Ethereum" in unique
