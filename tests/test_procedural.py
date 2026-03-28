"""Tests for procedural memory — skill extraction, search, feedback, evolution."""

from __future__ import annotations

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
