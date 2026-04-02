"""Tests for extract.py — LLM extraction and parsing."""

from __future__ import annotations

import json

from tensory.extract import CLAIM_TO_MEMORY_TYPE, _parse_extraction, extract_claims
from tensory.models import ClaimType, Context, MemoryType

# ── Fake LLM for testing ─────────────────────────────────────────────────


class FakeLLM:
    """Returns pre-configured JSON response."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.last_prompt: str = ""

    async def __call__(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self._response


# ── Parsing tests ─────────────────────────────────────────────────────────


def test_parse_valid_json() -> None:
    response = json.dumps(
        {
            "claims": [
                {
                    "text": "EigenLayer has 50 members",
                    "type": "fact",
                    "entities": ["EigenLayer"],
                    "temporal": "2026",
                    "confidence": 0.9,
                    "relevance": 0.8,
                }
            ],
            "relations": [
                {
                    "from": "Google",
                    "to": "EigenLayer",
                    "type": "PARTNERED_WITH",
                    "fact": "Google partnered with EigenLayer",
                }
            ],
        }
    )

    claims, relations = _parse_extraction(response, context_id="ctx_1")

    assert len(claims) == 1
    assert claims[0].text == "EigenLayer has 50 members"
    assert claims[0].type.value == "fact"
    assert claims[0].memory_type == MemoryType.SEMANTIC  # fact → semantic
    assert claims[0].confidence == 0.9
    assert claims[0].relevance == 0.8
    assert claims[0].context_id == "ctx_1"
    assert "EigenLayer" in claims[0].entities

    assert len(relations) == 1
    assert relations[0].from_entity == "Google"
    assert relations[0].to_entity == "EigenLayer"
    assert relations[0].rel_type == "PARTNERED_WITH"


def test_parse_markdown_wrapped_json() -> None:
    response = '```json\n{"claims": [{"text": "Test", "type": "fact"}], "relations": []}\n```'
    claims, relations = _parse_extraction(response)
    assert len(claims) == 1
    assert claims[0].text == "Test"


def test_parse_empty_response() -> None:
    claims, relations = _parse_extraction('{"claims": [], "relations": []}')
    assert claims == []
    assert relations == []


def test_parse_invalid_json() -> None:
    claims, relations = _parse_extraction("not json at all")
    assert claims == []
    assert relations == []


def test_memory_type_mapping_from_claim_type() -> None:
    """Deterministic ClaimType → MemoryType mapping (Option A)."""
    assert CLAIM_TO_MEMORY_TYPE[ClaimType.EXPERIENCE] == MemoryType.EPISODIC
    assert CLAIM_TO_MEMORY_TYPE[ClaimType.FACT] == MemoryType.SEMANTIC
    assert CLAIM_TO_MEMORY_TYPE[ClaimType.OBSERVATION] == MemoryType.SEMANTIC
    assert CLAIM_TO_MEMORY_TYPE[ClaimType.OPINION] == MemoryType.SEMANTIC


def test_experience_claim_gets_episodic_memory_type() -> None:
    """Experience claims should be classified as episodic memory."""
    response = json.dumps(
        {
            "claims": [
                {"text": "On 20 May 2023, John ran a marathon", "type": "experience"},
                {"text": "John is a runner", "type": "fact"},
                {"text": "John seems dedicated", "type": "observation"},
                {"text": "Running is beneficial", "type": "opinion"},
            ],
            "relations": [],
        }
    )
    claims, _ = _parse_extraction(response)
    assert len(claims) == 4
    assert claims[0].memory_type == MemoryType.EPISODIC  # experience
    assert claims[1].memory_type == MemoryType.SEMANTIC  # fact
    assert claims[2].memory_type == MemoryType.SEMANTIC  # observation
    assert claims[3].memory_type == MemoryType.SEMANTIC  # opinion


def test_parse_missing_fields() -> None:
    response = json.dumps(
        {
            "claims": [{"text": "Minimal claim"}],
            "relations": [],
        }
    )
    claims, _ = _parse_extraction(response)
    assert len(claims) == 1
    assert claims[0].type.value == "fact"  # default
    assert claims[0].confidence == 1.0  # default
    assert claims[0].relevance == 1.0  # default


# ── Extraction tests (with FakeLLM) ──────────────────────────────────────


async def test_extract_with_context() -> None:
    llm = FakeLLM(
        json.dumps(
            {
                "claims": [
                    {"text": "Test claim", "type": "fact", "entities": ["Test"], "relevance": 0.9}
                ],
                "relations": [],
            }
        )
    )

    ctx = Context(id="ctx1", goal="Track testing", domain="tech")
    claims, _ = await extract_claims("some text", llm, context=ctx)

    assert len(claims) == 1
    assert "RESEARCH GOAL: Track testing" in llm.last_prompt
    assert "DOMAIN: tech" in llm.last_prompt


async def test_extract_without_context() -> None:
    llm = FakeLLM(
        json.dumps(
            {
                "claims": [{"text": "Generic claim", "type": "experience"}],
                "relations": [],
            }
        )
    )

    claims, _ = await extract_claims("some text", llm)
    assert len(claims) == 1
    assert claims[0].memory_type == MemoryType.EPISODIC  # experience → episodic
    assert "RESEARCH GOAL" not in llm.last_prompt
    assert "Extract all factual claims" in llm.last_prompt


async def test_extract_llm_failure_returns_empty() -> None:
    async def failing_llm(prompt: str) -> str:
        raise RuntimeError("LLM unavailable")

    claims, relations = await extract_claims("text", failing_llm)
    assert claims == []
    assert relations == []
