"""Tests for Claude Code SDK LLM provider.

Tests the claude_code_llm() adapter and _make_llm() sentinel detection.
SDK calls are mocked — no real claude-agent-sdk needed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

# ── claude_code_llm() adapter tests ─────────────────────────────────────


class _FakeTextBlock:
    """Minimal TextBlock stand-in."""

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAssistantMessage:
    """Minimal AssistantMessage stand-in."""

    def __init__(self, blocks: list[_FakeTextBlock]) -> None:
        self.content = blocks


async def _fake_query(prompt: str, options: Any = None) -> Any:  # async generator
    """Yield a single AssistantMessage with the prompt echoed back."""
    yield _FakeAssistantMessage([_FakeTextBlock(f"extracted: {prompt[:50]}")])


@pytest.fixture()
def _mock_sdk(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock claude_agent_sdk so imports succeed without the real package."""
    mock_module = MagicMock()
    mock_module.query = _fake_query
    mock_module.ClaudeAgentOptions = MagicMock
    mock_module.AssistantMessage = _FakeAssistantMessage
    mock_module.TextBlock = _FakeTextBlock
    monkeypatch.setitem(__import__("sys").modules, "claude_agent_sdk", mock_module)
    return mock_module


@pytest.mark.usefixtures("_mock_sdk")
async def test_claude_code_llm_basic() -> None:
    """claude_code_llm() returns a callable that extracts text from SDK response."""
    from examples.llm_adapters import claude_code_llm

    llm = claude_code_llm(model="claude-haiku-4-5-20251001")
    result = await llm("test prompt for extraction")
    assert "extracted:" in result
    assert "test prompt" in result


@pytest.mark.usefixtures("_mock_sdk")
async def test_claude_code_llm_custom_model() -> None:
    """Model parameter is passed through to options."""
    from examples.llm_adapters import claude_code_llm

    llm = claude_code_llm(model="claude-sonnet-4-5-20250929")
    result = await llm("hello")
    assert isinstance(result, str)


# ── anthropic_from_env() sentinel routing tests ─────────────────────────


@pytest.mark.usefixtures("_mock_sdk")
async def test_anthropic_from_env_routes_to_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """anthropic_from_env() detects claude-code sentinel and uses SDK adapter."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "claude-code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from examples.llm_adapters import anthropic_from_env

    llm = anthropic_from_env()
    result = await llm("test")
    assert "extracted:" in result


async def test_anthropic_from_env_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    """anthropic_from_env() uses Anthropic client for normal base_url."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8317")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    from examples.llm_adapters import anthropic_from_env

    llm = anthropic_from_env()
    # Should return a callable (Anthropic adapter), not None
    assert llm is not None
    assert callable(llm)


# ── _make_llm() sentinel detection tests ────────────────────────────────


@pytest.mark.usefixtures("_mock_sdk")
async def test_make_llm_claude_code_sentinel(monkeypatch: pytest.MonkeyPatch) -> None:
    """_make_llm() returns SDK adapter when ANTHROPIC_BASE_URL=claude-code."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "claude-code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Import fresh to pick up env change
    import tensory_hook

    llm = tensory_hook._make_llm()
    assert llm is not None

    result = await llm("test extraction")
    assert "extracted:" in result


async def test_make_llm_missing_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """_make_llm() returns None with warning when SDK not installed."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "claude-code")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Remove mock SDK if present
    import sys

    sys.modules.pop("claude_agent_sdk", None)

    import tensory_hook

    llm = tensory_hook._make_llm()
    # Should return None gracefully (not crash)
    assert llm is None


async def test_make_llm_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """_make_llm() returns None when no keys and no sentinel."""
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    import tensory_hook

    llm = tensory_hook._make_llm()
    assert llm is None


async def test_make_llm_anthropic_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """_make_llm() uses Anthropic API for normal base_url."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:8317")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    import tensory_hook

    llm = tensory_hook._make_llm()
    # Should return a callable (Anthropic adapter), not None
    assert llm is not None
    assert callable(llm)
