"""tensory hook CLI — automatic memory for Claude Code plugin.

Called by hook shell scripts. Each invocation creates a store, does work, closes.
No background server needed.

Subcommands::

    tensory-hook recall --cwd /path   → search memory, print additionalContext JSON
    tensory-hook save                 → read transcript from stdin, extract & store claims
    tensory-hook health               → check components, print JSON
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from typing import Any

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("tensory-hook")

DEBUG = os.environ.get("TENSORY_DEBUG", "").strip() in ("1", "true", "yes")

# ── Store factory (reuses tensory_mcp patterns) ─────────────────────────


def _make_embedder() -> Any:
    """Create OpenAIEmbedder if OPENAI_API_KEY is set."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    from tensory.embedder import OpenAIEmbedder

    base_url = os.environ.get("OPENAI_BASE_URL")
    return OpenAIEmbedder(api_key=api_key, base_url=base_url)


def _make_llm() -> Any:
    """Create LLM adapter from env vars.

    Provider priority:
    1. ANTHROPIC_BASE_URL=claude-code → Claude Agent SDK (no API key)
    2. ANTHROPIC_BASE_URL + ANTHROPIC_API_KEY → Anthropic API (proxy/direct)
    3. Neither → None (LLM extraction unavailable)
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("TENSORY_MODEL", "claude-haiku-4-5-20251001")

    # Claude Code SDK mode — no API key needed
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
            try:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                text += block.text
            except Exception as e:
                err_msg = str(e).lower()
                if any(w in err_msg for w in ("auth", "login", "credential", "token")):
                    logger.error(
                        "Claude Code SDK auth failed. Run 'claude auth login'. Error: %s", e
                    )
                raise
            return text

        logger.info("Using Claude Code SDK (model=%s)", model)
        return sdk_call

    if not base_url and not api_key:
        return None

    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(
        api_key=api_key or None,
        base_url=base_url or None,  # type: ignore[arg-type]
    )

    async def llm_call(prompt: str) -> str:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else ""

    return llm_call


async def _create_store() -> Any:
    """Create a Tensory store from env vars."""
    from tensory import Tensory

    db_path = os.environ.get("TENSORY_DB", "~/.local/share/tensory/memory.db")
    db_path = os.path.expanduser(db_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    return await Tensory.create(db_path, llm=_make_llm(), embedder=_make_embedder())


# ── Subcommands ──────────────────────────────────────────────────────────


async def cmd_recall(cwd: str) -> None:
    """Search memory for context relevant to current project.

    Prints hook-compatible JSON with additionalContext to stdout.
    """
    import time

    start = time.monotonic()
    store = await _create_store()
    try:
        # Build a query from the project directory name
        project_name = os.path.basename(cwd) if cwd else "project"
        results = await store.search(project_name, limit=10)
        elapsed_ms = (time.monotonic() - start) * 1000

        if not results:
            if DEBUG:
                _debug_stderr(
                    f"recall: query='{project_name}' results=0 time={elapsed_ms:.0f}ms"
                )
            _print_hook_output("")
            return

        # Format results using tensory's built-in formatter
        from tensory.context import format_context

        context_text = format_context(results)

        # Prepend a header so Claude knows what this is
        header = f"[tensory] Recalled {len(results)} memories for project '{project_name}':\n\n"

        # Debug: full detail to log file only (not in Claude's context)
        if DEBUG:
            debug_block = _format_debug_recall(project_name, results, elapsed_ms)
            _debug_stderr(
                f"recall: query='{project_name}' results={len(results)} "
                f"time={elapsed_ms:.0f}ms"
            )
            _debug_log(debug_block)

        _print_hook_output(header + context_text)
    finally:
        await store.close()


async def cmd_save(transcript: str) -> None:
    """Extract claims from transcript and store them.

    Uses Tensory's native pipeline: text → LLM extraction → claims + collisions.
    Falls back to raw claim storage if LLM is unavailable.
    """
    import time

    if not transcript or len(transcript.strip()) < 50:
        if DEBUG:
            _debug_stderr("save: skipped — transcript too short")
        logger.info("Transcript too short, skipping save")
        return

    start = time.monotonic()
    store = await _create_store()
    try:
        # Truncate very long transcripts (last 8000 chars ≈ last few turns)
        max_chars = int(os.environ.get("TENSORY_MAX_TRANSCRIPT", "8000"))
        if len(transcript) > max_chars:
            transcript = transcript[-max_chars:]

        if store._llm is not None:
            # Full pipeline: LLM extraction → claims + collision detection
            result = await store.add(transcript, source="claude-code:hook")
            elapsed_ms = (time.monotonic() - start) * 1000

            if DEBUG:
                _format_debug_save(result, elapsed_ms)

            logger.info(
                "Saved %d claims, %d collisions",
                len(result.claims),
                len(result.collisions),
            )
        else:
            # No LLM — store as a single raw episode (still searchable via FTS)
            from tensory import Claim

            await store.add_claims(
                [Claim(text=transcript[:2000], entities=[], type="experience")],
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            if DEBUG:
                _debug_stderr(f"save: raw transcript (no LLM) time={elapsed_ms:.0f}ms")
            logger.info("Saved raw transcript (no LLM)")
    finally:
        await store.close()


async def cmd_health() -> None:
    """Print component health as JSON."""
    store = await _create_store()
    try:
        from tensory.embedder import NullEmbedder

        health = {
            "llm": store._llm is not None,
            "embedder": not isinstance(store._embedder, NullEmbedder),
            "vec_available": getattr(store, "_vec_available", False),
            "db_path": str(getattr(store, "_path", "unknown")),
        }
        print(json.dumps(health))
    finally:
        await store.close()


# ── Helpers ──────────────────────────────────────────────────────────────


def _debug_stderr(msg: str) -> None:
    """Print debug message to stderr + log file.

    stderr is captured by Claude Code and not shown to the user,
    so we also append to a log file the user can ``tail -f``.
    """
    line = f"[tensory:debug] {msg}"
    print(line, file=sys.stderr)
    # Also write to log file so user can see it in terminal
    _debug_log(line)


def _debug_log(line: str) -> None:
    """Append a line to the tensory debug log file."""
    log_path = os.path.expanduser(
        os.environ.get("TENSORY_DEBUG_LOG", "~/.local/share/tensory/debug.log")
    )
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    with open(log_path, "a") as f:
        f.write(f"[{ts}] {line}\n")


def _format_debug_recall(query: str, results: list[Any], elapsed_ms: float) -> str:
    """Format debug block for recall — appended to additionalContext."""
    lines = [
        f"[tensory:debug] Recall results (query='{query}', {len(results)} found, {elapsed_ms:.0f}ms):",
    ]
    for i, r in enumerate(results[:5], 1):
        claim = r.claim
        entities = ", ".join(claim.entities[:3]) if claim.entities else "—"
        lines.append(
            f"  {i}. [{claim.type}, score={r.score:.2f}] {claim.text[:80]}"
            f"{'...' if len(claim.text) > 80 else ''}"
        )
        lines.append(f"     entities: {entities}")
    if len(results) > 5:
        lines.append(f"  ... and {len(results) - 5} more")
    return "\n".join(lines)


def _format_debug_save(result: Any, elapsed_ms: float) -> None:
    """Print debug info about saved claims to stderr + log file."""
    from collections import Counter

    type_counts = Counter(c.type for c in result.claims)
    types_str = ", ".join(f"{count} {t}" for t, count in type_counts.most_common())

    summary = (
        f"save: {len(result.claims)} claims ({types_str}), "
        f"{len(result.collisions)} collisions, "
        f"time={elapsed_ms:.0f}ms"
    )
    _debug_stderr(summary)

    # Full detail to log file
    lines: list[str] = []
    for i, c in enumerate(result.claims, 1):
        entities = ", ".join(c.entities[:3]) if c.entities else "—"
        lines.append(
            f"  {i}. [{c.type}] {c.text[:100]}"
            f"{'...' if len(c.text) > 100 else ''}"
        )
        lines.append(f"     entities: {entities}")
    for col in result.collisions[:5]:
        lines.append(
            f"  collision: {col.type} — "
            f"{col.explanation[:80] if col.explanation else '?'}"
        )
    if lines:
        _debug_log("\n".join(lines))


def _print_hook_output(additional_context: str) -> None:
    """Print Claude Code hook-compatible JSON to stdout."""
    output: dict[str, Any] = {}
    if additional_context:
        output["hookSpecificOutput"] = {
            "hookEventName": "SessionStart",
            "additionalContext": additional_context,
        }
    print(json.dumps(output))


def _read_stdin() -> str:
    """Read all of stdin (hook input JSON)."""
    if sys.stdin.isatty():
        return ""
    return sys.stdin.read()


# ── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point: tensory-hook <recall|save|health> [args]."""
    if len(sys.argv) < 2:
        print("Usage: tensory-hook <recall|save|health>", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    stdin_data = _read_stdin()

    # Parse hook input JSON (Claude Code sends context on stdin)
    hook_input: dict[str, Any] = {}
    if stdin_data.strip():
        with contextlib.suppress(json.JSONDecodeError):
            hook_input = json.loads(stdin_data)

    if command == "recall":
        cwd = hook_input.get("cwd", os.getcwd())
        asyncio.run(cmd_recall(cwd))
    elif command == "save":
        # Read transcript from hook input
        transcript = hook_input.get("last_assistant_message", "")
        asyncio.run(cmd_save(transcript))
    elif command == "health":
        asyncio.run(cmd_health())
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
