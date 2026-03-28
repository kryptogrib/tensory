"""Tests for procedural memory — skill extraction, search, feedback, evolution."""

from __future__ import annotations

from tensory import Claim
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
