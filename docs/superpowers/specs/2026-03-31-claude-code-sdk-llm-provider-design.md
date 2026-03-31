# Claude Code SDK LLM Provider

**Date:** 2026-03-31
**Status:** Approved

## Problem

Tensory requires an LLM for claim extraction (the core pipeline: text -> LLM -> claims + entities + collisions). Currently, the only way to provide an LLM is via `ANTHROPIC_API_KEY` + optional `ANTHROPIC_BASE_URL` proxy. Users on Claude Pro/Max subscriptions must set up an external proxy (e.g., Docker-based CLIProxyAPI) to route LLM calls, which adds friction to onboarding.

Hindsight solved this by using the `claude-agent-sdk` Python package, which authenticates via OAuth tokens from `claude auth login` (stored in system keychain). No API key or proxy needed.

## Solution

Add a new LLM provider mode triggered by the sentinel value `ANTHROPIC_BASE_URL=claude-code`. When detected, Tensory uses `claude-agent-sdk` to make LLM calls through the user's Claude Code subscription instead of calling the Anthropic API directly.

Embeddings remain independent -- `OPENAI_API_KEY` controls `OpenAIEmbedder` as before.

## Configuration Matrix

| `ANTHROPIC_BASE_URL` | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` | LLM | Embedder |
|---|---|---|---|---|
| `claude-code` | ignored | present | claude-agent-sdk | OpenAIEmbedder |
| `claude-code` | ignored | absent | claude-agent-sdk | NullEmbedder |
| proxy URL | present | present | Anthropic API (proxy) | OpenAIEmbedder |
| absent | present | present | Anthropic API (direct) | OpenAIEmbedder |
| absent | absent | absent | None (warning) | NullEmbedder |

## Components

### 1. New adapter: `claude_code_llm()` in `examples/llm_adapters.py`

Factory function returning an `async (str) -> str` callable (matches `LLMProtocol`).

```python
def claude_code_llm(model: str = "claude-haiku-4-5-20251001") -> object:
    """Claude Code SDK adapter. No API key needed -- uses OAuth from claude auth login."""
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock

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
```

Key decisions:
- `max_turns=1` -- single LLM call, no agentic loop
- `allowed_tools=[]` -- pure text completion, no tool use (safety: prevents SDK from executing tools during extraction)
- Import inside function body -- `claude-agent-sdk` is optional dependency
- Model defaults to haiku for cost efficiency (same as current default)
- SDK `prompt` parameter maps to a user-turn message, matching how Tensory prompts are structured

### 2. Modified `_make_llm()` in `tensory_hook.py` and `tensory_mcp.py`

Add sentinel detection **before** the existing early-return guard. This is critical -- the sentinel check must come first, because the existing `if not base_url and not api_key` guard would pass through `base_url="claude-code"` to the Anthropic client constructor, which would fail with a nonsensical URL.

```python
def _make_llm() -> Any:
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")

    # Claude Code SDK mode -- no API key needed
    if base_url == "claude-code":
        try:
            from claude_agent_sdk import (  # type: ignore[import-untyped]
                AssistantMessage,
                ClaudeAgentOptions,
                TextBlock,
                query,
            )
        except ImportError:
            logger.warning(
                "ANTHROPIC_BASE_URL=claude-code but claude-agent-sdk not installed. "
                "Install with: pip install tensory[claude-code]"
            )
            return None

        async def sdk_call(prompt: str) -> str:
            text = ""
            options = ClaudeAgentOptions(max_turns=1, allowed_tools=[], model=model)
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text += block.text
            return text

        logger.info("Using Claude Code SDK (model=%s)", model)
        return sdk_call

    if not base_url and not api_key:
        logger.warning("No ANTHROPIC_BASE_URL/API_KEY -- LLM extraction unavailable")
        return None

    # ... existing Anthropic API logic unchanged ...
```

The adapter is **inlined** in `_make_llm()` rather than imported from `examples/`. This is because `examples/` is not included in the wheel (`pyproject.toml` packages = `["tensory", "api"]`), so `from examples.llm_adapters import ...` would fail when running via `uvx --from tensory[claude-code]`.

Both `tensory_hook.py` and `tensory_mcp.py` have their own `_make_llm()` -- both get the same change.

### 3. Updated `anthropic_from_env()` in `examples/llm_adapters.py`

`anthropic_from_env()` is part of the documented public API (module docstring, line 18). It reads `ANTHROPIC_BASE_URL` from env and passes it to `AsyncAnthropic(base_url=...)`. If a user sets `ANTHROPIC_BASE_URL=claude-code` and calls `anthropic_from_env()`, they'd get a broken client.

Add sentinel routing:

```python
def anthropic_from_env(model: str | None = None) -> object:
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    if base_url == "claude-code":
        return claude_code_llm(
            model=model or os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")
        )
    return anthropic_llm(
        model=model or os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001"),
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN"),
        base_url=base_url,
    )
```

### 4. Optional dependency in `pyproject.toml`

```toml
[project.optional-dependencies]
claude-code = ["claude-agent-sdk>=0.1.50"]
```

Also add to the `all` extra:
```toml
all = ["tensory[mcp,ui,claude-code]"]
```

### 5. Updated `.env.example`

Document the new option alongside existing ones:

```bash
# Anthropic (LLM extraction) -- choose ONE:
#   Option 1: Direct API
#     ANTHROPIC_API_KEY=sk-ant-...
#   Option 2: Via proxy (CLIProxyAPI, etc.)
#     ANTHROPIC_BASE_URL=http://localhost:8317
#     ANTHROPIC_API_KEY=signal-hunter-local
#   Option 3: Claude Code SDK (no API key needed, uses claude auth login)
#     ANTHROPIC_BASE_URL=claude-code
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=
```

### 6. Updated `plugins/claude-code/scripts/session-start.sh`

Two changes:

**a) Fix guard condition** -- the first-run check must also allow `claude-code` sentinel through:

```bash
# Before (blocks claude-code mode):
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then

# After (allows claude-code mode):
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] && [ "${ANTHROPIC_BASE_URL:-}" != "claude-code" ]; then
```

**b) Add Option 3 to onboarding message:**

```
Option 3 (no API key): Uses Claude Code's own model
  echo 'ANTHROPIC_BASE_URL=claude-code' >> .env
```

**c) Update `uvx` invocation** to include `claude-code` extra:

```bash
# Before:
echo "$INPUT" | uvx --from "tensory[mcp]" tensory-hook recall 2>/dev/null

# After:
echo "$INPUT" | uvx --from "tensory[mcp,claude-code]" tensory-hook recall 2>/dev/null
```

Similarly update `stop.sh`:
```bash
uvx --from "tensory[mcp,claude-code]" tensory-hook save 2>/dev/null
```

### 7. Error handling for SDK auth failures

If `claude auth login` has not been completed or the OAuth token expired, `claude_agent_sdk.query()` raises an exception. The adapter wraps this with a clear error message:

```python
async def sdk_call(prompt: str) -> str:
    try:
        # ... SDK call ...
    except Exception as e:
        err_msg = str(e).lower()
        if any(word in err_msg for word in ("auth", "login", "credential", "token")):
            logger.error(
                "Claude Code SDK auth failed. Run 'claude auth login' to authenticate. "
                "Error: %s", e
            )
        raise
```

This follows Tensory's pattern -- extraction failures propagate up to `store.add()` which the caller handles. We do NOT silently swallow errors (unlike search channels which degrade gracefully), because a failed extraction means lost data.

## Files Changed

| File | Change |
|---|---|
| `examples/llm_adapters.py` | Add `claude_code_llm()`, update `anthropic_from_env()` |
| `tensory_hook.py` | `_make_llm()` sentinel detection (inlined adapter) |
| `tensory_mcp.py` | `_make_llm()` sentinel detection (inlined adapter) |
| `pyproject.toml` | `claude-code` optional dependency, update `all` extra |
| `.env.example` | Document Option 3 |
| `plugins/claude-code/scripts/session-start.sh` | Guard fix, onboarding update, uvx extra |
| `plugins/claude-code/scripts/stop.sh` | Update uvx extra |
| `tests/test_claude_code_llm.py` | Unit tests for new adapter |

## What Does NOT Change

- `LLMProtocol` signature (`async (str) -> str`)
- `extract.py`, `chunking.py`, `store.py` -- accept any `LLMProtocol`
- `prompts.py` -- all prompts work with any LLM
- Embedder logic -- independent of LLM provider
- Hook shell scripts (`.claude/hooks/`) -- call `uvx tensory-hook` as before
- `load-env.sh` -- already passes `ANTHROPIC_BASE_URL` through

## Constraints

- `claude-agent-sdk` spawns Claude CLI as subprocess -- first call ~2-3s latency
- SDK does not report token usage -- no tracking possible
- Rate limits depend on user's Pro/Max subscription
- Requires Claude Code CLI >= 2.0.0 and `claude auth login` completed
- `claude-agent-sdk` requires Python 3.10+ (we require 3.11+, so OK)
- `allowed_tools=[]` is a safety requirement -- prevents SDK from executing tools during extraction

## Testing Strategy

- Unit test: mock `claude_agent_sdk.query` to verify adapter wraps correctly
- Unit test: `_make_llm()` returns correct adapter type based on env vars
- Unit test: `anthropic_from_env()` routes to `claude_code_llm()` when sentinel is set
- Unit test: auth error handling produces clear log message
- Integration test: skip if `claude-agent-sdk` not installed (optional dep)
- Existing tests unchanged -- they use mock LLMs / NullEmbedder
