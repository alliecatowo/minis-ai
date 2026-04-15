# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI personality clones ("minis") built from GitHub profiles. An agentic pipeline analyzes commits, PRs, reviews, blog posts, and more, then creates an AI that thinks, writes, and argues like the developer.

## Commands

```bash
# Dev servers
mise run dev              # Both backend (:8000) and frontend (:3000)
mise run dev-backend      # Backend only
mise run dev-frontend     # Frontend only

# Testing
mise run test              # Run all backend tests
mise run test-unit         # Unit tests only (excludes integration/e2e)
mise run test-coverage     # Tests with HTML + terminal coverage report

# Linting & formatting
mise run lint              # Lint check (ruff)
mise run lint-fix          # Auto-fix lint issues
mise run format            # Format backend code

# Frontend
mise run typecheck         # TypeScript type check
mise run build             # Build frontend for production

# Database
mise run migrate           # Run DB migrations (alembic upgrade head)
mise run migrate-create    # Create a new migration (append -m "message")
mise run db-reset          # Stamp current state as head

# Utilities
mise run health            # Check backend health endpoint
mise run logs              # Tail backend/logs/app.log

# One-off pytest invocations
cd backend && uv run pytest tests/test_agent.py    # Run single test file
cd backend && uv run pytest -k "test_name"         # Run test by name

# Deployment
cd frontend && vercel --prod           # Deploy frontend to Vercel
cd backend && fly deploy               # Deploy backend to Fly.io
```

## Project Structure

- `backend/` — FastAPI + SQLAlchemy + PostgreSQL (Python 3.13, uv)
- `frontend/` — Next.js 15 + Tailwind v4 + shadcn/ui (pnpm)
- `mcp-server/` — FastMCP server wrapping Minis API (13 tools)
- `github-app/` — GitHub App webhook server for PR reviews by minis
- `.claude/` — Claude Code skills, commands, and agent definitions

Tooling is managed by mise (see `mise.toml`): pnpm, uv, node 22, python 3.13.

## Architecture

### Pipeline (3 stages)

Creating a mini runs a pipeline defined in `backend/app/synthesis/pipeline.py`:

1. **FETCH** — Ingestion sources pull raw data (GitHub API, blog scraping, etc.) and store it as `Evidence` DB records
2. **EXPLORE** — Per-source PydanticAI explorer agents run in parallel. Each agent uses the DB-backed tool suite (`tools.py`) to browse, read, and annotate evidence, persisting findings/quotes/knowledge nodes directly to the database
3. **SYNTHESIZE** — Chief synthesizer agent reads all persisted findings from DB to craft the soul document, then saves all structured data to the `Mini` record

### Key concepts

- **Soul document** (`spirit_content`): WHO the person is — personality, communication style, values. Written as instructions, not descriptions. Produced by the chief synthesizer.
- **Memory document** (`memory_content`): WHAT the person knows — projects, expertise, opinions, behavioral quotes. Assembled inline from explorer `ExplorerReport.memory_entries` during the SYNTHESIZE stage.
- **System prompt** (`system_prompt`): Wraps soul + memory into a four-pillar prompt (Personality, Style, Values, Knowledge). Built by `spirit.build_system_prompt()`.
- **Knowledge graph** (`knowledge_graph_json`): Structured nodes (skills, projects, patterns) and edges extracted by explorers via `save_knowledge_node` / `save_knowledge_edge` tools.
- **Principles matrix** (`principles_json`): Decision rules (trigger → action → value) extracted by explorers via `save_principle` tool.

### Agent framework

`backend/app/core/agent.py` wraps PydanticAI's `Agent` class:

- **`AgentTool`** dataclass: `name`, `description`, `parameters` (JSON Schema), `handler` (async callable). Kept for backward compatibility; converted to PydanticAI `Tool` objects (via `FunctionSchema`) at agent run time.
- **`run_agent()`**: Non-streaming loop calling `Agent.run()`. Returns `AgentResult` with `final_response`, `tool_outputs`, and `turns_used`.
- **`run_agent_streaming()`**: Streaming variant calling `Agent.run_stream_events()`, yielding `AgentEvent`s (`tool_call`, `tool_result`, `chunk`, `done`, `error`).

### Model hierarchy

`backend/app/core/models.py` defines the model tier system:

- **`ModelTier`** enum: `FAST` (compaction/summaries), `STANDARD` (explorers/chat), `THINKING` (soul synthesis), `EMBEDDING` (vectors)
- **`get_model(tier, user_override)`**: Resolves a PydanticAI model string (`"provider:model-name"`). Resolution order: user override → provider defaults → Gemini fallback.
- **`DEFAULT_PROVIDER`** env var: Selects the active provider (`gemini` / `anthropic` / `openai`). Defaults to `gemini`.
- Provider defaults are defined in `PROVIDER_DEFAULTS` — e.g. Gemini STANDARD = `google-gla:gemini-2.5-flash`, Anthropic STANDARD = `anthropic:claude-sonnet-4-6`, OpenAI STANDARD = `openai:gpt-4.1`.

### Compaction

`backend/app/core/compaction.py` applies per-provider context compaction via `create_compaction_processor()`:

- **Gemini / unknown providers**: Uses `pydantic_ai_summarization` to LLM-summarize history when it grows too large (FAST tier model, triggers at 40 messages, keeps 10).
- **Anthropic**: Returns `None` — native server-side compaction via `compact-2026-01-12` beta header.
- **OpenAI**: Returns `None` — native API compaction via `context_management.compact_threshold`.

The returned processor (or `None`) is passed as `history_processors` when constructing a PydanticAI `Agent`.

### Explorer system

Explorers extend `Explorer` ABC (`backend/app/synthesis/explorers/base.py`), implement `system_prompt()` and `user_prompt()`, and self-register via `register_explorer()`. Current explorers: `github`, `claude_code`, `blog`, `hackernews`, `stackoverflow`, `devto`, `website`.

Each explorer's `explore()` method calls `run_agent()` with the DB-backed tool suite from `tools.py`. When a `db_session` and `mini_id` are available (normal pipeline path), findings are written directly to the database. A fallback in-memory path exists for tests.

### Explorer tool suite

`backend/app/synthesis/explorers/tools.py` — `build_explorer_tools()` returns 12 `AgentTool` instances backed by the Evidence DB tables:

| Tool | Purpose |
|---|---|
| `browse_evidence` | Paginate through evidence items for a source |
| `search_evidence` | Keyword search across evidence content |
| `read_item` | Read a full evidence item (content + metadata) |
| `save_finding` | Persist a structured finding (personality, values, skills, etc.) |
| `save_memory` | Save a factual memory entry |
| `save_quote` | Save a behavioral quote with context and significance |
| `save_knowledge_node` | Add a node to the knowledge graph |
| `save_knowledge_edge` | Add an edge between knowledge graph nodes |
| `save_principle` | Add a decision principle (trigger → action → value) |
| `mark_explored` | Mark an evidence item as analyzed |
| `get_progress` | Check exploration progress counters |
| `finish` | Signal exploration complete, set status to "completed" |

### Evidence DB models

`backend/app/models/evidence.py`:

- **`Evidence`**: Raw ingestion data per mini per source (`source_type`, `item_type`, `content`, `explored` flag)
- **`ExplorerFinding`**: Structured findings from explorer agents (`category`, `content`, `confidence`)
- **`ExplorerQuote`**: Behavioral quotes with `context` and `significance`
- **`ExplorerProgress`**: Per-source agent progress tracker (counters for explored items, findings, memories, quotes, nodes; `status`; `summary`)

### Ingestion sources

Implement `IngestionSource` ABC (`backend/app/plugins/base.py`). Registered via plugin registry (`backend/app/plugins/registry.py`). Sources: `github` (default), `claude_code`, `blog`, `stackoverflow`, `devblog`, `hackernews`.

### Database

PostgreSQL via async SQLAlchemy + asyncpg. Neon in production, local PostgreSQL in dev. Migrations managed by Alembic (`backend/alembic/`). Connection config in `backend/app/db.py` — prefers `NEON_DATABASE_URL` over `DATABASE_URL`.

Key models beyond evidence: `Mini`, `User`, `Conversation`, `Message` (chat persistence), `Embedding` (pgvector), `MiniRevision` (pipeline history), `KnowledgeGraph` / `PrinciplesMatrix` (structured outputs).

### Authentication (Neon Auth + BFF proxy)

1. Frontend uses `@neondatabase/auth` with GitHub OAuth
2. Next.js BFF proxy (`frontend/src/app/api/proxy/[...path]/route.ts`) calls `/api/auth/sync` to upsert user, then issues a service JWT signed with `SERVICE_JWT_SECRET`
3. Backend validates service JWT via `get_current_user` dependency (`backend/app/core/auth.py`)

### LLM integration

All LLM calls go through PydanticAI (`backend/app/core/agent.py`, `backend/app/core/models.py`). Provider selection is driven by `DEFAULT_PROVIDER` env var; model strings use PydanticAI format (`provider:model-name`). `GOOGLE_API_KEY` (or `GEMINI_API_KEY`, which is auto-bridged on startup) is read directly by PydanticAI's Google provider. Langfuse tracing is optional (`LANGFUSE_ENABLED=true`).

## Key File Map

| To change... | Modify... |
|---|---|
| Pipeline stages/flow | `backend/app/synthesis/pipeline.py` |
| Soul document prompts | `backend/app/synthesis/chief.py` |
| Memory assembly logic | `backend/app/synthesis/memory_assembler.py` |
| System prompt structure | `backend/app/synthesis/spirit.py` |
| Add/modify an explorer | `backend/app/synthesis/explorers/<source>_explorer.py` |
| Explorer DB tool suite | `backend/app/synthesis/explorers/tools.py` |
| Explorer base class | `backend/app/synthesis/explorers/base.py` |
| Agent loop / PydanticAI wrapper | `backend/app/core/agent.py` |
| Model tier / provider config | `backend/app/core/models.py` |
| Compaction strategy | `backend/app/core/compaction.py` |
| Add an ingestion source | `backend/app/plugins/sources/<source>.py` + register in `registry.py` |
| Chat behavior/tools | `backend/app/routes/chat.py` |
| Mini creation endpoint | `backend/app/routes/minis.py` |
| Database models | `backend/app/models/` (`mini.py`, `user.py`, `evidence.py`, `conversation.py`, etc.) |
| Database connection | `backend/app/db.py` |
| App config / env vars | `backend/app/core/config.py` |
| Auth flow (backend) | `backend/app/core/auth.py`, `backend/app/routes/auth.py` |
| Auth flow (frontend) | `frontend/src/lib/auth.ts`, `frontend/src/app/api/proxy/[...path]/route.ts` |
| Frontend pages | `frontend/src/app/<route>/page.tsx` |
| API client functions | `frontend/src/lib/api.ts` |

## Worktree Setup

This project uses Claude Code worktrees for isolated parallel development. Worktrees are pre-configured:

- **Dependencies are symlinked** (`.venv`, `node_modules`, `.next`) — no reinstall needed
- **Secrets are copied** (`.env`, `.env.local`) — available immediately

To spawn an isolated subagent, use `isolation: "worktree"` in the Agent tool call. The subagent gets its own branch and working directory with everything ready to go.

## Environment Setup

```bash
# 1. Install mise, then install toolchain
curl https://mise.run | sh && mise install

# 2. Backend
cd backend && cp .env.example .env
# Edit .env — set GEMINI_API_KEY (or GOOGLE_API_KEY) and GITHUB_TOKEN at minimum
# Set DATABASE_URL to a PostgreSQL connection string
uv sync

# 3. Run migrations
mise run migrate

# 4. Frontend
cd frontend && pnpm install
# Create .env.local with AUTH_GITHUB_ID, AUTH_GITHUB_SECRET, AUTH_SECRET,
# BACKEND_URL=http://localhost:8000, SERVICE_JWT_SECRET (must match backend)

# 5. Run
mise run dev
```

## Required Environment Variables

**Backend** (`backend/.env`):
- `GEMINI_API_KEY` — Google Gemini API key (auto-bridged to `GOOGLE_API_KEY` for PydanticAI)
- `GITHUB_TOKEN` — GitHub PAT for profile ingestion
- `DATABASE_URL` — PostgreSQL connection (`postgresql+asyncpg://...`)
- `JWT_SECRET`, `SERVICE_JWT_SECRET` — Auth secrets (defaults provided for dev)
- `DEFAULT_PROVIDER` — Optional: `gemini` (default), `anthropic`, or `openai`

**Frontend** (`frontend/.env.local`):
- `AUTH_GITHUB_ID`, `AUTH_GITHUB_SECRET` — GitHub OAuth app credentials
- `AUTH_SECRET` — Neon Auth secret (generate with `npx auth secret`)
- `BACKEND_URL` — Backend URL (`http://localhost:8000` in dev)
- `SERVICE_JWT_SECRET` — Must match backend's value

## Claude Code Commands

- `/mini-review <username>` — Get a code review from a developer mini
- `/mini-chat <username>` — Chat with a developer mini
- `/mini-create <username>` — Create a new mini from a GitHub username
- `/mini-team <action> [usernames...]` — Assemble a team of minis for review/discuss/brainstorm

## API

Backend runs at `http://localhost:8000`. Swagger docs available at `/docs` in development.

- `POST /api/minis` — Create mini `{"username": "torvalds"}`
- `GET /api/minis` — List all minis
- `GET /api/minis/{username}` — Get mini details
- `POST /api/minis/{username}/chat` — Chat with mini (SSE)
- `GET /api/minis/{id}/progress` — Stream pipeline progress (SSE)
- `GET /api/health` — Health check
