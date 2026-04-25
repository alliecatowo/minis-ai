# Minis E2E Tests (Playwright)

End-to-end tests for the Minis frontend, targeting Chromium via Playwright.

## Prerequisites

- Node 22 + pnpm
- `mise` (for `mise run dev` to auto-start the dev servers locally)
- A running local dev environment (`mise run dev`) — OR let Playwright start it for you

## Install

```bash
cd e2e
pnpm install
pnpm playwright install chromium
```

## Run locally

```bash
# Run the full suite (auto-starts mise run dev if not already running)
pnpm playwright test

# Run a single spec file
pnpm playwright test specs/smoke.spec.ts

# Interactive UI mode (great for debugging)
pnpm playwright test --ui

# Headed mode (watch the browser)
pnpm playwright test --headed

# Debug a single test
pnpm playwright test --debug specs/smoke.spec.ts
```

The `playwright.config.ts` sets `reuseExistingServer: true`, so if `mise run dev`
is already running on `:3000`/`:8000` the tests will use it without restarting.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:3000` | Frontend base URL to test against |
| `NEXT_PUBLIC_DEV_AUTH_BYPASS` | _(unset)_ | Set `true` to bypass GitHub OAuth and use the hardcoded dev user (`alliecatowo`). Required for `create-mini` and `regenerate` specs. |
| `VERCEL_AUTOMATION_BYPASS_SECRET` | _(unset)_ | Vercel Deployment Protection automation bypass secret. Required in CI when preview deployments use Vercel Authentication/Password Protection. Sent as `x-vercel-protection-bypass`. |

### Local setup

Add to your `frontend/.env.local`:

```
NEXT_PUBLIC_DEV_AUTH_BYPASS=true
```

This is already handled by the `webServer` config when Playwright starts the dev
server — if you're starting it yourself, ensure the env var is set.

## Spec coverage

| Spec | What it tests |
|---|---|
| `smoke.spec.ts` | Landing page title, header nav links, no console errors, footer |
| `create-mini.spec.ts` | Dev-auth bypass → `/create` form renders, source selection, submit shows progress UI |
| `regenerate.spec.ts` | `/m/[username]` loads, chat input visible, regenerate navigation works |

Backend API calls are mocked via `page.route()` in `fixtures/dev-mini.ts` — no
live backend is required for these tests.

## CI

Tests run automatically on every pull request via `.github/workflows/e2e.yml`.

For Vercel-protected preview deployments, configure:

- GitHub Actions repository secret `VERCEL_AUTOMATION_BYPASS_SECRET` with the
  Vercel Project Settings → Deployment Protection → Protection Bypass for
  Automation secret.
- Vercel Preview environment variable `NEXT_PUBLIC_DEV_AUTH_BYPASS=true` so the
  deployed Next.js bundle enables the dev user for auth-dependent specs.
- Vercel Preview environment variable `DEV_AUTH_BYPASS=true` if any unmocked
  server-side proxy/backend auth paths are exercised by future e2e specs.

The Playwright global setup checks `/` before running specs. If Vercel returns
its login page, the run fails immediately with the exact bypass remediation
instead of cascading into broad page/snapshot assertion failures.

Artifacts (HTML report + test results including failure screenshots/videos) are
uploaded and retained for 14 days.

## What's NOT covered yet

These are follow-up tickets:

- **Full pipeline e2e** — Real backend + ingestion flow against a staging environment
  (needs `E2E_DATABASE_URL`, `GEMINI_API_KEY`, `GITHUB_TOKEN` secrets in CI)
- **Visual regression** — Screenshot diffing for layout/styling changes
- **Accessibility audit** — `@axe-core/playwright` sweep on key pages
- **Mobile / Safari** — Additional Playwright projects for `webkit` + `Mobile Chrome`
- **Chat interaction** — Message send/receive flow with a mocked streaming response
- **Auth gate** — Verify protected pages redirect unauthenticated users correctly
