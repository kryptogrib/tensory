"""Tests for hybrid extraction — long text → topic segmentation → parallel extract."""

from __future__ import annotations

import json

import pytest

from tensory.models import Context


class FakeHybridLLM:
    """Handles both segmentation and extraction prompts."""

    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)

        if "Split this text" in prompt or "thematic sections" in prompt:
            return json.dumps({
                "sections": [
                    {"title": "Market Update", "text": "Bitcoin hit $100K today."},
                    {"title": "Team News", "text": "EigenLayer hired 20 engineers."},
                ]
            })
        else:
            return json.dumps({
                "claims": [
                    {
                        "text": f"Claim from: {prompt[:50]}",
                        "type": "fact",
                        "entities": ["Bitcoin"],
                        "temporal": None,
                        "confidence": 0.9,
                        "relevance": 1.0,
                    }
                ],
                "relations": [],
            })


async def test_extract_long_returns_claims_from_all_sections() -> None:
    """extract_long segments text and extracts claims from each section."""
    from tensory.extract import extract_long

    llm = FakeHybridLLM()
    claims, relations = await extract_long(
        "A very long text about markets and teams...",
        llm,
        max_segments=3,
    )

    assert len(claims) >= 2
    assert llm.call_count == 3  # 1 segmentation + 2 extraction


async def test_extract_long_with_context() -> None:
    """extract_long passes context to each section's extraction."""
    from tensory.extract import extract_long

    llm = FakeHybridLLM()
    ctx = Context(id="ctx1", goal="Track crypto prices", domain="crypto")
    claims, relations = await extract_long(
        "Long text...",
        llm,
        max_segments=3,
        context=ctx,
    )

    assert len(claims) >= 1
    assert all(c.context_id == "ctx1" for c in claims)


async def test_extract_long_prepends_section_header() -> None:
    """Each section's prompt includes section header with position info."""
    from tensory.extract import extract_long

    llm = FakeHybridLLM()
    await extract_long("Long text...", llm, max_segments=3)

    extraction_prompts = [p for p in llm.prompts if "thematic sections" not in p]
    assert len(extraction_prompts) == 2
    all_prompt_text = "\n".join(extraction_prompts)
    assert "[Section 1 of 2]" in all_prompt_text
    assert "[Section 2 of 2]" in all_prompt_text


async def test_extract_long_with_document_date() -> None:
    """Document date is included in section headers."""
    from tensory.extract import extract_long

    llm = FakeHybridLLM()
    await extract_long(
        "Long text...",
        llm,
        max_segments=3,
        document_date="2026-03-15",
    )

    extraction_prompts = [p for p in llm.prompts if "thematic sections" not in p]
    assert all("2026-03-15" in p for p in extraction_prompts)


async def test_extract_long_fallback_on_segmentation_failure() -> None:
    """If segmentation fails, fall back to paragraph splitting."""
    from tensory.extract import extract_long

    call_count = 0

    async def fail_then_extract(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if "thematic sections" in prompt:
            raise RuntimeError("Segmentation failed")
        return json.dumps({
            "claims": [{"text": "Fallback claim", "type": "fact", "entities": [], "confidence": 0.9, "relevance": 1.0}],
            "relations": [],
        })

    text = "Paragraph one about markets.\n\nParagraph two about teams."
    claims, relations = await extract_long(text, fail_then_extract, max_segments=3)

    assert len(claims) >= 1
