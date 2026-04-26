# Codex Device-Auth Feasibility Spike (Minis)

## 1. TL;DR
- Codex CLI package here is binary-only; direct Rust source isn’t shipped.
- Device flow artifacts are visible: `/deviceauth/*`, `/oauth/token`, `client_id`, `user_code`.
- Client id `app_EMoamEEZ73f0CkXaXp7hrann` appears in auth paths.
- Minis currently assumes API-key auth for OpenAI provider calls.
- [DESIGN PROPOSAL] Use backend-owned token broker; avoid exposing refresh tokens to frontend.

## 2. Feasibility Verdict
Short answer: **partially feasible, not drop-in feasible**. Minis can likely add a user-owned Codex/ChatGPT auth path, but it is **not** a direct replacement for today’s `OPENAI_API_KEY` path without new provider plumbing. The Codex CLI artifacts show two distinct surfaces: ChatGPT backend auth (`https://chatgpt.com/backend-api`) and OpenAI API endpoint usage (`https://api.openai.com/v1`) (source: `/tmp/codex_strings.txt:1921439`, `/tmp/codex_strings.txt:1931349`).

Given current Minis code, chat calls pass `llm_api_key` into PydanticAI OpenAI provider as an API key (source: `backend/app/routes/chat.py:976`, `backend/app/routes/chat.py:1138`, `backend/app/core/agent.py:114`, `backend/app/core/agent.py:118`, `backend/app/core/agent.py:402`, `backend/app/core/agent.py:511`). That path assumes API-key semantics, not ChatGPT-device OAuth semantics. So feasibility is **Medium** if we add a dedicated auth mode + token store + custom provider transport; **Low** if we try to reuse existing BYOK path unchanged.

## 3. OAuth Flow
Observed from local binary string table (`/tmp/codex_strings.txt`) and embedded source-path references:

- Device-flow code path names are present under `codex-rs/login/src/device_code_auth.rs` and auth manager/server modules (source: `/tmp/codex_strings.txt:1875868`, `/tmp/codex_strings.txt:1875879`, `/tmp/codex_strings.txt:1875887`).
- Device-flow endpoint fragments are present: `/codex/device`, `/deviceauth/usercode`, `/deviceauth/callback`, `/deviceauth/token` (source: `/tmp/codex_strings.txt:1875873`, `/tmp/codex_strings.txt:1875870`, `/tmp/codex_strings.txt:1875874`, `/tmp/codex_strings.txt:1875867`).
- OAuth authorize/token artifacts are present: `/oauth/authorize?`, `/oauth/token`, and `grant_type=authorization_code&code=...&redirect_uri=...&client_id=...&code_verifier=...` (source: `/tmp/codex_strings.txt:1881216`, `/tmp/codex_strings.txt:1875890`, `/tmp/codex_strings.txt:1875891`, `/tmp/codex_strings.txt:1875892`, `/tmp/codex_strings.txt:1875893`, `/tmp/codex_strings.txt:1875894`).
- Token endpoint host appears explicitly as `https://auth.openai.com/oauth/token` (source: `/tmp/codex_strings.txt:1930744`).
- Device-auth payload fields appear explicitly: `device_auth_id`, `user_code`, `authorization_code`, `code_challenge`, `code_verifier`, `client_id`, `access_token`, `refresh_token`, `grant_type`, `token_type_hint` (source: `/tmp/codex_strings.txt:1921439`).
- OAuth `client_id` appears as `app_EMoamEEZ73f0CkXaXp7hrann` (source: `/tmp/codex_strings.txt:1921439`, `/tmp/codex_strings.txt:1931103`).
- Refresh behavior is explicitly present (skip refresh guard, refresh-token-expired/revoked/used errors, oauth exchange success/failure states) (source: `/tmp/codex_strings.txt:1930744`, `/tmp/codex_strings.txt:1921439`).

Resulting token structure (observed fields):
- `access_token`, `refresh_token`, `client_id`, `grant_type`; plus ChatGPT metadata (`chatgpt_account_id`, `plan_type`, `auth_mode`, `tokens`, `last_refresh`) in storage/auth strings (source: `/tmp/codex_strings.txt:1930744`).
- `id_token` / token-exchange artifacts also appear (`urn:ietf:params:oauth:grant-type:token-exchange`, `urn:ietf:params:oauth:token-type:id_token`) (source: `/tmp/codex_strings.txt:1930744`).

Token storage/refresh:
- `auth.json` and `login/src/auth/storage.rs` are explicitly referenced; OAuth keyring persistence strings are also present (source: `/tmp/codex_strings.txt:1930744`, `/tmp/codex_strings.txt:1881192`, `/tmp/codex_strings.txt:1881193`, `/tmp/codex_strings.txt:1881194`).
- [HYPOTHESIS] Codex uses a hybrid strategy: local JSON + keyring-backed secure storage depending runtime/platform.

Scope requested:
- **NOT FOUND** (explicit scope value for ChatGPT device auth) in local shipped files.
- I found `scope` parameter artifacts but no stable literal scope string tied to Codex login flow (source: `/tmp/codex_strings.txt:1882031`, `/tmp/codex_strings.txt:2003126`).

## 4. API Endpoint Analysis
Observed endpoint families in Codex binary artifacts:

- ChatGPT backend family:
  - `https://chatgpt.com/backend-api` and `https://chatgpt.com/backend-api/codex` (source: `/tmp/codex_strings.txt:1931103`, `/tmp/codex_strings.txt:1931349`).
  - Error strings: “ChatGPT backend requests require Codex backend auth”, “ChatGPT account ID not available, please re-run `codex login`” (source: `/tmp/codex_strings.txt:1921707`).
- OpenAI API family:
  - `https://api.openai.com/v1`, plus `/v1/models` and `/responses` paths (source: `/tmp/codex_strings.txt:1931349`, `/tmp/codex_strings.txt:1876057`, `/tmp/codex_strings.txt:1876176`).

Interpretation:
- ChatGPT/Codex plan auth is accepted on ChatGPT backend paths (source evidence above).
- API key mode is separately supported (“Provide your own API key”, usage-based billing; and `OPENAI_API_KEY`/`CODEX_API_KEY` envs) (source: `/tmp/codex_strings.txt:1938671`, `/tmp/codex_strings.txt:1930744`).
- [HYPOTHESIS] `api.openai.com/v1` calls in Codex likely expect standard API-key auth unless Codex injects a distinct bearer/token-exchange header path.

Models/capabilities visible in embedded model catalog artifacts:
- Slugs include `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.2` (source: `/tmp/codex_strings.txt:1931613`, `/tmp/codex_strings.txt:1931714`, `/tmp/codex_strings.txt:1931816`, `/tmp/codex_strings.txt:1931921`, `/tmp/codex_strings.txt:1932026`).
- `gpt-5.3-codex` is marked `supported_in_api: true` in embedded model JSON blob (source: `/tmp/codex_strings.txt:1931885`).
- Capability flags include `supports_parallel_tool_calls` and `supports_search_tool` (source: `/tmp/codex_strings.txt:1931810`, `/tmp/codex_strings.txt:1931789`).
- Structured-output-related protocol items (`final_output_json_schema`, function call output items) are present (source: `/tmp/codex_strings.txt:1927639`, `/tmp/codex_strings.txt:1929100`).
- [HYPOTHESIS] Tool-calling + structured outputs are available for these Codex models on at least one Codex transport, but exact per-endpoint matrix is not fully recoverable from local binary strings.

## 5. Minis Integration Design
Current Minis touch points:

- Model/provider tier system: OpenAI defaults currently `openai:gpt-5` / `openai:o3` (source: `backend/app/core/models.py:43`, `backend/app/core/models.py:46`, `backend/app/core/models.py:47`).
- Per-request key injection path: `run_agent`/`run_agent_streaming` accept `api_key` and instantiate `OpenAIProvider(api_key=...)` (source: `backend/app/core/agent.py:330`, `backend/app/core/agent.py:337`, `backend/app/core/agent.py:402`, `backend/app/core/agent.py:437`, `backend/app/core/agent.py:444`, `backend/app/core/agent.py:511`).
- User secret store today: `UserSettings.llm_api_key` encrypted/decrypted via Fernet helper (source: `backend/app/models/user_settings.py:16`, `backend/app/routes/settings.py:192`, `backend/app/routes/chat.py:984`, `backend/app/routes/chat.py:986`, `backend/app/core/encryption.py:47`, `backend/app/core/encryption.py:51`).
- Chat path reads user settings and passes model+api_key into streaming agent (source: `backend/app/routes/chat.py:976`, `backend/app/routes/chat.py:983`, `backend/app/routes/chat.py:1137`, `backend/app/routes/chat.py:1138`).
- Route placement precedent: auth flows live in `backend/app/routes/auth.py`, mounted at `/api/auth/*` (source: `backend/app/routes/auth.py:20`, `backend/app/main.py:113`).
- Frontend BFF currently mints service JWT for backend user identity; it is not an OAuth broker for OpenAI today (source: `frontend/src/app/api/proxy/[...path]/route.ts:97`, `frontend/src/app/api/proxy/[...path]/route.ts:241`).

[DESIGN PROPOSAL] Handshake location:
- Prefer **backend-owned device flow** under `/api/auth/codex-device/*` (parallel to GitHub device flow already present) (source: `backend/app/routes/auth.py:105`, `backend/app/routes/auth.py:113`).
- Rationale: keep refresh token and token-exchange secrets server-side; frontend only handles poll UX and confirmation code display.

[DESIGN PROPOSAL] Token storage strategy:
- Extend `user_settings` (or a new `user_external_auth` table) with encrypted fields:
  - `codex_access_token_enc`, `codex_refresh_token_enc`, `codex_token_expires_at`, `codex_client_id`, `codex_chatgpt_account_id`, `codex_plan_type`, `codex_last_refresh_at`.
- Reuse existing encryption infra (`encrypt_value`/`decrypt_value`) and lifecycle checks (source: `backend/app/core/encryption.py:31`, `backend/app/core/encryption.py:47`, `backend/app/core/encryption.py:51`).

[DESIGN PROPOSAL] Per-request wiring into agent stack:
- Add auth mode selector in chat path (`api_key` vs `codex_oauth`).
- For `codex_oauth`, do **not** pass token to current `OpenAIProvider(api_key=...)` path unchanged.
- Implement a Codex/ChatGPT transport provider (or custom HTTP client wrapper) that targets the accepted endpoint family and uses OAuth bearer tokens.
- Keep existing API-key path untouched for BYOK fallback.

[DESIGN PROPOSAL] Refresh cadence:
- Refresh on-demand before expiry (e.g., if `expires_at - now < 5m`) and opportunistically after 401.
- Honor rotation errors (`expired`, `revoked`, `already used`) by forcing re-login (matching observed Codex behavior strings) (source: `/tmp/codex_strings.txt:1930744`).

## 6. Security and Abuse Considerations
- User-bound token isolation: never share one user’s ChatGPT refresh token across users/teams.
- Encrypt tokens at rest and redact from logs; current encryption pattern is adequate baseline (source: `backend/app/core/encryption.py:15`, `backend/app/core/encryption.py:47`).
- Enforce revocation/logout path to clear stored tokens; Codex has revoke URL artifacts (`/oauth/revoke`) (source: `/tmp/codex_strings.txt:1930744`).
- Device-code phishing risk: display origin + verification URL explicitly; require short-lived pending sessions.
- Abuse vector: “free compute” could become shared-account laundering. Add per-user attestation + anomaly detection. [HYPOTHESIS]
- Terms/compliance: ensure ChatGPT plan terms permit third-party backend proxying for automated workloads. [HYPOTHESIS]

## 7. Cost-of-Ownership Comparison
| Dimension | API Key Path (Current Minis) | Codex ChatGPT Auth Path (Proposed) |
|---|---|---|
| Who pays inference | Minis (usage metered) | End user subscription/credits [HYPOTHESIS] |
| Pricing basis | Per-token in `MODEL_PRICING`/fallback (source: `backend/app/core/pricing.py:5`, `backend/app/core/pricing.py:20`) | Included plan + credits windows shown in Codex UI strings (source: `/tmp/codex_strings.txt:1938628`) |
| Backend implementation complexity | Already shipped | High: new OAuth broker + token store + custom transport |
| Operational risk | Known, stable | Higher: token refresh/revoke, auth drift, entitlement checks |
| Marginal cost to Minis per request | Non-zero | Near-zero inference spend, higher auth complexity [HYPOTHESIS] |
| Rate-limit bypass semantics | BYOK bypasses limits today (source: `backend/app/core/rate_limit.py:33`, `backend/app/core/rate_limit.py:36`) | Could similarly bypass after Codex auth [DESIGN PROPOSAL] |

## 8. Follow-up Implementation Tickets
- `MINI-XXX: Spike Validation Harness for Codex OAuth Endpoints`
  - Build a backend-only prototype that validates one request path using stored OAuth tokens and logs endpoint/auth failures.
- `MINI-XXX: Add Codex OAuth Token Schema + Migration`
  - Add encrypted token fields and expiry metadata (new table or `user_settings` extension).
- `MINI-XXX: Auth Routes for Codex Device Flow`
  - Implement `/api/auth/codex-device/start`, `/poll`, `/revoke`, mirroring existing GitHub device route style.
- `MINI-XXX: Provider Abstraction for ChatGPT/Codex Transport`
  - Add a dedicated provider path instead of overloading `OpenAIProvider(api_key=...)`.
- `MINI-XXX: Chat Route Auth Mode Selection`
  - Add per-user auth mode resolution and fallback precedence (`codex_oauth` -> `llm_api_key` -> default provider key).
- `MINI-XXX: Security Hardening + Audit Events`
  - Add token-redaction, suspicious device-flow telemetry, and forced relogin logic on refresh-token rotation errors.
