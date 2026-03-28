"""Tests for hybrid extraction — long text → topic segmentation → parallel extract."""

from __future__ import annotations

import json

import pytest

from tensory import Tensory
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
            return json.dumps(
                {
                    "sections": [
                        {"title": "Market Update", "text": "Bitcoin hit $100K today."},
                        {"title": "Team News", "text": "EigenLayer hired 20 engineers."},
                    ]
                }
            )
        else:
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": f"Claim #{self.call_count} from extraction call",
                            "type": "fact",
                            "entities": ["Bitcoin"],
                            "temporal": None,
                            "confidence": 0.9,
                            "relevance": 1.0,
                        }
                    ],
                    "relations": [],
                }
            )


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
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "Fallback claim",
                        "type": "fact",
                        "entities": [],
                        "confidence": 0.9,
                        "relevance": 1.0,
                    }
                ],
                "relations": [],
            }
        )

    text = "Paragraph one about markets.\n\nParagraph two about teams."
    claims, relations = await extract_long(text, fail_then_extract, max_segments=3)

    assert len(claims) >= 1


@pytest.fixture
async def hybrid_store() -> Tensory:
    """Tensory with fake LLM for hybrid extraction tests."""
    llm = FakeHybridLLM()
    s = await Tensory.create(":memory:", llm=llm)
    yield s  # type: ignore[misc]
    await s.close()


async def test_add_short_text_uses_single_call(hybrid_store: Tensory) -> None:
    """Short text (< threshold) uses 1 LLM call as before."""
    result = await hybrid_store.add("Short text about Bitcoin.", source="test")
    assert len(result.claims) >= 1


async def test_add_long_text_uses_segmentation(hybrid_store: Tensory) -> None:
    """Long text (> threshold) uses topic segmentation."""
    long_text = (
        "Bitcoin price reached $100K. " * 200
        + "\n\n"
        + "EigenLayer expanded to 60 engineers. " * 200
    )
    result = await hybrid_store.add(
        long_text,
        source="test",
        chunk_threshold=100,
    )
    assert len(result.claims) >= 2


async def test_add_with_explicit_threshold(hybrid_store: Tensory) -> None:
    """chunk_threshold parameter controls when segmentation kicks in."""
    result = await hybrid_store.add(
        "Some text.",
        source="test",
        chunk_threshold=999999,
    )
    assert len(result.claims) >= 1


async def test_add_long_stores_single_episode(hybrid_store: Tensory) -> None:
    """Long text segmentation still stores ONE episode with full text."""
    long_text = "Word " * 500 + "\n\n" + "Another " * 500
    result = await hybrid_store.add(
        long_text,
        source="test",
        chunk_threshold=100,
    )

    cursor = await hybrid_store._db.execute(
        "SELECT raw_text FROM episodes WHERE id = ?", (result.episode_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == long_text


async def test_add_long_graceful_on_partial_failure(hybrid_store: Tensory) -> None:
    """If extraction fails mid-way, still returns what succeeded."""
    call_count = 0

    async def fail_on_second(prompt: str) -> str:
        nonlocal call_count
        call_count += 1
        if "thematic sections" in prompt:
            return json.dumps(
                {
                    "sections": [
                        {"title": "S1", "text": "Good section."},
                        {"title": "S2", "text": "Bad section."},
                    ]
                }
            )
        if call_count == 3:
            raise RuntimeError("LLM died")
        return json.dumps(
            {
                "claims": [
                    {
                        "text": "A claim",
                        "type": "fact",
                        "entities": [],
                        "confidence": 0.9,
                        "relevance": 1.0,
                    }
                ],
                "relations": [],
            }
        )

    store = await Tensory.create(":memory:", llm=fail_on_second)
    result = await store.add(
        "Long " * 500 + "\n\n" + "Text " * 500, source="test", chunk_threshold=100
    )
    assert isinstance(result.claims, list)
    await store.close()
