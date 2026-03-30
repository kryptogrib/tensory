#!/bin/bash
# tensory Stop hook — save learnings from the conversation turn.
#
# Receives hook JSON on stdin with last_assistant_message.
# Runs async — doesn't block Claude's response.
set -euo pipefail

# Map plugin userConfig → env vars expected by tensory-hook
export OPENAI_API_KEY="${CLAUDE_PLUGIN_OPTION_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
export ANTHROPIC_API_KEY="${CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}"
export ANTHROPIC_BASE_URL="${CLAUDE_PLUGIN_OPTION_ANTHROPIC_BASE_URL:-${ANTHROPIC_BASE_URL:-}}"
export TENSORY_DB="${CLAUDE_PLUGIN_OPTION_TENSORY_DB:-${TENSORY_DB:-}}"

INPUT=$(cat)

# Guard: skip if this is a recursive stop hook call
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo "false")
if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

# Pass hook input to tensory-hook save (it reads last_assistant_message from JSON)
echo "$INPUT" | uvx --from "tensory[mcp]" tensory-hook save 2>/dev/null

exit 0
