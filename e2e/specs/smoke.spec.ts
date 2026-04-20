/**
 * smoke.spec.ts — Basic page-load and navigation smoke tests.
 *
 * No auth required. These tests verify:
 *  - The landing page loads with the correct title
 *  - The header/nav is present and contains expected links
 *  - No unexpected console errors occur on page load
 */

import { test, expect } from '@playwright/test';

// Console errors we know are harmless in a dev environment:
const IGNORED_CONSOLE_PATTERNS = [
  /\[Fast Refresh\]/,
  /Download the React DevTools/,
  /Warning: ReactDOM.render is no longer supported/,
  /webpack-hmr/,
  /hot-update/,
];

test.describe('smoke', () => {
  test('landing page loads with correct title', async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') {
        const text = msg.text();
        const ignored = IGNORED_CONSOLE_PATTERNS.some((re) => re.test(text));
        if (!ignored) {
          consoleErrors.push(text);
        }
      }
    });

    await page.goto('/');
    await expect(page).toHaveTitle(/Minis/);

    // Report any unexpected console errors
    expect(
      consoleErrors,
      `Unexpected console errors: ${consoleErrors.join('\n')}`,
    ).toHaveLength(0);
  });

  test('header nav is present', async ({ page }) => {
    await page.goto('/');

    const header = page.locator('header');
    await expect(header).toBeVisible();

    // Brand / logo link — use the "minis" text link specifically
    await expect(header.getByRole('link', { name: 'minis' })).toBeVisible();
  });

  test('header contains expected nav links', async ({ page }) => {
    await page.goto('/');

    const header = page.locator('header');

    // These links are always visible in the nav regardless of auth state
    await expect(header.locator('a[href="/features"]')).toBeVisible();
    await expect(header.locator('a[href="/pricing"]')).toBeVisible();
  });

  test('home page renders a username input', async ({ page }) => {
    await page.goto('/');

    // The hero input lets visitors enter a GitHub username
    const input = page.locator('input[type="text"]').first();
    await expect(input).toBeVisible();
  });

  test('footer is present on the landing page', async ({ page }) => {
    await page.goto('/');

    const footer = page.locator('footer');
    await expect(footer).toBeVisible();
  });
});
