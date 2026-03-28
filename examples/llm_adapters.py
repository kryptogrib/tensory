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
    """Create Anthropic adapter from environment variables.

    Reads:
        ANTHROPIC_BASE_URL  — Proxy URL (if set)
        ANTHROPIC_API_KEY   — API key / proxy key
        ANTHROPIC_AUTH_TOKEN — Alternative to api_key
        TENSORY_MODEL       — Model (default: claude-haiku-4-5-20251001)

    Compatible with .env / .env.local from openHunter:
        ANTHROPIC_BASE_URL=http://localhost:8317
        ANTHROPIC_API_KEY=signal-hunter-local
    """
    return anthropic_llm(
        model=model or os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
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
