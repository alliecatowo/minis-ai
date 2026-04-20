import { defineConfig, devices } from '@playwright/test';

const isCI = !!process.env.CI;

export default defineConfig({
  testDir: './specs',
  fullyParallel: true,
  forbidOnly: isCI,
  retries: isCI ? 2 : 1,
  workers: isCI ? 1 : undefined,
  reporter: isCI
    ? [['html', { outputFolder: 'playwright-report' }], ['github']]
    : 'list',

  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:3000',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  // Auto-start dev server only when not in CI (CI manages its own servers).
  // We start the frontend only; the backend is not required because all API
  // calls in the test suite are mocked via page.route().
  //
  // WORKTREE NOTE: node_modules is a symlink in git worktrees and Turbopack
  // chokes on it. We start the dev server from the canonical repo root to
  // avoid the Turbopack "Symlink node_modules is invalid" panic.
  // If you are running from the main repo checkout (not a worktree), remove
  // the `TURBOPACK=0` override — Turbopack is fine in that context.
  //
  // Set NEXT_PUBLIC_DEV_AUTH_BYPASS=true in frontend/.env.local for auth bypass.
  webServer: isCI
    ? undefined
    : {
        command: 'pnpm --dir ../frontend dev',
        url: 'http://localhost:3000',
        reuseExistingServer: true,
        timeout: 120_000,
        env: {
          NEXT_PUBLIC_DEV_AUTH_BYPASS: 'true',
          // Disable Turbopack to avoid symlinked node_modules crash in worktrees
          TURBOPACK: '0',
        },
      },
});
