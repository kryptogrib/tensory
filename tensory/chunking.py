"""Text chunking and segmentation for hybrid extraction.

Provides token estimation, paragraph splitting (fallback), and
section header construction for multi-pass extraction of long texts.

References:
- Think Council verdict: topic segmentation over sliding window
- max_segments formula prevents over-splitting short texts
"""

from __future__ import annotations

import re


def estimate_tokens(text: str) -> int:
    """Estimate token count from text (words ≈ tokens for English).

    This is a cheap heuristic — no tokenizer dependency needed.
    Accuracy: ±15% for English text, good enough for threshold dispatch.
    """
    return len(text.split())


def compute_max_segments(token_count: int) -> int:
    """Compute maximum segments allowed for a given token count.

    Formula: max(2, tokens // 3000)
    Ensures short-ish texts (3001 tokens) get at most 2 segments,
    while very long texts scale proportionally.
    """
    return max(2, token_count // 3000)


def split_by_paragraphs(text: str, *, max_sections: int) -> list[str]:
    """Split text by double newlines (paragraph boundaries).

    Fallback chunking strategy when LLM segmentation fails.
    Merges paragraphs to stay within max_sections limit.
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    if len(paragraphs) <= max_sections:
        return paragraphs if paragraphs else [text]

    # Distribute paragraphs evenly across max_sections
    sections: list[str] = []
    per_section = max(1, len(paragraphs) // max_sections)
    for i in range(0, len(paragraphs), per_section):
        chunk = "\n\n".join(paragraphs[i : i + per_section])
        sections.append(chunk)

    # Merge overflow into last section
    while len(sections) > max_sections:
        last = sections.pop()
        sections[-1] = sections[-1] + "\n\n" + last

    return sections


def build_section_header(
    *,
    document_date: str | None = None,
    section_index: int,
    total_sections: int,
    section_title: str = "",
) -> str:
    """Build a context header to prepend to each section before extraction.

    Preserves document-level metadata (date, section position) that would
    be lost if we just sent the raw section text to the LLM.
    """
    parts: list[str] = []
    parts.append(f"[Section {section_index + 1} of {total_sections}]")
    if section_title:
        parts.append(f"Topic: {section_title}")
    if document_date:
        parts.append(f"Document date: {document_date}")
    return " | ".join(parts)
