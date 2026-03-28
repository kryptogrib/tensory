"""Tests for chunking — token estimation, paragraph splitting, segmentation."""

from __future__ import annotations


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
