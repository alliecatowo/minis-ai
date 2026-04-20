/**
 * dev-mini fixture — a static mock of a "ready" mini for use in tests that
 * need an existing mini without running the real pipeline.
 *
 * All frontend API calls go through `/api/proxy` (Next.js BFF). Tests use
 * `page.route('/api/proxy/...')` to intercept calls and return deterministic
 * fixture data. This keeps the suite fast, hermetic, and runnable without a
 * live backend.
 */

import type { Page } from '@playwright/test';

export const TEST_USERNAME = 'test-dev-user';

export const MOCK_MINI = {
  id: 1,
  username: TEST_USERNAME,
  display_name: 'Test Dev User',
  avatar_url: `https://github.com/${TEST_USERNAME}.png`,
  status: 'ready',
  owner_id: 'dev-user-001',
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
  spirit_content: 'You are a helpful developer.',
  memory_content: '',
  system_prompt: 'You are a helpful developer.',
  knowledge_graph_json: null,
  principles_json: null,
};

export const MOCK_MINI_LIST = [MOCK_MINI];

/**
 * Install API route mocks on `page` so that calls to /api/proxy/minis/*
 * return fixture data without hitting the real backend.
 *
 * Call this before navigating to any page that fetches mini data.
 */
export async function mockMiniApi(page: Page) {
  // GET /api/proxy/minis/by-username/[username]
  await page.route(
    `**/api/proxy/minis/by-username/${TEST_USERNAME}`,
    async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_MINI),
      });
    },
  );

  // GET /api/proxy/minis/sources — source list for create page
  await page.route('**/api/proxy/minis/sources', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'github',
          name: 'GitHub',
          description: 'Commits, PRs, and reviews',
          available: true,
        },
      ]),
    });
  });

  // POST /api/proxy/minis — mini creation; return a "processing" mini
  await page.route('**/api/proxy/minis', async (route) => {
    if (route.request().method() === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_MINI, id: 42, status: 'processing' }),
      });
    } else {
      // GET list
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_MINI_LIST),
      });
    }
  });
}

/**
 * Install a mock for the pipeline status SSE endpoint so that the create
 * page immediately sees a "done" event without waiting for a real pipeline.
 */
export async function mockPipelineSse(page: Page, miniId: number = 42) {
  await page.route(`**/api/proxy/minis/${miniId}/status`, async (route) => {
    // Respond with a minimal SSE stream that signals completion immediately.
    const body = [
      'event: progress\ndata: {"stage":"fetching","message":"Fetching\u2026","progress":0.1}\n\n',
      'event: done\ndata: {}\n\n',
    ].join('');

    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body,
    });
  });
}
