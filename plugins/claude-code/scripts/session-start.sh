#!/bin/bash
# tensory SessionStart hook — recall relevant memories on session start.
#
# Receives hook JSON on stdin (session_id, cwd, source, etc.)
# Outputs JSON with additionalContext for Claude's context window.
set -euo pipefail

# Map plugin userConfig → env vars expected by tensory-hook
export OPENAI_API_KEY="${CLAUDE_PLUGIN_OPTION_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
export ANTHROPIC_API_KEY="${CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}"
export ANTHROPIC_BASE_URL="${CLAUDE_PLUGIN_OPTION_ANTHROPIC_BASE_URL:-${ANTHROPIC_BASE_URL:-}}"
export TENSORY_DB="${CLAUDE_PLUGIN_OPTION_TENSORY_DB:-${TENSORY_DB:-}}"

INPUT=$(cat)

# Pass hook input to tensory-hook recall (it reads cwd from JSON)
echo "$INPUT" | uvx --from "tensory[mcp]" tensory-hook recall 2>/dev/null

exit 0
