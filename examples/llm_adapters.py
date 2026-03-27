"""LLM адаптеры для tensory.

tensory принимает любую async функцию `(prompt: str) -> str`.
Вот готовые адаптеры для популярных LLM провайдеров.

Использование:
    from examples.llm_adapters import openai_llm, anthropic_llm, ollama_llm

    store = await Tensory.create("memory.db", llm=openai_llm())

    # С прокси (как в openHunter):
    store = await Tensory.create("memory.db", llm=anthropic_llm(
        base_url="http://localhost:8317",
        api_key="signal-hunter-local",
    ))

    # Из env (ANTHROPIC_BASE_URL, ANTHROPIC_API_KEY):
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
    """OpenAI adapter. Нужен: pip install openai

    Рекомендуемые модели:
    - gpt-4o-mini  — дешёвый, быстрый, достаточный для extraction
    - gpt-4o       — лучшее качество extraction

    Args:
        model: Модель для использования.
        api_key: API ключ (или env OPENAI_API_KEY).
        base_url: Custom base URL (для прокси или совместимых API).
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


# ── Anthropic (прямой + через прокси) ────────────────────────────────────


def anthropic_llm(
    model: str = "claude-haiku-4-5-20251001",
    api_key: str | None = None,
    auth_token: str | None = None,
    base_url: str | None = None,
) -> object:
    """Anthropic Claude adapter. Нужен: pip install anthropic

    Поддерживает прямое подключение и через прокси (CLIProxyAPI и др.)

    Args:
        model: Модель. haiku дешевле для extraction.
        api_key: API ключ Anthropic (или прокси-ключ, напр. "signal-hunter-local").
        auth_token: Auth token (альтернатива api_key).
        base_url: URL прокси (напр. "http://localhost:8317" для CLIProxyAPI).

    Примеры:
        # Прямое подключение
        anthropic_llm(api_key="sk-ant-...")

        # Через CLIProxyAPI (как в openHunter)
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
    """Создаёт Anthropic adapter из переменных окружения.

    Читает:
        ANTHROPIC_BASE_URL  — URL прокси (если есть)
        ANTHROPIC_API_KEY   — API ключ / прокси ключ
        ANTHROPIC_AUTH_TOKEN — альтернатива api_key
        TENSORY_MODEL       — модель (default: claude-haiku-4-5-20251001)

    Совместимо с .env / .env.local из openHunter:
        ANTHROPIC_BASE_URL=http://localhost:8317
        ANTHROPIC_API_KEY=signal-hunter-local
    """
    return anthropic_llm(
        model=model or os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
    )


# ── Ollama (локальный) ───────────────────────────────────────────────────


def ollama_llm(
    model: str = "llama3.1",
    base_url: str = "http://localhost:11434",
) -> object:
    """Ollama adapter. Нужен: установленный Ollama + модель.

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


# ── MCP passthrough (вызывающая модель делает extraction) ─────────────────


def mcp_passthrough_llm() -> object:
    """Заглушка для MCP-режима.

    В MCP-режиме extraction делает НЕ tensory, а вызывающая модель.
    MCP tool `tensory_add` принимает уже извлечённые claims.

    Эта функция — для документации. В реальности MCP server
    использует store.add_claims() напрямую (без LLM).

    См. plans/tensory-plan.md → "MCP Protocol" для полной схемы.
    """

    async def _call(prompt: str) -> str:
        msg = "MCP passthrough: extraction should be done by the calling model"
        raise NotImplementedError(msg)

    return _call
