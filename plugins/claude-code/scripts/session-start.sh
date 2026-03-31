#!/bin/bash
# tensory SessionStart hook — recall relevant memories on session start.
#
# Receives hook JSON on stdin (session_id, cwd, source, etc.)
# Outputs JSON with additionalContext for Claude's context window.
#
# First run: detects missing API keys → outputs setup instructions.
# Normal run: searches memory → outputs recalled context.
set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")

# Load env vars: .env (project) → userConfig (plugin) → shell env
# shellcheck disable=SC1091
source "$(dirname "$0")/load-env.sh"

# ── First-run detection: no API keys configured ──────────────────────────
if [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  SETUP_MSG="[tensory] Memory plugin installed but not configured yet.

To activate, create a .env file in your project root:

\`\`\`bash
cat > .env << 'EOF'
OPENAI_API_KEY=sk-...        # Required: for vector search (embeddings)
ANTHROPIC_API_KEY=sk-ant-... # Optional: for LLM claim extraction
# ANTHROPIC_BASE_URL=        # Optional: proxy URL
# TENSORY_DB=~/.local/share/tensory/memory.db
EOF
\`\`\`

Or set these as environment variables in your shell profile (~/.zshrc).
After creating .env, restart the session — memory will activate automatically."

  jq -n --arg ctx "$SETUP_MSG" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
  exit 0
fi

# ── Normal run: recall memories ──────────────────────────────────────────
echo "$INPUT" | uvx --from "tensory[mcp]" tensory-hook recall 2>/dev/null

exit 0
