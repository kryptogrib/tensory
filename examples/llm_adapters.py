"""LLM адаптеры для tensory.

tensory принимает любую async функцию `(prompt: str) -> str`.
Вот готовые адаптеры для популярных LLM провайдеров.

Использование:
    from examples.llm_adapters import openai_llm, anthropic_llm, ollama_llm

    store = await Tensory.create("memory.db", llm=openai_llm())
"""

from __future__ import annotations


# ── OpenAI ────────────────────────────────────────────────────────────────


def openai_llm(
    model: str = "gpt-4o-mini",
    api_key: str | None = None,
) -> object:
    """OpenAI adapter. Нужен: pip install openai

    Рекомендуемые модели:
    - gpt-4o-mini  — дешёвый, быстрый, достаточный для extraction
    - gpt-4o       — лучшее качество extraction
    """
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)

    async def _call(prompt: str) -> str:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        return response.choices[0].message.content or ""

    return _call


# ── Anthropic ─────────────────────────────────────────────────────────────


def anthropic_llm(
    model: str = "claude-sonnet-4-20250514",
    api_key: str | None = None,
) -> object:
    """Anthropic Claude adapter. Нужен: pip install anthropic"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=api_key)

    async def _call(prompt: str) -> str:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    return _call


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
