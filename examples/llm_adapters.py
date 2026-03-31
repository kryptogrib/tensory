"""LLM adapters for tensory.

tensory accepts any async function `(prompt: str) -> str`.
Here are ready-to-use adapters for popular LLM providers.

Usage:
    from examples.llm_adapters import openai_llm, anthropic_llm, ollama_llm

    store = await Tensory.create("memory.db", llm=openai_llm())

    # With proxy (e.g. openHunter):
    store = await Tensory.create("memory.db", llm=anthropic_llm(
        base_url="http://localhost:8317",
        api_key="signal-hunter-local",
    ))

    # From env (ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY):
    store = await Tensory.create("memory.db", llm=anthropic_from_env())

    # Claude Code SDK (no API key, uses claude auth login):
    store = await Tensory.create("memory.db", llm=claude_code_llm())
"""

from __future__ import annotations

import os

# ── OpenAI ────────────────────────────────────────────────────────────────


def openai_llm(
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
    base_url: str | None = None,
) -> object:
    """OpenAI adapter. Requires: pip install openai

    Recommended models:
    - gpt-4o-mini  — cheap, fast, sufficient for extraction
    - gpt-4o       — best extraction quality

    Args:
        model: Model to use.
        api_key: API key (or env OPENAI_API_KEY).
        base_url: Custom base URL (for proxy or compatible APIs).
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return _call


# ── Anthropic (direct + via proxy) ───────────────────────────────────────


def anthropic_llm(
    model: str = "claude-haiku-4-5-20251001",
    api_key: str | None = None,
    auth_token: str | None = None,
    base_url: str | None = None,
) -> object:
    """Anthropic Claude adapter. Requires: pip install anthropic

    Supports direct connection and via proxy (CLIProxyAPI, etc.)

    Args:
        model: Model. Haiku is cheaper for extraction.
        api_key: Anthropic API key (or proxy key, e.g. "signal-hunter-local").
        auth_token: Auth token (alternative to api_key).
        base_url: Proxy URL (e.g. "http://localhost:8317" for CLIProxyAPI).

    Examples:
        # Direct connection
        anthropic_llm(api_key="sk-ant-...")

        # Via CLIProxyAPI (e.g. openHunter)
        anthropic_llm(base_url="http://localhost:8317", api_key="signal-hunter-local")
    """
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=api_key or None,
        auth_token=auth_token or None,
        base_url=base_url or None,  # type: ignore[arg-type]
    )

    async def _call(prompt: str) -> str:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    return _call


def anthropic_from_env(
    model: str | None = None,
) -> object:
    """Create LLM adapter from environment variables.

    Reads:
        ANTHROPIC_BASE_URL  — Proxy URL, or "claude-code" for SDK mode
        ANTHROPIC_API_KEY   — API key / proxy key
        ANTHROPIC_AUTH_TOKEN — Alternative to api_key
        TENSORY_MODEL       — Model (default: claude-haiku-4-5-20251001)

    When ANTHROPIC_BASE_URL=claude-code, routes to claude_code_llm()
    (no API key needed, uses OAuth from `claude auth login`).

    Compatible with .env / .env.local from openHunter:
        ANTHROPIC_BASE_URL=http://localhost:8317
        ANTHROPIC_API_KEY=signal-hunter-local
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    resolved_model = model or os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")

    if base_url == "claude-code":
        return claude_code_llm(model=resolved_model)

    return anthropic_llm(
        model=resolved_model,
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=base_url,
    )


# ── Ollama (local) ───────────────────────────────────────────────────────


def ollama_llm(
    model: str = "llama3.1",
    base_url: str = "http://localhost:11434",
) -> object:
    """Ollama adapter. Requires: Ollama installed + model pulled.

    ollama pull llama3.1
    """
    import httpx

    async def _call(prompt: str) -> str:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
            )
            return response.json().get("response", "")

    return _call


# ── OpenAI-compatible (LiteLLM, vLLM, Together, etc.) ────────────────────


def openai_compatible_llm(
    model: str = "meta-llama/Llama-3-8b-chat-hf",
    base_url: str = "https://api.together.xyz/v1",
    api_key: str | None = None,
) -> object:
    """Any OpenAI-compatible API (Together, vLLM, LiteLLM proxy, etc.)"""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    async def _call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return _call


# ── Claude Code SDK (no API key) ─────────────────────────────────────────


def claude_code_llm(
    model: str = "claude-haiku-4-5-20251001",
) -> object:
    """Claude Code SDK adapter. No API key needed.

    Uses claude-agent-sdk to make LLM calls via OAuth tokens
    from ``claude auth login`` (stored in system keychain).

    Requires:
        pip install claude-agent-sdk   (or: pip install tensory[claude-code])
        Claude Code CLI >= 2.0.0
        ``claude auth login`` completed

    Args:
        model: Model to use. Haiku is cheaper for extraction.

    Examples:
        # Direct usage
        store = await Tensory.create("memory.db", llm=claude_code_llm())

        # Via env (ANTHROPIC_BASE_URL=claude-code)
        store = await Tensory.create("memory.db", llm=anthropic_from_env())
    """
    from claude_agent_sdk import (  # type: ignore[import-untyped]
        AssistantMessage,
        ClaudeAgentOptions,
        TextBlock,
        query,
    )

    async def _call(prompt: str) -> str:
        text = ""
        options = ClaudeAgentOptions(max_turns=1, allowed_tools=[], model=model)
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        text += block.text
        return text

    return _call


# ── MCP passthrough (calling model handles extraction) ───────────────────


def mcp_passthrough_llm() -> object:
    """Stub for MCP mode.

    In MCP mode, extraction is done by the calling model, NOT tensory.
    MCP tool `tensory_add` accepts pre-extracted claims.

    This function is for documentation only. In practice, the MCP server
    uses store.add_claims() directly (no LLM).

    See plans/tensory-plan.md → "MCP Protocol" for the full scheme.
    """

    async def _call(prompt: str) -> str:
        msg = "MCP passthrough: extraction should be done by the calling model"
        raise NotImplementedError(msg)

    return _call
