# Minis MCP Server

MCP server that wraps the Minis API, letting you create and chat with AI personality clones of GitHub developers from any MCP client (Claude Desktop, Claude Code, etc).

## Tools

| Tool | Description |
|------|-------------|
| `list_sources` | List the ingestion sources currently exposed by the backend |
| `create_mini` | Create or regenerate a mini from a GitHub username |
| `list_minis` | List public minis, or your own minis with auth |
| `get_mini` | Get the current mini profile by UUID or username |
| `get_mini_status` | Follow pipeline progress events until completion |
| `chat_with_mini` | Send a message to a mini and collect the streamed reply |
| `get_mini_graph` | Fetch the mini's knowledge graph and principles payload |
| `predict_review` | Ask what a mini would likely block on for a proposed change before review |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) installed
- Minis backend running at `http://localhost:8000` (or set `MINIS_BACKEND_URL`)
- Optional: `MINIS_AUTH_TOKEN` bearer token for authenticated routes such as `create_mini` and `list_minis(mine=true)`

## Running standalone

```bash
cd mcp-server
uv run minis-mcp
```

## Claude Code configuration

Add to `.claude/settings.json` or project `.mcp.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/home/Allie/develop/minis-hackathon/mcp-server", "minis-mcp"],
      "env": {
        "MINIS_BACKEND_URL": "http://localhost:8000",
        "MINIS_AUTH_TOKEN": "optional-user-bearer-token"
      }
    }
  }
}
```

## Claude Code pre-review workflow

Use `predict_review` when you want a quick "what would this reviewer likely block on?" pass before sending code for human review. Pass at least one of `title`, `description`, `diff_summary`, or `changed_files`.

Example prompt:

```text
Use the minis MCP server `predict_review` tool for reviewer `alliecatowo`.
Title: "Refactor auth retries"
Description: "Touches token refresh and worker retry behavior."
Changed files: ["backend/app/core/auth.py", "backend/app/worker.py"]
Diff summary: "Adds retry logic and reshapes the auth error path."
Tell me the likely blockers first, then the open questions.
```

## Claude Desktop configuration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "minis": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/mcp-server", "minis-mcp"],
      "env": {
        "MINIS_BACKEND_URL": "http://localhost:8000",
        "MINIS_AUTH_TOKEN": "optional-user-bearer-token"
      }
    }
  }
}
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MINIS_BACKEND_URL` | `http://localhost:8000` | URL of the Minis FastAPI backend |
| `MINIS_AUTH_TOKEN` | unset | Optional bearer token forwarded to authenticated backend routes |
