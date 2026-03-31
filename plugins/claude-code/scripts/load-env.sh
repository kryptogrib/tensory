#!/bin/bash
# Load tensory env vars from multiple sources (priority: high → low):
#
#   1. Project .env file (cwd/.env) — per-project config, like MCP's "env" block
#   2. CLAUDE_PLUGIN_OPTION_* — set via `claude plugin install` userConfig prompts
#   3. Shell environment — ~/.zshrc, ~/.bashrc, etc.
#
# Usage: source this file from hook scripts after reading stdin.
#   CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
#   source "$(dirname "$0")/load-env.sh"

# Source project .env if it exists (highest priority)
if [ -n "${CWD:-}" ]; then
  for envfile in "$CWD/.env" "$CWD/.tensory.env"; do
    if [ -f "$envfile" ]; then
      set -a
      # shellcheck disable=SC1090
      source "$envfile"
      set +a
      break
    fi
  done
fi

# Plugin userConfig overrides shell env (but not .env — .env wins via source above)
: "${OPENAI_API_KEY:=${CLAUDE_PLUGIN_OPTION_OPENAI_API_KEY:-}}"
: "${ANTHROPIC_API_KEY:=${CLAUDE_PLUGIN_OPTION_ANTHROPIC_API_KEY:-}}"
: "${ANTHROPIC_BASE_URL:=${CLAUDE_PLUGIN_OPTION_ANTHROPIC_BASE_URL:-}}"
: "${TENSORY_DB:=${CLAUDE_PLUGIN_OPTION_TENSORY_DB:-}}"

export OPENAI_API_KEY ANTHROPIC_API_KEY ANTHROPIC_BASE_URL TENSORY_DB
