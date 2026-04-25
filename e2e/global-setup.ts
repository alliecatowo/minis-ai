import { request, type FullConfig } from '@playwright/test';

const VERCEL_LOGIN_PATTERNS = [
  /<title>\s*Login\s+[–-]\s+Vercel\s*<\/title>/i,
  /\bLogin\s+[–-]\s+Vercel\b/i,
  /\bVercel Authentication\b/i,
  /\bVercel\s+Login\b/i,
];

function baseURLFromConfig(config: FullConfig): string {
  const projectBaseURL = config.projects[0]?.use.baseURL;
  if (typeof projectBaseURL === 'string') return projectBaseURL;
  return process.env.E2E_BASE_URL ?? 'http://localhost:3000';
}

function isVercelLoginPage(body: string): boolean {
  return VERCEL_LOGIN_PATTERNS.some((pattern) => pattern.test(body));
}

function protectionFailureMessage(baseURL: string, hasBypassSecret: boolean): string {
  const secretState = hasBypassSecret
    ? 'VERCEL_AUTOMATION_BYPASS_SECRET was provided, but Vercel still returned its login page. The secret may be invalid, revoked, or not the selected automation bypass for this Vercel project.'
    : 'VERCEL_AUTOMATION_BYPASS_SECRET is not set in the GitHub Actions e2e job, so Playwright cannot bypass Vercel Deployment Protection.';

  return [
    `E2E preflight reached Vercel Deployment Protection instead of the Minis app: ${baseURL}`,
    secretState,
    'Remediation:',
    '1. In Vercel Project Settings -> Deployment Protection, create/select a Protection Bypass for Automation secret for the frontend project.',
    '2. Add the same value as the GitHub Actions repository secret VERCEL_AUTOMATION_BYPASS_SECRET.',
    '3. Keep NEXT_PUBLIC_DEV_AUTH_BYPASS=true in the Vercel Preview environment for auth-dependent specs; setting it only in the Playwright job is too late for a deployed Next.js bundle.',
  ].join('\n');
}

async function globalSetup(config: FullConfig) {
  const baseURL = baseURLFromConfig(config);
  const bypassSecret = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
  const headers = bypassSecret
    ? {
        'x-vercel-protection-bypass': bypassSecret,
        'x-vercel-set-bypass-cookie': 'true',
      }
    : undefined;

  const context = await request.newContext({
    baseURL,
    extraHTTPHeaders: headers,
  });

  try {
    const response = await context.get('/');
    const body = await response.text();

    if (isVercelLoginPage(body)) {
      throw new Error(protectionFailureMessage(baseURL, !!bypassSecret));
    }
  } finally {
    await context.dispose();
  }
}

export default globalSetup;
