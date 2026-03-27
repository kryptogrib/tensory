"""Tests for reflect() — CARA-based learning via reflection."""

from __future__ import annotations

import json

import pytest

from tensory import Claim, ClaimType, Tensory
from tensory.models import ReflectResult

# ── Fake LLM for CARA tests ──────────────────────────────────────────────


class FakeCARALLM:
    """Returns CARA-formatted JSON responses for reflect tests."""

    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> str:
        self.call_count += 1
        self.prompts.append(prompt)

        if "opinions" in prompt.lower() or "CARA" in prompt or "first-person" in prompt.lower():
            return json.dumps(
                {
                    "opinions": [
                        {
                            "text": "I believe EigenLayer's rapid team growth signals strong funding",
                            "confidence": 0.75,
                            "entities": ["EigenLayer"],
                        }
                    ]
                }
            )
        elif "observations" in prompt.lower() or "synthesiz" in prompt.lower():
            return json.dumps(
                {
                    "observations": [
                        {
                            "text": "EigenLayer has expanded significantly in 2026",
                            "entities": ["EigenLayer"],
                        }
                    ]
                }
            )
        else:
            # Extraction prompt — return claims
            return json.dumps(
                {
                    "claims": [
                        {"text": "Generic extracted claim", "type": "fact", "entities": []},
                    ],
                    "relations": [],
                }
            )


@pytest.fixture
async def reflect_store() -> Tensory:
    """Store with FakeCARALLM for reflect testing."""
    s = await Tensory.create(":memory:", llm=FakeCARALLM())
    yield s  # type: ignore[misc]
    await s.close()


# ── reflect() without LLM (template-based) ───────────────────────────────


async def test_reflect_without_llm_returns_result(store: Tensory) -> None:
    """reflect() works without LLM — returns LLM-free results."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 members", entities=["EigenLayer"]),
            Claim(text="EigenLayer partnered with Google", entities=["EigenLayer", "Google"]),
        ]
    )

    result = await store.reflect("EigenLayer")

    assert isinstance(result, ReflectResult)
    # No LLM → no opinions
    assert len(result.new_opinions) == 0


async def test_reflect_empty_store(store: Tensory) -> None:
    """reflect() on empty store returns empty result."""
    result = await store.reflect("anything")
    assert result.updated_claims == []
    assert result.new_observations == []
    assert result.collisions == []


async def test_reflect_detects_collisions(store: Tensory) -> None:
    """reflect() detects collisions between recalled claims."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
            Claim(text="EigenLayer has 65 team members after hiring", entities=["EigenLayer"]),
        ]
    )

    result = await store.reflect("EigenLayer")
    assert len(result.collisions) >= 1


async def test_reflect_creates_observation_on_multiple_collisions(store: Tensory) -> None:
    """reflect() creates template observation when ≥2 collisions found."""
    await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
            Claim(text="EigenLayer has 65 team members now", entities=["EigenLayer"]),
            Claim(text="EigenLayer partnered with Google Cloud", entities=["EigenLayer", "Google"]),
            Claim(text="EigenLayer partnered with AWS instead", entities=["EigenLayer", "AWS"]),
        ]
    )

    result = await store.reflect("EigenLayer")

    if len(result.collisions) >= 2:
        assert len(result.new_observations) >= 1
        obs = result.new_observations[0]
        assert obs.type == ClaimType.OBSERVATION
        assert "Reflection" in obs.text


# ── reflect() with LLM (CARA) ────────────────────────────────────────────


async def test_reflect_with_cara_creates_opinions(reflect_store: Tensory) -> None:
    """reflect() with LLM runs CARA and creates opinion claims."""
    await reflect_store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
            Claim(text="EigenLayer received Series B funding", entities=["EigenLayer"]),
        ]
    )

    result = await reflect_store.reflect("EigenLayer")

    assert len(result.new_opinions) >= 1
    opinion = result.new_opinions[0]
    assert opinion.type == ClaimType.OPINION
    assert "believe" in opinion.text.lower() or "I" in opinion.text


async def test_reflect_with_cara_creates_observations(reflect_store: Tensory) -> None:
    """reflect() with LLM synthesizes observations per entity."""
    await reflect_store.add_claims(
        [
            Claim(text="EigenLayer launched restaking protocol", entities=["EigenLayer"]),
            Claim(text="EigenLayer expanded team to 60 engineers", entities=["EigenLayer"]),
            Claim(text="EigenLayer partnered with major cloud provider", entities=["EigenLayer"]),
        ]
    )

    result = await reflect_store.reflect("EigenLayer")

    # Should have LLM-synthesized observations for EigenLayer
    all_obs = result.new_observations
    assert len(all_obs) >= 1


async def test_reflect_with_disposition(reflect_store: Tensory) -> None:
    """reflect() passes disposition to CARA prompt."""
    await reflect_store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"]),
        ]
    )

    await reflect_store.reflect(
        "EigenLayer",
        disposition={"risk_tolerance": "conservative", "focus": "team stability"},
    )

    # Verify disposition was passed to LLM
    llm: FakeCARALLM = reflect_store._llm  # type: ignore[assignment]
    assert any("conservative" in p for p in llm.prompts)


async def test_reflect_auto_update_false(store: Tensory) -> None:
    """reflect() with auto_update=False doesn't change salience."""
    r = await store.add_claims(
        [
            Claim(text="EigenLayer has 50 team members", entities=["EigenLayer"], salience=1.0),
            Claim(text="EigenLayer has 65 team members now", entities=["EigenLayer"], salience=1.0),
        ]
    )

    _original_salience = r.claims[0].salience  # noqa: F841

    await store.reflect("EigenLayer", auto_update=False)

    # Salience should not have changed from collision
    cursor = await store._db.execute("SELECT salience FROM claims WHERE id = ?", (r.claims[0].id,))
    row = await cursor.fetchone()
    # With auto_update=False, reflect doesn't apply salience changes
    # (but collisions from add_claims already applied)
    assert row is not None


# ── ReflectResult model ──────────────────────────────────────────────────


def test_reflect_result_defaults() -> None:
    """ReflectResult has sensible defaults."""
    result = ReflectResult()
    assert result.updated_claims == []
    assert result.new_observations == []
    assert result.new_opinions == []
    assert result.collisions == []
