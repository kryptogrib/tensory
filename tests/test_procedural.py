"""Tests for procedural memory — skill extraction, search, feedback, evolution."""

from __future__ import annotations

import json

import pytest

from tensory import Claim, Tensory
from tensory.models import MemoryType, ProceduralResult

# ── Model tests ──────────────────────────────────────────────────────────


def test_memory_type_enum() -> None:
    """MemoryType enum has episodic, semantic, procedural values."""
    assert MemoryType.EPISODIC == "episodic"
    assert MemoryType.SEMANTIC == "semantic"
    assert MemoryType.PROCEDURAL == "procedural"


def test_claim_defaults_to_semantic() -> None:
    """Claim memory_type defaults to SEMANTIC for backward compat."""
    c = Claim(text="Bitcoin costs $50K")
    assert c.memory_type == MemoryType.SEMANTIC


def test_claim_procedural_fields() -> None:
    """Procedural claim carries trigger, steps, termination, success_rate."""
    c = Claim(
        text="How to check crypto price",
        memory_type=MemoryType.PROCEDURAL,
        trigger="user asks for crypto price",
        steps=["open Binance", "enter BTC/USDT", "show price"],
        termination_condition="price displayed to user",
        success_rate=0.8,
        usage_count=5,
        source_episode_ids=["ep1", "ep2"],
    )
    assert c.memory_type == MemoryType.PROCEDURAL
    assert c.trigger == "user asks for crypto price"
    assert len(c.steps) == 3
    assert c.termination_condition == "price displayed to user"
    assert c.success_rate == 0.8
    assert c.usage_count == 5
    assert c.source_episode_ids == ["ep1", "ep2"]


def test_procedural_result_model() -> None:
    """ProceduralResult contains skills, updated, deprecated lists."""
    r = ProceduralResult(episode_id="ep1")
    assert r.skills == []
    assert r.updated_skills == []
    assert r.deprecated_skills == []


# ── Schema tests ─────────────────────────────────────────────────────────


async def test_schema_has_procedural_columns(store: Tensory) -> None:
    """Claims table has procedural columns after schema creation."""
    cursor = await store._db.execute("PRAGMA table_info(claims)")
    rows = await cursor.fetchall()
    columns = {row[1] for row in rows}

    assert "memory_type" in columns
    assert "trigger" in columns
    assert "steps" in columns
    assert "termination_condition" in columns
    assert "success_rate" in columns
    assert "usage_count" in columns
    assert "last_used" in columns
    assert "source_episode_ids" in columns


# ── Prompt tests ─────────────────────────────────────────────────────────


def test_procedural_induction_prompt_has_placeholders() -> None:
    """PROCEDURAL_INDUCTION_PROMPT has {text} placeholder."""
    from tensory.prompts import PROCEDURAL_INDUCTION_PROMPT

    assert "{text}" in PROCEDURAL_INDUCTION_PROMPT
    assert "trigger" in PROCEDURAL_INDUCTION_PROMPT
    assert "steps" in PROCEDURAL_INDUCTION_PROMPT
    assert "termination_condition" in PROCEDURAL_INDUCTION_PROMPT


def test_skill_update_prompt_has_placeholders() -> None:
    """SKILL_UPDATE_PROMPT has {skill_text} and {outcome} placeholders."""
    from tensory.prompts import SKILL_UPDATE_PROMPT

    assert "{skill_text}" in SKILL_UPDATE_PROMPT
    assert "{outcome}" in SKILL_UPDATE_PROMPT


# ── Fake LLM ─────────────────────────────────────────────────────────────


class FakeProceduralLLM:
    """Returns procedural extraction JSON for testing."""

    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)

        if "procedural" in prompt.lower() or "skill" in prompt.lower():
            return json.dumps(
                {
                    "skills": [
                        {
                            "trigger": "user asks for crypto price",
                            "steps": ["open Binance", "enter BTC/USDT", "show price"],
                            "termination_condition": "price displayed",
                            "expected_outcome": "user sees current price",
                            "entities": ["Binance", "BTC"],
                        }
                    ]
                }
            )
        elif "update" in prompt.lower() or "evaluate" in prompt.lower():
            return json.dumps(
                {
                    "updated_steps": ["open Binance", "enter BTC/USDT", "check spread", "show price"],
                    "updated_trigger": None,
                    "updated_termination": None,
                    "should_deprecate": False,
                    "reasoning": "Added spread check step",
                }
            )
        else:
            return json.dumps({"claims": [], "relations": []})


# ── Extraction tests ─────────────────────────────────────────────────────


async def test_extract_procedural_parses_skills() -> None:
    """extract_procedural returns Claim objects with procedural fields."""
    from tensory.extract import extract_procedural

    llm = FakeProceduralLLM()
    skills = await extract_procedural("I opened Binance and showed the price", llm)

    assert len(skills) == 1
    skill = skills[0]
    assert skill.memory_type == MemoryType.PROCEDURAL
    assert skill.trigger == "user asks for crypto price"
    assert skill.steps == ["open Binance", "enter BTC/USDT", "show price"]
    assert skill.termination_condition == "price displayed"
    assert "Binance" in skill.entities


async def test_extract_procedural_returns_empty_on_no_skills() -> None:
    """extract_procedural returns [] when LLM finds no skills."""
    from tensory.extract import extract_procedural

    async def empty_llm(prompt: str) -> str:
        return json.dumps({"skills": []})

    skills = await extract_procedural("Just a regular chat", empty_llm)
    assert skills == []


async def test_extract_procedural_handles_llm_failure() -> None:
    """extract_procedural returns [] on LLM error (graceful degradation)."""
    from tensory.extract import extract_procedural

    async def broken_llm(prompt: str) -> str:
        raise RuntimeError("LLM offline")

    skills = await extract_procedural("some text", broken_llm)
    assert skills == []


# ── Search tests ─────────────────────────────────────────────────────────


async def test_search_filters_by_memory_type(store: Tensory) -> None:
    """search() with memory_type filter returns only matching claims."""
    # Add a semantic claim
    await store.add_claims([
        Claim(text="Bitcoin price is $50K", entities=["Bitcoin"]),
    ])
    # Add a procedural claim
    await store.add_claims([
        Claim(
            text="Skill: when user asks for price, do: open exchange; check price",
            memory_type=MemoryType.PROCEDURAL,
            trigger="user asks for price",
            steps=["open exchange", "check price"],
            entities=["Bitcoin"],
        ),
    ])

    # Search all — should get both
    all_results = await store.search("Bitcoin")
    assert len(all_results) >= 2

    # Search procedural only
    proc_results = await store.search("Bitcoin", memory_type=MemoryType.PROCEDURAL)
    assert len(proc_results) >= 1
    assert all(r.claim.memory_type == MemoryType.PROCEDURAL for r in proc_results)

    # Search semantic only
    sem_results = await store.search("Bitcoin", memory_type=MemoryType.SEMANTIC)
    assert len(sem_results) >= 1
    assert all(r.claim.memory_type == MemoryType.SEMANTIC for r in sem_results)


# ── Store integration tests ──────────────────────────────────────────────


@pytest.fixture
async def proc_store() -> Tensory:
    """Tensory with fake LLM for procedural tests."""
    llm = FakeProceduralLLM()
    s = await Tensory.create(":memory:", llm=llm)
    yield s  # type: ignore[misc]
    await s.close()


async def test_add_procedural_extracts_and_stores_skill(proc_store: Tensory) -> None:
    """add_procedural() uses LLM to extract skills and stores them."""
    from tensory.models import ProceduralResult

    result = await proc_store.add_procedural(
        "I opened Binance, entered BTC/USDT, and showed the price to the user.",
        source="manual_demo",
    )

    assert isinstance(result, ProceduralResult)
    assert len(result.skills) == 1
    skill = result.skills[0]
    assert skill.memory_type == MemoryType.PROCEDURAL
    assert skill.trigger == "user asks for crypto price"
    assert len(skill.steps) == 3
    assert skill.success_rate == 0.5  # default for new skills

    # Verify it's in the DB
    stats = await proc_store.stats()
    assert stats["counts"]["claims"] >= 1


async def test_add_procedural_stores_episode(proc_store: Tensory) -> None:
    """add_procedural() stores the raw episode for provenance."""
    result = await proc_store.add_procedural("Some procedure text", source="test")
    assert result.episode_id != ""

    # Episode exists in DB
    cursor = await proc_store._db.execute(
        "SELECT raw_text FROM episodes WHERE id = ?", (result.episode_id,)
    )
    row = await cursor.fetchone()
    assert row is not None
    assert row[0] == "Some procedure text"


async def test_add_procedural_requires_llm() -> None:
    """add_procedural() raises ValueError without LLM."""
    store = await Tensory.create(":memory:")
    with pytest.raises(ValueError, match="LLM required"):
        await store.add_procedural("text")
    await store.close()
