# Multi-Bot Actors Design Spike (2026-04-26)

## 1. Executive Summary
Minis should be first-class actors, not one anonymous assistant surface. Today we already persist some identity on `minis` (`display_name`, `avatar_url`, `username`) and `users` (`display_name`, `avatar_url`, `github_username`), but distribution surfaces still flatten identity (especially GitHub App comments from `minis-app[bot]`). This spike proposes a consistent actor identity layer across chat UI, GitHub App, MCP, CLI, and future Slack/email: stable per-mini display identity, avatar resolution, signature conventions, per-mini scoped integration tokens, and an explicit action audit log with both `mini_id` and `actor_user_id`.

## 2. Identity Model Schema Diff

### What already exists
- `minis`: `id`, `username`, `owner_id`, `org_id`, `display_name`, `avatar_url`, `visibility`, etc.
- `users`: `id`, `github_username`, `display_name`, `avatar_url`.
- Org/team scaffolding exists: `organizations`, `org_members`, `org_invitations`, `teams`, `team_members`.
- Evidence has `lifecycle_audit_json` but this is evidence-level provenance, not cross-surface actor action logging.

### Proposed additions
- Keep core actor fields on `minis` as canonical runtime identity:
  - `display_name` (existing) remains the primary rendered name.
  - `avatar_url` (existing) remains the resolved avatar used by clients.
- Add a new table `mini_identity_profiles`:
  - `id`, `mini_id` (FK minis, unique), `name_mode` (`auto|custom`), `avatar_mode` (`source|derived|custom`), `signature_mode` (`none|via_handle|full_footer`), `voice_badge_color`, `signature_template`, `source_user_id` (FK users, nullable), `updated_by_user_id`, timestamps.
  - Rationale: avoids overloading `minis.metadata_json`; keeps identity strategy explicit and auditable.
- Add `mini_actor_tokens` table (hashed token storage):
  - `id`, `mini_id`, `token_hash`, `token_prefix`, `scope` (`github_app|mcp|cli|slack|email|all`), `created_by_user_id`, `expires_at`, `last_used_at`, `revoked_at`, timestamps.
- Add `mini_action_audit_log` table:
  - `id`, `mini_id`, `actor_user_id` (nullable for service-only calls), `surface` (`chat_ui|github_app|mcp|cli|slack|email|api`), `action` (`chat.send`, `review.post`, `token.rotate`, etc), `target_ref`, `request_id`, `metadata_json`, `created_at`.

### Avatar resolution strategy
1. `mini_identity_profiles.avatar_mode=custom`: use explicit profile asset.
2. `avatar_mode=derived`: generated/branded variant (same subject identity, surface-safe style).
3. Default `avatar_mode=source`: `mini.avatar_url` if present, else source owner `user.avatar_url`, else deterministic initials/avatar fallback.

### Display name strategy
- `name_mode=auto` default:
  - Prefer `mini.display_name` if already set.
  - Else derive from source user: `"<User display_name>'s mini"` (or GitHub username fallback).
- `name_mode=custom`:
  - Owner/admin can set display name with validation and collision checks in org/team scopes.

## 3. Surface-by-Surface Implementation Plan

### GitHub App
Current state:
- Reviews/comments are posted by one bot identity (`github_bot_login` default `minis-app[bot]`).
- `format_review_comment()` adds text header: `Review by @username's mini`.

Plan:
- Near term (compatible with GitHub App constraints): keep posting as app bot, but render a branded actor header in markdown:
  - Mini avatar image
  - Display name
  - Signature (`via @allie-mini`)
  - Optional confidence/voice badge color
- Include actor identity metadata in idempotency marker payload to prevent wrong-mini supersede behavior.
- Longer term: evaluate multiple GitHub Apps or delegated identities only if platform constraints and operational burden justify it.

### Chat UI
Current state:
- Conversation model links `mini_id` and `user_id`, but access control is mostly public-or-owner (`require_mini_access`).

Plan:
- Message bubbles render `mini.avatar_url` + resolved display name + optional signature chip.
- Mini picker lists minis user can access: own minis, team-shared minis, org-shared minis.
- Add identity preview card in mini settings (name/avatar/signature modes).

### MCP server
Decision: keep a single tool surface with `identifier`/`mini_id` parameter (current pattern), not per-mini tool names.

Justification:
- Current MCP design already resolves mini by username/UUID across tools.
- Per-mini tool explosion (`predict_review_allie`, `predict_review_linus`) breaks discoverability, increases registration churn, and complicates auth.
- Better UX: one stable tool set plus strong actor metadata in responses (`mini_id`, `display_name`, `avatar_url`, `signature`).

### CLI
- Support explicit actor targeting: `mini chat allie`, `mini chat linus`.
- Add user default actor config and override flag (e.g., `--mini <id|username>`).
- Display actor banner on session start to avoid silent wrong-mini conversations.

### Slack/email (future)
- Preserve actor envelope fields in outbound messages: `mini_id`, display name, avatar URL, signature template, and source audit IDs.
- Enforce same token scope model as MCP/CLI/GitHub App.

## 4. Distribution-Surface Auth
- Introduce per-mini short-lived tokens minted by backend (JWT or opaque + DB lookup):
  - Claims: `mini_id`, `scope`, `owner_user_id`, `expires_at`, `token_id`.
  - Max TTL by scope (e.g., CLI/MCP 24h; app-to-app 1h).
- Rotation:
  - Owner/org admin can rotate/revoke all tokens for a mini.
  - Single-surface revoke supported by `scope` and `token_id`.
- Usage:
  - GitHub App trusted calls can include mini-scoped token when acting for a mini.
  - MCP/CLI uses user auth to request ephemeral mini token before action.
- Security:
  - Store only token hash + prefix in DB.
  - Emit audit log row for mint, rotate, revoke, and use.

## 5. Sharing Model (Org → Team → Mini)
Current state:
- `TeamMember` maps team to mini (`team_id`, `mini_id`), not user-to-team membership.
- Mini access checks currently do not use org/team (`require_mini_access` only public or owner).

Proposed permission model:
- Read/chat mini:
  - Owner always.
  - Org admins/members if mini is org-visible.
  - Team members if mini is shared to team.
- Edit mini identity/framework settings:
  - Owner and delegated org admins.
- Delete mini:
  - Owner; org owner override for org-owned minis.
- Implement with explicit ACL relation (recommended new `mini_access_grants`) instead of implicit inference from current team shape.

## 6. Prioritized Tickets
1. `MINI-210` (S): Add spike acceptance tests and actor identity contract doc (API response fields + surface invariants).
2. `MINI-211` (M): Add `mini_identity_profiles` schema/model + CRUD service.
3. `MINI-212` (M): Add avatar/name resolution service with auto/custom modes.
4. `MINI-213` (M): Add `mini_action_audit_log` schema/model + shared logging middleware.
5. `MINI-214` (M): Add `mini_actor_tokens` schema/model + mint/rotate/revoke endpoints.
6. `MINI-215` (L): Update access control to org/team/ACL-aware read/write/delete checks.
7. `MINI-216` (M): Chat UI actor rendering (avatar/name/signature) + accessible mini selector.
8. `MINI-217` (M): GitHub App branded actor header (avatar embed + display name + signature) + idempotency update.
9. `MINI-218` (S): MCP response contract upgrade to return actor identity envelope on all mini tools.
10. `MINI-219` (S): CLI actor selection flags + default actor config + startup banner.
11. `MINI-220` (M): Token enforcement across MCP/CLI/GitHub App trusted calls.
12. `MINI-221` (S): Slack/email actor-envelope adapter interface (placeholder implementation + tests).

## 7. Open Questions
- GitHub constraints: do we accept permanent posting as one app bot with rich actor headers, or pursue multi-app identity despite operational overhead?
- Naming policy: should auto names be humanized (`Allie`) or explicit ownership form (`Allie's mini`) by default?
- Avatar policy: how much branding transformation is acceptable before identity trust degrades?
- Team model evolution: do we add user-team membership first, or go directly to mini ACL grants independent of teams?
- Token UX: should CLI/MCP silently refresh mini-scoped tokens, or require explicit `login --mini` flow for stronger operator awareness?
- Audit retention: what retention window is required for actor action logs in enterprise mode?
