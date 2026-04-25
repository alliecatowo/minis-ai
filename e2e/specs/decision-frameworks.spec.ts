/**
 * decision-frameworks.spec.ts — Verify the DecisionFrameworksCard renders on
 * the mini profile page.
 *
 * All API calls are mocked via page.route() so no running backend is required.
 * The test mounts /m/alliecatowo with a fixture mini that has two decision
 * frameworks and asserts the card renders at least one row with a badge.
 */

import { test, expect } from '@playwright/test';
import { mockMiniApi, MOCK_MINI } from '../fixtures/dev-mini';

const PROFILE_USERNAME = 'alliecatowo';

const MOCK_FRAMEWORKS_RESPONSE = {
  username: PROFILE_USERNAME,
  frameworks: [
    {
      framework_id: 'fw-001',
      confidence: 0.85,
      revision: 3,
      trigger: 'a PR ships without tests for new code paths',
      action: 'block and request coverage before approving',
      value: 'craftsmanship',
      badge: 'high',
    },
    {
      framework_id: 'fw-002',
      confidence: 0.6,
      revision: 0,
      trigger: 'an API contract changes without a migration path',
      action: 'flag as blocker and propose a versioned rollout',
      value: 'reliability',
      badge: null,
    },
  ],
  summary: { total: 2, mean_confidence: 0.725, max_revision: 3 },
};

test.describe('decision-frameworks', () => {
  test.beforeEach(async ({ page }) => {
    // Mock the standard mini API
    await mockMiniApi(page);

    // Override by-username to return a mini with the profile username
    await page.route(
      `**/api/proxy/minis/by-username/${PROFILE_USERNAME}`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ...MOCK_MINI, username: PROFILE_USERNAME }),
        });
      },
    );

    // Mock the decision-frameworks endpoint
    await page.route(
      `**/api/proxy/minis/by-username/${PROFILE_USERNAME}/decision-frameworks**`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_FRAMEWORKS_RESPONSE),
        });
      },
    );

    // Mock conversations (keep it quiet)
    await page.route(
      `**/api/proxy/minis/${MOCK_MINI.id}/conversations`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify([]),
        });
      },
    );
  });

  test('renders at least one framework row with a badge', async ({ page }) => {
    await page.goto(`/m/${PROFILE_USERNAME}`);

    // Wait for the card heading to appear
    await expect(page.getByRole('heading', { name: 'Decision Frameworks' })).toBeVisible({
      timeout: 10_000,
    });

    // At least one row should render
    const rows = page.locator('[data-testid="framework-row"]');
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThanOrEqual(1);

    // The HIGH CONFIDENCE badge should appear for fw-001
    await expect(page.getByText(/HIGH CONFIDENCE/)).toBeVisible();
  });

  test('renders validated pill for frameworks with revision > 0', async ({ page }) => {
    await page.goto(`/m/${PROFILE_USERNAME}`);

    await expect(page.getByRole('heading', { name: 'Decision Frameworks' })).toBeVisible({
      timeout: 10_000,
    });

    // fw-001 has revision: 3, so the "validated N×" pill should appear
    await expect(page.getByTestId('validated-pill').first()).toBeVisible();
    await expect(page.getByTestId('validated-pill').first()).toContainText('validated');
  });

  test('does not render card when frameworks list is empty', async ({ page }) => {
    // Override to return empty frameworks
    await page.route(
      `**/api/proxy/minis/by-username/${PROFILE_USERNAME}/decision-frameworks**`,
      async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            username: PROFILE_USERNAME,
            frameworks: [],
            summary: { total: 0, mean_confidence: 0.0, max_revision: 0 },
          }),
        });
      },
    );

    await page.goto(`/m/${PROFILE_USERNAME}`);

    // Wait for the page to settle (chat input visible means the page loaded)
    await expect(page.locator('textarea, input[type="text"]').first()).toBeVisible({
      timeout: 10_000,
    });

    // The card heading should NOT be present
    await expect(page.getByRole('heading', { name: 'Decision Frameworks' })).not.toBeVisible();
  });
});
