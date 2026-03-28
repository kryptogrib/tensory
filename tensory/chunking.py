"""Text chunking and segmentation for hybrid extraction.

Provides token estimation, paragraph splitting (fallback), and
section header construction for multi-pass extraction of long texts.

References:
- Think Council verdict: topic segmentation over sliding window
- max_segments formula prevents over-splitting short texts
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Protocol, cast, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class LLMCallable(Protocol):
    """Any async callable (str) -> str. Separate from extract.LLMProtocol to avoid circular imports."""

    async def __call__(self, prompt: str) -> str: ...


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


def normalize_entity(name: str) -> str:
    """Normalize entity name for comparison.

    Lowercase + strip. Does NOT use LLM — pure string normalization.
    Handles: "Bitcoin" = "BITCOIN" = " bitcoin ".
    Does NOT handle: "ETH" ≠ "Ethereum" (abbreviation resolution
    requires an alias table, not string matching).
    """
    return name.strip().lower()


def deduplicate_entities(entities: list[str]) -> list[str]:
    """Deduplicate entity names, keeping first-seen form as canonical.

    Uses normalize_entity() for comparison. Returns unique entities
    in order of first appearance.
    """
    seen: dict[str, str] = {}  # normalized → first-seen original
    for entity in entities:
        key = normalize_entity(entity)
        if key not in seen:
            seen[key] = entity
    return list(seen.values())


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


async def segment_text(
    text: str,
    llm: LLMCallable,
    *,
    max_segments: int,
) -> list[tuple[str, str]]:
    """Split text into thematic sections via LLM.

    Returns list of (title, text) tuples. Falls back to paragraph
    splitting if LLM fails (graceful degradation).
    """
    from tensory.prompts import TOPIC_SEGMENTATION_PROMPT

    prompt = TOPIC_SEGMENTATION_PROMPT.format(
        text=text,
        max_segments=max_segments,
    )

    try:
        response = await llm(prompt)
        sections = _parse_segmentation(response, max_segments=max_segments)
        if sections:
            return sections
    except Exception as exc:
        logger.warning("Topic segmentation failed, falling back to paragraphs: %s", exc)

    # Fallback: paragraph splitting
    paragraphs = split_by_paragraphs(text, max_sections=max_segments)
    return [("", para) for para in paragraphs]


def _parse_segmentation(
    response: str,
    *,
    max_segments: int,
) -> list[tuple[str, str]]:
    """Parse LLM segmentation response into (title, text) tuples."""
    raw = response.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Failed to parse segmentation response as JSON")
        return []

    sections: list[tuple[str, str]] = []
    for item in cast(list[dict[str, Any]], data.get("sections", [])):
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        if text:
            sections.append((title, text))

    # Enforce max_segments cap
    if len(sections) > max_segments:
        kept = sections[: max_segments - 1]
        overflow_text = "\n\n".join(s[1] for s in sections[max_segments - 1 :])
        overflow_title = sections[max_segments - 1][0]
        kept.append((overflow_title, overflow_text))
        return kept

    return sections
