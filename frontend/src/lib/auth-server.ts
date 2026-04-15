import { createNeonAuth } from '@neondatabase/auth/next/server';

const cookieDomain = process.env.COOKIE_DOMAIN;

// NEON_AUTH_BASE_URL must point to the Neon Auth server for this project.
// Default is the project's Neon Auth endpoint for local development.
// In production set NEON_AUTH_BASE_URL in your hosting environment (Vercel env vars).
const NEON_AUTH_BASE_URL =
  process.env.NEON_AUTH_BASE_URL ||
  'https://ep-noisy-king-ai4zxs01.c-4.us-east-1.aws.neon.tech/neondb/auth';

export const auth = createNeonAuth({
  baseUrl: NEON_AUTH_BASE_URL,
  cookies: {
    secret: process.env.NEON_AUTH_COOKIE_SECRET || 'dev-secret-change-in-production-min-32-chars!',
    ...(cookieDomain ? { domain: cookieDomain } : {}),
  },
});
