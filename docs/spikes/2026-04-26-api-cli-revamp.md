# API + CLI Revamp Design Spike (2026-04-26)

## Scope
Revamp three distribution surfaces together: HTTP API, hosted CLI, and MCP server. Goal: make hackathon onboarding trivial while preserving high-fidelity review workflows.

## Current State (Inventory)

### API platform shape
- All routers are mounted under `/api` (not versioned), plus `/api/health`; no `/api/v1` namespace exists today ([backend/app/main.py:111], [backend/app/main.py:132]).
- Global unhandled errors return `{ "detail": "Internal server error" }`; per-route errors largely use `HTTPException(detail=...)`, so error shape is not standardized ([backend/app/main.py:124], [backend/app/routes/minis.py:389], [backend/app/routes/auth.py:93]).
- Routers already have tags, but tag strategy is file-local and uneven for product personas (`chat`, `team_chat`, `minis`, etc.) ([backend/app/routes/chat.py:43], [backend/app/routes/team_chat.py:22], [backend/app/routes/minis.py:79]).

### Current HTTP routes (method, path, return)
- `auth` (`/auth`): `GET /github-device/config -> GithubDeviceConfigResponse`, `POST /github-device/exchange -> TokenResponse`, `POST /logout -> {detail}`, `GET /me -> UserResponse`, `POST /sync -> SyncResponse` ([backend/app/routes/auth.py:20], [backend/app/routes/auth.py:105], [backend/app/routes/auth.py:113], [backend/app/routes/auth.py:159], [backend/app/routes/auth.py:164], [backend/app/routes/auth.py:174]).
- `minis` core (`/minis`): sources/promo/create/list/get-by-username/get-by-id/review+artifact+patch advisor/status-stream/delete/repos/dataset/revisions/graph/frameworks-at-risk/retire-framework; returns typed models for many review endpoints, mixed raw dict/list for others, and SSE for status ([backend/app/routes/minis.py:159], [backend/app/routes/minis.py:183], [backend/app/routes/minis.py:206], [backend/app/routes/minis.py:295], [backend/app/routes/minis.py:361], [backend/app/routes/minis.py:766], [backend/app/routes/minis.py:789], [backend/app/routes/minis.py:806], [backend/app/routes/minis.py:823], [backend/app/routes/minis.py:881], [backend/app/routes/minis.py:864], [backend/app/routes/minis.py:920], [backend/app/routes/minis.py:973], [backend/app/routes/minis.py:1064], [backend/app/routes/minis.py:1097], [backend/app/routes/minis.py:1266], [backend/app/routes/minis.py:1293], [backend/app/routes/minis.py:917]).
- `minis` trusted + owner review-cycle surfaces: duplicate trusted and owner variants for review cycles, artifact cycles, prediction-feedback memories, and review/artifact/patch prediction endpoints ([backend/app/routes/minis.py:538], [backend/app/routes/minis.py:558], [backend/app/routes/minis.py:570], [backend/app/routes/minis.py:590], [backend/app/routes/minis.py:604], [backend/app/routes/minis.py:627], [backend/app/routes/minis.py:639], [backend/app/routes/minis.py:653], [backend/app/routes/minis.py:669], [backend/app/routes/minis.py:685], [backend/app/routes/minis.py:714], [backend/app/routes/minis.py:727], [backend/app/routes/minis.py:742]).
- `chat` (`/minis/{mini_id}/chat`): POST SSE stream via `EventSourceResponse` ([backend/app/routes/chat.py:43], [backend/app/routes/chat.py:1041], [backend/app/routes/chat.py:1305]).
- `conversations` (`/minis/{mini_id}/conversations`): list/get/update-title/delete, JSON dict/list payloads ([backend/app/routes/conversations.py:17], [backend/app/routes/conversations.py:55], [backend/app/routes/conversations.py:83], [backend/app/routes/conversations.py:126], [backend/app/routes/conversations.py:157]).
- `teams` (`/teams`): create/list/get/update/delete + member add/remove; typed response models ([backend/app/routes/teams.py:63], [backend/app/routes/teams.py:66], [backend/app/routes/teams.py:88], [backend/app/routes/teams.py:125], [backend/app/routes/teams.py:185], [backend/app/routes/teams.py:212], [backend/app/routes/teams.py:231], [backend/app/routes/teams.py:281]).
- `team_chat`: `POST /teams/{team_id}/chat` SSE multi-mini stream ([backend/app/routes/team_chat.py:22], [backend/app/routes/team_chat.py:51]).
- `orgs` (`/orgs`): org CRUD, invites/join, members, org teams ([backend/app/routes/orgs.py:106], [backend/app/routes/orgs.py:182], [backend/app/routes/orgs.py:234], [backend/app/routes/orgs.py:273], [backend/app/routes/orgs.py:297], [backend/app/routes/orgs.py:332], [backend/app/routes/orgs.py:349], [backend/app/routes/orgs.py:386], [backend/app/routes/orgs.py:435], [backend/app/routes/orgs.py:499], [backend/app/routes/orgs.py:521], [backend/app/routes/orgs.py:553]).
- `export` (`/export`): mini subagent markdown, soul-doc markdown, and team-agent bundle JSON ([backend/app/routes/export.py:15], [backend/app/routes/export.py:87], [backend/app/routes/export.py:114], [backend/app/routes/export.py:139]).
- `settings` (`/settings`): get/update settings, usage, model catalogs, live key test ([backend/app/routes/settings.py:22], [backend/app/routes/settings.py:162], [backend/app/routes/settings.py:180], [backend/app/routes/settings.py:207], [backend/app/routes/settings.py:252], [backend/app/routes/settings.py:258], [backend/app/routes/settings.py:277]).
- `usage` (`/usage`): user summary/history/budget + admin global budget + admin LLM dashboards ([backend/app/routes/usage.py:18], [backend/app/routes/usage.py:86], [backend/app/routes/usage.py:118], [backend/app/routes/usage.py:149], [backend/app/routes/usage.py:196], [backend/app/routes/usage.py:213], [backend/app/routes/usage.py:245], [backend/app/routes/usage.py:259]).
- `upload`: `POST /upload/claude-code -> {files_saved,total_size}` ([backend/app/routes/upload.py:13], [backend/app/routes/upload.py:18], [backend/app/routes/upload.py:63]).
- Explicit `deprecated=` route flags are not present in the inspected route decorators ([backend/app/routes/auth.py:105], [backend/app/routes/minis.py:159], [backend/app/routes/chat.py:1041], [backend/app/routes/teams.py:66], [backend/app/routes/orgs.py:182], [backend/app/routes/settings.py:162], [backend/app/routes/usage.py:86]).

### Pagination and auth today
- Cursor pagination exists for `GET /minis` (`cursor`, `limit`, `next_cursor`, `has_more`) ([backend/app/routes/minis.py:295], [backend/app/routes/minis.py:309], [backend/app/routes/minis.py:353]).
- Other list endpoints are inconsistent: e.g. usage history uses `limit+offset`; many list endpoints have no pagination contract ([backend/app/routes/usage.py:118], [backend/app/routes/usage.py:120], [backend/app/routes/teams.py:88], [backend/app/routes/orgs.py:234]).
- User auth is bearer service JWT (`/auth/github-device/exchange` issues token); trusted integrations also use `require_trusted_service` secret-gated routes ([backend/app/routes/auth.py:113], [backend/app/routes/auth.py:150], [backend/app/routes/minis.py:542]).

### CLI inventory
- CLI is HTTP-API-first and expects API base + bearer token from env or local file (`~/.config/minis/mcp-token`) ([backend/cli.py:26], [backend/cli.py:27], [backend/cli.py:59], [backend/cli.py:94], [backend/cli.py:149]).
- Commands: `list`, `status`, `login`, `get`, `create`, `pre-review`, `patch-advisor`, `agreement`, `delete`, `recreate`, `chat`, `decision-frameworks` ([backend/cli.py:556], [backend/cli.py:612], [backend/cli.py:686], [backend/cli.py:704], [backend/cli.py:717], [backend/cli.py:783], [backend/cli.py:841], [backend/cli.py:908], [backend/cli.py:961], [backend/cli.py:974], [backend/cli.py:1068], [backend/cli.py:1144]).
- `login` currently delegates to MCP auth command instead of first-class CLI OAuth UX ([backend/cli.py:28], [backend/cli.py:699]).

### MCP inventory
- Current MCP exposes 11 tools in code: `list_sources`, `create_mini`, `list_minis`, `get_mini`, `get_mini_status`, `chat_with_mini`, `get_mini_graph`, `predict_review`, `advise_patch`, `advise_coding_changes`, `get_decision_frameworks`; auth is CLI subcommand (`auth login/status`), not MCP tool ([mcp-server/main.py:396], [mcp-server/main.py:406], [mcp-server/main.py:434], [mcp-server/main.py:449], [mcp-server/main.py:456], [mcp-server/main.py:489], [mcp-server/main.py:533], [mcp-server/main.py:544], [mcp-server/main.py:638], [mcp-server/main.py:732], [mcp-server/main.py:825], [mcp-server/main.py:917]).
- Repo docs still reference “13 tools,” so tool-count/docs drift exists ([CLAUDE.md:63]).

## Proposed State

### 1) API revamp
- Version all routes under `/api/v1/*`.
- Keep existing `/api/*` aliases for 3 months; return `Deprecation`, `Sunset`, and `Link` headers on legacy paths.
- Standardize all non-2xx errors to:
  - `{ "error": { "code": "...", "message": "...", "details": { ... } } }`
- Standardize list pagination contract across all list endpoints:
  - Request: `?cursor=...&limit=...`
  - Response: `{ data: [...], next_cursor, has_more }`
  - For expensive admin lists, optionally keep `limit` only but still return envelope.
- Auth model:
  - User-facing: bearer user JWT.
  - Distribution-surface actions (CLI/MCP/GitHub App): mini-scoped short-lived tokens per multi-bot actor spike (scope + mini_id + TTL).
- OpenAPI tags: enforce stable tag taxonomy (`auth`, `minis`, `chat`, `review`, `orgs`, `teams`, `admin`, `settings`, `usage`, `export`) and move duplicate review-cycle endpoints under one `review` tag set.
- Deprecate/remove candidates:
  - Duplicate trusted/owner review-cycle paths in favor of unified review resources with auth-based policy.
  - `settings/usage` in favor of canonical `usage` routes.
  - Legacy `/api/*` aliases after sunset.

### 2) CLI revamp
- First-class device-code OAuth: `mini login` opens browser, polls token exchange, writes `~/.config/mini/auth.json`.
- Command model:
  - `mini login`, `mini list`, `mini chat <username>`, `mini review <pr-url>`, `mini regen <username> --admin`, `mini eval`, `mini whoami`.
- Keep compatibility shims for old commands for one release with warnings.
- Add shell completion generation (`mini completion zsh|fish`).
- Add anonymous telemetry opt-in (`mini telemetry enable|disable`) with per-command counters only.

### 3) MCP revamp
- Split into two MCP surfaces:
  - User MCP: mini management + chat (`list_minis`, `chat_with_mini`, `whoami`, etc.).
  - Review MCP: review prediction + patch guidance only.
- Remove duplicative review tools by keeping one review-prediction primitive + one patch-guidance primitive.
- Multi-mini-aware design:
  - Required actor envelope in every response: `{mini_id, username, display_name}`.
  - Optional `default_mini` context to reduce repeated identifier args.

## Migration Plan and Deprecation Windows
- 2026-04-26 to 2026-05-10: ship `/api/v1` routes + unified error envelope + OpenAPI tags.
- 2026-05-11 to 2026-06-15: migrate CLI and MCP to `/api/v1`; add dual-write telemetry and command shims.
- 2026-06-16 to 2026-07-26: legacy `/api/*` serves with warning headers only; remove from docs/UI.
- Sunset date: 2026-07-26 (3 months from 2026-04-26).

## Breaking-Change List
- Legacy clients parsing `detail` errors will break once forced to error envelope.
- Offset-based callers (`/usage/me/history`) must move to cursor pagination.
- CLI command renames (`pre-review`/`patch-advisor`/`recreate`) require compatibility aliases.
- MCP consumers relying on current tool names may need migration mapping.

## Prioritized Implementation Tickets (12)
1. MINI-API-001: Add `/api/v1` router mounting and compatibility middleware for `/api/*` aliases.
2. MINI-API-002: Introduce shared error-envelope exception handlers + code taxonomy.
3. MINI-API-003: Add `Deprecation/Sunset/Link` headers on legacy alias paths.
4. MINI-API-004: Normalize cursor pagination schema and response envelope across list endpoints.
5. MINI-API-005: Migrate `usage/me/history` from offset to cursor.
6. MINI-API-006: Unify review-cycle endpoints (trusted + owner) behind resource + policy checks.
7. MINI-API-007: Add OpenAPI tag registry + per-route tag normalization.
8. MINI-AUTH-001: Implement mini-scoped token mint/verify/revoke for CLI/MCP/review surfaces.
9. MINI-CLI-001: Build `mini login` device-code OAuth storing `~/.config/mini/auth.json`.
10. MINI-CLI-002: Replace command tree with `login/list/chat/review/regen/eval/whoami` + backward aliases.
11. MINI-CLI-003: Add zsh/fish completion generation and install docs.
12. MINI-CLI-004: Add opt-in anonymous CLI telemetry with local toggle and privacy notice.

## Do This First
- Ship `/api/v1` + compatibility headers before CLI/MCP changes.
- Implement one shared error-envelope layer early to avoid client-by-client drift.
- Build CLI `mini login` device flow next; hackathon UX gains are immediate and unblock all other command work.
