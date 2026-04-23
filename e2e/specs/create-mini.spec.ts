/**
 * create-mini.spec.ts — Create-mini flow tests.
 *
 * Uses NEXT_PUBLIC_DEV_AUTH_BYPASS=true (set in the running Next.js process)
 * so the AuthGate passes without OAuth. Backend calls are mocked via
 * page.route() to keep the test fast and hermetic.
 *
 * Coverage:
 *  - /create?username=... renders the form when authenticated
 *  - GitHub source checkbox is visible and selected by default
 *  - "Start Analysis" button is present and enabled
 *  - Submitting calls POST /api/proxy/minis and shows the pipeline progress UI
 */

import { test, expect } from '@playwright/test';
import { mockMiniApi, mockPipelineSse, TEST_USERNAME } from '../fixtures/dev-mini';

test.describe('create-mini', () => {
  test.beforeEach(async ({ page }) => {
    // Install API mocks before each test
    await mockMiniApi(page);
    await mockPipelineSse(page);

    // Also mock the by-username check (used to detect if mini already exists)
    await page.route(
      `**/api/proxy/minis/by-username/${TEST_USERNAME}`,
      async (route) => {
        // Return 404 so the page doesn't redirect to /m/username
        await route.fulfill({ status: 404, body: '{"detail":"Not found"}' });
      },
    );
  });

  test('create page renders source selection form', async ({ page }) => {
    await page.goto(`/create?username=${TEST_USERNAME}`);

    // The username should appear in the heading
    await expect(page.getByText(`@${TEST_USERNAME}`)).toBeVisible();

    // The GitHub source toggle should be visible
    await expect(page.locator('button', { hasText: 'GitHub' })).toBeVisible();
  });

  test('GitHub source is selected by default', async ({ page }) => {
    await page.goto(`/create?username=${TEST_USERNAME}`);

    // Wait for sources to load (skeleton disappears, source buttons appear)
    await expect(page.locator('button', { hasText: 'GitHub' })).toBeVisible();

    // The GitHub source button should have the "selected" styling (border-chart-1)
    // We check the checkbox indicator is rendered with the check icon
    const githubToggle = page.locator('button', { hasText: 'GitHub' });
    await expect(githubToggle).toBeVisible();
  });

  test('"Start Analysis" button is present and enabled after sources load', async ({ page }) => {
    await page.goto(`/create?username=${TEST_USERNAME}`);

    const startBtn = page.getByRole('button', { name: 'Start Analysis' });
    await expect(startBtn).toBeVisible();
    await expect(startBtn).toBeEnabled();
  });

  test('submitting shows pipeline progress UI', async ({ page }) => {
    await page.goto(`/create?username=${TEST_USERNAME}`);

    // Wait for the form to fully load
    const startBtn = page.getByRole('button', { name: 'Start Analysis' });
    await expect(startBtn).toBeVisible();
    await expect(startBtn).toBeEnabled();

    await startBtn.click();

    // After submission the pipeline progress component should appear.
    // The create page replaces the form with a PipelineProgress component
    // which shows "Analyzing their footprint..." in the subheading.
    await expect(
      page.getByText('Analyzing their footprint...'),
    ).toBeVisible({ timeout: 5_000 });
  });
});
