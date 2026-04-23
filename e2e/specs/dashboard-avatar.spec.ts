import { test, expect } from '../fixtures/auth';

const DEV_USERNAME = 'alliecatowo';
const MINI_LINK = `a[href="/m/${DEV_USERNAME}"]`;

async function mockDashboardApis(
  page: import('@playwright/test').Page,
  miniAvatarUrl: string | null,
) {
  await page.route(`**/api/proxy/minis/by-username/${DEV_USERNAME}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'mini-123',
        username: DEV_USERNAME,
        display_name: 'Allie',
        avatar_url: miniAvatarUrl,
        status: 'ready',
        owner_id: 'dev-user-001',
        created_at: '2024-01-01T00:00:00Z',
        updated_at: '2024-01-01T00:00:00Z',
      }),
    });
  });

  await page.route('**/api/proxy/minis/promo', async (route) => {
    await route.fulfill({ status: 404, body: '{"detail":"Not found"}' });
  });

  await page.route('**/api/proxy/minis', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '[]',
    });
  });
}

test.describe('dashboard avatar', () => {
  test('my mini card prefers the mini avatar over the GitHub auth avatar', async ({ authedPage: page }) => {
    const miniAvatarUrl = 'https://github.com/octocat.png';
    await mockDashboardApis(page, miniAvatarUrl);

    await page.goto('/');

    const myMiniCard = page.locator(MINI_LINK).filter({ hasText: 'My Mini' });
    await expect(myMiniCard).toBeVisible();
    await expect(myMiniCard.locator('img')).toHaveAttribute('src', miniAvatarUrl);
  });

  test('my mini card falls back locally when the mini has no avatar', async ({ authedPage: page }) => {
    await mockDashboardApis(page, null);

    await page.goto('/');

    const myMiniCard = page.locator(MINI_LINK).filter({ hasText: 'My Mini' });
    await expect(myMiniCard).toBeVisible();
    await expect(myMiniCard.locator('img')).toHaveCount(0);
    await expect(myMiniCard.locator('[data-slot="avatar-fallback"]')).toContainText('AL');
  });
});
