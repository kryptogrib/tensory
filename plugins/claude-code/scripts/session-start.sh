#!/bin/bash
# tensory SessionStart hook — recall relevant memories on session start.
#
# Receives hook JSON on stdin (session_id, cwd, source, etc.)
# Outputs JSON with additionalContext for Claude's context window.
set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")

# Load env vars: .env (project) → userConfig (plugin) → shell env
# shellcheck disable=SC1091
source "$(dirname "$0")/load-env.sh"

# Pass hook input to tensory-hook recall (it reads cwd from JSON)
echo "$INPUT" | uvx --from "tensory[mcp]" tensory-hook recall 2>/dev/null

exit 0
