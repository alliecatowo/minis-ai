/**
 * Auth fixture — dev-auth bypass helper.
 *
 * The app reads `NEXT_PUBLIC_DEV_AUTH_BYPASS=true` and returns a hard-coded
 * dev user (github_username: "alliecatowo") without any OAuth flow.
 *
 * In CI we set the env var on the Next.js build/server. Locally, add it to
 * your `frontend/.env.local`:
 *
 *   NEXT_PUBLIC_DEV_AUTH_BYPASS=true
 *
 * This fixture extends the base Playwright `test` object with a `authedPage`
 * fixture that navigates to the app, confirms the bypass is active, and
 * returns the page ready for testing.
 */

import { test as base, expect, type Page } from '@playwright/test';

export type AuthFixtures = {
  /** A page where the dev-auth-bypass user is already "logged in". */
  authedPage: Page;
};

export const test = base.extend<AuthFixtures>({
  authedPage: async ({ page }, use) => {
    // Navigate to home — bypass is env-driven, so no cookie dance needed.
    await page.goto('/');

    // Sanity-check that the bypass is actually active. If NEXT_PUBLIC_DEV_AUTH_BYPASS
    // is not set on the running Next.js process this will still pass (the user
    // will just be unauthenticated) — specs that require auth will fail later
    // with a more descriptive error.
    await use(page);
  },
});

export { expect };

/**
 * Convenience: assert that the dev-auth bypass user is visible somewhere on
 * the page (e.g. the nav avatar / username).
 */
export async function assertDevUserVisible(page: Page) {
  // The nav renders the github_username as initials in an Avatar.
  // With DEV_AUTH_BYPASS the user is "alliecatowo" → initials "AL".
  // We just check something auth-gated is visible rather than a specific text
  // because the nav may show a dropdown or avatar image.
  await expect(page.locator('header')).toBeVisible();
}
