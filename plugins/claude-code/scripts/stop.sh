#!/bin/bash
# tensory Stop hook — save learnings from the conversation turn.
#
# Receives hook JSON on stdin with last_assistant_message.
# Runs async — doesn't block Claude's response.
set -euo pipefail

INPUT=$(cat)
CWD=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || echo "")

# Load env vars: .env (project) → userConfig (plugin) → shell env
# shellcheck disable=SC1091
source "$(dirname "$0")/load-env.sh"

# Guard: skip if this is a recursive stop hook call
STOP_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || echo "false")
if [ "$STOP_ACTIVE" = "true" ]; then
  exit 0
fi

# Pass hook input to tensory-hook save (it reads last_assistant_message from JSON)
# Pass through [tensory:debug] stderr lines, suppress uvx pip noise
echo "$INPUT" | uvx --refresh-package tensory --from "tensory[mcp,claude-code]" tensory-hook save 2> >(grep -v "^[[:space:]]*\(Downloading\|Downloaded\|Installed\|Resolved\|Audited\|Prepared\|Using\)" >&2)

exit 0
