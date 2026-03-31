# Tensory Memory Plugin for Claude Code

Context-aware long-term memory for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) using [Tensory](https://github.com/kryptogrib/tensory). Automatically recalls relevant context on every session start and saves learnings from conversations — full cognitive stack with collision detection, entity graphs, and temporal reasoning.

## Quick Start

```bash
# 1. Install the plugin from marketplace
claude plugin marketplace add kryptogrib/tensory
claude plugin install tensory

# 2. Configure LLM provider (choose ONE option)

# Option A: Anthropic API (direct)
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env

# Option B: Via proxy (CLIProxyAPI, LiteLLM, etc.)
echo 'ANTHROPIC_BASE_URL=http://localhost:8317' >> .env
echo 'ANTHROPIC_API_KEY=signal-hunter-local' >> .env

# Option C: No API key needed (uses Claude Code's own model)
echo 'ANTHROPIC_BASE_URL=claude-code' >> .env

# 3. (Optional) Add embeddings for vector search
echo 'OPENAI_API_KEY=sk-...' >> .env

# 4. Restart Claude Code — memory activates automatically
claude
```

## Features

- **Auto-recall** — on every session start, searches memory for relevant context and injects it invisibly via `additionalContext`
- **Auto-save** — after each response, extracts claims and entities from the conversation via LLM and stores them with collision detection
- **No API key mode** — set `ANTHROPIC_BASE_URL=claude-code` to use Claude Code's own model via `claude-agent-sdk` (Claude Pro/Max subscription)
- **Hybrid search** — FTS5 full-text + vector similarity + entity graph, fused with Reciprocal Rank Fusion
- **Collision detection** — structural + semantic dedup prevents contradictory or duplicate memories
- **Temporal reasoning** — tracks when facts were valid, detects superseded information
- **Zero daemon** — no background server needed; each hook invocation creates a store, does work, closes
- **Project-scoped config** — `.env` file per project, plugin userConfig, or shell env vars

## Architecture

The plugin uses two Claude Code hook events:

| Hook | Event | Timeout | Async | Purpose |
|------|-------|---------|-------|---------|
| `session-start.sh` | `SessionStart` | 15s | no | Search memory, inject recalled context |
| `stop.sh` | `Stop` | 30s | yes | Extract claims from conversation, store |

### How It Works

```
Session Start                          Stop (after each response)
─────────────                          ─────────────────────────
1. Load .env                           1. Load .env
2. Check API keys configured?          2. Read last_assistant_message
   ├─ No → show setup instructions     3. tensory-hook save
   └─ Yes ↓                               ├─ LLM available?
3. tensory-hook recall                     │  ├─ Yes → full extraction pipeline
   ├─ Search memory (project name)         │  │   text → LLM → claims + entities
   ├─ Format results                       │  │   → collision detection → store
   └─ Output additionalContext             │  └─ No → store raw text (FTS only)
      (Claude sees it, user doesn't)       └─ Done (async, non-blocking)
```

### Directory Structure

```
plugins/claude-code/
├── .claude-plugin/
│   ├── plugin.json          # Plugin metadata + userConfig schema
│   └── marketplace.json     # Marketplace distribution config
├── hooks/
│   └── hooks.json           # Hook event → script mapping
├── scripts/
│   ├── load-env.sh          # Environment loader (priority chain)
│   ├── session-start.sh     # SessionStart hook
│   └── stop.sh              # Stop hook (async)
└── README.md                # This file
```

### Core Pipeline

Tensory's claim extraction pipeline runs inside `tensory-hook save`:

```
Conversation text
    ↓
[Token count check]
    ├─ < 3000 tokens → single LLM extraction call
    └─ ≥ 3000 tokens → topic segmentation → parallel extraction
        ↓
[Claims + Entities extracted]
    ↓
[Collision detection]  ← structural (entity overlap) + semantic (embedding similarity)
    ↓
[Dedup]  ← MinHash/LSH Jaccard similarity
    ↓
[Store]  → SQLite + sqlite-vec + FTS5 + entity graph
```

## LLM Provider Options

### Option A: Anthropic API (direct)

Requires an Anthropic API key. Best extraction quality with Claude models.

```bash
ANTHROPIC_API_KEY=sk-ant-...
TENSORY_MODEL=claude-haiku-4-5-20251001   # default, cheapest
```

### Option B: Via Proxy

Use CLIProxyAPI, LiteLLM, or any Anthropic-compatible proxy.

```bash
ANTHROPIC_BASE_URL=http://localhost:8317
ANTHROPIC_API_KEY=signal-hunter-local
```

### Option C: Claude Code SDK (no API key)

Uses `claude-agent-sdk` to make LLM calls through your Claude Pro/Max subscription. No API key or proxy needed — authenticates via OAuth tokens from `claude auth login`.

```bash
ANTHROPIC_BASE_URL=claude-code
```

**Requirements:**
- Claude Code CLI >= 2.0.0
- `claude auth login` completed
- Claude Pro or Max subscription

**How it works:** The `claude-agent-sdk` Python package spawns the Claude CLI as a subprocess and communicates via JSON streaming. It reads OAuth tokens from your system keychain (stored by `claude auth login`). The SDK makes single-turn LLM calls with `max_turns=1, allowed_tools=[]` — pure text completion, no tool use.

**Trade-offs:**
- First call ~2-3s latency (CLI subprocess startup)
- No token usage tracking (SDK doesn't report usage)
- Rate limits depend on your subscription tier

## Embeddings (Optional)

Embeddings enable vector similarity search on top of FTS5 full-text search. Without them, search still works via FTS5 + entity graph — just less precise for semantic queries.

```bash
OPENAI_API_KEY=sk-...                    # enables OpenAIEmbedder
# OPENAI_BASE_URL=http://localhost:8080  # optional proxy
```

Embeddings are **independent** of the LLM provider — you can use `ANTHROPIC_BASE_URL=claude-code` for extraction and `OPENAI_API_KEY` for embeddings simultaneously.

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | — | Anthropic API key for LLM extraction |
| `ANTHROPIC_BASE_URL` | — | Proxy URL, or `claude-code` for SDK mode |
| `ANTHROPIC_AUTH_TOKEN` | — | Alternative to API key (for some proxies) |
| `OPENAI_API_KEY` | — | OpenAI API key for embeddings |
| `OPENAI_BASE_URL` | — | OpenAI proxy URL |
| `TENSORY_MODEL` | `claude-haiku-4-5-20251001` | Model for claim extraction |
| `TENSORY_DB` | `~/.local/share/tensory/memory.db` | SQLite database path |
| `TENSORY_MAX_TRANSCRIPT` | `8000` | Max chars of transcript to process per save |

### Configuration Priority

Environment variables are loaded in this order (later wins):

1. **Shell environment** (`~/.zshrc`, `~/.bashrc`) — lowest priority
2. **Plugin userConfig** (`CLAUDE_PLUGIN_OPTION_*`) — set during `claude plugin install`
3. **Project `.env` file** (`$CWD/.env` or `$CWD/.tensory.env`) — highest priority

This means you can set global defaults in your shell profile and override per-project with `.env` files.

### Plugin userConfig

During `claude plugin install`, you'll be prompted for these settings:

| Setting | Description |
|---------|-------------|
| `OPENAI_API_KEY` | For embeddings (vector search) |
| `ANTHROPIC_API_KEY` | For LLM claim extraction |
| `ANTHROPIC_BASE_URL` | Proxy URL or `claude-code` |
| `TENSORY_DB` | Database path |

All are optional — you can configure via `.env` instead.

## Configuration Matrix

| `ANTHROPIC_BASE_URL` | `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` | LLM | Embedder | Search |
|---|---|---|---|---|---|
| `claude-code` | ignored | present | SDK | OpenAI | FTS5 + vector + graph |
| `claude-code` | ignored | absent | SDK | None | FTS5 + graph only |
| proxy URL | present | present | Anthropic (proxy) | OpenAI | FTS5 + vector + graph |
| absent | present | present | Anthropic (direct) | OpenAI | FTS5 + vector + graph |
| absent | absent | absent | None | None | FTS5 + graph (raw text only) |

## Troubleshooting

### Plugin not activating

- Check plugin is installed: `claude plugin list`
- Verify hooks are registered in Claude Code settings
- Restart Claude Code after installation

### "Memory plugin installed but not configured yet"

This message appears when no API keys are detected. Fix:

```bash
# Quickest setup (no API key needed):
echo 'ANTHROPIC_BASE_URL=claude-code' >> .env

# Or with full features:
echo 'OPENAI_API_KEY=sk-...' >> .env
echo 'ANTHROPIC_API_KEY=sk-ant-...' >> .env
```

### Claude Code SDK auth error

If you see "Run 'claude auth login'" errors:

```bash
claude auth login    # re-authenticate
claude               # restart
```

### No memories being recalled

- Memories need at least one save cycle first (talk to Claude, let it respond)
- Check database exists: `ls ~/.local/share/tensory/memory.db`
- Run health check: `uvx --from "tensory[mcp,claude-code]" tensory-hook health`

### Slow recall

- The SessionStart hook has a 15-second timeout
- First call with `claude-code` mode takes 2-3s (CLI startup)
- Subsequent calls are faster within the same session

### Using a custom database path

```bash
echo 'TENSORY_DB=/path/to/my/memory.db' >> .env
```

The directory will be created automatically.

## How Memory Works

Tensory stores memories as **claims** — atomic facts extracted from conversations:

```
"The project uses PostgreSQL for production"
  → entities: [project, PostgreSQL]
  → type: semantic (fact)
  → valid_from: 2026-03-31
```

When recalling, Tensory searches across three channels:
1. **FTS5** — full-text keyword matching
2. **Vector** — semantic similarity via embeddings (if OPENAI_API_KEY set)
3. **Graph** — entity relationship traversal

Results are fused with Reciprocal Rank Fusion and deduplicated with MMR reranking.

### Memory Types

| Type | What it stores | Example |
|------|---------------|---------|
| **Semantic** | Facts, observations | "The API uses JWT tokens" |
| **Episodic** | Events, what happened | "Deployed v2.0 on March 15" |
| **Procedural** | Skills, how-to | "To deploy: run `make release`" |

## Development

### Testing the plugin locally

```bash
# Run tensory-hook directly
echo '{"cwd": "/your/project"}' | uvx --from "tensory[mcp,claude-code]" tensory-hook recall

# Check component health
uvx --from "tensory[mcp,claude-code]" tensory-hook health

# Run the test suite
uv run pytest tests/test_claude_code_llm.py -v
```

### Building from source

```bash
git clone https://github.com/kryptogrib/tensory
cd tensory
uv sync --all-extras
uv run pytest tests/
```

## Links

- [Tensory Repository](https://github.com/kryptogrib/tensory)
- [Claude Code Documentation](https://docs.anthropic.com/en/docs/claude-code)
- [Claude Code Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Claude Agent SDK](https://github.com/anthropics/claude-agent-sdk-python)

## License

MIT
